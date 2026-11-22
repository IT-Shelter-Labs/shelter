"""Применить безопасные настройки без перезапуска ядра.

Окно сохраняет data/settings.json, затем просит ядро перечитать его. Сюда
попадают только разделы, которые ядро читает при каждом использовании;
остальное (микрофон, распознавание, голос, модель) требует перезапуска —
окно показывает конкретную причину.
"""

import copy

# Разделы целиком и отдельные ключи, которые можно менять «на ходу».
LIVE_SECTIONS = ("ui", "gaming", "confirm", "discord", "obs", "location", "search", "home", "plugins", "factorio")
LIVE_KEYS = {"wake": ("earcon", "duck", "close_after_action"), "tts": ("reply_sentences", "pronunciations"),
             "llm": ("tools", "system", "action_plans")}


def reload(config):
    """-> {"applied": [пути], "layout": новый вид окна или None}."""
    import main
    fresh = main.load_config()
    applied = []
    old_ui = copy.deepcopy(config.get("ui") or {})
    for section in LIVE_SECTIONS:
        if section in fresh and fresh.get(section) != config.get(section):
            config[section] = copy.deepcopy(fresh[section])
            applied.append(section)
    for section, keys in LIVE_KEYS.items():
        target = config.setdefault(section, {})
        for key in keys:
            value = (fresh.get(section) or {}).get(key)
            if value is not None and target.get(key) != value:
                target[key] = copy.deepcopy(value)
                applied.append(f"{section}.{key}")
    if "tts.pronunciations" in applied:
        import speech_text
        speech_text.PRONUNCIATIONS = (config.get("tts") or {}).get("pronunciations") or {}
    ui = config.get("ui") or {}
    if "ui" in applied:
        import actions
        actions.AVATAR.refresh_options(config)
        if ui.get("layout") != old_ui.get("layout"):
            import display
            display.set_mode(config, ui.get("layout", "auto"))
        elif (ui.get("monitor"), ui.get("position")) != (old_ui.get("monitor"), old_ui.get("position")):
            actions.place_hud(int(ui.get("monitor") or 0), ui.get("position") or "")
    return {"applied": applied}
