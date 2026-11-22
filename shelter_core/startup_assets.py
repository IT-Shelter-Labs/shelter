"""Restore only known files for enabled built-in features; never touch custom paths."""
from pathlib import Path

from shelter_core import setup_tool
from shelter_core.voice_assets import present


def _default_path(value, path):
    root = Path(setup_tool.ROOT)
    return (root / (value or path)).resolve() == (root / path).resolve()


def needed(config):
    wake = config.get("wake") or {}
    asr = config.get("asr") or {}
    vad = wake.get("vad", {})
    root = Path(setup_tool.MODELS)
    models = []
    if _default_path(wake.get("model_path"), "models/vosk-ru"):
        models.append(("vosk", setup_tool.model_complete(root / "vosk-ru", "vosk")))
    if wake.get("engine") == "kws":
        models.append(("kws", setup_tool.model_complete(root / "kws-ru", "kws")))
    if asr.get("engine") == "gigaam" and _default_path(asr.get("model"), "models/gigaam-v3"):
        models.append(("gigaam", setup_tool.model_complete(root / "gigaam-v3", "gigaam")))
    if isinstance(vad, dict) and vad.get("enabled", True) and vad.get("engine", "silero") == "silero" and _default_path(
        vad.get("model"), "models/silero_vad.onnx"
    ):
        models.append(("vad", present(root / "silero_vad.onnx")))
    return [component for component, complete in models if not complete]


def listen(target, cap, config, events, stop, update):
    # Text control is already online while the speech worker restores its files.
    if config.get("repair_components", True) is not False:
        for component in needed(config):
            if stop.is_set():
                return
            update("repairing")
            try:
                setup_tool.install(component)
            except Exception as error:
                print(f"[repair] {component}: {error}", flush=True)
                if component == "vosk":
                    raise RuntimeError("Не удалось восстановить распознавание. Проверьте сеть и перезапустите Джарвиса.") from error
    if not stop.is_set():
        update("running")
        target(cap, config, events, stop)


def repair_piper(engine, name, config):
    if engine not in ("piper", "files", "clone") or name not in setup_tool.PIPER_VOICES or config.get("repair_components", True) is False:
        return
    try:
        setup_tool.install("piper:" + name)
    except Exception as error:
        print(f"[repair] piper: {error}", flush=True)
