"""Сценарии — единый формат команд Джарвиса.

Один сценарий запускается голосом, кнопкой в окне, по расписанию, по событию
(«подключил наушники»), моделью-агентом и с телефона — везде одним и тем же
исполнителем. Формат версионируется (`format`/`version`), у каждого сценария
устойчивый `id`, поэтому переименование и перестановка ничего не ломают.

Хранится в data/scenarios.json. Прежние команды из config.yaml (`commands`)
переносятся сюда при первом запуске; исходный список сохраняется в
data/backups/, его можно вернуть кнопкой «Восстановить».

Типы шагов описаны в реестре ACTIONS: поля для формы в окне, подписи, проверка,
нужные права и поддержка ОС. Неизвестный тип или более новая версия формата
отклоняются с объяснением — молча ничего не пропускается.
"""

from shelter_core.paths import ROOT_DIR

import copy
import datetime
import hashlib
import json
import os
import re
import secrets as _secrets
import sys
import tempfile
import threading
import time
import webbrowser

from shelter_core import bus
from shelter_core import tasks

ROOT = ROOT_DIR
STORE = os.path.join(ROOT, "data", "scenarios.json")
BACKUPS = os.path.join(ROOT, "data", "backups")
FORMAT = "jarvis.scenario"
LIST_FORMAT = "jarvis.scenarios"
VERSION = 1
PLATFORM = "windows" if os.name == "nt" else "linux"
MAX_DEPTH = 4          # сценарий в сценарии — не глубже
MAX_REPEAT = 20
MAX_STEPS = 60

_lock = threading.RLock()
_config = {}
_persist = False        # писать на диск только после configure() из ядра: тесты и проверки не трогают data/
_run_tool = None        # main.run_tool(config, name, arg) — общий исполнитель инструментов
_switch_persona = None

# --------------------------------------------------------------- реестр

def _f(key, label, kind="text", **extra):
    return {"key": key, "label": label, "kind": kind, **extra}


MEDIA_KEYS = [["play", "Продолжить"], ["pause", "Пауза"], ["toggle", "Пауза / продолжить"],
              ["next", "Следующий трек"], ["prev", "Предыдущий трек"],
              ["volup", "Громче (в плеере)"], ["voldown", "Тише (в плеере)"]]
WINDOW_ACTIONS = [["focus", "Перейти к окну"], ["place", "Поставить на монитор"], ["minimize", "Свернуть"],
                  ["maximize", "Развернуть"], ["close", "Закрыть (как крестик)"]]
POSITIONS = [["full", "Весь экран"], ["left", "Левая половина"], ["right", "Правая половина"],
             ["top-left", "Левый верхний угол"], ["top-right", "Правый верхний угол"],
             ["bottom-left", "Левый нижний угол"], ["bottom-right", "Правый нижний угол"], ["center", "По центру"]]

# group — раздел в списке «Добавить шаг»; advanced — только в продвинутом режиме;
# safe_retry — повтор не навредит (повторное «поставь громкость 30» безопасно,
# повторная отправка сообщения — нет); irreversible — отменить нельзя.
ACTIONS = {
    "say": {"label": "Сказать фразу", "group": "Ответ", "icon": "message-square",
            "fields": [_f("text", "Что сказать", "textarea", required=True, max=500)]},
    "open_app": {"label": "Открыть программу", "group": "Программы", "icon": "app-window", "capability": "app",
                 "fields": [_f("target", "Программа", "app", required=True,
                               hint="Название как в меню «Пуск»: «Telegram», «OBS Studio»")]},
    "launch": {"label": "Запустить файл", "group": "Программы", "icon": "file-play", "capability": "app",
               "fields": [_f("path", "Файл или папка", "file", required=True),
                          _f("args", "Параметры запуска", "list", advanced=True,
                             hint="Каждый параметр отдельной строкой")]},
    "url": {"label": "Открыть сайт или ссылку", "group": "Программы", "icon": "globe", "capability": "app",
            "fields": [_f("url", "Адрес", "url", required=True, hint="https://… или spotify:playlist:…")]},
    "app": {"label": "Приложение Microsoft Store", "group": "Программы", "icon": "store", "capability": "app",
            "platforms": ["windows"], "advanced": True,
            "fields": [_f("id", "Идентификатор (AppUserModelID)", "text", required=True)]},
    "window": {"label": "Окно программы", "group": "Окна", "icon": "layout-panel-left", "safe_retry": True,
               "fields": [_f("action", "Что сделать", "select", options=WINDOW_ACTIONS, default="focus"),
                          _f("title", "Окно", "app", required=True, hint="Название программы или часть заголовка"),
                          _f("monitor", "Монитор", "monitor", default=1, show_if={"action": "place"}),
                          _f("position", "Место", "select", options=POSITIONS, default="full", show_if={"action": "place"})],
               "platforms": ["windows"]},
    "wait_for": {"label": "Дождаться окна или программы", "group": "Ожидание", "icon": "hourglass", "safe_retry": True,
                 "fields": [_f("what", "Чего ждать", "select", default="window",
                               options=[["window", "Появится окно"], ["process", "Запустится программа"],
                                        ["process_gone", "Программа закроется"]]),
                            _f("value", "Окно или программа", "app", required=True),
                            _f("timeout", "Ждать не дольше, с", "number", default=20, min=1, max=600)]},
    "wait": {"label": "Пауза", "group": "Ожидание", "icon": "timer",
             "fields": [_f("seconds", "Секунд", "number", default=2, min=0.1, max=3600, required=True)]},
    "media": {"label": "Музыка и видео", "group": "Звук", "icon": "music", "capability": "media", "safe_retry": True,
              "fields": [_f("key", "Действие", "select", options=MEDIA_KEYS, default="toggle"),
                         _f("process", "Плеер", "text", advanced=True, hint="Например Spotify.exe; пусто — любой, что играет"),
                         _f("delay", "Задержка перед нажатием, с", "number", default=0, min=0, max=60, advanced=True)]},
    "browser_episode": {"label": "Следующая серия в браузере", "group": "Звук", "icon": "film",
                        "capability": "media", "fields": [],
                        "hint": "Плеер в активном браузере должен поддерживать системную команду перехода."},
    "volume": {"label": "Громкость компьютера", "group": "Звук", "icon": "volume-2", "safe_retry": True,
               "fields": [_f("value", "Громкость, %", "range", default=30, min=0, max=100, required=True)]},
    "keys": {"label": "Нажать клавиши", "group": "Клавиатура", "icon": "keyboard", "platforms": ["windows"],
             "fields": [_f("combo", "Сочетание", "combo", required=True, hint="Например ctrl+shift+m или f11")]},
    "type_text": {"label": "Напечатать текст", "group": "Клавиатура", "icon": "type", "platforms": ["windows"],
                  "fields": [_f("text", "Текст", "textarea", required=True, max=2000)]},
    "timer": {"label": "Напоминание", "group": "Время", "icon": "alarm-clock",
              "fields": [_f("minutes", "Через сколько минут", "number", default=5, min=0.1, max=10080, required=True),
                         _f("label", "О чём напомнить", "text")]},
    "home": {"label": "Умный дом", "group": "Дом", "icon": "lightbulb", "capability": "smarthome",
             "fields": [_f("device", "Устройство", "device", required=True),
                        _f("state", "Состояние", "select", default="on",
                           options=[["on", "Включить"], ["off", "Выключить"], ["toggle", "Переключить"]])]},
    "avatar": {"label": "Движение персонажа", "group": "Персонаж", "icon": "person-standing",
               "fields": [_f("animation", "Движение", "animation", default="wave")]},
    "persona": {"label": "Сменить персонажа", "group": "Персонаж", "icon": "user-round",
                "fields": [_f("id", "Персонаж", "persona", required=True)]},
    "overlay": {"label": "Надпись на экране", "group": "Ответ", "icon": "panel-top", "advanced": True,
                "fields": [_f("text", "Надпись", "text", required=True, max=60),
                           _f("seconds", "Секунд", "number", default=5, min=0, max=120)]},
    "close": {"label": "Закрыть окно Джарвиса", "group": "Ответ", "icon": "x", "fields": []},
    "settings": {"label": "Открыть настройки Джарвиса", "group": "Ответ", "icon": "settings", "advanced": True, "fields": []},
    "ask": {"label": "Спросить нейросеть", "group": "Нейросеть", "icon": "brain", "capability": "llm",
            "hint": "Единственный шаг, где думает модель: пересказать погоду, найти и ответить.",
            "fields": [_f("text", "Вопрос", "textarea", required=True, max=1000)]},
    "tool": {"label": "Инструмент ассистента", "group": "Нейросеть", "icon": "wrench", "advanced": True,
             "fields": [_f("name", "Инструмент", "text", required=True), _f("arg", "Аргумент", "text")]},
    "scenario": {"label": "Запустить другой сценарий", "group": "Логика", "icon": "workflow",
                 "fields": [_f("id", "Сценарий", "scenario", required=True)]},
    "if": {"label": "Если… то… иначе", "group": "Логика", "icon": "split", "container": True,
           "fields": [_f("condition", "Условие", "condition", required=True)]},
    "repeat": {"label": "Повторить несколько раз", "group": "Логика", "icon": "repeat", "container": True,
               "fields": [_f("times", "Сколько раз", "number", default=2, min=1, max=MAX_REPEAT, required=True)]},
    "profile": {"label": "Профиль из config.yaml", "group": "Продвинутое", "icon": "layers", "advanced": True,
                "fields": [_f("name", "Профиль", "text", required=True)]},
    "plugin": {"label": "Действие дополнения", "group": "Дополнения", "icon": "puzzle", "capability": "plugins",
               "hint": "Дополнение работает в отдельном процессе с ограничением времени. Ставьте только те, которым доверяете.",
               "fields": [_f("name", "Дополнение", "plugin", required=True), _f("action", "Действие", "plugin_action"),
                          _f("params", "Параметры", "plugin_params")]},
    "shell": {"label": "Команда Windows", "group": "Продвинутое", "icon": "terminal", "advanced": True,
              "capability": "shell", "irreversible": True,
              "hint": "Выполняется как есть. Нужен «Разрешить команды оболочки» в настройках безопасности.",
              "fields": [_f("cmd", "Команда", "text", required=True)]},
    "riot": {"label": "Riot Client", "group": "Продвинутое", "icon": "gamepad-2", "advanced": True, "platforms": ["windows"],
             "fields": [_f("path", "RiotClientServices.exe", "file", required=True),
                        _f("timeout", "Ждать, с", "number", default=30, min=5, max=180)]},
}

