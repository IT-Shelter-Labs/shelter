"""Жесты и танец: команды без LLM, оценка ритма без сохранения аудио."""
import re
import threading
import time
import uuid
import json
from collections import deque

import numpy as np

GESTURES = {
    "sit-window": ("сядь на окно", "сядь на край окна", "присядь на окно"),
    "sit-taskbar": ("сядь на панель задач", "присядь у панели задач"),
    "stand": ("встань", "поднимись", "перестань сидеть"),
    "wave": ("помаши", "помаши рукой", "помаши мне рукой", "поприветствуй меня"),
    "nod": ("кивни", "кивни мне", "кивни головой"),
    "bow": ("поклонись", "сделай поклон"),
    "dance": ("танцуй", "потанцуй", "начни танцевать", "танцуй под музыку", "танцуй под бит"),
    "stop": ("хватит танцевать", "перестань танцевать", "останови танец", "останови анимацию", "стоп", "остановись", "хватит", "стоп танец"),
}


def active_stop(text):
    from avatar import AVATAR
    return AVATAR.motion_active and text.lower().strip(" .!?,") in GESTURES["stop"]


def resize_command(text):
    q = text.lower().replace("ё", "е").strip(" .!?,")
    q = re.sub(r"\s+", " ", q)
    q = re.sub(r"^пожалуйста[, ]+", "", q)
    q = re.sub(r"[, ]+пожалуйста$", "", q)
    if re.search(r"\b(?:не|как|почему)\b", q):
        return None
    q = q.replace("вдвое", "в два раза").replace("втрое", "в три раза")
    q = re.sub(r"\bувеличься\b", "увеличь себя", q)
    q = re.sub(r"\bуменьшись\b", "уменьши себя", q)
    q = re.sub(r"\b(?:крупнее|побольше)\b", "больше", q)
    q = re.sub(r"\b(?:поменьше|мельче)\b", "меньше", q)
    q = re.sub(r"^будь\b", "стань", q)
    subject = r"(?: (?:себя|модельку|модель|персонажа|размер))?"
    absolute = re.fullmatch(r"(?:(?:установи|поставь|сделай) )?(?:размер|масштаб)(?: модели| персонажа)?(?: на| в)? (.+?)(?:\s*%| процентов| процента| процент)?", q)
    if not absolute:
        absolute = re.fullmatch(r"(?:увеличь|уменьши|сделай)" + subject + r" до (.+?)(?:\s*%| процентов| процента| процент)?", q)
    if absolute:
        value = _size_number(absolute[1])
        return {"scale": value / 100} if value is not None else None
    relative = re.fullmatch(r"(увеличь|уменьши)" + subject + r" на (.+?)(?:\s*%| процентов| процента| процент)", q)
    if relative:
        value = _size_number(relative[2])
        return {"factor": 1 + (value / 100 if relative[1] == "увеличь" else -value / 100)} if value is not None else None
    multiple = re.fullmatch(r"(?:увеличь|уменьши|стань|сделай)" + subject + r"(?: больше| меньше)? в (.+?) раз(?:а)?(?: больше| меньше)?", q)
    if multiple:
        value = _size_number(multiple[1])
        if value is not None and value > 0:
            return {"factor": 1 / value if "уменьши" in q or "меньше" in q else value}
    if re.fullmatch(r"(?:увеличь|увеличивай)(?: себя| модель| модельку| персонажа)?|(?:стань|сделай себя) (?:немного |чуть )?больше", q):
        return {"delta": 0.1}
    if re.fullmatch(r"(?:уменьши|уменьшай)(?: себя| модель| модельку| персонажа)?|(?:стань|сделай себя) (?:немного |чуть )?меньше", q):
        return {"delta": -0.1}
    return None


def _size_number(text):
    if re.fullmatch(r"\d+(?:[.,]\d+)?", text):
        return float(text.replace(",", "."))
    import tools
    words = {**tools._NUMBERS, "полтора": 1.5, "двести": 200, "триста": 300, "четыреста": 400,
             "пятьсот": 500, "тысяча": 1000, "двенадцать": 12, "одиннадцать": 11}
    parts = text.split()
    return sum(words[p] for p in parts) if parts and all(p in words for p in parts) else None


def resize(config, delta=None, *, scale=None, factor=None):
    from avatar import AVATAR
    import personas
    import bus
    import tasks
    values = [v for v in (delta, scale, factor) if v is not None]
    if not AVATAR.builtin or len(values) != 1 or type(values[0]) not in (int, float) or not np.isfinite(values[0]):
        raise ValueError("Укажите один способ изменения размера: процент, множитель или шаг.")
    persona = config["persona"]
    old = (persona.get("avatar") or {}).get("scale", 1)
    requested = scale if scale is not None else old * factor if factor is not None else old + delta
    if delta is None and not 0.2 <= requested <= 4:
        raise ValueError("Размер персонажа — от 20 до 400 процентов.")
    size = round(max(0.2, min(4, requested)), 3)
    personas.set_size(persona["id"], size)
    persona.setdefault("avatar", {})["scale"] = size
    AVATAR.configure(config)
    AVATAR.start(dialogue=False)
    tasks.continue_dialogue()
    bus.publish("persona", persona=personas.public(personas.get(persona["id"])))
    return f"Размер — {size * 100:g} процентов."


