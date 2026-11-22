"""Как Джарвис показывается на экране — меняется голосом.

«Работай без окна», «режим кругляша», «большое окно», «автоматический режим»
и «перейди на второй монитор» / «встань в левый угол» для обычного Джарвиса
(персонаж с 3D-моделью ходит сам — avatar_motion). Выбор сохраняется в
data/settings.json, а приложение получает событие и показывает его в настройках.
"""

from shelter_core.paths import ROOT_DIR

import json
import os
import re
import tempfile

ROOT = ROOT_DIR
SETTINGS = os.path.join(ROOT, "data", "settings.json")

# (шаблон фразы, режим, что сказать)
MODES = [
    (r"(?:работай|будь|режим|включи режим|переключись в режим)\s*(?:без окна|в фоне|фонов\w*|сверну\w*|скрыт\w*|невидим\w*)"
     r"|(?:не показывай|скрой|убери) (?:окно|интерфейс|себя)(?: совсем| насовсем| навсегда)?"
     r"|сверни (?:интерфейс|себя)(?: совсем| насовсем| навсегда)?",      # «сверни окно» — про текущее окно
     "hidden", "Хорошо, сэр, буду работать без окна. Скажите «покажи окно», чтобы вернуть."),
    (r"(?:режим|включи режим|переключись (?:в|на) режим|сделай)\s*(?:кругляш\w*|компактн\w*|маленьк\w*)(?: окно| режим)?",
     "orb", "Перехожу в компактный режим, сэр."),
    (r"(?:режим|включи режим|переключись (?:в|на) режим|покажи|сделай)\s*(?:больш\w* окн\w*|полн\w* интерфейс\w*)",
     "full", "Буду показываться большим окном, сэр."),
    (r"(?:режим|включи режим|переключись (?:в|на) режим)\s*(?:автоматическ\w*|авто|как обычно)"
     r"|(?:покажи|верни|показывай) (?:окно|интерфейс)|автоматическ\w* режим",
     "auto", "Вернул обычный режим, сэр: большое окно, а в игре — компактно."),
]


PRESENCE = [
    (r"(?:исчезни|пропади|сгинь|скройся|спрячься|уйди|испарись|убирайся|свали|кыш)(?: с экрана| отсюда| пожалуйста)?"
     r"|(?:убери|скрой) себя с экрана|уйди с экрана", "dismiss", "Исчезаю, сэр."),
    (r"(?:появись|покажись|вернись на экран|выйди на экран|покажи себя)(?: пожалуйста)?", "appear", "Я здесь, сэр."),
]


def presence_command(text):
    """«Исчезни» / «появись» -> (действие, ответ) или None."""
    q = text.lower().replace("ё", "е").strip(" .!?,")
    for pattern, action, reply in PRESENCE:
        if re.fullmatch(pattern, q):
            return action, reply
    return None


def mode_command(text):
    """Фраза о режиме окна -> (режим, ответ) или None."""
    q = text.lower().replace("ё", "е").strip(" .!?,")
    for pattern, mode, reply in MODES:
        if re.fullmatch(pattern, q):
            return mode, reply
    return None


def remember(config, **ui):
    """Применить сразу и сохранить в настройках приложения (раздел ui)."""
    config.setdefault("ui", {}).update(ui)
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    section = data.setdefault("ui", {})
    if isinstance(section, dict):
        section.update(ui)
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(SETTINGS), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temporary, SETTINGS)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    from shelter_core import bus
    bus.publish("settings", ui=ui)          # приложение обновит переключатели без перезапуска


def set_mode(config, mode):
    from shelter_core import actions
    remember(config, layout=mode)
    # Размер окна у большого и компактного режима разный — окно открывается заново.
    actions.close_hud()
    if mode != "hidden":
        from shelter_core.audio import LISTENING
        if LISTENING.is_set():
            actions.run_action({"type": "overlay", "seconds": 0, "text": "AWAITING ORDERS"})


def move(config, monitor=0, position="center"):
    """Переставить окно Джарвиса на монитор/в угол; живое окно переезжает сразу."""
    from shelter_core import actions
    remember(config, monitor=int(monitor), position=position)
    actions.place_hud(int(monitor), position)
    where = {1: "основной монитор", 2: "второй монитор", 3: "третий монитор"}.get(int(monitor), "")
    return f"Перехожу на {where}, сэр." if where else "Перехожу, сэр."
