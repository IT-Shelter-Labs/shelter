"""Начальные наборы сценариев: «Работа», «Учёба», «Стрим», «Музыка», шаблон своего режима.

Перед установкой — предпросмотр: какие программы найдены на этом компьютере,
каких нет и что придётся настроить. Отсутствующая программа не ломает набор:
её шаг выключается с пояснением, остальные сценарии ставятся как есть.
Параметры ({{music_url}}) подставляет человек в окне установки.
"""

import copy
import re

import scenarios

PACKS = [
    {
        "id": "work", "name": "Работа", "icon": "briefcase",
        "about": "Рабочий стол за одну фразу: почта, мессенджер, заметки и тишина.",
        "params": [],
        "requires": [{"app": "Telegram", "label": "Telegram", "optional": True},
                     {"app": "Obsidian", "label": "Obsidian или другие заметки", "optional": True}],
        "items": [
            {"name": "Рабочий режим", "category": "Режимы", "phrases": ["рабочий режим", "начинаю работу", "за работу"],
             "match": "whole",
             "steps": [{"type": "say", "text": "Готовлю рабочее место, сэр."},
                       {"type": "open_app", "target": "Telegram", "requires": "Telegram"},
                       {"type": "wait_for", "what": "window", "value": "Telegram", "timeout": 20, "requires": "Telegram"},
                       {"type": "window", "action": "place", "title": "Telegram", "monitor": 2, "position": "right", "requires": "Telegram"},
                       {"type": "open_app", "target": "Obsidian", "requires": "Obsidian"},
                       {"type": "volume", "value": 25}]},
            {"name": "Перерыв", "category": "Режимы", "phrases": ["перерыв", "сделаю перерыв"], "match": "whole",
             "steps": [{"type": "media", "key": "pause"}, {"type": "timer", "minutes": 10, "label": "перерыв закончился"},
                       {"type": "say", "text": "Отдыхайте, сэр. Напомню через десять минут."}]},
        ],
    },
    {
        "id": "study", "name": "Учёба", "icon": "graduation-cap",
        "about": "Фокус-сессия: таймер помидора, тихий звук и заметки.",
        "params": [],
        "requires": [{"app": "Obsidian", "label": "Obsidian или другие заметки", "optional": True}],
        "items": [
            {"name": "Фокус 25 минут", "category": "Учёба", "phrases": ["режим учебы", "помидор", "фокус"], "match": "whole",
             "steps": [{"type": "media", "key": "pause"}, {"type": "volume", "value": 20},
                       {"type": "open_app", "target": "Obsidian", "requires": "Obsidian"},
                       {"type": "timer", "minutes": 25, "label": "фокус-сессия закончилась, пора отдохнуть"},
                       {"type": "say", "text": "Двадцать пять минут фокуса, сэр. Не отвлекаю."}]},
        ],
    },
    {
        "id": "stream", "name": "Стрим", "icon": "radio",
        "about": "OBS и Discord на своих мониторах, музыка на паузе. Трансляцию запускаете вы — нарочно.",
        "params": [],
        "requires": [{"app": "OBS Studio", "label": "OBS Studio"}, {"app": "Discord", "label": "Discord", "optional": True}],
        "items": [
            {"name": "Подготовка к стриму", "category": "Стрим", "phrases": ["готовим стрим", "режим стрима"], "match": "whole",
             "confirm": "", "on_error": "continue",
             "steps": [{"type": "media", "key": "pause"},
                       {"type": "open_app", "target": "OBS Studio", "requires": "OBS Studio"},
                       {"type": "wait_for", "what": "window", "value": "OBS", "timeout": 40, "requires": "OBS Studio"},
                       {"type": "window", "action": "place", "title": "OBS", "monitor": 2, "position": "full", "requires": "OBS Studio"},
                       {"type": "open_app", "target": "Discord", "requires": "Discord"},
                       {"type": "say", "text": "Студия готова, сэр. Эфир запускаете вы."}]},
            {"name": "После стрима", "category": "Стрим", "phrases": ["стрим окончен", "конец стрима"], "match": "whole",
             "steps": [{"type": "window", "action": "close", "title": "OBS", "requires": "OBS Studio"},
                       {"type": "volume", "value": 35}, {"type": "say", "text": "Отличный эфир, сэр."}]},
        ],
    },
    {
        "id": "music", "name": "Музыка", "icon": "music",
        "about": "Свой плейлист голосом и музыка, когда подключаете наушники.",
        "params": [{"key": "music_url", "label": "Ссылка на плейлист", "default": "https://music.yandex.ru/",
                    "hint": "Spotify (spotify:playlist:…), Яндекс Музыка или YouTube"}],
        "requires": [],
        "items": [
            {"name": "Мой плейлист", "category": "Музыка", "phrases": ["мой плейлист", "включи мой плейлист"], "match": "whole",
             "steps": [{"type": "url", "url": "{{music_url}}"}, {"type": "wait", "seconds": 4}, {"type": "media", "key": "play"}]},
            {"name": "Наушники подключены", "category": "Музыка", "phrases": [], "enabled": False,
             "description": "Включите, если хотите музыку сразу после подключения наушников",
             "triggers": [{"type": "audio_added", "name": ""}, {"type": "button"}], "cooldown": 120,
             "steps": [{"type": "say", "text": "Наушники на месте, сэр."}, {"type": "media", "key": "play"}]},
        ],
    },
    {
        "id": "template", "name": "Свой режим", "icon": "wand-sparkles",
        "about": "Заготовка: фраза, программа, окно на мониторе. Поменяйте под себя.",
        "params": [{"key": "app", "label": "Главная программа", "default": "Блокнот"}],
        "requires": [],
        "items": [
            {"name": "Мой режим", "category": "Режимы", "phrases": ["мой режим"], "match": "whole",
             "steps": [{"type": "open_app", "target": "{{app}}"},
                       {"type": "wait_for", "what": "window", "value": "{{app}}", "timeout": 20},
                       {"type": "window", "action": "place", "title": "{{app}}", "monitor": 1, "position": "left"},
                       {"type": "say", "text": "Готово, сэр."}]},
        ],
    },
]