def command(text, persona):
    q = re.sub(r"[.!?,]+$", "", text.lower().strip()).replace("ё", "е")
    if re.search(r"\b(?:не|как|почему|расскажи|объясни)\b", q):
        return None
    # «Помаши мне ручкой, милашка» — да; «когда я скажу пока, ты мне помаши» — это
    # уже инструкция на будущее, её разбирает модель.
    if (len(q.split()) <= 5 and re.search(r"\b(?:помаши|помахай|помахивай)\b", q)
            and not re.search(r"\b(?:и|затем|потом|когда|если|скажу)\b", q)):
        return {"animation": "wave", "beat": False}
    for name, phrases in GESTURES.items():
        if q in phrases:
            return {"animation": name, "beat": "под бит" in q or "под музыку" in q}
    for item in persona.get("animations", []):
        if q in [p.lower().strip().replace("ё", "е") for p in item.get("phrases", [])]:
            return {"animation": item["id"], "beat": False}
    match = re.fullmatch(r"танцуй (?:в темпе|под) (\d{2,3})(?: (?:bpm|ударов в минуту))?", q)
    if match and 50 <= int(match[1]) <= 200:
        return {"animation": "dance", "bpm": int(match[1]), "beat": False}
    return None


POSITIONS = ("center", "left", "right", "top-left", "top-right", "bottom-left", "bottom-right", "home")


def movement(text):
    q = text.lower().replace("ё", "е").strip(" .!?,")
    if re.fullmatch(r"(?:встань|вернись|перейди|верни себя) (?:в |на )?(?:свое |тво[её] )?(?:исходное (?:положение|место)|начальное (?:положение|место)|место по умолчанию|свое место|место)", q):
        return {"monitor": 1, "position": "home"}
    if not re.match(r"^(?:пожалуйста[, ]+)?(?:перейди|переходи|переместись|переберись|встань|иди)\b", q):
        return None
    monitor = 0
    match = re.search(r"(?:на|в)\s+(перв\w*|основн\w*|втор\w*|трет\w*|четверт\w*|\d+)\s+(?:монитор|экран)", q)
    if match:
        word = match[1]
        monitor = int(word) if word.isdigit() else next((n for prefix, n in (("перв", 1), ("основн", 1), ("втор", 2), ("трет", 3), ("четверт", 4)) if word.startswith(prefix)), 0)
    position = "center" if re.search(r"центр|середин", q) else "bottom-right"
    side = "left" if re.search(r"лев", q) else "right" if re.search(r"прав", q) else ""
    if side:
        position = ("top-" if re.search(r"верх", q) else "bottom-" if re.search(r"низ|ниж|угол", q) else "") + side
    if not match and not side and position != "center":
        return None
    return {"monitor": monitor, "position": position}


def move(config, monitor=0, position="center"):
    from avatar import AVATAR
    if not AVATAR.builtin:
        raise ValueError("Передвигаться по экрану может персонаж с 3D-моделью.")
    if type(monitor) is not int or not 0 <= monitor <= 16 or position not in POSITIONS:
        raise ValueError("Неверный монитор или положение")
    BEAT.stop()
    AVATAR.start(dialogue=False)
    motion_id = uuid.uuid4().hex
    AVATAR.hold_motion(300, motion_id)  # окно живёт до подтверждения прибытия
    import bus
    bus.publish("avatar_move", monitor=monitor, position=position, motion_id=motion_id)
    return "Перехожу."


def catalog(config):
    return [{"id": name, "name": phrases[0]} for name, phrases in GESTURES.items()] + [
        {"id": item["id"], "name": item.get("name", item["id"]), "phrases": item.get("phrases", [])}
        for item in (config.get("persona") or {}).get("animations", [])]


def execute(config, argument):
    """Единая граница для тегового и native tool calling; модель выбирает только существующие id."""
    if argument.strip().startswith("{"):
        data = json.loads(argument)
        if not isinstance(data, dict):
            raise ValueError("нужен объект действия")
        if data.get("action") == "move":
            return move(config, data.get("monitor", 0), data.get("position", "center"))
        if data.get("action") == "resize":
            return resize(config, data.get("delta"), scale=data.get("scale"), factor=data.get("factor"))
        return perform(config, str(data.get("action", "")), data.get("bpm"), data.get("beat", False))
    parts = [p.strip() for p in argument.split("|")]
    if parts[0] in ("size", "scale"):
        return resize(config, **({"scale": float(parts[1]) / 100} if parts[0] == "size" else {"factor": float(parts[1])}))
    if parts[0] == "resize":
        return resize(config, float(parts[1]))
    if parts[0] == "move":
        return move(config, int(parts[1]) if len(parts) > 1 else 0, parts[2] if len(parts) > 2 else "center")
    return perform(config, parts[0], float(parts[2]) if len(parts) > 2 else None, len(parts) > 1 and parts[1] == "beat")


