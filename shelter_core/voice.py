"""TTS (silero) и распознавание команд (vosk)."""

from shelter_core.paths import ROOT_DIR

from shelter_core import netfix  # noqa: F401 — локальное мимо системного прокси
import collections
import difflib
import hashlib
import io
import json
import math
import os
import queue
import re
import threading
import time
import urllib.request
import tempfile
from shelter_core import tasks
from shelter_core import tts_auth
from shelter_core.policy import CONFIRMATIONS
from shelter_core.speech_text import prepare_for_speech, split_for_speech

import numpy as np
PLUGIN_TTS = {}
import sounddevice as sd
from shelter_core import audio_io as wavfile
from shelter_core.native_runtime import resample_poly

from shelter_core.audio import LISTENING, SPEAKING, THINKING

# Оверлей — отдельный процесс и про SPEAKING не знает, поэтому дублируем
# состояние файлом-флагом. Тот же путь продублирован в overlay.py.
SPEAK_FLAG = os.path.join(ROOT_DIR,
                          "logs", "speaking.flag")

TTS_CACHE = "models/tts_cache"
TTS_SR = 48000
SPEAKER = "aidar"      # переопределяется из config.yaml -> tts.speaker
SILERO_MODEL = "v5_6_ru"
SILERO_THREADS = 2
STRESS = {}
ENGINE = "files"       # files — свои записи, остальное silero; silero — всё silero;
                       # clone — свои записи, остальное клонированным голосом
CLONE_URL = ""         # адрес сервера клонирования (tts_server.py), ставит main.py
CLOUD_TTS = {}
PIPER_VOICE = "ruslan"  # голос без видеокарты: models/piper/<голос> (tts.piper.voice)
PIPER_SPEED = 1.0
CACHE_MAX_CHARS = 90   # длинные ответы модели не повторяются — в кэш не кладём
CACHE_PROFILE = ""
EFFECT = ""                # эффект голоса персонажа: "" | robot (Вейн)
PITCH = 1.0                # высота запасных голосов (Piper, silero) для персонажа: 1.12 — выше
PREPARE_EPOCH = 0          # растёт при смене персонажа: старая подготовка фраз останавливается
_voice_lock = threading.Lock()
_preparing = set()
_preparing_lock = threading.Lock()


def cancel_preparation():
    with _preparing_lock:
        tokens = list(_preparing)
    for token in tokens:
        token.cancel()


CLONE_REF = {}             # образец голоса персонажа: {"reference": путь, "reference_text": текст}
CLONE_WAIT = 45.0          # сколько ждать загрузки клона, прежде чем говорить запасным голосом
VOSK_SR = 16000
# Копим блоки перед децимацией: на стыках resample_poly портит края,
# чем реже стыки, тем чище то, что видит vosk.
CHUNK = 8192

_model = None


def _resample_for_vosk(wave, source_sr):
    """Привести фрагмент записи к частоте, с которой создан recognizer.

    Раньше здесь было жёсткое ``resample_poly(..., 1, 2)``. Оно верно для
    текущих 32 кГц, но при выборе микрофона на 44.1/48 кГц Vosk получал бы
    PCM с неверной заявленной частотой 16 кГц. Сокращённое отношение сохраняет
    прежний быстрый путь 32 -> 16 и работает для любой целой частоты из конфига.
    """
    source_sr = int(source_sr)
    if source_sr <= 0:
        raise ValueError("частота микрофона должна быть положительной")
    divisor = math.gcd(source_sr, VOSK_SR)
    return resample_poly(wave, VOSK_SR // divisor, source_sr // divisor)


def _avatar():
    from shelter_core.avatar import AVATAR
    return AVATAR if AVATAR.builtin else None


def mouth(sample_rate, samples, frames=None, delay=.08):
    """Timestamped vowel weights, produced from the same PCM as playback."""
    if _avatar() is None or not len(samples):
        return
    from shelter_core import bus
    from shelter_core import lip_sync
    if frames is None:
        frames = lip_sync.acoustic(sample_rate, samples)
    bus.publish("mouth", frames=frames, rate=lip_sync.RATE,
                duration=len(samples) / sample_rate, delay=delay)


def speaking_flag(on):
    if not on:
        from shelter_core import bus
        bus.publish("mouth", clear=True)
    avatar = _avatar()
    if avatar is not None:
        avatar.trigger("speaking" if on else "listening")
    try:
        if on:
            os.makedirs(os.path.dirname(SPEAK_FLAG), exist_ok=True)
            open(SPEAK_FLAG, "w").close()
        elif os.path.exists(SPEAK_FLAG):
            os.remove(SPEAK_FLAG)
    except OSError:
        pass


def _cache_path(text):
    # Движок и голос в ключе: сменили их — кэш пересинтезируется, а не подсунет старое.
    voice_id = "clone" if ENGINE == "clone" else (SPEAKER if ENGINE == "silero" else f"piper-{PIPER_VOICE}")
    key = f"v2|{voice_id}|{PIPER_SPEED}|{CACHE_PROFILE}|{text}".encode("utf-8")
    return os.path.join(TTS_CACHE, hashlib.sha1(key).hexdigest() + ".wav")


def _load_tts():
    global _model
    if _model is None:
        import torch
        local = os.path.join(ROOT_DIR, "models", "silero", SILERO_MODEL + ".pt")
        if not os.path.isfile(local):
            raise FileNotFoundError("Русский голос не установлен. Установите Silero V5 в разделе «Слух и голос».")
        torch.set_num_threads(max(1, min(8, SILERO_THREADS)))
        _model = torch.package.PackageImporter(local).load_pickle("tts_models", "model")
        _model.to(torch.device("cpu"))
    return _model


def clone_health(timeout=0.4):
    """Отвечает ли сервер клонирования и загружена ли в нём модель."""
    if not CLONE_URL:
        return {}
    try:
        request = urllib.request.Request(CLONE_URL + "/health", headers=tts_auth.headers())
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except (OSError, ValueError, RuntimeError):
        return {}


def clone_ready(timeout=0.4):
    return bool(clone_health(timeout).get("ready"))


def _clone_chunks(text, reference=None):
    """Порции (частота, int16) с сервера голоса по мере генерации.
    reference — образец голоса, зафиксированный вместе с ключом кэша."""
    reference = CLONE_REF if reference is None else reference
    request = urllib.request.Request(
        CLONE_URL + "/stream", data=json.dumps({"text": text, **reference}).encode("utf-8"),
        method="POST", headers={"Content-Type": "application/json", **tts_auth.headers()})
    with urllib.request.urlopen(request, timeout=60) as response:
        token = tasks.current()
        if token:
            token.register(response.close)
        sample_rate = int(response.headers.get("X-Sample-Rate") or 24000)
        tail = b""
        while not _is_cancelled():
            data = response.read1(8192) if hasattr(response, "read1") else response.read(8192)
            if not data:
                break
            data = tail + data
            usable = len(data) // 2 * 2       # не рвать отсчёт PCM16 пополам
            tail = data[usable:]
            if usable:
                yield sample_rate, np.frombuffer(data[:usable], dtype="<i2")


def _silero(text):
    import re
    for word, spoken in STRESS.items():
        text = re.sub(r"(?<!\w)" + re.escape(word) + r"(?!\w)", lambda m: spoken, text, flags=re.I)
    with _generation_lock:
        tasks.check()
        wave = _load_tts().apply_tts(text=text, speaker=SPEAKER, sample_rate=TTS_SR, put_accent=True, put_yo=True)
    return TTS_SR, (np.clip(_pitch(wave.numpy()), -1.0, 1.0) * 32767).astype(np.int16)


_piper = None
_piper_name = ""
_piper_lock = threading.Lock()
_generation_lock = threading.Lock()


def _piper_model(name=None):
    """Голос Piper (sherpa-onnx, процессор, без PyTorch) из models/piper/<голос>."""
    global _piper, _piper_name
    name = name or PIPER_VOICE
    with _piper_lock:
        if _piper is None or _piper_name != name:
            import sherpa_onnx
            folder = os.path.join(ROOT_DIR, "models", "piper", name)
            onnx = next((f for f in os.listdir(folder) if f.endswith(".onnx")), None) if os.path.isdir(folder) else None
            if onnx is None:
                raise FileNotFoundError(f"нет голоса Piper в {folder}")
            config = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=os.path.join(folder, onnx), tokens=os.path.join(folder, "tokens.txt"),
                    data_dir=os.path.join(folder, "espeak-ng-data")),
                num_threads=2))
            _piper = sherpa_onnx.OfflineTts(config)
            _piper_name = name
        return _piper