CONDITIONS = {
    "time_between": {"label": "Время между", "fields": [_f("from", "С", "time", default="08:00"), _f("to", "До", "time", default="23:00")]},
    "days": {"label": "Дни недели", "fields": [_f("days", "Дни", "days", default=[0, 1, 2, 3, 4])]},
    "app_running": {"label": "Программа запущена", "fields": [_f("app", "Программа", "app", required=True)]},
    "app_not_running": {"label": "Программа не запущена", "fields": [_f("app", "Программа", "app", required=True)]},
    "window_open": {"label": "Открыто окно", "fields": [_f("title", "Окно", "app", required=True)], "platforms": ["windows"]},
    "on_battery": {"label": "Ноутбук работает от батареи", "fields": []},
    "charging": {"label": "Зарядка подключена", "fields": []},
    "online": {"label": "Есть интернет", "fields": []},
    "in_game": {"label": "Идёт игра", "fields": []},
    "monitors": {"label": "Мониторов не меньше", "fields": [_f("count", "Мониторов", "number", default=2, min=1, max=8)],
                 "platforms": ["windows"]},
    "last_step": {"label": "Предыдущий шаг", "fields": [_f("state", "Результат", "select", default="ok",
                                                         options=[["ok", "удался"], ["failed", "не удался"]])]},
}

# Когда запускать. Голос — фразы сценария, остальное — список triggers.
TRIGGERS = {
    "voice": {"label": "Голосом", "fields": []},
    "button": {"label": "Кнопкой в окне и с телефона", "fields": []},
    "schedule": {"label": "По расписанию", "fields": [_f("time", "Время", "time", default="09:00", required=True),
                                                      _f("days", "Дни", "days", default=[0, 1, 2, 3, 4]),
                                                      _f("missed", "Если компьютер был выключен", "select", default="skip",
                                                         options=[["skip", "пропустить"], ["run", "выполнить при запуске (до 6 часов)"]])]},
    "app_started": {"label": "Открылась программа", "fields": [_f("app", "Программа", "app", required=True)]},
    "app_closed": {"label": "Закрылась программа", "fields": [_f("app", "Программа", "app", required=True)]},
    "audio_added": {"label": "Подключили наушники / звук", "fields": [_f("name", "Название устройства содержит", "text", hint="Пусто — любое")]},
    "audio_removed": {"label": "Отключили наушники / звук", "fields": [_f("name", "Название устройства содержит", "text")]},
    "power_plugged": {"label": "Подключили зарядку", "fields": []},
    "power_unplugged": {"label": "Отключили зарядку", "fields": []},
    "battery_low": {"label": "Заряд ниже", "fields": [_f("percent", "Процентов", "number", default=20, min=5, max=95)]},
    "online": {"label": "Появился интернет", "fields": []},
    "offline": {"label": "Пропал интернет", "fields": []},
    "wifi": {"label": "Подключился Wi-Fi", "fields": [_f("ssid", "Название сети", "text", required=True)], "platforms": ["windows"]},
    "idle": {"label": "Компьютер не трогают", "fields": [_f("minutes", "Минут", "number", default=10, min=1, max=600)],
             "platforms": ["windows"]},
    "returned": {"label": "Вернулись к компьютеру", "fields": [], "platforms": ["windows"]},
    "assistant_started": {"label": "Джарвис запустился", "fields": []},
    "can_opened": {"label": "Звук открытой банки", "fields": [], "hint": "Детектор звука из config.yaml"},
    "hotkey": {"label": "Горячая клавиша", "fields": [_f("combo", "Сочетание", "combo", required=True)],
               "platforms": ["windows"]},
}

TRIGGERS["plugin_event"] = {"label": "Событие дополнения", "fields": [
    _f("plugin", "ID дополнения", "text", required=True, hint="Установленное дополнение с типом trigger"),
    _f("event", "Имя события", "text", default="default", required=True)]}