def _found(app):
    try:
        import tools
        return bool(tools.find_app(app))
    except Exception:
        return False


def catalog():
    """Наборы с предпросмотром: найденные и отсутствующие программы."""
    installed = {i.get("origin") for i in scenarios.load()}
    out = []
    for pack in PACKS:
        requires = [{**r, "found": _found(r["app"])} for r in pack["requires"]]
        out.append({k: v for k, v in pack.items() if k != "items"} | {
            "requires": requires, "installed": f"pack:{pack['id']}" in installed,
            "items": [{"name": i["name"], "phrases": i.get("phrases", []),
                       "steps": [scenarios.describe(s) for s in i["steps"]]} for i in pack["items"]]})
    return out


def _fill(value, params):
    if isinstance(value, str):
        return re.sub(r"\{\{(\w+)\}\}", lambda m: str(params.get(m[1], "")), value)
    if isinstance(value, list):
        return [_fill(v, params) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, params) for k, v in value.items()}
    return value


def install(pack_id, params=None, include=None):
    pack = next((p for p in PACKS if p["id"] == pack_id), None)
    if pack is None:
        raise scenarios.ScenarioError("нет такого набора")
    params = {p["key"]: (params or {}).get(p["key"]) or p.get("default", "") for p in pack["params"]}
    missing = {r["app"] for r in pack["requires"] if not _found(r["app"])}
    items = [i for i in scenarios.load() if i.get("origin") != f"pack:{pack_id}"]
    added, notes = [], []
    for index, raw in enumerate(pack["items"]):
        if include is not None and index not in include:
            continue
        item = _fill(copy.deepcopy(raw), params)
        for step in item["steps"]:
            need = step.pop("requires", None)
            if need in missing:
                step["enabled"] = False
                step["note"] = f"нет программы {need}"
                notes.append(f"«{item['name']}»: шаг «{scenarios.describe(step)}» выключен — не найдена {need}")
        item.setdefault("triggers", [{"type": "voice"}, {"type": "button"}])
        item = scenarios.normalize({**item, "id": f"pack_{pack_id}_{index}", "origin": f"pack:{pack_id}"})
        problems = scenarios.validate(item)
        if problems:
            notes.append(f"«{item['name']}» не установлен: {'; '.join(problems)}")
            continue
        items.append(item)
        added.append(item["name"])
    scenarios.save_all(items, f"перед установкой набора «{pack['name']}»")
    return {"added": added, "notes": notes}