def _piper_say(text, name=None):
    model = _piper_model(name)
    with _generation_lock:
        tasks.check()
        # Выше тон без «бурундука»: синтез медленнее ровно настолько, насколько
        # потом ускоряем при повышении тона, — темп остаётся прежним.
        audio = model.generate(text, sid=0, speed=PIPER_SPEED / PITCH)
    samples = _pitch(np.asarray(audio.samples, dtype=np.float32))
    return audio.sample_rate, (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)


def _pitch(samples):
    if abs(PITCH - 1.0) < 0.01 or not len(samples):
        return samples
    return resample_poly(samples, 100, int(round(100 * PITCH))).astype(np.float32)


def _fallback(text):
    """Голос без видеокарты: Piper (лёгкий, без PyTorch), если его нет — silero.

    Для клона запасной — silero (tts.speaker), если он установлен: так было до
    появления Piper, и голос меньше «прыгает» на время загрузки клона."""
    if ENGINE == "clone":
        try:
            return _silero(text)
        except tasks.Cancelled:
            raise
        except Exception:
            pass
    # Свой голос, потом голоса того же пола, silero, и только в конце — любой Piper:
    # девушке лучше silero xenia, чем мужской «Руслан».
    same = [n for n in _available_piper() if (n in FEMALE_PIPER) == (PIPER_VOICE in FEMALE_PIPER)]
    others = [n for n in _available_piper() if n not in same]
    for name in [*dict.fromkeys([PIPER_VOICE, *same]), None, *others]:
        try:
            return _silero(text) if name is None else _piper_say(text, name)
        except tasks.Cancelled:
            raise
        except (FileNotFoundError, ImportError, RuntimeError):
            continue
    raise RuntimeError("Нет установленного голоса. Установите Piper в разделе «Слух и голос».")


FEMALE_PIPER = {"irina"}


def _available_piper():
    """Только полностью скачанные голоса; не меняет настройки персонажа."""
    root = os.path.join(ROOT_DIR, "models", "piper")
    if not os.path.isdir(root):
        return []
    return [name for name in sorted(os.listdir(root))
            if os.path.isfile(os.path.join(root, name, "tokens.txt"))
            and os.path.isdir(os.path.join(root, name, "espeak-ng-data"))
            and any(f.endswith(".onnx") for f in os.listdir(os.path.join(root, name)))]


def _save(path, sample_rate, parts):
    os.makedirs(TTS_CACHE, exist_ok=True)
    handle, temporary = tempfile.mkstemp(suffix=".wav", dir=TTS_CACHE)
    os.close(handle)
    try:
        wavfile.write(temporary, sample_rate, np.concatenate(parts))
        os.replace(temporary, path)
        if _avatar() is not None:
            from shelter_core import lip_sync
            lip_sync.prepare(sample_rate, np.concatenate(parts))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _wait_for_clone():
    """Клон ещё грузится (первые ~10–35 с после запуска) — подождать его, а не
    говорить чужим голосом. Упал или нет видеокарты — сразу запасной голос."""
    from shelter_core import neural
    deadline = time.monotonic() + CLONE_WAIT
    while time.monotonic() < deadline and neural.loading():
        if clone_ready(0.5):
            return True
        tasks.check()
        time.sleep(0.25)
    return clone_ready(0.5)


def synthesize_chunks(text):
    """Фраза -> порции (частота, int16) с эффектом голоса персонажа («робот»)."""
    effect = make_effect(EFFECT)
    for rate, chunk in _synthesize_raw(text):
        yield (rate, effect(rate, chunk)) if effect else (rate, chunk)


class _Robot:
    """Автоматон: кольцевая модуляция (металлический призвук), короткий
    гребенчатый резонанс («корпус») и лёгкое огрубление. Фаза и хвост резонатора
    переносятся между кусками — склейки не щёлкают."""

    def __init__(self):
        self.n = 0
        self.tail = None

    def __call__(self, rate, chunk):
        x = np.asarray(chunk, dtype=np.float32) / 32768.0
        if x.ndim > 1:
            x = x[:, 0]
        t = (self.n + np.arange(len(x))) / rate
        self.n += len(x)
        y = 0.55 * x + 0.8 * x * np.sin(2 * np.pi * 52.0 * t)
        delay = max(1, int(rate * 0.0055))
        if self.tail is None or len(self.tail) != delay:
            self.tail = np.zeros(delay, dtype=np.float32)
        history = np.concatenate((self.tail, y))
        out = y + 0.45 * history[:len(y)]
        self.tail = history[-delay:]
        out = np.round(out * 96) / 96                     # чуть «цифровой» голос
        return (np.clip(out * 0.85, -1.0, 1.0) * 32767).astype(np.int16)


def make_effect(name):
    return _Robot() if name == "robot" else None


def _synthesize_raw(text):
    """Фраза -> порции (частота, int16). Порядок: кэш, клон потоком, silero.

    Короткие фразы попадают в кэш: «Да, сэр» второй раз не синтезируется.
    """
    tasks.check()
    from shelter_core import personas
    text = prepare_for_speech(personas.rewrite(text))      # «Готово, сэр» — словами персонажа
    if ENGINE == "plugin":
        from shelter_core import plugin_extensions
        yield plugin_extensions.synthesize(text, PLUGIN_TTS)
        return
    if ENGINE == "cloud":
        from shelter_core import cloud_media
        try:
            yield cloud_media.speech(text, CLOUD_TTS)
        except (ValueError, KeyError, TypeError) as error:
            from shelter_core import bus
            bus.publish("error", text=f"Облачная озвучка: {error}")
            tasks.check()
            yield _fallback(text)
        return
    # Голос и ключ кэша — одним снимком: персонажа могут сменить посреди синтеза,
    # и тогда фраза одного голоса не должна лечь в кэш другого.
    with _voice_lock:
        path, reference, profile = _cache_path(text), dict(CLONE_REF), CACHE_PROFILE
    if os.path.exists(path):
        yield wavfile.read(path)
        return
    if ENGINE == "clone" and not reference.get("skip_clone") and (clone_ready() or _wait_for_clone()):
        parts, sample_rate = [], 0
        try:
            for sample_rate, chunk in _clone_chunks(text, reference):
                parts.append(chunk)
                yield sample_rate, chunk
        except tasks.Cancelled:
            return
        except Exception as error:
            tasks.check()  # отменённая подготовка не должна запускать запасной синтез
            if not parts:
                print(f"[tts] клон не ответил ({error}) — говорю запасным голосом")
            else:
                print(f"[tts] клон оборвался на середине ({error})")
                return
        else:
            if (parts and not _is_cancelled() and len(text) <= CACHE_MAX_CHARS and profile == CACHE_PROFILE
                    and clean_take(text, sample_rate, np.concatenate(parts))):
                _save(path, sample_rate, parts)
            if parts:
                return
    tasks.check()
    audio = _silero(text) if ENGINE == "silero" else _fallback(text)
    # Запасной голос в кэш клона не кладём: иначе он там останется навсегда.
    preferred_ready = ENGINE not in ("piper", "files") or PIPER_VOICE in _available_piper()
    if ENGINE != "clone" and preferred_ready and len(text) <= CACHE_MAX_CHARS and profile == CACHE_PROFILE:
        _save(path, audio[0], [audio[1]])
    yield audio