DEFAULTS = {"enabled": True, "category": "Мои", "phrases": [], "match": "word", "keep_listening": False,
            "triggers": [{"type": "voice"}, {"type": "button"}], "conditions": [], "confirm": "",
            "steps": [], "timeout": 180, "on_error": "stop", "cooldown": 30,
            "platforms": ["windows", "linux"], "description": ""}


class ScenarioError(ValueError):
    pass


def new_id():
    return "sc_" + _secrets.token_hex(5)


# ------------------------------------------------------------ проверка

def _check_fields(spec, data, where, problems, advanced_ok=True):
    for field in spec.get("fields", []):
        value = data.get(field["key"])
        empty = value is None or value == "" or value == []
        defaults = {f["key"]: f.get("default") for f in spec.get("fields", [])}
        if field.get("show_if") and any(data.get(k, defaults.get(k)) != v for k, v in field["show_if"].items()):
            continue
        if field.get("required") and empty:
            problems.append(f"{where}: не заполнено «{field['label']}»")
            continue
        if empty:
            continue
        kind = field["kind"]
        if kind in ("number", "range"):
            try:
                number = float(value)
            except (TypeError, ValueError):
                problems.append(f"{where}: «{field['label']}» — нужно число")
                continue
            if "min" in field and number < field["min"] or "max" in field and number > field["max"]:
                problems.append(f"{where}: «{field['label']}» — от {field.get('min')} до {field.get('max')}")
        elif kind == "select" and field.get("options"):
            if value not in [o[0] for o in field["options"]]:
                problems.append(f"{where}: «{field['label']}» — неизвестное значение {value!r}")
        elif kind == "time" and not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", str(value)):
            problems.append(f"{where}: время в виде ЧЧ:ММ")
        elif kind == "days" and (not isinstance(value, list) or not all(isinstance(d, int) and 0 <= d <= 6 for d in value)):
            problems.append(f"{where}: дни недели — числа 0 (пн) … 6 (вс)")
        elif kind in ("text", "textarea", "url", "app", "file", "combo") and not isinstance(value, str):
            problems.append(f"{where}: «{field['label']}» — нужен текст")
        elif field.get("max") and isinstance(value, str) and len(value) > field["max"]:
            problems.append(f"{where}: «{field['label']}» длиннее {field['max']} символов")


def _check_steps(steps, problems, path="Шаг", depth=0, count=None):
    count = count if count is not None else [0]
    if not isinstance(steps, list):
        problems.append(f"{path}: шаги должны быть списком")
        return
    for index, step in enumerate(steps, 1):
        count[0] += 1
        where = f"{path} {index}"
        if not isinstance(step, dict) or not isinstance(step.get("type"), str):
            problems.append(f"{where}: нет типа действия")
            continue
        spec = ACTIONS.get(step["type"])
        if spec is None:
            problems.append(f"{where}: неизвестное действие «{step['type']}»")
            continue
        _check_fields(spec, step, where, problems)
        if step["type"] == "if":
            _check_condition(step.get("condition"), where, problems)
            _check_steps(step.get("then") or [], problems, where + " → то", depth + 1, count)
            _check_steps(step.get("else") or [], problems, where + " → иначе", depth + 1, count)
        elif step["type"] == "repeat":
            _check_steps(step.get("steps") or [], problems, where + " → повтор", depth + 1, count)
        if depth > 3:
            problems.append(f"{where}: слишком глубокая вложенность")
    if count[0] > MAX_STEPS:
        problems.append(f"Не больше {MAX_STEPS} шагов в сценарии")


def _check_condition(condition, where, problems):
    if not isinstance(condition, dict) or condition.get("type") not in CONDITIONS:
        problems.append(f"{where}: неизвестное условие")
        return
    _check_fields(CONDITIONS[condition["type"]], condition, where + " (условие)", problems)


def validate(item, others=()):
    """Список понятных проблем; пусто — сценарий можно сохранить."""
    problems = []
    if not isinstance(item, dict):
        return ["Сценарий должен быть объектом"]
    if item.get("format", FORMAT) != FORMAT:
        problems.append(f"Это не сценарий Джарвиса (format={item.get('format')!r})")
    try:
        version = int(item.get("version", VERSION))
    except (TypeError, ValueError):
        version = -1
    if version > VERSION:
        problems.append(f"Сценарий из более новой версии Джарвиса (формат {version}, поддерживается {VERSION}) — обновите программу")
    elif version < 1:
        problems.append("Неизвестная версия формата сценария")
    if not str(item.get("name", "")).strip():
        problems.append("Дайте сценарию название")
    phrases = item.get("phrases", [])
    if not isinstance(phrases, list) or not all(isinstance(p, str) for p in phrases):
        problems.append("Фразы — список строк")
        phrases = []
    triggers = item.get("triggers", [])
    if not isinstance(triggers, list):
        problems.append("Триггеры — список")
        triggers = []
    for trigger in triggers:
        spec = TRIGGERS.get((trigger or {}).get("type"))
        if spec is None:
            problems.append(f"Неизвестный способ запуска «{(trigger or {}).get('type')}»")
            continue
        _check_fields(spec, trigger, spec["label"], problems)
        if trigger.get("type") == "hotkey":
            from shelter_core.scenario_hotkeys import parse
            try: parse(trigger.get("combo", ""))
            except ValueError as error: problems.append(str(error))
    if any(t.get("type") == "voice" for t in triggers if isinstance(t, dict)) and not [p for p in phrases if p.strip()]:
        problems.append("Для запуска голосом добавьте хотя бы одну фразу")
    if item.get("match", "word") not in ("word", "whole"):
        problems.append("match: word или whole")
    if item.get("on_error", "stop") not in ("stop", "continue"):
        problems.append("on_error: stop или continue")
    for condition in item.get("conditions") or []:
        _check_condition(condition, "Условие запуска", problems)
    steps = item.get("steps")
    if not steps:
        problems.append("Добавьте хотя бы один шаг")
    else:
        _check_steps(steps, problems)
    try:
        if not 1 <= float(item.get("timeout", 180)) <= 3600:
            problems.append("Ограничение времени — от 1 до 3600 секунд")
    except (TypeError, ValueError):
        problems.append("Ограничение времени — число секунд")
    return problems


def normalize(item):
    """Заполнить значения по умолчанию, не трогая неизвестные поля плагинов."""
    out = {**copy.deepcopy(DEFAULTS), **copy.deepcopy(item)}
    out["format"], out["version"] = FORMAT, VERSION
    out["id"] = out.get("id") if re.fullmatch(r"[a-z0-9_\-]{3,64}", str(out.get("id", ""))) else new_id()
    out["name"] = str(out.get("name", "")).strip()[:80]
    out["phrases"] = [p.strip().lower().replace("ё", "е") for p in out.get("phrases") or [] if isinstance(p, str) and p.strip()]
    return out


# --------------------------------------------------------------- хранилище

