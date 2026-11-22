"""Таймеры и напоминания, которые переживают перезапуск.

«Таймер на 10 минут», «напомни через час позвонить маме», «напомни завтра в
9 про встречу», «каждый будний день в 8:30 напоминай выпить таблетку».
Всё лежит в data/schedule.json. Если Джарвис был выключен, когда что-то
должно было сработать, он скажет об этом при следующем запуске (если прошло
не больше 12 часов).
"""

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(ROOT, "data", "schedule.json")
STALE = 12 * 3600          # пропущенное дольше — уже неактуально

_lock = threading.Lock()
_items = None
_fire = None

DAY_WORDS = {
    "пн": 0, "понедельник": 0, "вт": 1, "вторник": 1, "ср": 2, "среда": 2, "среду": 2,
    "чт": 3, "четверг": 3, "пт": 4, "пятница": 4, "пятницу": 4, "сб": 5, "суббота": 5,
    "субботу": 5, "вс": 6, "воскресенье": 6,
}


def _load():
    global _items
    if _items is None:
        try:
            with open(PATH, encoding="utf-8") as file:
                _items = json.load(file).get("items", [])
        except (OSError, ValueError):
            _items = []
    return _items


def _save():
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    temporary = PATH + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump({"items": _items}, file, ensure_ascii=False, indent=1)
    os.replace(temporary, PATH)
    import bus
    bus.publish("timers", items=[dict(i) for i in _items if i.get("kind") == "timer"])


def parse_days(text):
    """«будни», «каждый день», «пн, ср», «завтра», «сегодня» -> (дни недели | None, сдвиг в днях)."""
    text = (text or "").strip().lower()
    if not text or text in ("сегодня", "once", "однажды", "один раз"):
        return None, 0
    if "послезавтра" in text:
        return None, 2
    if "завтра" in text:
        return None, 1
    if any(w in text for w in ("каждый день", "ежедневно", "daily", "всегда", "каждое утро", "каждый вечер")):
        return list(range(7)), 0
    if "будн" in text or "weekday" in text:
        return [0, 1, 2, 3, 4], 0
    if "выходн" in text or "weekend" in text:
        return [5, 6], 0
    days = sorted({DAY_WORDS[w] for w in re.findall(r"[а-яё]+", text) if w in DAY_WORDS})
    if days:
        # «в пятницу» — один раз, «каждую пятницу», «по пятницам» — повтор.
        repeat = any(w in text for w in ("кажд", "по ", "пятницам", "понедельникам"))
        if repeat:
            return days, 0
        today = datetime.now().weekday()
        return None, (days[0] - today) % 7
    return None, 0


def parse_clock(text):
    """«9», «9:30», «21.15», «в 8 утра» -> (часы, минуты) или None."""
    match = re.fullmatch(r"\s*(?:в\s+)?(\d{1,2})(?:[:.](\d{2}))?(?:\s+(?:утра|дня|вечера|ночи))?\s*", str(text))
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    if "вечер" in str(text) and hour < 12:
        hour += 12
    return (hour, minute) if 0 <= hour < 24 and 0 <= minute < 60 else None


