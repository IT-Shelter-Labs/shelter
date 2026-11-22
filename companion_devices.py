"""Сопряжённые устройства пульта (телефон, планшет, Telegram) и защита от повторов.

Сопряжение: окно Джарвиса показывает одноразовый код (6 цифр, 5 минут),
телефон вводит код и имя — получает свой ключ. На диске хранится только хэш
ключа, поэтому файл устройств не даёт доступа. Отозванное устройство больше
ничего не выполняет. Старый общий токен (secrets/companion_token.txt) работает
как устройство «Основной ключ», пока его не отозвать.

Повтор одного запроса (обрыв связи, двойное нажатие, переотправка сообщения)
опознаётся по request_id и возвращает прежний ответ, ничего не выполняя снова.
"""

import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(ROOT, "data", "companion_devices.json")
CODE_TTL = 300
REQUEST_TTL = 600

_lock = threading.Lock()
_codes = {}            # код -> срок действия
_requests = {}         # (устройство, request_id) -> (время, ответ)


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _load():
    try:
        with open(STORE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) and isinstance(data.get("devices"), list) else {"devices": []}
    except (OSError, ValueError):
        return {"devices": []}


def _save(data):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(STORE), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temporary, STORE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def pairing_code():
    """Одноразовый код для нового устройства."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    with _lock:
        now = time.time()
        for old in [c for c, t in _codes.items() if t < now]:
            del _codes[old]
        _codes[code] = now + CODE_TTL
    return {"code": code, "expires": CODE_TTL}


def pair(code, name, kind="phone"):
    """Обменять код на ключ устройства. -> (id, ключ) или ValueError."""
    code = str(code or "").strip()
    with _lock:
        expires = _codes.pop(code, 0)
    if expires < time.time():
        raise ValueError("код неверный или устарел — получите новый в окне Джарвиса")
    token = secrets.token_urlsafe(32)
    device = {"id": "dev_" + secrets.token_hex(4), "name": str(name or "Устройство").strip()[:40] or "Устройство",
              "kind": kind, "hash": _hash(token), "created": time.time(), "last_seen": time.time(), "revoked": False}
    with _lock:
        data = _load()
        data["devices"].append(device)
        _save(data)
    return device["id"], token


def pair_chat(code, chat_id, name):
    """Telegram: «/start 123456» от владельца — запомнить его чат (ключа нет, вход по номеру чата)."""
    code = str(code or "").strip()
    with _lock:
        expires = _codes.pop(code, 0)
    if expires < time.time():
        raise ValueError("код неверный или устарел")
    device = {"id": "tg_" + secrets.token_hex(4), "name": str(name or "Telegram")[:40], "kind": "telegram",
              "chat": int(chat_id), "hash": "", "created": time.time(), "last_seen": time.time(), "revoked": False}
    with _lock:
        data = _load()
        data["devices"] = [d for d in data["devices"] if d.get("chat") != int(chat_id)] + [device]
        _save(data)
    return device["id"]


def chat_device(chat_id):
    """Сопряжённый и не отозванный чат Telegram -> устройство, иначе None."""
    for device in _load()["devices"]:
        if device.get("kind") == "telegram" and device.get("chat") == chat_id and not device.get("revoked"):
            return {k: v for k, v in device.items() if k != "hash"}
    return None


def verify(token, legacy=""):
    """Ключ -> устройство (без хэша) или None. Отозванное — None."""
    if not token:
        return None
    digest = _hash(token)
    with _lock:
        data = _load()
        for device in data["devices"]:
            if device.get("hash") and hmac.compare_digest(device.get("hash", ""), digest):
                if device.get("revoked"):
                    return None
                if time.time() - device.get("last_seen", 0) > 60:
                    device["last_seen"] = time.time()
                    _save(data)
                return {k: v for k, v in device.items() if k != "hash"}
        if legacy and hmac.compare_digest(token, legacy) and not data.get("legacy_revoked"):
            return {"id": "legacy", "name": "Основной ключ", "kind": "phone", "revoked": False}
    return None


def devices():
    data = _load()
    out = [{k: v for k, v in d.items() if k != "hash"} for d in data["devices"]]
    out.append({"id": "legacy", "name": "Основной ключ (общий)", "kind": "phone", "revoked": bool(data.get("legacy_revoked")),
                "created": 0, "last_seen": 0})
    return out


def revoke(device_id):
    with _lock:
        data = _load()
        if device_id == "legacy":
            data["legacy_revoked"] = True
        else:
            found = [d for d in data["devices"] if d["id"] == device_id]
            if not found:
                raise ValueError("нет такого устройства")
            found[0]["revoked"] = True
        _save(data)


def remember(device_id, request_id, run):
    """Выполнить один раз: повтор того же request_id вернёт прежний ответ.

    run() вызывается только для нового запроса. Без request_id — без защиты (старые клиенты)."""
    if not request_id:
        return run(), False
    key = (device_id, str(request_id)[:80])
    now = time.time()
    with _lock:
        for old in [k for k, (t, _) in _requests.items() if now - t > REQUEST_TTL]:
            del _requests[old]
        if key in _requests:
            return _requests[key][1], True
        _requests[key] = (now, {"accepted": True, "pending": True})
    result = run()
    with _lock:
        _requests[key] = (now, result)
    return result, False