def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _hash(commands):
    return hashlib.sha256(json.dumps(commands or [], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def from_command(command, origin="config"):
    """Прежняя команда config.yaml -> сценарий (те же фразы, те же действия)."""
    keywords = [str(k) for k in command.get("keywords") or []]
    description = str(command.get("description") or "").strip()
    name = description.split(" — ")[0].split(":")[0].strip() or (keywords[0].rstrip("*") if keywords else "Команда")
    confirm = command.get("confirm") or ""
    if isinstance(confirm, dict):
        confirm = confirm.get("text", "Вы уверены, сэр?")
    item = {
        "id": "cmd_" + hashlib.sha1(("|".join(keywords) or name).encode()).hexdigest()[:10],
        "name": name[:1].upper() + name[1:], "description": description, "category": _category(command),
        "phrases": keywords, "match": "whole" if command.get("whole") else "word",
        "keep_listening": bool(command.get("keep_listening")), "confirm": confirm,
        "steps": [dict(a) for a in command.get("actions") or []], "origin": origin,
        "triggers": [{"type": "voice"}, {"type": "button"}],
    }
    return normalize(item)


def _category(command):
    text = (" ".join(command.get("keywords") or []) + " " + str(command.get("description") or "")).lower()
    for words, category in ((("музык", "трек", "пауз", "громче", "тише", "spotify", "спотифай"), "Музыка"),
                            (("выключ", "компьютер", "отбой"), "Компьютер"),
                            (("режим", "программирован", "креатор", "монтаж"), "Режимы"),
                            (("привет", "пока", "настройк"), "Разговор")):
        if any(w in text for w in words):
            return category
    return "Программы"


def _backup(commands, reason):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(BACKUPS, f"commands-{stamp}.json")
    _write(path, {"reason": reason, "created": time.time(), "commands": commands})
    return path


def _empty():
    return {"format": LIST_FORMAT, "version": VERSION, "items": [], "legacy_hash": ""}


def _read_store():
    try:
        with open(STORE, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    if not isinstance(data, dict) or data.get("format") != LIST_FORMAT:
        raise ScenarioError("data/scenarios.json повреждён: это не список сценариев")
    if int(data.get("version", 0)) > VERSION:
        raise ScenarioError("data/scenarios.json создан более новой версией Джарвиса")
    if not isinstance(data.get("items"), list):
        raise ScenarioError("data/scenarios.json: нет списка items")
    return data


def load(config=None):
    """Сценарии; при первом запуске — перенос прежних команд с резервной копией."""
    config = config if config is not None else _config
    commands = (config or {}).get("legacy_commands", (config or {}).get("commands")) or []
    commands = [c for c in commands if not (isinstance(c, dict) and c.get("scenario"))]
    with _lock:
        data = _read_store()
        if data is None and not _persist:
            # Ядро ещё не настроило сценарии (тест, разовая проверка) — перенос только в памяти.
            return [_stock_media(from_command(c)) for c in commands if isinstance(c, dict)]
        if data is None:
            data = _empty()
            if commands:
                _backup(commands, "перенос команд в сценарии")
            data["items"] = [from_command(c) for c in commands if isinstance(c, dict)]
            data["legacy_hash"] = _hash(commands)
            _write(STORE, data)
        elif _persist and commands and data.get("legacy_hash") != _hash(commands):
            # config.yaml поменяли руками — новые команды добавить, ничего не удаляя.
            known = {tuple(i.get("phrases") or []) for i in data["items"]} | {i["id"] for i in data["items"]}
            added = [from_command(c) for c in commands if isinstance(c, dict)]
            added = [a for a in added if a["id"] not in known and tuple(a["phrases"]) not in known]
            if added:
                _backup([i for i in data["items"]], "перед добавлением команд из config.yaml")
                data["items"].extend(added)
            data["legacy_hash"] = _hash(commands)
            _write(STORE, data)
        return [_stock_media(normalize(i)) for i in data["items"]
                if isinstance(i, dict) and i.get("id") != "personal_can_opened"]


def _stock_media(item):
    """Keep legacy stock media controls independent of the old personal player."""
    replacements = {
        "cmd_d23ac1734c": ("Включить музыку (плейлист в Spotify)", "Включить воспроизведение",
                           ["включи музыку", "продолжи воспроизведение"], "play"),
        "cmd_864e388705": ("Остановить и выключить музыку совсем (закрыть Spotify)", "Остановить воспроизведение",
                           ["останови музыку", "останови воспроизведение"], "stop"),
    }
    if item.get("origin") == "config" and item["id"] in replacements:
        old_name, name, phrases, key = replacements[item["id"]]
        if item["name"] == old_name:
            item.update(name=name, description="", phrases=phrases, match="whole", steps=[{"type": "media", "key": key}])
    if item.get("origin") == "config" and item["id"] in {
        "cmd_dbf4d34a6c", "cmd_9f100ef519", "cmd_6357cf7db5", "cmd_bf64c60715"
    } and len(item["steps"]) == 1:
        step = item["steps"][0]
        if step.get("type") == "media" and str(step.get("process", "")).lower() == "spotify.exe":
            step.pop("process")
    return item


def save_all(items, reason=""):
    with _lock:
        data = _read_store() or _empty()
        if reason:
            _backup(data["items"], reason)
        data["items"] = items
        _write(STORE, data)
    _refresh()


DRAFTS = {}         # пробный запуск несохранённого черновика из окна


def get(scenario_id):
    if scenario_id in DRAFTS:
        return DRAFTS[scenario_id]
    return next((s for s in load() if s["id"] == scenario_id), None)


def save(item):
    item = normalize(item)
    items = load()
    problems = validate(item, items)
    if problems:
        raise ScenarioError("; ".join(problems))
    item["updated"] = time.time()
    for index, old in enumerate(items):
        if old["id"] == item["id"]:
            item.setdefault("created", old.get("created", item["updated"]))
            items[index] = item
            break
    else:
        item.setdefault("created", item["updated"])
        items.append(item)
    save_all(items)
    return item


def delete(scenario_id):
    items = load()
    kept = [i for i in items if i["id"] != scenario_id]
    if len(kept) == len(items):
        raise ScenarioError("нет такого сценария")
    save_all(kept, "перед удалением сценария")


def backups():
    try:
        names = sorted((n for n in os.listdir(BACKUPS) if n.endswith(".json")), reverse=True)
    except OSError:
        return []
    out = []
    for name in names[:20]:
        try:
            with open(os.path.join(BACKUPS, name), encoding="utf-8") as f:
                data = json.load(f)
            out.append({"id": name, "reason": data.get("reason", ""), "created": data.get("created", 0),
                        "count": len(data.get("commands") or [])})
        except (OSError, ValueError):
            continue
    return out


def restore(backup_id):
    """Вернуть список из резервной копии; текущий тоже сохраняется копией."""
    if not re.fullmatch(r"commands-[\d\-]+\.json", backup_id or ""):
        raise ScenarioError("неверное имя резервной копии")
    with open(os.path.join(BACKUPS, backup_id), encoding="utf-8") as f:
        data = json.load(f)
    restored = []
    for item in data.get("commands") or []:
        restored.append(normalize(item) if item.get("format") == FORMAT or "steps" in item else from_command(item))
    save_all(restored, "перед восстановлением из копии")
    return len(restored)


def _refresh():
    """Голосовой поиск команд сразу видит изменения — без перезапуска ядра."""
    if _config:
        _config["commands"] = as_commands(load(_config))
    try:
        from shelter_core import triggers
        triggers.reload()
    except Exception as error:
        print(f"[scenarios] триггеры не обновлены: {error}")
    bus.publish("scenarios")


def as_commands(items):
    """Сценарии с голосовым запуском -> записи для голосового поиска команд.

    actions — копия шагов: по ним голосовой цикл понимает, открывает ли команда
    программу («закрой телеграм» не должно её запускать) и говорит ли она сама.
    Выполняет же их общий исполнитель (действие type: scenario)."""
    out = []
    for item in items:
        if not item.get("enabled", True) or PLATFORM not in (item.get("platforms") or [PLATFORM]):
            continue
        if not any(t.get("type") == "voice" for t in item.get("triggers") or []) or not item.get("phrases"):
            continue
        out.append({"keywords": list(item["phrases"]), "whole": item.get("match") == "whole",
                    "keep_listening": bool(item.get("keep_listening")), "description": item.get("description") or item["name"],
                    "confirm": item.get("confirm") or None, "scenario": item["id"], "actions": _flat(item.get("steps") or [])})
    return out


def _flat(steps):
    out = []
    for step in steps:
        if step.get("enabled", True) is False:
            continue
        out.append({k: v for k, v in step.items() if k not in ("then", "else", "steps")})
        for key in ("then", "else", "steps"):
            out.extend(_flat(step.get(key) or []))
    return out


def configure(config, run_tool=None, switch_persona=None):
    global _config, _run_tool, _switch_persona, _persist
    _config = config
    _persist = True
    _run_tool = run_tool or _run_tool
    _switch_persona = switch_persona or _switch_persona
    try:
        legacy = [c for c in config.get("commands") or [] if not c.get("scenario")]
        config.setdefault("legacy_commands", legacy)
        config["commands"] = as_commands(load(config))
    except (ScenarioError, OSError, ValueError) as error:
        # Сценарии не читаются — работать на прежних командах и сказать об этом.
        print(f"[scenarios] {error} — работаю на командах из config.yaml")
        bus.publish("error", text=f"Сценарии не загружены: {error}. Работают прежние команды.")


# ---------------------------------------------------------- описание шага

def describe(step):
    """Понятная строка: «Открыть программу Telegram»."""
    kind = step.get("type")
    spec = ACTIONS.get(kind, {"label": kind})
    value = {
        "say": lambda: f"«{_short(step.get('text'))}»",
        "open_app": lambda: step.get("target", ""),
        "launch": lambda: os.path.basename(str(step.get("path", ""))),
        "url": lambda: _short(step.get("url"), 40),
        "app": lambda: str(step.get("id", "")).split("!")[0].split("_")[0],
        "window": lambda: f"{dict(WINDOW_ACTIONS).get(step.get('action', 'focus'), '').lower()} «{step.get('title', '')}»"
                          + (f" → монитор {step.get('monitor', 1)}, {dict(POSITIONS).get(step.get('position', 'full'), '').lower()}"
                             if step.get("action") == "place" else ""),
        "wait_for": lambda: f"{step.get('value', '')} (до {step.get('timeout', 20)} с)",
        "wait": lambda: f"{step.get('seconds', 0)} с",
        "media": lambda: dict(MEDIA_KEYS).get(step.get("key", "toggle"), step.get("key", "")).lower(),
        "volume": lambda: f"{step.get('value', '')}%",
        "keys": lambda: step.get("combo", ""),
        "type_text": lambda: f"«{_short(step.get('text'))}»",
        "timer": lambda: f"через {step.get('minutes', '')} мин" + (f": {step['label']}" if step.get("label") else ""),
        "home": lambda: f"{step.get('device', '')} — {dict(ACTIONS['home']['fields'][1]['options']).get(step.get('state', 'on'), '')}",
        "avatar": lambda: step.get("animation", ""),
        "persona": lambda: step.get("id", ""),
        "overlay": lambda: step.get("text", ""),
        "ask": lambda: f"«{_short(step.get('text'))}»",
        "tool": lambda: f"{step.get('name', '')}: {step.get('arg', '')}",
        "scenario": lambda: (get(step.get("id", "")) or {}).get("name", step.get("id", "")),
        "if": lambda: describe_condition(step.get("condition") or {}),
        "repeat": lambda: f"{step.get('times', 1)} раз",
        "shell": lambda: _short(step.get("cmd"), 40),
        "profile": lambda: step.get("name", ""),
        "plugin": lambda: step.get("name", ""),
    }.get(kind, lambda: "")
    try:
        detail = value()
    except Exception:
        detail = ""
    return f"{spec['label']}: {detail}" if detail else spec["label"]


def describe_condition(condition):
    kind = condition.get("type")
    spec = CONDITIONS.get(kind, {"label": kind or "?"})
    days = "пн вт ср чт пт сб вс".split()
    detail = {"time_between": f"{condition.get('from', '')}–{condition.get('to', '')}",
              "days": " ".join(days[d] for d in condition.get("days") or [] if 0 <= d <= 6),
              "app_running": condition.get("app", ""), "app_not_running": condition.get("app", ""),
              "window_open": condition.get("title", ""), "monitors": str(condition.get("count", "")),
              "last_step": "удался" if condition.get("state", "ok") == "ok" else "не удался"}.get(kind, "")
    return f"{spec['label']} {detail}".strip()


def _short(text, limit=60):
    text = str(text or "").replace("\n", " ")
    return text if len(text) <= limit else text[:limit - 1] + "…"


# --------------------------------------------------------------- условия

def _process_names():
    import psutil
    names = set()
    for process in psutil.process_iter(["name"]):
        name = (process.info.get("name") or "").lower()
        names.add(name.removesuffix(".exe"))
    return names


def _app_matches(app, names):
    app = str(app or "").lower().removesuffix(".exe").strip()
    if not app:
        return False
    if app in names:
        return True
    compact = app.replace(" ", "")
    return any(compact and (compact in n or (len(n) > 3 and n in compact)) for n in names)


def supported(kind, spec):
    if PLATFORM == "linux":
        feature = {"window": "windows", "window_open": "windows", "keys": "keys", "type_text": "keys", "monitors": "monitors"}.get(kind)
        if feature:
            from shelter_core import desktop_linux
            return bool(desktop_linux.capabilities().get(feature))
    return PLATFORM in spec.get("platforms", [PLATFORM])


def registry_for_platform(registry):
    """UI and executor use the same runtime capabilities, including missing tools."""
    result = copy.deepcopy(registry)
    for kind, spec in result.items():
        if supported(kind, spec) and PLATFORM not in spec.get("platforms", [PLATFORM]):
            spec["platforms"].append(PLATFORM)
        elif not supported(kind, spec):
            spec["platforms"] = [p for p in spec.get("platforms", []) if p != PLATFORM]
    return result


def check_condition(condition, context=None):
    """(выполнено, пояснение). Недоступное на этой ОС — False с причиной, не исключение."""
    kind = condition.get("type")
    spec = CONDITIONS.get(kind)
    if spec is None:
        return False, "неизвестное условие"
    if not supported(kind, spec):
        return False, "недоступно на этой системе"
    now = datetime.datetime.now()
    if kind == "time_between":
        start, end = condition.get("from", "00:00"), condition.get("to", "23:59")
        current = now.strftime("%H:%M")
        ok = start <= current <= end if start <= end else (current >= start or current <= end)
        return ok, f"сейчас {current}"
    if kind == "days":
        return now.weekday() in (condition.get("days") or []), "сегодня " + "пн вт ср чт пт сб вс".split()[now.weekday()]
    if kind in ("app_running", "app_not_running"):
        running = _app_matches(condition.get("app"), _process_names())
        return (running if kind == "app_running" else not running), "запущена" if running else "не запущена"
    if kind == "window_open":
        from shelter_core import pc
        return pc.find_window(condition.get("title", "")) is not None, ""
    if kind in ("on_battery", "charging"):
        import psutil
        battery = psutil.sensors_battery()
        if battery is None:
            return kind == "charging", "батареи нет — компьютер от сети"
        return (not battery.power_plugged) if kind == "on_battery" else bool(battery.power_plugged), f"заряд {round(battery.percent)}%"
    if kind == "online":
        return _online(), ""
    if kind == "in_game":
        from shelter_core import gaming
        return bool(gaming.busy(_config or {})), ""
    if kind == "monitors":
        from shelter_core import pc
        count = len(pc.monitors())
        return count >= int(condition.get("count", 1)), f"мониторов: {count}"
    if kind == "last_step":
        last = (context or {}).get("last_ok")
        want = condition.get("state", "ok") == "ok"
        return (last is not None and last == want), ""
    return False, ""


def _online(timeout=1.5):
    import socket
    for host in (("1.1.1.1", 53), ("8.8.8.8", 53)):
        try:
            with socket.create_connection(host, timeout=timeout):
                return True
        except OSError:
            continue
    return False


# ------------------------------------------------------------- исполнитель

class StepFailed(RuntimeError):
    pass


RECENT = []          # последние запуски для окна: [{run, scenario, name, source, status, steps, ...}]
_cancelled_runs = set()
_running = set()
_tokens = {}         # run -> tasks.Token: остановить один запуск по ID


def _sleep(seconds):
    """Пауза, которую обрывает «стоп»."""
    end = time.monotonic() + float(seconds)
    while True:
        tasks.check()
        left = end - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(0.1, left))


def _tool(name, arg):
    if _run_tool is None:
        raise StepFailed("исполнитель инструментов ещё не готов")
    outcome, reply = _run_tool(name, arg)
    if outcome == "fail":
        raise StepFailed(reply or f"{name} не выполнено")
    return reply or ""


def _expand(path):
    return os.path.expandvars(os.path.expanduser(str(path or "")))


def _run_step(step, context):
    """Выполнить один шаг и проверить результат. -> короткое пояснение."""
    kind = step["type"]
    spec = ACTIONS.get(kind)
    if spec is None:
        raise StepFailed(f"неизвестное действие «{kind}»")
    if not supported(kind, spec):
        raise StepFailed("это действие недоступно на этой системе")
    from shelter_core import actions
    if kind == "browser_episode":
        return _tool("browser_episode", "next")
    if context.get("voice_plan"):
        from shelter_core import automation_intent as auto
        auto.check_policy(_config, step)
        if kind == "open_app":
            return auto.launch_exact(step["target"])
        if kind == "window" and step.get("action") in ("focus", "minimize", "maximize"):
            return auto.change_window(step)
        if kind == "media" and step.get("key") in ("pause", "play") and not step.get("process"):
            return auto.set_player(step["key"])
    if kind == "open_app":
        return _tool("app", step["target"]) or step["target"]
    if kind == "volume":
        from shelter_core import pc
        value = pc.set_volume(step.get("value", 30))
        actual = pc.get_volume()
        if abs(actual - value) > 2:
            raise StepFailed(f"громкость осталась {actual}%")
        return f"{actual}%"
    if kind == "keys":
        from shelter_core import pc
        pc.send_keys(step["combo"])
        return step["combo"]
    if kind == "type_text":
        from shelter_core import pc
        pc.type_text(step["text"])
        return ""
    if kind == "window":
        from shelter_core import pc
        action = step.get("action", "focus")
        if action == "place":
            placed = pc.place_window(step["title"], step.get("monitor", 1), step.get("position", "full"))
            if not placed:
                raise StepFailed(f"окно «{step['title']}» не найдено")
            return placed[2] or f"монитор {placed[1]}"
        done = pc.window(action, step["title"])
        if not done:
            raise StepFailed(f"окно «{step['title']}» не найдено")
        return done
    if kind == "wait":
        _sleep(step.get("seconds", 1))
        return ""
    if kind == "wait_for":
        return _wait_for(step)
    if kind == "media" and not step.get("process"):
        from shelter_core import media
        _sleep(float(step.get("delay", 0)))
        key = {"prev": "previous"}.get(step.get("key", "toggle"), step.get("key", "toggle"))
        if key in ("pause", "play"):
            if not media.ensure(key):
                raise StepFailed("сейчас ничего не играет")
            return ""
        if not media.control(key):
            raise StepFailed("плеер не ответил")
        return ""
    if kind == "timer":
        seconds = max(1, round(float(step.get("minutes", 1)) * 60))
        return _tool("timer", f"{seconds} | {step['label']}" if step.get("label") else str(seconds))
    if kind == "home":
        return _tool("home", f"{step['device']} | {step.get('state', 'on')}")
    if kind == "persona":
        if _switch_persona is None:
            raise StepFailed("смена персонажа ещё не готова")
        reply = _switch_persona(step["id"])
        if reply:
            from shelter_core import voice
            voice.speak_stream([reply])
        return ""
    if kind == "launch":
        step = {**step, "path": _expand(step.get("path"))}
        if not os.path.exists(step["path"]):
            raise StepFailed(f"нет файла {step['path']}")
    if kind == "scenario":
        target = get(step.get("id", ""))
        if target is None:
            raise StepFailed("вложенный сценарий удалён")
        if target["id"] in context["stack"]:
            raise StepFailed("сценарий вызывает сам себя — остановлено")
        if len(context["stack"]) >= MAX_DEPTH:
            raise StepFailed("слишком глубокая вложенность сценариев")
        result = execute(target, source="scenario", parent=context)
        if result["status"] != "done":
            raise StepFailed(result.get("error") or "вложенный сценарий не выполнен")
        return target["name"]
    # Прежние действия (say, url, media с плеером, launch, app, overlay, close, avatar,
    # ask, tool, profile, plugin, shell, riot, settings) — их собственный исполнитель.
    try:
        actions.run_action(step)
    except tasks.Cancelled:
        raise
    except RuntimeError as error:
        raise StepFailed(str(error.__cause__ or error)) from error
    return ""


def _wait_for(step):
    what, value = step.get("what", "window"), step.get("value", "")
    timeout = float(step.get("timeout", 20))
    deadline = time.monotonic() + timeout
    while True:
        if what == "window":
            from shelter_core import pc
            found = pc.find_window(value)
            ok = found is not None and bool(found[1] or found[2])
        else:
            running = _app_matches(value, _process_names())
            ok = running if what == "process" else not running
        if ok:
            return "дождался"
        if time.monotonic() >= deadline:
            raise StepFailed(f"не дождался «{value}» за {timeout:g} с")
        _sleep(0.5)


def _publish(run, **extra):
    bus.publish("scenario", run=run["run"], scenario=run["scenario"], name=run["name"], source=run["source"],
                status=run["status"], **extra)


def _walk(steps, run, context, path):
    for index, step in enumerate(steps):
        tasks.check()
        label = describe(step)
        where = f"{path}{index + 1}"
        if step.get("enabled", True) is False:
            run["steps"].append({"path": where, "label": label, "status": "skipped", "detail": "шаг выключен"})
            continue
        entry = {"path": where, "label": label, "status": "running", "detail": "", "started": time.time()}
        run["steps"].append(entry)
        _publish(run, step=where, label=label, state="running")
        kind = step["type"]
        try:
            if kind == "if":
                ok, why = check_condition(step.get("condition") or {}, context)
                entry.update(status="done", detail=("да" if ok else "нет") + (f" ({why})" if why else ""))
                _walk(step.get("then" if ok else "else") or [], run, context, where + ".")
                continue
            if kind == "repeat":
                times = max(1, min(MAX_REPEAT, int(step.get("times", 1))))
                for turn in range(times):
                    _walk(step.get("steps") or [], run, context, f"{where}.{turn + 1}:")
                entry.update(status="done", detail=f"{times} раз")
                continue
            attempts = 1 + (min(3, int(step.get("retry", 0))) if ACTIONS.get(kind, {}).get("safe_retry") else 0)
            for attempt in range(attempts):
                try:
                    entry["detail"] = _run_step(step, context) or ""
                    break
                except StepFailed:
                    if attempt + 1 >= attempts:
                        raise
                    _sleep(1.0)
            entry["status"] = "done"
            context["last_ok"] = True
            if kind == "say":
                tasks.reply(step.get("text", ""))
        except tasks.Cancelled:
            entry.update(status="cancelled", detail="остановлено")
            raise
        except Exception as error:
            entry.update(status="failed", detail=str(error))
            context["last_ok"] = False
            if run["on_error"] == "continue":
                run["warnings"].append(f"{label}: {error}")
                continue
            raise StepFailed(f"{label}: {error}") from error
        finally:
            entry["ms"] = round((time.time() - entry.pop("started", time.time())) * 1000)
            _publish(run, step=where, label=label, state=entry["status"], detail=entry["detail"])


def execute(item, source="button", parent=None, run_id=None):
    """Выполнить сценарий в текущей задаче. -> структурированный результат.

    status: done | partial (были ошибки при on_error=continue) | failed | cancelled | skipped.
    Ошибка шага — это failed с понятной причиной, а не «готово»."""
    run = {"run": run_id or "run_" + _secrets.token_hex(4), "scenario": item["id"], "name": item["name"],
           "source": source, "status": "running", "steps": [], "warnings": [], "error": "",
           "on_error": item.get("on_error", "stop"), "started": time.time(), "finished": 0}
    context = {"stack": (parent or {}).get("stack", ()) + (item["id"],), "last_ok": None,
               "voice_plan": item.get("origin") == "voice_plan"}
    with _lock:
        RECENT.insert(0, run)
        del RECENT[30:]
    _publish(run)
    token = tasks.current()
    own_token = None
    if token is None or parent is None:
        # Ограничение времени сценария — своё, в пределах общей задачи.
        own_token = tasks.Token(parent=token, timeout=float(item.get("timeout", 180)))
        own_token.deadline = time.monotonic() + float(item.get("timeout", 180))
        if token is not None:
            own_token.deadline = min(own_token.deadline, token.deadline)
    with _lock:
        _tokens[run["run"]] = own_token or token
    try:
        with tasks.scope(own_token or token):
            if run["run"] in _cancelled_runs:
                raise tasks.Cancelled()
            if context["voice_plan"]:
                from shelter_core import automation_intent as auto
                for step in _flat(item.get("steps") or []):
                    auto.check_policy(_config, step)
            for condition in item.get("conditions") or []:
                ok, why = check_condition(condition, context)
                if not ok:
                    run.update(status="skipped", error=f"не выполнено условие: {describe_condition(condition)}" + (f" ({why})" if why else ""))
                    return run
            with _lock:
                _running.add(item["id"])
            _walk(item.get("steps") or [], run, context, "")
            run["status"] = "partial" if run["warnings"] else "done"
    except tasks.Cancelled:
        run["status"] = "cancelled"
        run["error"] = (own_token and tasks._root(own_token).error) or "остановлено"
        if parent is not None:
            raise
    except StepFailed as error:
        run.update(status="failed", error=str(error))
    except Exception as error:
        run.update(status="failed", error=f"сбой исполнителя: {error}")
    finally:
        with _lock:
            _running.discard(item["id"])
            _cancelled_runs.discard(run["run"])
            _tokens.pop(run["run"], None)
        run["finished"] = time.time()
        _publish(run, error=run["error"])
        if run["status"] == "failed":
            bus.publish("error", text=f"Сценарий «{item['name']}»: {run['error']}")
    return run


def running():
    with _lock:
        return set(_running)


def cancel(run_id=None):
    """Остановить запуск по ID (или все). Отправленное сообщение не откатывается."""
    with _lock:
        targets = [r for r in RECENT if r["status"] == "running" and (run_id is None or r["run"] == run_id)]
        for run in targets:
            _cancelled_runs.add(run["run"])
            token = _tokens.get(run["run"])
            if token is not None:
                token.cancel()
    return [r["run"] for r in targets]


def recent():
    with _lock:
        return [{k: v for k, v in r.items() if k != "on_error"} for r in RECENT[:20]]


# ------------------------------------------------------ план без исполнения

def plan(item):
    """Что сделает сценарий — без выполнения: шаги, условия, проблемы и зависимости."""
    item = normalize(item)
    lines, needs = [], []

    def walk(steps, depth):
        for step in steps:
            spec = ACTIONS.get(step.get("type"), {})
            off = step.get("enabled", True) is False
            note = ""
            if not spec:
                note = "неизвестное действие"
            elif not supported(step.get("type"), spec):
                note = "недоступно на этой системе"
            elif spec.get("capability") and not _capability_allowed(spec["capability"]):
                note = "выключено в настройках"
            elif step.get("type") == "launch" and not os.path.exists(_expand(step.get("path"))):
                note = "файл не найден"
                needs.append(f"нет файла {step.get('path')}")
            elif step.get("type") in ("open_app",) and not _app_exists(step.get("target", "")):
                note = "программа не найдена"
                needs.append(f"не найдена программа «{step.get('target')}»")
            lines.append({"depth": depth, "text": describe(step), "off": off, "note": note,
                          "irreversible": bool(spec.get("irreversible")), "llm": step.get("type") == "ask"})
            if step.get("type") == "if":
                lines.append({"depth": depth + 1, "text": "то:", "group": True})
                walk(step.get("then") or [], depth + 2)
                if step.get("else"):
                    lines.append({"depth": depth + 1, "text": "иначе:", "group": True})
                    walk(step.get("else") or [], depth + 2)
            elif step.get("type") == "repeat":
                walk(step.get("steps") or [], depth + 1)

    walk(item.get("steps") or [], 0)
    starts = []
    for trigger in item.get("triggers") or []:
        spec = TRIGGERS.get(trigger.get("type"), {})
        text = spec.get("label", trigger.get("type"))
        if trigger.get("type") == "voice":
            text += ": " + ", ".join(f"«{p}»" for p in item.get("phrases") or [])
        elif trigger.get("type") == "schedule":
            text += f" {trigger.get('time', '')}"
        elif trigger.get("app") or trigger.get("name"):
            text += f": {trigger.get('app') or trigger.get('name')}"
        if spec.get("unavailable"):
            text += f" — {spec['unavailable']}"
        starts.append(text)
    return {"steps": lines, "triggers": starts, "conditions": [describe_condition(c) for c in item.get("conditions") or []],
            "problems": validate(item), "needs": needs, "confirm": item.get("confirm") or "",
            "uses_llm": any(l.get("llm") for l in lines)}


def _capability_allowed(capability):
    if capability == "shell":
        return bool((_config.get("security") or {}).get("allow_shell"))
    if capability == "plugins":
        return bool((_config.get("security") or {}).get("allow_plugins"))
    if capability == "llm":
        return bool((_config.get("llm") or {}).get("enabled", True))
    try:
        from shelter_core import policy
        return policy.allowed(_config, capability)
    except Exception:
        return True


def _app_exists(name):
    try:
        from shelter_core import tools
        return bool(tools.find_app(name)) or tools._norm(name) in tools.APP_ALIASES or tools._norm(name) in tools.SITES
    except Exception:
        return True


# ----------------------------------------------------------- импорт/экспорт

SECRET_KEYS = re.compile(r"(token|password|passwd|secret|api[_-]?key|authorization|cookie)", re.I)


def _scrub(value, removed, where=""):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if SECRET_KEYS.search(str(key)):
                removed.append(f"{where}{key}")
                continue
            out[key] = _scrub(item, removed, f"{where}{key}.")
        return out
    if isinstance(value, list):
        return [_scrub(v, removed, where) for v in value]
    if isinstance(value, str):
        home = os.path.expanduser("~")
        if home and home.lower() in value.lower():
            value = re.sub(re.escape(home), "%USERPROFILE%", value, flags=re.I)
        if re.search(r"(?:sk-|ghp_|xox[bp]-|Bearer\s)[A-Za-z0-9_\-]{12,}", value):
            removed.append(where.rstrip(".") or "текст")
            return ""
    return value


def export(ids=None):
    """Пакет для обмена: без секретов, имя пользователя в путях заменено на %USERPROFILE%."""
    items = [i for i in load() if ids is None or i["id"] in ids]
    removed = []
    clean = []
    for item in items:
        item = {k: v for k, v in item.items() if k not in ("created", "updated", "legacy_trigger")}
        clean.append(_scrub(item, removed, item["name"] + ": "))
    return {"format": LIST_FORMAT, "version": VERSION, "exported": time.time(), "items": clean, "removed": removed}


def import_items(payload, replace=False):
    """Принять пакет сценариев. Проблемные — не ставятся, остальные ставятся; ничего не теряется."""
    if isinstance(payload, str):
        payload = json.loads(payload)
    if isinstance(payload, dict) and payload.get("format") == FORMAT:
        payload = {"format": LIST_FORMAT, "version": payload.get("version", VERSION), "items": [payload]}
    if not isinstance(payload, dict) or payload.get("format") != LIST_FORMAT:
        raise ScenarioError("Это не файл сценариев Джарвиса")
    if int(payload.get("version", 0)) > VERSION:
        raise ScenarioError(f"Файл из более новой версии Джарвиса (формат {payload.get('version')}) — обновите программу")
    items = load()
    ids = {i["id"] for i in items}
    added, rejected = [], []
    for raw in payload.get("items") or []:
        if not isinstance(raw, dict):
            rejected.append({"name": "?", "problems": ["не сценарий"]})
            continue
        raw = {k: v for k, v in raw.items() if k not in ("created", "updated")}
        item = normalize(raw)
        problems = validate(item)
        if problems:
            rejected.append({"name": item.get("name") or "?", "problems": problems})
            continue
        if item["id"] in ids and not replace:
            item["id"] = new_id()
        item["origin"] = item.get("origin") if item.get("origin", "").startswith("pack:") else "import"
        item["created"] = item["updated"] = time.time()
        items = [i for i in items if i["id"] != item["id"]] + [item]
        ids.add(item["id"])
        added.append(item["name"])
    if added:
        save_all(items, "перед импортом сценариев")
    return {"added": added, "rejected": rejected}


# ------------------------------------------- «Сохранить как сценарий» из задачи

# Инструменты, которые что-то делают (их можно повторить без модели).
ACTION_TOOLS = {"app", "pc", "media", "home", "timer", "display", "avatar", "obs", "discord"}


def from_run(detail):
    """Черновик сценария из выполненной задачи: только проверенные шаги с действиями."""
    if not detail or detail.get("status") != "done":
        raise ScenarioError("сохранить можно только успешно выполненную задачу")
    plans = [row for row in detail.get("steps") or [] if row.get("name") == "voice_plan" and row.get("outcome") == "done"]
    if plans:
        try:
            from shelter_core import automation_intent as auto
            steps = json.loads(plans[-1]["argument"])
            if not isinstance(steps, list) or not 1 <= len(steps) <= auto.MAX_STEPS or any(
                not isinstance(step, dict) or step.get("type") not in (*auto._CAP, "wait") for step in steps
            ):
                raise ValueError
            removed = []
            steps = _scrub(steps, removed)
            if removed:
                raise ValueError
            title = _short(str(detail.get("question", "")).strip(), 60) or "Цепочка по просьбе"
            draft = normalize({"name": title, "description": "Сохранено из голосовой цепочки",
                               "steps": steps, "origin": "voice_plan", "timeout": 60,
                               "triggers": [{"type": "button"}], "match": "whole"})
            if validate(draft):
                raise ValueError
            return {"draft": draft, "skipped": []}
        except (ValueError, KeyError, TypeError):
            raise ScenarioError("не удалось восстановить проверенную цепочку из журнала") from None
    steps, skipped = [], []
    for step in detail.get("steps") or []:
        name = str(step.get("name", ""))
        if step.get("outcome") != "done":
            skipped.append(f"{name}: не подтверждён")
            continue
        if name.startswith("action:"):
            continue          # служебная отметка цепочки
        if name not in ACTION_TOOLS:
            skipped.append(f"{name}: справочный шаг — его заново выполнит модель")
            continue
        arg = str(step.get("argument", ""))
        removed = []
        arg = _scrub(arg, removed)
        if removed:
            skipped.append(f"{name}: убран секрет")
        if name == "app":
            steps.append({"type": "open_app", "target": arg})
        elif name == "pc" and arg.startswith("volume |"):
            steps.append({"type": "volume", "value": int(re.sub(r"\D", "", arg.split("|", 1)[1]) or 30)})
        else:
            steps.append({"type": "tool", "name": name, "arg": arg})
    if not steps:
        raise ScenarioError("в задаче нет проверенных действий, которые можно повторить без модели")
    question = str(detail.get("question", "")).strip()
    return {"draft": normalize({"name": _short(question, 60)[:1].upper() + _short(question, 60)[1:],
                                "phrases": [question.lower()] if question else [], "steps": steps,
                                "origin": "from_task", "description": "Сохранено из выполненной задачи"}),
            "skipped": skipped}
