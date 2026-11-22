"""Voice service credentials shared by the parent, server and local benchmark."""
from shelter_core.paths import ROOT_PATH

import os
from pathlib import Path
import secrets

TOKEN_PATH = ROOT_PATH / "secrets" / "tts.token"
TOKEN_ENV = "JARVIS_TTS_TOKEN"


def token():
    inherited = os.environ.get(TOKEN_ENV, "")
    if inherited:
        return inherited
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        value = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if len(value) < 32:
            raise RuntimeError("Повреждён secrets/tts.token; перезапустите настройку голоса")
        return value
    value = secrets.token_urlsafe(32)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(value)
    return value


def headers():
    return {"Authorization": "Bearer " + token()}
