"""Точное распознавание речи (GigaAM v3) и нейросетевой детектор речи (Silero VAD).

vosk по-прежнему ловит слово «Джарвис» — он лёгкий и потоковый. А фразу,
обращённую к Джарвису, целиком переслушивает GigaAM v3 от Сбера: на русском
он ошибается в разы реже маленькой модели vosk. Работает на процессоре через
sherpa-onnx, фраза в 3 секунды распознаётся примерно за 0.1 с; фоновые
разговоры и звук игры через него не идут — только фразы для Джарвиса.

Silero VAD отличает речь от щелчков клавиатуры, выстрелов и музыки, поэтому
декодер не просыпается на шум, а конец фразы ловится раньше.

Нет sherpa-onnx или моделей — всё работает по-старому, на одном vosk.
"""

import difflib
import os
import re
import time

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
SR = 16000

_recognizer = None
_tried = False


class _PluginRecognizer:
    def __init__(self, profile):
        self.profile = dict(profile)


def _models_dir(cfg):
    path = cfg.get("model", "models/gigaam-v3")
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


def load(config):
    """Загрузить GigaAM один раз. None — нет пакета или модели."""
    global _recognizer, _tried
    if _tried:
        return _recognizer
    _tried = True
    cfg = config.get("asr") or {}
    if cfg.get("engine") == "plugin":
        import plugin_extensions
        plugin_extensions.configure(config)
        profile = cfg.get("plugin") or {}
        if not any(p["id"] == profile.get("id") for p in plugin_extensions.available("stt", config)):
            raise ValueError("выбранное дополнение распознавания недоступно")
        _recognizer = _PluginRecognizer(profile)
        return _recognizer
    if str(cfg.get("engine", "gigaam")).lower() != "gigaam":
        return None
    folder = _models_dir(cfg)
    # Сжатая (int8) версия, если есть: вдвое меньше памяти и быстрее на процессоре.
    files = {}
    for name in ("encoder", "decoder", "joiner"):
        quantized = os.path.join(folder, f"{name}.int8.onnx")
        files[name] = quantized if os.path.exists(quantized) else os.path.join(folder, f"{name}.onnx")
    tokens = os.path.join(folder, "tokens.txt")
    if not all(os.path.exists(p) for p in [*files.values(), tokens]):
        print(f">> ASR  //  GigaAM не найден в {folder} — распознаёт vosk (см. README)")
        return None
    try:
        import sherpa_onnx
        started = time.perf_counter()
        _recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=files["encoder"], decoder=files["decoder"], joiner=files["joiner"],
            tokens=tokens, model_type="nemo_transducer",
            # 1–2 потока: по замерам onnxruntime на всех ядрах распознаёт медленнее.
            num_threads=int(cfg.get("threads", 2)), decoding_method="greedy_search")
        print(f">> ASR  //  GigaAM v3 ONLINE  ({time.perf_counter() - started:.1f} с)")
    except Exception as error:
        print(f">> ASR  //  GigaAM не загрузился: {error} — распознаёт vosk")
        _recognizer = None
    return _recognizer


def normalize(text):
    """Как у vosk: строчные буквы, без знаков препинания, «ё» как есть."""
    text = re.sub(r"[^\w\s-]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def transcribe(samples):
    """float32 16 кГц -> текст; пустая строка, если распознавать нечем."""
    if _recognizer is None or len(samples) < SR // 5:
        return ""
    if isinstance(_recognizer, _PluginRecognizer):
        import plugin_extensions
        return normalize(plugin_extensions.transcribe(samples, _recognizer.profile))
    stream = _recognizer.create_stream()
    # Полсекунды тишины в хвосте: модели легче закончить последнее слово.
    stream.accept_waveform(SR, np.concatenate([samples, np.zeros(SR // 2, dtype=np.float32)]))
    _recognizer.decode_stream(stream)
    return normalize(stream.result.text)


def strip_wake(text, wake_words):
    """«джарвис открой браузер» -> «открой браузер».

    Сначала ищем точное имя, затем ограниченные варианты ошибок распознавания.
    Всё до обращения отбрасывается. Если имя не найдено, возвращаем исходный
    текст и False; вызывающий код обязан отдельно проверить право на команду.
    """
    tokens = text.split()
    clean = [t.lower().replace("ё", "е").strip(",.!?;:") for t in tokens]
    names = [str(w).lower().replace("ё", "е").split() for w in wake_words]
    for index in range(len(tokens)):
        for name in names:
            if name and clean[index:index + len(name)] == name:
                return " ".join(tokens[index + len(name):]), True
    for index, token in enumerate(clean):
        for name in names:
            if len(name) != 1 or min(len(token), len(name[0])) < 4:
                continue
            word = name[0]
            if token.startswith(word) and len(token) > len(word):
                continue  # «Джарвисом» is a persona target, not a fresh call.
            if abs(len(token)-len(word)) <= 2 and difflib.SequenceMatcher(None, token, word).ratio() >= .8:
                return " ".join(tokens[index + 1:]), True
    return text, False


def called_transcript(text, wake_words):
    """KWS alone authorizes listening, never unrelated pre-call transcript text."""
    rest, found = strip_wake(text, wake_words)
    return (str(wake_words[0]) + (" " + rest if found and rest else "")).strip()


# ------------------------------------------------------------------ VAD

class Vad:
    """Silero VAD через sherpa-onnx: есть ли речь в свежем куске звука."""

    def __init__(self, config):
        import sherpa_onnx
        cfg = (config.get("wake") or {}).get("vad") or {}
        path = cfg.get("model", "models/silero_vad.onnx")
        path = path if os.path.isabs(path) else os.path.join(ROOT, path)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        vad_config = sherpa_onnx.VadModelConfig()
        vad_config.silero_vad.model = path
        vad_config.silero_vad.threshold = float(cfg.get("threshold", 0.5))
        vad_config.silero_vad.min_silence_duration = float(cfg.get("min_silence", 0.25))
        vad_config.silero_vad.min_speech_duration = float(cfg.get("min_speech", 0.1))
        vad_config.silero_vad.window_size = 512
        vad_config.sample_rate = SR
        vad_config.num_threads = 1
        self._vad = sherpa_onnx.VoiceActivityDetector(vad_config, buffer_size_in_seconds=30)
        self._speech_samples = 0

    def speech(self, samples):
        """Скормить кусок 16 кГц; True — сейчас идёт речь."""
        self._vad.accept_waveform(samples.astype(np.float32))
        while not self._vad.empty():
            self._vad.pop()               # готовые отрезки не нужны — только состояние
        voiced = self._vad.is_speech_detected()
        # Детектор копит звук незаконченной речи. Долгая музыка или голосовой
        # чат переполнили бы буфер — после 20 с сплошной «речи» начать заново.
        self._speech_samples = self._speech_samples + len(samples) if voiced else 0
        if self._speech_samples > SR * 20:
            self._vad.reset()
            self._speech_samples = 0
        return voiced


def make_vad(config):
    cfg = (config.get("wake") or {}).get("vad") or {}
    if not isinstance(cfg, dict) or str(cfg.get("engine", "silero")).lower() != "silero":
        return None
    try:
        vad = Vad(config)
        print(">> VAD  //  Silero")
        return vad
    except Exception as error:
        print(f">> VAD  //  Silero недоступен ({error}) — энергетический гейт")
        return None
