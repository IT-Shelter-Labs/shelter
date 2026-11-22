"""Opt-in catalog sources: preview a hash-pinned package, then install it.

HTTPS authenticates the source; a SHA256 pins the reviewed archive but does
not make its author trusted. Never downloads or executes on application start.
"""
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse
import urllib.request

import plugins_manager as plugins

CACHE = os.path.join(plugins.ROOT, "data", "plugin-downloads")
_pending = {}
_lock = threading.Lock()


def _url(value, *, local=False):
    parsed = urllib.parse.urlparse(value)
    if parsed.username or parsed.password or parsed.fragment or parsed.query or not parsed.hostname:
        raise plugins.PluginError("Нужен адрес каталога без пароля и фрагмента")
    if parsed.scheme != "https" and not (local and parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")):
        raise plugins.PluginError("Источник должен использовать HTTPS; локальная демонстрация допускает только localhost")
    return value


def _read(url, limit, local=False):
    _url(url, local=local)
    request = urllib.request.Request(url, headers={"User-Agent": "JarvisCatalog/1"})
    with urllib.request.urlopen(request, timeout=12) as response:
        _url(response.url, local=local)
        if int(response.headers.get("Content-Length", 0) or 0) > limit:
            raise plugins.PluginError("Файл источника слишком большой")
        deadline = time.monotonic() + 20
        data = bytearray()
        while len(data) <= limit:
            if time.monotonic() > deadline:
                raise plugins.PluginError("Источник загружает файл слишком долго")
            chunk = response.read1(min(65536, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
    if len(data) > limit:
        raise plugins.PluginError("Файл источника слишком большой")
    return bytes(data)


def fetch(source, local=False):
    index = json.loads(_read(source, 512 * 1024, local))
    if index.get("format") != "jarvis.catalog" or index.get("version") != 1 or not isinstance(index.get("packages"), list):
        raise plugins.PluginError("Неподдерживаемый формат каталога")
    packages = []
    seen = set()
    for entry in index["packages"][:200]:
        if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str) for k in ("id", "version", "file", "sha256")):
            raise plugins.PluginError("Повреждена запись каталога")
        import re
        if not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise plugins.PluginError("У пакета отсутствует SHA256")
        key = entry["id"], entry["version"]
        if key in seen:
            raise plugins.PluginError("В каталоге повторяется версия пакета")
        seen.add(key)
        url = _url(urllib.parse.urljoin(source, entry["file"]), local=local)
        if urllib.parse.urlparse(url).netloc != urllib.parse.urlparse(source).netloc:
            raise plugins.PluginError("Архив должен находиться на том же источнике")
        packages.append({"id": entry["id"], "name": str(entry.get("name", entry["id"]))[:120], "version": entry["version"],
                         "sha256": entry["sha256"], "url": url, "description": str(entry.get("description", ""))[:1000]})
    return {"name": str(index.get("name", "Каталог"))[:120], "source": source, "packages": packages}


def prepare(source, plugin_id, version, expected_hash, local=False):
    index = fetch(source, local)
    entry = next((p for p in index["packages"] if p["id"] == plugin_id and p["version"] == version), None)
    if not entry or entry["sha256"] != expected_hash:
        raise plugins.PluginError("Каталог изменился. Обновите список перед установкой")
    data = _read(entry["url"], plugins.MAX_PACKAGE, local)
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise plugins.PluginError("Контрольная сумма архива не совпадает — установка отменена")
    os.makedirs(CACHE, exist_ok=True)
    ticket = secrets.token_hex(20)
    path = os.path.join(CACHE, ticket + ".zip")
    try:
        with open(path, "xb") as stream:
            stream.write(data)
        info = plugins.inspect(path)
        if info["problems"]:
            raise plugins.PluginError("; ".join(info["problems"]))
        if (info["manifest"]["id"], info["manifest"]["version"]) != (plugin_id, version):
            raise plugins.PluginError("Манифест архива не соответствует каталогу")
        with _lock:
            for old, record in list(_pending.items()):
                if record["due"] < time.monotonic():
                    os.unlink(record["path"]) if os.path.isfile(record["path"]) else None
                    del _pending[old]
            if len(_pending) >= 8:
                raise plugins.PluginError("Слишком много ожидающих установок. Завершите предыдущие")
            _pending[ticket] = {"path": path, "sha256": expected_hash, "due": time.monotonic() + 600}
        return {**info, "ticket": ticket, "source": source, "sha256": expected_hash}
    except Exception:
        os.unlink(path) if os.path.isfile(path) else None
        raise


def install(ticket):
    with _lock:
        record = _pending.pop(ticket, None)
    if not record:
        raise plugins.PluginError("Предпросмотр установки устарел. Выберите пакет заново")
    path = record["path"]
    try:
        with open(path, "rb") as stream:
            digest = hashlib.sha256(stream.read()).hexdigest()
        if record["due"] < time.monotonic() or digest != record["sha256"]:
            raise plugins.PluginError("Пакет изменился или время подтверждения истекло")
        return plugins.install(path, trusted=False)
    finally:
        os.unlink(path) if os.path.isfile(path) else None