def perform(config, animation, bpm=None, beat=False):
    from avatar import AVATAR
    if not AVATAR.builtin:
        raise ValueError("Сначала выберите персонажа с 3D-моделью в разделе «Персонаж».")
    persona = config.get("persona") or {}
    custom = next((item for item in persona.get("animations", []) if item["id"] == animation), None)
    custom = custom or next((item for item in persona.get("animations", []) if item.get("role") == animation), None)
    if animation in ("sit-window", "sit-taskbar", "stand"):
        import bus
        BEAT.stop()
        AVATAR.hold_motion(0)
        AVATAR.set_seated(animation != "stand")
        bus.publish("avatar_seat", surface={"sit-window": "window", "sit-taskbar": "taskbar", "stand": "stand"}[animation])
        return "Проверю свободное место для посадки." if animation != "stand" else "Встаю."
    if animation not in GESTURES and custom is None:
        raise ValueError("Нет такой анимации у этого персонажа")
    if type(beat) is not bool:
        raise ValueError("Синхронизация с музыкой: логическое значение")
    value = float(bpm if bpm is not None else (persona.get("avatar") or {}).get("bpm", 120))
    if not np.isfinite(value) or not 50 <= value <= 200:
        raise ValueError("Темп: от 50 до 200 ударов в минуту")
    BEAT.stop()
    motion_id = uuid.uuid4().hex if animation != "stop" else ""
    if animation != "stop":
        durations = {"wave": 5.3, "nod": 1.2, "bow": 4, "dance": 1800}
        AVATAR.hold_motion(durations.get(animation, 1800 if (custom or {}).get("loop") else 600), motion_id)
    else:
        AVATAR.set_seated(False)
        AVATAR.hold_motion(0)
    import bus
    bus.publish("avatar_motion", animation=animation, motion_id=motion_id, bpm=value, file=(custom or {}).get("file", ""),
                loop=bool((custom or {}).get("loop", False)))
    if animation == "dance" and beat:
        BEAT.start()
    return "Хорошо." if animation != "stop" else "Остановилась." if persona.get("gender") == "f" else "Остановился."


class BeatTracker:
    """Оценка периода по огибающей энергии, а не обещание точного анализа музыки."""
    def __init__(self):
        self.energy = deque(maxlen=160)       # восемь секунд, 20 Гц
        self.count = 0

    def feed(self, rms):
        self.energy.append(max(0, float(rms)))
        self.count += 1
        if len(self.energy) < 80 or self.count % 10:
            return None
        energy = np.asarray(self.energy)
        if energy.max() < 0.003:
            return None
        flux = np.maximum(0, np.diff(energy))
        if flux.max() < 0.001:
            return None
        flux -= flux.mean()
        lags = np.arange(6, 25)              # 50–200 BPM при 20 Гц
        corr = np.array([np.dot(flux[:-lag], flux[lag:]) for lag in lags])
        i = int(np.argmax(corr))
        if corr[i] <= np.dot(flux, flux) * 0.2:
            return None
        lag = int(lags[i])
        # Последний пик задаёт фазу: сколько секунд прошло с удара.
        last = int(np.argmax(energy[-lag:]))
        return {"bpm": round(1200 / lag, 1), "age": (lag - last - 1) / 20}


class BeatFollower:
    def __init__(self):
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def start(self):
        self.stop()
        self._stop = threading.Event()
        threading.Thread(target=self._listen, args=(self._stop,), name="avatar-beat", daemon=True).start()

    @staticmethod
    def _listen(stop):
        import bus
        try:
            import soundcard as sc
            from audio import SPEAKING
            tracker = BeatTracker()
            deadline = time.monotonic() + 30 * 60
            while not stop.is_set() and time.monotonic() < deadline:
                speaker = sc.default_speaker()
                loop = sc.get_microphone(str(speaker.id), include_loopback=True)
                with loop.recorder(samplerate=16000, blocksize=800) as recorder:
                    checked = time.monotonic()
                    while not stop.is_set() and time.monotonic() < deadline:
                        samples = recorder.record(numframes=800)
                        energy = 0 if SPEAKING.is_set() else float(np.sqrt(np.mean(samples ** 2)))
                        result = tracker.feed(energy)
                        if result:
                            bus.publish("avatar_beat", **result)
                        if time.monotonic() - checked > 3:
                            checked = time.monotonic()
                            if sc.default_speaker().id != speaker.id:
                                break
        except Exception as error:
            bus.publish("avatar_notice", text="Ритм недоступен: танцую в выбранном темпе. " + str(error)[:120])


BEAT = BeatFollower()