def _next_due(hour, minute, days, shift=0, after=None):
    now = after or datetime.now()
    base = (now + timedelta(days=shift)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if days is None:
        if base <= now:
            base += timedelta(days=1)
        return base.timestamp()
    for add in range(8):
        candidate = base + timedelta(days=add)
        if candidate.weekday() in days and candidate > now:
            return candidate.timestamp()
    return (base + timedelta(days=1)).timestamp()


def timers():
    with _lock:
        return [dict(i) for i in _load() if i.get("kind") == "timer"]


def all_items():
    """Таймеры и повторяющиеся напоминания — для карточки на главной."""
    with _lock:
        return [dict(i) for i in _load()]


def add_timer(seconds, label=""):
    """Таймер: через seconds секунд."""
    item = {"id": uuid.uuid4().hex[:8], "due": time.time() + max(1, float(seconds)),
            "label": label.strip(), "kind": "timer"}
    with _lock:
        _load().append(item)
        _save()
    return item


def add_reminder(clock, days_text, label):
    """Напоминание на время: разово или по дням недели. None — время не понял."""
    parsed = parse_clock(clock)
    if parsed is None:
        return None
    days, shift = parse_days(days_text)
    item = {"id": uuid.uuid4().hex[:8], "due": _next_due(*parsed, days, shift),
            "label": label.strip(), "kind": "reminder",
            "repeat": {"time": f"{parsed[0]:02d}:{parsed[1]:02d}", "days": days} if days else None}
    with _lock:
        _load().append(item)
        _save()
    return item


def cancel_id(item_id):
    """Отменить одно напоминание кнопкой в окне. -> True, если было."""
    with _lock:
        items = _load()
        keep = [i for i in items if i.get("id") != item_id]
        if len(keep) == len(items):
            return False
        items[:] = keep
        _save()
    return True


def cancel(query=""):
    """Отменить подходящие по словам (или все, если запрос пустой/«все»). Вернуть число."""
    words = set(re.findall(r"[а-яёa-z0-9]{3,}", (query or "").lower()))
    timers = {w for w in words if w.startswith("таймер")}
    reminders = {w for w in words if w.startswith(("напомин", "будильн"))}
    topic = words - timers - reminders - {"все", "всё", "всех", "all"}
    with _lock:
        items = _load()
        if topic:                                     # «отмени напоминание про маму»
            keep = [i for i in items if not (topic & set(re.findall(r"[а-яёa-z0-9]{3,}", i["label"].lower())))]
        elif timers and not reminders:                # «отмени таймер»
            keep = [i for i in items if i["kind"] != "timer"]
        elif reminders and not timers:                # «отмени напоминания»
            keep = [i for i in items if i["kind"] != "reminder"]
        else:                                         # «отмени всё»
            keep = []
        removed = len(items) - len(keep)
        if removed:
            items[:] = keep
            _save()
    return removed


def _spoken_time(timestamp):
    moment = datetime.fromtimestamp(timestamp)
    today = datetime.now().date()
    day = "сегодня" if moment.date() == today else (
        "завтра" if moment.date() == today + timedelta(days=1) else moment.strftime("%d.%m"))
    return f"{day} в {moment:%H:%M}"


def describe():
    """Список для ответа «какие у меня таймеры / напоминания»."""
    with _lock:
        items = sorted(_load(), key=lambda i: i["due"])
    if not items:
        return "Таймеров и напоминаний нет, сэр."
    parts = []
    for item in items[:6]:
        left = item["due"] - time.time()
        if item["kind"] == "timer":
            minutes = max(1, round(left / 60))
            what = f"таймер{(' «' + item['label'] + '»') if item['label'] else ''}: осталось {minutes} мин"
        else:
            what = f"«{item['label']}» {_spoken_time(item['due'])}"
            if item.get("repeat"):
                what += " (повторяется)"
        parts.append(what)
    return "У вас " + "; ".join(parts) + "."


def today():
    """Напоминания на сегодня — для утренней сводки."""
    end = datetime.now().replace(hour=23, minute=59, second=59).timestamp()
    with _lock:
        return [i for i in sorted(_load(), key=lambda i: i["due"]) if i["due"] <= end and i["kind"] == "reminder"]


def _tick():
    now = time.time()
    fired = []
    with _lock:
        items = _load()
        keep = []
        for item in items:
            if item["due"] > now:
                keep.append(item)
                continue
            missed = now - item["due"] > 60
            if now - item["due"] <= STALE:
                fired.append((item, missed))
            repeat = item.get("repeat")
            if repeat:
                hour, minute = map(int, repeat["time"].split(":"))
                item["due"] = _next_due(hour, minute, repeat["days"])
                keep.append(item)
        if len(keep) != len(items) or fired:
            items[:] = keep
            _save()
    for item, missed in fired:
        try:
            _fire(item, missed)
        except Exception as error:
            print(f"[schedule] {error}")


def start(on_fire):
    """on_fire(item, missed) — сработало; missed — пока ассистент был выключен."""
    global _fire
    _fire = on_fire

    def loop():
        time.sleep(4.0)          # дать ассистенту подняться: пропущенное не должно потеряться
        while True:
            _tick()
            time.sleep(1.0)
    threading.Thread(target=loop, name="schedule", daemon=True).start()
