"""Typed extension boundaries. Workers execute trusted code, not sandboxed code.

Speech uses PCM16/base64; widgets contain text only; reactions name existing motions.
"""
import base64
import threading
import queue
import time

from shelter_core import plugins_manager as plugins

_config = {}
_lock = threading.Lock()
_reactions = queue.Queue(maxsize=1)
_reaction_thread = None
_generation = 0


def configure(config):
    global _config
    with _lock:
        _config = config


def react(state):
    """Latest-state-only worker; never blocks speech or replays old reactions."""
    global _reaction_thread, _generation
    with _lock:
        _generation += 1
        try:
            _reactions.get_nowait()
        except queue.Empty:
            pass
        _reactions.put_nowait((_generation, state))
        if _reaction_thread is None or not _reaction_thread.is_alive():
            _reaction_thread = threading.Thread(target=_react_loop, name="plugin-reactions", daemon=True)
            _reaction_thread.start()


def _react_loop():
    last = {}
    while True:
        generation, state = _reactions.get()
        if state not in ("listening", "speaking", "thinking", "confirm", "error"):
            continue
        for plugin in available("reaction"):
            if time.monotonic() - last.get(plugin["id"], -100) < 5:
                continue
            try:
                result = invoke("reaction", plugin["id"], {"state": state}, timeout=2)
                if generation != _generation:
                    break
                if isinstance(result, dict) and result.get("animation") in ("wave", "nod", "bow"):
                    from shelter_core import bus
                    bus.publish("avatar_motion", animation=result["animation"], source="plugin:" + plugin["id"])
                    last[plugin["id"]] = time.monotonic()
            except Exception as error:
                from shelter_core import bus
                bus.publish("plugin_error", name=plugin["id"], text=str(error)[:250])


def available(kind, config=None):
    config = _config if config is None else config
    if not (config.get("security") or {}).get("allow_plugins"):
        return []
    return [p for p in plugins.installed() if p.get("enabled", True) and not p.get("broken") and not p.get("problems")
            and kind in (p.get("kinds") or ["action"])]


def invoke(kind, plugin_id, params, *, config=None, settings=None, timeout=10, token=None):
    config = _config if config is None else config
    if not any(p["id"] == plugin_id for p in available(kind, config)):
        raise plugins.PluginError("дополнение выключено, не установлено или не поддерживает " + kind)
    from shelter_core import tasks
    token = token if token is not None else tasks.current()
    if settings is None:
        settings = ((config.get("plugins") or {}).get("settings") or {}).get(plugin_id, {})
    return plugins.call(plugin_id, action=kind, params=params, settings=settings,
                        timeout=timeout, token=token, strict=True)


def synthesize(text, profile):
    result = invoke("tts", profile.get("id"), {"text": text, "language": "ru"},
                    settings=profile.get("settings"), timeout=30)
    if not isinstance(result, dict) or result.get("encoding") != "pcm_s16le":
        raise plugins.PluginError("голос должен вернуть encoding: pcm_s16le, audio и sample_rate")
    rate = result.get("sample_rate")
    if not isinstance(rate, int) or isinstance(rate, bool) or not 8000 <= rate <= 48000:
        raise plugins.PluginError("частота голоса должна быть от 8000 до 48000 Гц")
    raw = base64.b64decode(result.get("audio", ""), validate=True)
    if not raw or len(raw) % 2 or len(raw) > rate * 2 * 60:
        raise plugins.PluginError("неверный размер аудио; максимум 60 секунд моно PCM16")
    import numpy as np
    return rate, np.frombuffer(raw, dtype="<i2").copy()


def transcribe(samples, profile):
    import numpy as np
    values = np.asarray(samples, dtype=np.float32).reshape(-1)
    if len(values) > 16000 * 90:
        raise plugins.PluginError("фраза для дополнения длиннее 90 секунд")
    raw = (np.clip(values, -1, 1) * 32767).astype("<i2").tobytes()
    result = invoke("stt", profile.get("id"), {"audio": base64.b64encode(raw).decode("ascii"),
                    "encoding": "pcm_s16le", "sample_rate": 16000, "language": "ru"},
                    settings=profile.get("settings"), timeout=30)
    if not isinstance(result, dict) or not isinstance(result.get("text"), str) or len(result["text"]) > 16000:
        raise plugins.PluginError("распознавание должно вернуть объект с text до 16000 знаков")
    return result["text"]


def widgets(config):
    items = []
    for plugin in available("widget", config):
        try:
            result = invoke("widget", plugin["id"], {}, config=config, timeout=2)
            if not isinstance(result, dict):
                raise ValueError("нужен объект виджета")
            rows = result.get("rows") or []
            items.append({"id": plugin["id"], "name": plugin["name"], "title": str(result.get("title", plugin["name"]))[:120],
                          "text": str(result.get("text", ""))[:2000], "rows": [
                              {"label": str(r.get("label", ""))[:100], "value": str(r.get("value", ""))[:200]}
                              for r in rows[:12] if isinstance(r, dict)]})
        except Exception as error:
            items.append({"id": plugin["id"], "name": plugin["name"], "error": str(error)[:250]})
    return items


def poll(plugin_id, event, config):
    result = invoke("trigger", plugin_id, {"event": event}, config=config, timeout=2)
    if not isinstance(result, dict) or not isinstance(result.get("active"), bool):
        raise plugins.PluginError("триггер должен вернуть active: true/false")
    return result["active"], str(result.get("key", event))[:120]