def synthesize(text):
    """Фраза целиком -> (частота, int16)."""
    parts, sample_rate = [], TTS_SR
    for sample_rate, chunk in synthesize_chunks(text):
        parts.append(chunk)
    return sample_rate, (np.concatenate(parts) if parts else np.zeros(0, np.int16))


def prepare(texts):
    """Синтезировать постоянные фразы заранее, чтобы первый ответ не ждал.

    Сменили персонажа — подготовка для прежнего голоса бросается: иначе она
    занимает видеокарту, и первая фраза нового голоса ждёт в очереди."""
    if ENGINE == "cloud":
        return
    from shelter_core import personas
    epoch = PREPARE_EPOCH
    missing = [t for t in dict.fromkeys(texts)
               if not os.path.exists(_cache_path(prepare_for_speech(personas.rewrite(t))))]
    if not missing:
        return
    print(f"[tts] готовлю {len(missing)} фраз...")
    token = tasks.Token(timeout=600)
    with _preparing_lock:
        if _preparing or SPEAKING.is_set() or THINKING.is_set():
            return
        _preparing.add(token)
    try:
        with tasks.scope(token):
            for text in missing:
                path = _cache_path(prepare_for_speech(personas.rewrite(text)))
                for _attempt in range(3):
                    token.check()
                    if PREPARE_EPOCH != epoch or SPEAKING.is_set() or THINKING.is_set():
                        return
                    synthesize(text)
                    if os.path.exists(path) or ENGINE != "clone":
                        break
    except tasks.Cancelled:
        pass
    finally:
        with _preparing_lock:
            _preparing.discard(token)


def clean_take(text, rate, audio):
    """Годится ли дубль клона для кэша: без долгой паузы внутри и не растянут.

    У сорвавшегося дубля «Хорошо, хозяин! Теперь я Юки…» внутри было 1.6 с
    тишины, а вся фраза тянулась 7.4 с вместо ~3.5 — после паузы тембр другой."""
    x = np.asarray(audio, dtype=np.float32)
    if x.ndim > 1:
        x = x[:, 0]
    if np.abs(x).max() > 2:
        x = x / 32768.0
    step = max(1, rate // 20)                                   # кадры по 50 мс
    env = np.array([np.sqrt(np.mean(x[i:i + step] ** 2)) for i in range(0, len(x), step)])
    if not len(env) or env.max() < 1e-4:
        return False
    voiced = np.flatnonzero(env > max(0.008, env.max() * 0.06))
    if not len(voiced):
        return False
    gaps = np.diff(voiced) - 1                                  # тишина между звучащими кадрами
    longest = (gaps.max() if len(gaps) else 0) * step / rate
    span = (voiced[-1] - voiced[0] + 1) * step / rate
    letters = len(re.sub(r"[^а-яёa-z0-9]", "", text.lower()))
    expected = letters / 13.0                                   # обычная речь — ~13 букв в секунду
    return longest <= 0.7 and span <= 2.2 * expected + 0.8


def set_voice(reference, configure):
    """Сменить образец клона и ключ кэша одним шагом (смена персонажа)."""
    global CLONE_REF, PREPARE_EPOCH
    cancel_preparation()
    with _voice_lock:
        CLONE_REF = reference
        configure()
        PREPARE_EPOCH += 1


_cancel = threading.Event()
# Говорит кто-то один: реплика модели и фраза команды идут из разных потоков,
# а sounddevice при втором play молча обрывает первый.
_speech_lock = threading.Lock()
_sessions_lock = threading.Lock()
_sessions = set()


def _is_cancelled():
    token = tasks.current()
    return token.is_set() if token else False


def configure_cache(config):
    """Ключ кэша — только то, что меняет звук выбранного голоса.

    Раньше в ключ шла вся секция tts: смена запасного голоса или скорости Piper
    выбрасывала весь кэш клона, и первые фразы после запуска звучали чужим голосом.
    """
    global CACHE_PROFILE, CLONE_WAIT, PLUGIN_TTS
    from shelter_core import plugin_extensions
    plugin_extensions.configure(config)
    from shelter_core import speech_text
    tts = config.get("tts") or {}
    PLUGIN_TTS = dict(tts.get("plugin") or {})
    cfg = tts.get("clone") or {}
    CLONE_WAIT = float(cfg.get("wait", CLONE_WAIT))
    if ENGINE == "clone":
        profile = {k: cfg.get(k) for k in ("model", "reference_text", "language", "speaker", "temperature", "top_p")}
        if CLONE_REF.get("model_profile") == "jarvis" and cfg.get("jarvis_adapter"):
            from shelter_core.tts_profiles import revision
            root = ROOT_DIR
            profile["jarvis_adapter"] = revision(os.path.join(root, cfg["jarvis_adapter"]))
    elif ENGINE == "silero":
        profile = {"speaker": tts.get("speaker"), "silero": tts.get("silero"), "stress": tts.get("stress"), "pitch": PITCH}
    else:
        profile = {"piper": tts.get("piper"), "pitch": PITCH}
    profile["pronunciations"] = tts.get("pronunciations") or {}
    profile["text"] = speech_text.VERSION
    digest = hashlib.sha256(json.dumps(profile, sort_keys=True, ensure_ascii=False).encode())
    path = cfg.get("reference") if ENGINE == "clone" else None
    if path:
        try:
            with open(path, "rb") as reference:
                for block in iter(lambda: reference.read(65536), b""):
                    digest.update(block)
        except OSError:
            pass
    CACHE_PROFILE = digest.hexdigest()

SPEECH_LEVELS = os.path.join(ROOT_DIR,
                             "logs", "speech_levels.json")


def _load_speech_levels():
    try:
        with open(SPEECH_LEVELS, encoding="utf-8") as file:
            return [float(v) for v in json.load(file)][-8:]
    except (OSError, ValueError, TypeError):
        return []


def _save_speech_levels(values):
    try:
        os.makedirs(os.path.dirname(SPEECH_LEVELS), exist_ok=True)
        with open(SPEECH_LEVELS, "w", encoding="utf-8") as file:
            json.dump(values, file)
    except OSError:
        pass

# Команды, выбранные языковой моделью. Поток распознавания проводит их тем же
# путём, что и голосовые: с переспросом опасных и снятием режима ожидания.
INBOX = queue.Queue()
# Горячая клавиша приложения (push-to-talk): слушать команду без слова «Джарвис».
ARM = threading.Event()
RESUME = threading.Event()
STOP_LISTENING = threading.Event()


def stop_listening():
    """Disarm the current utterance, including audio already being transcribed."""
    STOP_LISTENING.set()
    ARM.clear()
    RESUME.clear()
    LISTENING.clear()
    HEARING.clear()
ACK_AT = -100.0            # когда отзвучал последний отклик
HEARING = threading.Event()  # человек сейчас говорит (для «распознаю…» в окне)
ACK = threading.Event()     # звучит короткий отклик на обращение («Да, сэр») — микрофон не глушим
WAKE_ENGINE = "vosk"        # чем слушаем имя: vosk | kws (выставляет listen)
WAKE_READY = threading.Event()
# Что Джарвис говорит прямо сейчас: его собственные слова из колонок не должны
# сработать как «хватит» или «Джарвис» и перебить его же.
SAYING = []

# Короткие команды без имени — как «Алиса, …» без «Алиса». Срабатывают, только
# если это вся фраза целиком и если что-то играет: «пауза» в голосовом чате
# игры при выключенной музыке ничего не сделает.
QUICK = {
    "пауза": "pause", "поставь на паузу": "pause", "стоп": "pause", "хватит": "pause",
    "продолжи": "play", "продолжай": "play", "играй": "play", "сними с паузы": "play",
    "дальше": "next", "следующий": "next", "следующий трек": "next", "следующая": "next",
    "следующая песня": "next", "следующее видео": "next", "переключи": "next",
    "предыдущий": "previous", "предыдущий трек": "previous", "предыдущая песня": "previous",
    "назад": "previous", "верни": "previous",
    "громче": "louder", "погромче": "louder", "сделай громче": "louder",
    "тише": "quieter", "потише": "quieter", "сделай тише": "quieter",
}
# Перебить Джарвиса, пока он говорит: эти слова или его имя.
STOP_WORDS = ["хватит", "стоп", "замолчи", "достаточно", "отмена"]
# Не закрывают разговор: «перестань говорить» — тишина, «отмени задачу» — бросить дело.
SOFT_STOP = {"перестань говорить": "mute", "помолчи": "mute", "не говори": "mute",
             "отмени задачу": "cancel", "отмени это": "cancel", "останови задачу": "cancel",
             "прекрати": "cancel", "брось это": "cancel"}


def inject(command, text):
    tasks.check()
    INBOX.put((command, text, tasks.current()))


def stop_speaking():
    """Оборвать текущую речь: и воспроизведение, и очередь предложений."""
    _cancel.set()
    CONFIRMATIONS.clear()
    with _sessions_lock:
        sessions = list(_sessions)
    for token in sessions:
        token.cancel()
        if token.parent:
            token.parent.cancel()
    sd.stop()


def _play(sr, x):
    from shelter_core import remote_audio
    if remote_audio.write(sr, x):
        return
    from shelter_core import lip_sync
    cues = lip_sync.frames(sr, x)[0] if _avatar() and _avatar().config.get("persona",{}).get("options",{}).get("lips","auto") == "auto" else None
    mouth(sr, x, cues)
    sd.play(x, sr)
    sd.wait()


def pcm16(samples):
    """Preserve float WAV amplitude; casting [-1,1] directly to int16 is silence."""
    data = np.asarray(samples)
    kind = data.dtype
    if data.ndim > 2:
        raise ValueError("звук должен быть моно или стерео")
    if data.ndim == 2:
        data = data.astype(np.float32).mean(axis=1)
    if kind == np.int16 and data.dtype == np.int16:
        return np.ascontiguousarray(data)
    if kind == np.uint8:
        data = (data.astype(np.float32) - 128) / 128
    elif np.issubdtype(kind, np.integer):
        info = np.iinfo(kind)
        data = data.astype(np.float32) / max(abs(info.min), info.max)
    return (np.clip(np.nan_to_num(data), -1, 1) * 32767).astype(np.int16)


class _Output:
    """Непрерывный вывод порций: без щелчков и пауз между ними.

    Поток переоткрывается, только если поменялась частота (запись 44.1 кГц,
    клон 24 кГц, silero 48 кГц).
    """

    def __init__(self):
        self.stream = None
        self.rate = 0

    def write(self, sample_rate, chunk, frames=None):
        from shelter_core import remote_audio
        if remote_audio.write(sample_rate, chunk):
            return
        if self.stream is None or sample_rate != self.rate:
            self.close()
            self.rate = sample_rate
            self.stream = sd.OutputStream(samplerate=sample_rate, channels=1, dtype="int16")
            self.stream.start()
        data = pcm16(chunk)
        if data.ndim > 1:
            data = data[:, 0]
        mouth(sample_rate, data, frames, delay=float(self.stream.latency))
        self.stream.write(data.reshape(-1, 1))

    def close(self):
        if self.stream is not None:
            # Хвост буфера доигрывается, а не обрезается на последнем слоге;
            # перебили («хватит») — обрываем сразу, вместе с буфером.
            stream = self.stream
            self.stream = None
            try:
                if _is_cancelled(): stream.abort()
                else: stream.stop()  # PortAudio drains output buffers itself.
            finally:
                stream.close()


def say(text, file=None):
    """file — своя запись; без неё фраза синтезируется выбранным движком."""
    token = tasks.current()
    if token and getattr(tasks._root(token), "delivery", None) and not getattr(tasks._root(token), "remote", None):
        return
    from shelter_core import personas
    if file and (ENGINE in ("cloud", "silero") or personas.active()["id"] != personas.DEFAULT_ID):
        file = None    # чистый синтез или другой персонаж: записи — голос Джарвиса
    if not file:
        speak_stream([text])     # синтез потоком: звук начинается с первой порции
        return
    try:
        if not os.path.exists(file):
            print(f"[tts] нет файла {file} — синтезирую фразу")
            speak_stream([text])
            return
        sr, x = wavfile.read(file)
    except Exception as e:
        print(f"[tts] не прочитать {file} ({e}) — синтезирую фразу")
        speak_stream([text])
        return
    token = tasks.Token(tasks.current())
    with _sessions_lock:
        _sessions.add(token)
    acquired = False
    try:
        while not token.is_set():
            token.check()
            if _speech_lock.acquire(timeout=0.05):
                acquired = True
                break
        if not acquired or token.is_set():
            return
        SAYING[:] = [text]
        SPEAKING.set()
        speaking_flag(True)
        _play(sr, x)
    finally:
        try:
            if acquired:
                try:
                    SPEAKING.clear()
                    speaking_flag(False)
                finally:
                    _speech_lock.release()
        finally:
            with _sessions_lock:
                _sessions.discard(token)


def speak_stream(sentences):
    """Озвучить поток предложений без пауз между ними.

    Синтез идёт впереди воспроизведения: пока звучит первая фраза, следующая
    уже генерируется, а первая начинает звучать с первой готовой порции.
    """
    current = tasks.current()
    if current:
        root = tasks._root(current)
        if getattr(root, "delivery", None) and not getattr(root, "remote", None):
            for _ in sentences:
                tasks.check()
            return
    cancel_preparation()
    token = tasks.Token(tasks.current())
    ready = queue.Queue(maxsize=8)
    started_at = time.monotonic()
    first_audio = None
    audio_seconds = 0.0
    announced = False
    failed = False

    def report_error(error):
        tasks.fail("Воспроизведение речи: " + str(error))
        from shelter_core import bus
        bus.publish("error", text="Не удалось воспроизвести ответ: " + str(error))
        print(f"[tts] ошибка воспроизведения: {error}")

    def put(item):
        while not token.is_set():
            try:
                ready.put(item, timeout=0.05)
                return
            except queue.Full:
                continue

    def produce():
        nonlocal failed
        with tasks.scope(token):
            try:
                for sentence in sentences:
                    token.check()
                    SAYING.append(sentence)
                    for fragment in split_for_speech(sentence):
                        token.check()
                        generated = 0
                        for rate, samples in synthesize_chunks(fragment):
                            token.check()
                            if not len(samples):
                                continue
                            generated += len(samples)
                            # Bound memory by audio duration, not just number of sentences.
                            from shelter_core import lip_sync
                            cues = lip_sync.frames(rate, samples)[0] if _avatar() and _avatar().config.get("persona",{}).get("options",{}).get("lips","auto") == "auto" else None
                            for start in range(0, len(samples), max(1, rate // 4)):
                                end = start + max(1, rate // 4)
                                chunk_cues = cues[round(start * 50 / rate):round(min(end, len(samples)) * 50 / rate)] if cues is not None else None
                                put((rate, samples[start:end], chunk_cues))
                        if not generated:
                            raise RuntimeError("голос вернул пустой звук")
            except tasks.Cancelled:
                pass
            except Exception as error:
                failed = True
                tasks.fail("Синтез речи: " + str(error))
                from shelter_core import bus
                bus.publish("error", text="Не удалось озвучить ответ: " + str(error))
                print(f"[tts] синтез не удался: {error}")
            finally:
                try:
                    if hasattr(sentences, "close"):
                        sentences.close()
                except Exception as error:
                    failed = True
                    report_error(error)
                finally:
                    put(None)

    with _sessions_lock:
        _sessions.add(token)
    acquired = False
    output = _Output()
    try:
        while not token.is_set():
            if _speech_lock.acquire(timeout=0.05):
                acquired = True
                break
        if not acquired or token.is_set():
            return
        SAYING.clear()
        threading.Thread(target=produce, name="tts", daemon=True).start()
        with tasks.scope(token):
            while not token.is_set():
                token.check()
                try:
                    part = ready.get(timeout=0.05)
                except queue.Empty:
                    continue
                if part is None:
                    break
                rate, samples, cues = part
                if not len(samples): continue
                if not announced:
                    SPEAKING.set()
                    speaking_flag(True)
                    announced = True
                for start in range(0, len(samples), max(1, rate // 10)):
                    if token.is_set():
                        break
                    end = start + max(1, rate // 10)
                    chunk_cues = cues[round(start * 50 / rate):round(min(end, len(samples)) * 50 / rate)] if cues is not None else None
                    output.write(rate, samples[start:end], chunk_cues)
                    if first_audio is None: first_audio = time.monotonic() - started_at
                    audio_seconds += len(samples[start:end]) / rate
    except tasks.Cancelled:
        token.cancel()
        raise
    except Exception as error:
        failed = True
        token.cancel()  # release a producer blocked on a full queue/socket
        report_error(error)
    finally:
        try:
            with tasks.scope(token):
                output.close()
        except Exception as error:
            failed = True
            token.cancel()
            report_error(error)
        finally:
            if acquired:
                try:
                    SPEAKING.clear()
                    if announced: speaking_flag(False)
                except Exception as error:
                    report_error(error)
                finally:
                    _speech_lock.release()
            with _sessions_lock:
                _sessions.discard(token)
            if first_audio is not None:
                print(f"[tts] playback: first_write={first_audio:.2f}s audio={audio_seconds:.2f}s total={time.monotonic()-started_at:.2f}s status={'failed' if failed else 'cancelled' if token.is_set() else 'done'}")


# Вежливые и пустые слова не мешают «целой» команде: «пока, сэр», «закрой, пожалуйста».
FILLER = {"пожалуйста", "сэр", "ну", "тогда", "всё", "все", "уже", "давай", "джарвис", "окно", "интерфейс"}


# Фраза с таким глаголом — про закрытие: команды-«открывашки» её не берут.
CLOSING = {"закрой", "закрыть", "сверни", "свернуть", "выключи", "выруби", "убери", "заверши", "останови", "убей"}
OPENING = {"launch", "url", "process", "app"}


def strip_ack(text, config):
    """Убрать из начала фразы собственное «Да, сэр» (его слышно из колонок,
    пока человек уже говорит просьбу)."""
    from shelter_core import asr
    if not ACK.is_set() and time.monotonic() - ACK_AT > 4:
        return text                    # давно не звучал — это слова человека, не эхо
    for action in (config.get("wake") or {}).get("actions") or []:
        if action.get("type") != "say":
            continue
        from shelter_core import personas
        ack = asr.normalize(personas.rewrite(action.get("text", ""))).strip()
        low = text.strip()
        if ack and (low == ack or low.startswith(ack + " ")):
            return low[len(ack):].strip()
    return text


COMMAND_WORDS = 4          # длиннее — уже не команда, а разговор: решает модель


def find_command(text, commands):
    """Первая подходящая команда целиком, иначе None.

    По умолчанию ключ должен совпасть со словом целиком, иначе короткое
    "пока" срабатывало бы на "покажи". "музык*" — совпадение по началу слова,
    ключ с пробелом ищется как подстрока.
    """
    from shelter_core import automation_intent
    from shelter_core import browser_episode
    from shelter_core import minecraft_intents
    from shelter_core.minecraft_companion import MINECRAFT
    request = automation_intent.inspect(text)
    if (automation_intent.save_title(text) is not None or request and request.chain or
            browser_episode.matches(text) or minecraft_intents.desktop(text, MINECRAFT.phase == "ready") is not None):
        return None
    from shelter_core import desktop_input
    if desktop_input.resolve(text): return None
    from shelter_core import avatar_motion
    if avatar_motion.active_stop(text):
        return None  # «стоп» во время танца важнее старого сценария прощания
    words = text.split()
    closing = bool(words) and words[0] in CLOSING
    # Мгновенные команды — для коротких просьб («включи музыку», «следующий трек»).
    # В длинной фразе ключ — просто слово («следующей фразой я скажу привет…»):
    # её разбирает модель, а готовый сценарий она запустит сама (инструмент scenario).
    content = [w for w in re.findall(r"[а-яёa-z0-9]+", text.lower()) if w not in FILLER]
    if len(content) > COMMAND_WORDS:
        return None
    for cmd in commands:
        if closing and any(a.get("type") in OPENING for a in cmd.get("actions") or []):
            continue          # «закрой телеграм» не должно открывать Telegram
        if cmd.get("whole"):
            # «закрой» — закрыть интерфейс, а «закрой телеграм» — уже про окно:
            # такая команда срабатывает, только если ключ и есть вся фраза.
            rest = [w for w in re.findall(r"[а-яёa-z0-9]+", text.lower()) if w not in FILLER]
            if rest and any(" ".join(rest) == kw.lower().rstrip("*") or
                            (kw.endswith("*") and len(rest) == 1 and rest[0].startswith(kw[:-1]))
                            for kw in cmd.get("keywords", [])):
                return cmd
            continue
        for kw in cmd.get("keywords", []):
            if " " in kw:
                hit = kw in text
            elif kw.endswith("*"):
                hit = any(w.startswith(kw[:-1]) for w in words)
            else:
                hit = kw in words
            if hit:
                return cmd
    return None


# Перед обращением не команда: «эй, Джарвис», «слушай, Джарвис».
INTERJECTIONS = {"эй", "хей", "слушай", "ну", "о", "а", "алло", "ок", "окей", "так", "да", "привет"}


def match(text, wake_words, commands):
    """(услышали_обращение, команда, остаток_фразы)."""
    low = text.lower()
    from shelter_core import personas
    if personas.find_switch(low.strip(" ,.!?")):
        return False, None, ""  # A switch is handled in an already awake conversation.
    hits = [m for word in wake_words if word for m in
            re.finditer(r"(?<![\w-])" + re.escape(word.lower()) + r"(?![\w-])", low)]
    if not hits:
        return False, None, ""
    found = min(hits, key=lambda m:m.start())
    # Speech before the call is never promoted to a command, even at the end.
    rest = low[found.end():].strip(" ,.!?;:—-")
    return True, find_command(rest, commands), rest


def listen(cap, config, events, stop):
    """Поток vosk: распознаёт обращение и передаёт команды в главную очередь."""
    from vosk import KaldiRecognizer, Model, SetLogLevel

    STOP_LISTENING.clear()
    SetLogLevel(-1)   # vosk иначе сыплет своими LOG-строками при загрузке модели
    wake = config.get("wake") or {}
    model = Model(wake["model_path"])
    rec = KaldiRecognizer(model, VOSK_SR)
    words = list(wake.get("words") or [])
    # 0 — ждать команду бессрочно, пока она не прозвучит.
    follow_up = float(wake.get("follow_up", 12))
    commands = config.get("commands") or []
    verbose = bool(config.get("verbose"))
    armed_until = 0.0

    confirm_cfg = config.get("confirm") or {}
    yes_words = [w.lower() for w in (confirm_cfg.get("accept") or ["да"])]
    no_words = [w.lower() for w in (confirm_cfg.get("reject") or ["нет"])]
    confirm_timeout = float(confirm_cfg.get("timeout", 20))
    pending = None          # команда, ждущая "да"
    pending_until = 0.0

    # Детектор речи: vosk не должен круглосуточно декодировать тишину и шум.
    # Silero VAD (через sherpa-onnx, без torch) отличает голос от клавиатуры и
    # выстрелов; без него — дешёвый энергетический гейт.
    from shelter_core import asr
    vad_cfg = wake.get("vad") if isinstance(wake.get("vad"), dict) else {}
    vad_on = bool(wake.get("vad", True)) if not vad_cfg else vad_cfg.get("enabled", True)
    vad = asr.make_vad(config) if vad_on else None
    vad_factor = float(vad_cfg.get("factor", 2.5))
    vad_hangover = float(vad_cfg.get("hangover", 0.8 if vad is None else 0.45))
    # Фразу для Джарвиса целиком переслушивает GigaAM — vosk ловит только имя.
    giga = asr.load(config)
    from shelter_core import speaker
    owner_cfg = wake.get("owner") or {}
    owner_check = bool(owner_cfg.get("enabled")) and speaker.available() and speaker.enrolled()
    if owner_check:
        speaker.embedding(np.zeros(speaker.SR, dtype=np.float32))     # прогреть модель заранее
        print(f">> OWNER VOICE  //  ON  ({owner_cfg.get('mode', 'soft')})")
    utterance = []                                   # звук текущей фразы, 16 кГц
    preroll = collections.deque(maxlen=2)            # ~0.5 с до срабатывания гейта

    # Пока Джарвис говорит, основной распознаватель спит, а микрофон раз в
    # полсекунды переслушивает GigaAM: ищет «хватит», «стоп» или имя. Маленький
    # vosk для этого не годится — эхо ответа из колонок он «слышит» как стоп-слова.
    quick_on = bool(wake.get("quick", True))
    barge_on = bool(wake.get("barge_in", True)) and giga is not None

    # Слово-обращение: KWS (wake.engine: kws) слушает только имя и быстрые
    # команды за 2–3 % ядра; vosk включается, лишь когда к Джарвису обратились.
    global WAKE_ENGINE
    spotter = None
    if str(wake.get("engine", "vosk")).lower() == "kws":
        from shelter_core import wakeword
        if wakeword.available():
            try:
                spotter = wakeword.Spotter(words, list(QUICK) if quick_on else (),
                                           float(wake.get("sensitivity", 0.5)))
                print(f">> WAKE  //  KWS ({spotter.count} вариантов)")
            except Exception as error:
                print(f">> WAKE  //  KWS недоступен ({error}) — vosk")
        else:
            print(">> WAKE  //  модель слова-обращения не установлена — vosk")
    WAKE_ENGINE = "kws" if spotter else "vosk"
    kws_stream = spotter.stream() if spotter else None
    wake_signature = tuple(words)
    kws_woke = False        # имя в этой фразе поймал KWS
    kws_quick = None        # быстрая команда, услышанная KWS в этой фразе
    vosk_idle = False       # vosk сейчас не кормим — ждём имени
    barge_window = collections.deque(maxlen=6)   # ~1.5 с звука
    barge_buf = np.zeros(0, dtype=np.float32)
    barge_tick = 0
    # Имя поверх ответа GigaAM пропускает (держится за основной голос), а
    # потоковый vosk с полным словарём его ловит — им и ищем имя.
    barge_rec = KaldiRecognizer(model, VOSK_SR) if barge_on and spotter is None else None
    barge_stream = spotter.stream() if barge_on and spotter else None
    WAKE_READY.set()

    def barge_word(x16):
        """Стоп-слово или имя в свежем звуке; None — ничего."""
        saying = asr.normalize(" ".join(SAYING))
        if barge_stream is not None:
            hits = spotter.feed(barge_stream, x16)
            if any(h.startswith("w:") for h in hits) and not any(w[:5] in saying for w in words):
                return words[0]
        else:
            pcm16 = (np.clip(x16, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
            if barge_rec.AcceptWaveform(pcm16):
                partial = json.loads(barge_rec.Result()).get("text", "")
            else:
                partial = json.loads(barge_rec.PartialResult()).get("partial", "")
            if not any(w in saying for w in words) and any(w in partial.split() for w in words):
                return words[0]
        if barge_tick % 2 or len(barge_window) < 3:
            return None
        audio16 = np.concatenate(barge_window)
        if float(np.sqrt(np.mean(audio16 * audio16))) < 1e-3:
            return None
        heard_now = asr.transcribe(audio16).split()
        if verbose:
            print(f"   [перебивание?] {' '.join(heard_now)!r}")
        for token in heard_now:
            if token in STOP_WORDS and token not in saying:      # своё эхо не считается
                return token
        return None
    vad_speech_ratio = float(vad_cfg.get("speech_ratio", 0.08))
    levels = collections.deque(maxlen=80)   # ~20 с истории уровней
    last_voice = 0.0
    woke_on_partial = False
    # Самокалибровка: громкость, с которой реально произносят обращение.
    # В тихой комнате щелчок клавиши громче шумового пола в десять раз, и один
    # относительный порог держал бы декодер включённым половину времени.
    speech_levels = collections.deque(_load_speech_levels(), maxlen=8)
    utterance_peak = 0.0
    in_utterance = False     # vosk получил речь, но фразу ещё не закрыл

    def remember_speech_level():
        if utterance_peak > 0:
            speech_levels.append(utterance_peak)
            _save_speech_levels(list(speech_levels))

    def finish_command(command):
        """После команды либо продолжить диалог, либо снять режим ожидания."""
        nonlocal armed_until
        if command.get("keep_listening"):
            LISTENING.set()
            armed_until = (time.monotonic() + follow_up) if follow_up > 0 else 0.0
        else:
            LISTENING.clear()
            armed_until = 0.0

    def accept(command, text):
        """Опасные команды сначала переспрашивают, остальные идут сразу."""
        ask = command.get("confirm")
        if ask:
            CONFIRMATIONS.request(command, confirm_timeout)
            print(f">> CONFIRM REQUIRED  //  {text}")
            events.put(("confirm", ask if isinstance(ask, dict) else {"text": ask}))
            return command, time.monotonic() + confirm_timeout
        print(f">> COMMAND ACCEPTED  //  {text}")
        events.put(("command", command))
        finish_command(command)
        return None, 0.0

    def ask(question):
        """Свободная фраза уходит модели; окно ожидания держим до конца ответа,
        чтобы разговор можно было продолжить без повторного обращения."""
        nonlocal armed_until
        # Пока Джарвис думает над прошлым — в очередь, а не вместо него.
        events.put(("ask", {"text": question, "queue": True} if THINKING.is_set() else question))
        if follow_up > 0:
            armed_until = time.monotonic() + follow_up + ask_grace

    def pcm16(chunk):
        return (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16).tobytes()

    def quick_heard(name, audio):
        """Быстрая команда без имени, которую услышал KWS: короткая фраза целиком
        и подтверждение GigaAM — «дальше» посреди разговора не считается."""
        action = QUICK.get(name.replace("_", " "))
        if not action or len(audio) > 2.5 * VOSK_SR:
            return
        heard_now = asr.transcribe(audio) if giga is not None else name.replace("_", " ")
        if THINKING.is_set() and not SPEAKING.is_set() and heard_now in STOP_WORDS:
            events.put(("interrupt", None))
            return
        if CONFIRMATIONS.active() or QUICK.get(heard_now) != action:
            return
        if owner_check and not speaker.is_owner(audio, config):
            events.put(("guest_ignored", heard_now))
            return
        print(f">> QUICK  //  {heard_now}")
        events.put(("quick", action))

    def armed():
        """Команды без обращения принимаются, только пока открыт интерфейс.
        follow_up > 0 дополнительно ограничивает это время сверху."""
        if not LISTENING.is_set():
            return False
        return follow_up <= 0 or time.monotonic() < armed_until

    def refine(text, audio, kws_called=False):
        """Фразу для Джарвиса переслушать GigaAM; чужие разговоры — не тратить время.
        kws_called — имя поймал KWS, а в тексте vosk его может и не быть."""
        if not text:
            return text
        called = match(text, words, commands)[0] or kws_called
        if giga is None:
            if kws_called and not match(text, words, commands)[0]:
                return asr.called_transcript(text, words)
            return text
        if not (called or armed() or CONFIRMATIONS.active()):
            return text
        started = time.perf_counter()
        better = asr.transcribe(audio)
        if verbose:
            print(f"   [gigaam {1000 * (time.perf_counter() - started):.0f} мс] {better!r}  (vosk: {text!r})")
        if not better:
            return asr.called_transcript(text, words) if called else text
        if called:
            # Имя GigaAM пишет по-своему — убрать его и вернуть каноническое,
            # чтобы дальше всё шло тем же путём, что и раньше.
            return asr.called_transcript(better, words)
        return better

    # Выключен — фразы без совпадения просто игнорируются, как и раньше.
    llm_on = bool((config.get("llm") or {}).get("enabled"))
    ask_grace = float((config.get("llm") or {}).get("timeout", 30))
    print(f">> VOICE LINK ONLINE  //  WAKE WORD \"{words[0].upper() if words else '—'}\""
          + ("  //  LLM ON" if llm_on else ""))

    buf = np.zeros(0, dtype=np.float32)
    while not stop.is_set():
        if STOP_LISTENING.is_set():
            rec.Reset()
            if spotter:
                spotter.reset(kws_stream)
                if barge_stream:
                    spotter.reset(barge_stream)
            if barge_rec:
                barge_rec.Reset()
            utterance.clear()
            preroll.clear()
            barge_window.clear()
            buf = barge_buf = np.zeros(0, dtype=np.float32)
            armed_until = utterance_peak = 0.0
            in_utterance = woke_on_partial = kws_woke = vosk_idle = False
            kws_quick = None
            barge_tick = 0
            while True:
                try:
                    cap.vosk_queue.get_nowait()
                except queue.Empty:
                    break
            STOP_LISTENING.clear()
        from shelter_core import personas
        current_words = personas.runtime_call_words(config)
        if tuple(current_words) != wake_signature:
            words = current_words
            wake_signature = tuple(words)
            rec.Reset()
            utterance.clear(); preroll.clear(); barge_window.clear()
            HEARING.clear()
            buf = np.zeros(0, dtype=np.float32); barge_buf = np.zeros(0, dtype=np.float32)
            in_utterance = woke_on_partial = kws_woke = vosk_idle = False
            kws_quick = None
            spotter = None
            if str(wake.get("engine", "vosk")).lower() == "kws":
                try:
                    from shelter_core import wakeword
                    if wakeword.available():
                        spotter = wakeword.Spotter(words, list(QUICK) if quick_on else (), float(wake.get("sensitivity",.5)))
                except Exception as error:
                    print(f">> WAKE  //  новое имя: KWS недоступен ({error}) — vosk")
            WAKE_ENGINE = "kws" if spotter else "vosk"
            kws_stream = spotter.stream() if spotter else None
            barge_stream = spotter.stream() if barge_on and spotter else None
            barge_rec = KaldiRecognizer(model, VOSK_SR) if barge_on and spotter is None else None
            # Audio captured before the change belongs to the previous persona.
            while True:
                try: cap.vosk_queue.get_nowait()
                except queue.Empty: break
            print(f">> WAKE NAME  //  {', '.join(words)}")
        now = time.monotonic()
        pending = CONFIRMATIONS.active()
        if CONFIRMATIONS.expire():
            events.put(("listen_timeout", None))
            LISTENING.clear()
            pending = None
        # Expire silence, never an utterance or an outstanding response.
        if (SPEAKING.is_set() or in_utterance or THINKING.is_set()) and LISTENING.is_set() and follow_up > 0:
            # Не отнимать из окна ожидания время, пока сам Джарвис говорит.
            armed_until = now + follow_up
        elif (not pending and LISTENING.is_set() and follow_up > 0
              and armed_until > 0 and now >= armed_until):
            print(">> FOLLOW-UP TIMEOUT  //  STANDING BY")
            LISTENING.clear()
            armed_until = 0.0
            events.put(("listen_timeout", None))

        while not INBOX.empty():
            injected, said, origin = INBOX.get_nowait()
            if origin and origin.is_set():
                continue
            pending, pending_until = accept(injected, said)

        if RESUME.is_set():
            RESUME.clear()
            if not in_utterance:
                rec.Reset()               # человек уже говорит — начатую фразу не сбрасывать
            LISTENING.set()
            armed_until = (time.monotonic() + follow_up) if follow_up > 0 else 0.0

        if ARM.is_set():
            # Горячая клавиша (push-to-talk) — то же, что сказать «Джарвис».
            ARM.clear()
            if SPEAKING.is_set():
                stop_speaking()
            print(">> HOTKEY  //  AWAITING ORDERS")
            rec.Reset()
            LISTENING.set()
            armed_until = (time.monotonic() + follow_up) if follow_up > 0 else 0.0
            events.put(("wake", "visual"))

        try:
            block = cap.vosk_queue.get(timeout=0.2)
        except queue.Empty:
            continue
        if STOP_LISTENING.is_set():
            continue
        # Пока звучит короткое «Да, сэр», человек уже говорит просьбу: микрофон
        # слушаем как обычно, а имя в его речи не считается перебиванием.
        if SPEAKING.is_set() and not ACK.is_set():
            if barge_on:
                barge_buf = np.concatenate((barge_buf, block))
                if len(barge_buf) >= CHUNK:
                    fresh16 = _resample_for_vosk(barge_buf, cap.sample_rate)
                    barge_window.append(fresh16)
                    barge_buf = np.zeros(0, dtype=np.float32)
                    barge_tick += 1
                    word = barge_word(fresh16)
                    if word:
                        barge_window.clear()
                        stop_speaking()
                        rec.Reset()
                        if word in words:
                            # «Джарвис» поверх ответа — замолчать и слушать новую команду.
                            print(">> BARGE-IN  //  AWAITING ORDERS")
                            LISTENING.set()
                            armed_until = time.monotonic() + follow_up
                            events.put(("wake", "visual"))
                        else:
                            print(f">> BARGE-IN  //  {word.upper()}")
                            LISTENING.clear()
                            armed_until = 0.0
                            events.put(("listen_timeout", None))
            continue
        if barge_window or len(barge_buf):
            barge_window.clear()
            barge_buf = np.zeros(0, dtype=np.float32)
            if barge_rec is not None:
                barge_rec.Reset()
            else:
                spotter.reset(barge_stream)

        buf = np.concatenate((buf, block))
        if len(buf) < CHUNK:
            continue
        x = _resample_for_vosk(buf, cap.sample_rate)
        buf = np.zeros(0, dtype=np.float32)

        pcm = (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        # Гейт: пока тишина, кадры в декодер не идут. Ещё vad_hangover секунд
        # после последней речи кормим — иначе vosk не закроет фразу и не отдаст
        # финальный результат.
        flush = False
        if vad_on:
            level = float(np.sqrt(np.mean(x * x)))
            levels.append(level)
            if vad is not None:
                voiced = vad.speech(x)
            else:
                # Нижний перцентиль, а не медиана: после длинной фразы медиана
                # уезжает на уровень речи, и гейт закрывается посреди следующей.
                floor = max(float(np.percentile(levels, 20)), 1e-5)
                threshold = floor * vad_factor
                if speech_levels:
                    threshold = max(threshold, float(np.median(speech_levels)) * vad_speech_ratio)
                voiced = level > threshold
            if voiced:
                last_voice = time.monotonic()
                if LISTENING.is_set() and follow_up > 0:
                    armed_until = last_voice + follow_up
                utterance_peak = max(utterance_peak, level)
            elif time.monotonic() - last_voice > (
                    # В длинной просьбе люди делают паузы на запятых: не резать её на куски.
                    max(vad_hangover, 0.8) if LISTENING.is_set() and len(utterance) * CHUNK > 2.0 * cap.sample_rate
                    else vad_hangover):
                utterance_peak = 0.0
                if not in_utterance:
                    preroll.append(x)
                    continue
                # Речь кончилась — закрываем фразу сами. Эндпоинтеру vosk
                # после одиночного слова или вопроса нужно больше тишины, чем
                # гейт ему отдаёт, и фраза иначе так и не закрылась бы.
                flush = True

        if spotter is not None and not (LISTENING.is_set() or pending or CONFIRMATIONS.active() or kws_woke):
            # Ждём имени: звук слушает только KWS, vosk не декодирует.
            if not vosk_idle:
                vosk_idle = True
                rec.Reset()
                spotter.reset(kws_stream)
                utterance.clear()
                in_utterance = False
                kws_quick = None
            if flush:
                fresh = [np.zeros(VOSK_SR // 2, dtype=np.float32)]   # дожать хвост слова
            else:
                fresh = ([*preroll] if not in_utterance else []) + [x]
                utterance.extend(fresh)
            preroll.clear()
            in_utterance = not flush
            hits = []
            for chunk in fresh:
                hits += spotter.feed(kws_stream, chunk)
            kws_quick = next((h[2:] for h in hits if h.startswith("q:")), kws_quick)
            if any(h.startswith("w:") for h in hits):
                print(">> WAKE WORD  //  AWAITING ORDERS")
                events.put(("wake", "visual"))
                remember_speech_level()
                LISTENING.set()
                armed_until = time.monotonic() + follow_up
                woke_on_partial = kws_woke = True
                vosk_idle = False
                kws_quick = None
                # Имя и команда на одном дыхании: отдать распознаванию фразу с начала.
                rec.Reset()
                for chunk in utterance:
                    rec.AcceptWaveform(pcm16(chunk))
                if not flush:
                    continue
                # Фраза уже кончилась — дальше обычным путём, как у vosk.
            else:
                if flush:
                    audio = np.concatenate(utterance) if utterance else np.zeros(0, dtype=np.float32)
                    utterance.clear()
                    spotter.reset(kws_stream)
                    if kws_quick and quick_on:
                        quick_heard(kws_quick, audio)
                    kws_quick = None
                continue
        vosk_idle = False

        if not in_utterance and preroll and not flush:
            # Детектор речи срабатывает с опозданием на долю секунды — начало
            # слова лежит в предыдущих кусках. Отдать их распознаванию первыми.
            for early_x in preroll:
                rec.AcceptWaveform((np.clip(early_x, -1.0, 1.0) * 32767).astype(np.int16).tobytes())
                utterance.append(early_x)
            preroll.clear()
        if not flush:
            utterance.append(x)

        if flush:
            in_utterance = False
            HEARING.clear()
            text = json.loads(rec.FinalResult()).get("text", "")
        elif not rec.AcceptWaveform(pcm):
            in_utterance = True
            if LISTENING.is_set():
                HEARING.set()
            # Финального результата ждать ещё долго: обращение ловим по
            # частичному, иначе окно открывается почти на секунду позже.
            if not woke_on_partial and not LISTENING.is_set() and not pending:
                partial = json.loads(rec.PartialResult()).get("partial", "")
                if partial and match(partial, words, commands)[0]:
                    print(">> WAKE WORD  //  AWAITING ORDERS")
                    # Пока только окно. «Да, сэр» прозвучит, когда станет ясно,
                    # что человек замолчал: иначе ответ заглушит микрофон и
                    # обрежет команду, сказанную на одном дыхании.
                    events.put(("wake", "visual"))
                    remember_speech_level()
                    LISTENING.set()
                    armed_until = time.monotonic() + follow_up
                    woke_on_partial = True
            continue
        else:
            in_utterance = False
            HEARING.clear()
            text = json.loads(rec.Result()).get("text", "")
        audio = np.concatenate(utterance) if utterance else np.zeros(0, dtype=np.float32)
        utterance.clear()
        kws_called, kws_woke = kws_woke, False
        if not text:
            if kws_called:
                woke_on_partial = False
                events.put(("wake", "voice"))      # одно имя, vosk ничего не разобрал
            continue
        # A partial Vosk wake also establishes a boundary. Its final transcript
        # may omit the name; that must not authorize earlier speech as a request.
        text = strip_ack(refine(text, audio, kws_called or woke_on_partial), config)
        if STOP_LISTENING.is_set() or not text:
            continue
        # «Стоп» в разговоре — оборвать всё и закрыться сразу: и когда Джарвис
        # ждёт команду, и пока думает, и после «Джарвис, стоп». Без нейросети.
        heard_now, _cmd, rest_now = match(text, words, commands)
        stop_now = text.strip() in STOP_WORDS or (heard_now and rest_now.strip(" ,.!") in STOP_WORDS)
        if stop_now and (LISTENING.is_set() or THINKING.is_set() or heard_now or kws_called):
            print(f">> STOP  //  {text}")
            CONFIRMATIONS.clear()
            stop_speaking()
            events.put(("interrupt", None))
            events.put(("listen_timeout", None))      # закрыть окно и разговор
            LISTENING.clear()
            armed_until = 0.0
            woke_on_partial = False
            continue
        # «Перестань говорить» — только замолчать; «отмени задачу» — бросить дело.
        # В обоих случаях разговор продолжается (в отличие от «стоп»).
        soft = SOFT_STOP.get((rest_now if heard_now else text).strip(" ,.!"))
        if soft and (LISTENING.is_set() or THINKING.is_set() or SPEAKING.is_set() or heard_now):
            print(f">> {soft.upper()}  //  {text}")
            stop_speaking()
            if soft == "cancel":
                CONFIRMATIONS.clear()
                events.put(("interrupt", None))
            LISTENING.set()
            armed_until = (time.monotonic() + follow_up) if follow_up > 0 else 0.0
            continue
        if verbose:
            state = "жду команду" if armed() else "жду обращения"
            print(f"   [слышу] {text!r}   ({state})")

        # Узнавание хозяина (по желанию): чужой голос — из голосового чата, стрима,
        # YouTube — не командует компьютером. Проверяем только фразы для Джарвиса.
        called_now = match(text, words, commands)[0]
        if (owner_check and (called_now or armed() or CONFIRMATIONS.active()
                             or (quick_on and text.strip() in QUICK))
                and not speaker.is_owner(audio, config)):
            woke_on_partial = False
            mode = ((wake.get("owner") or {}).get("mode") or "soft")
            print(f">> GUEST VOICE  //  {text}")
            if mode != "strict":
                question = match(text, words, commands)[2] if called_now else text
                if len(question.strip()) > 2:
                    events.put(("guest", question.lower()))
            else:
                events.put(("guest_ignored", text))
            continue

        from shelter_core import avatar_motion
        if avatar_motion.active_stop(text):
            events.put(("interrupt", None))
            continue
        kind, confirmed = CONFIRMATIONS.resolve(text, config)
        if kind:
            events.put((kind, confirmed))
            if confirmed:
                finish_command(confirmed)
            continue

        heard, command, rest = match(text, words, commands)
        if heard and THINKING.is_set():
            if set(rest.split()) & set(STOP_WORDS):
                events.put(("interrupt", None))       # «Джарвис, стоп» — прервать
                LISTENING.clear()
                continue
            if not rest and not command:
                woke_on_partial = False
                continue                              # просто имя — текущий ответ не сбивать
            # Новая просьба с именем: прежняя доделывается, новая встаёт в очередь (ask).
        early = woke_on_partial      # обращение уже отработало по частичному
        woke_on_partial = False
        if heard:
            if command:
                pending, pending_until = accept(command, text)
            elif rest:
                if not early:
                    events.put(("wake", "visual"))
                    LISTENING.set()
                ask(rest)
            elif early:
                events.put(("wake", "voice"))
            else:
                # Позвали без команды — ждём её следующей фразой.
                print(">> WAKE WORD  //  AWAITING ORDERS")
                events.put(("wake", None))
                remember_speech_level()
                LISTENING.set()
                armed_until = (time.monotonic() + follow_up) if follow_up > 0 else 0.0
            continue

        # Пауза между "Джарвис" и командой заставляет vosk отдать их двумя
        # фразами: во второй обращения уже нет, поэтому ловим её по окну.
        if armed():
            command = find_command(text.lower(), commands)
            if command:
                pending, pending_until = accept(command, text)
            elif len(text) > 2:
                ask(text.lower())
        elif quick_on and not pending and text.strip() in QUICK:
            action = QUICK[text.strip()]
            # Короткое слово легко услышать в шуме — GigaAM должен подтвердить.
            if giga is not None and QUICK.get(asr.transcribe(audio)) != action:
                continue
            print(f">> QUICK  //  {text}")
            events.put(("quick", action))
