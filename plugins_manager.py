"""Расширения Джарвиса: манифест, установка, обновление с откатом, запуск в отдельном процессе.

Пакет .jarvis-plugin.zip:
    plugin.json  — манифест (см. MANIFEST_FIELDS ниже и docs/PLUGINS.md)
    main.py      — код (entry в манифесте)
    ...          — прочие файлы плагина

Установленные: data/plugins/<id>/<версия>/, активная версия — в data/plugins/state.json.
Обновление ставится рядом, переключение — после проверки; прежняя версия
остаётся для отката. Оборванная установка не трогает рабочую версию.

Вызов — в отдельном процессе (plugin_host.py) с таймаутом и ограничением
памяти: зависший или упавший плагин не останавливает голосовой цикл. Это не
защищённая песочница: плагин — доверенный код с правами пользователя, поэтому
перед установкой показываются автор, источник, права и лицензия.
Типы: action, tts, stt, trigger, widget и reaction (см. plugin_extensions.py).
"""

import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(ROOT, "data", "plugins")
STATE = os.path.join(DIR, "state.json")
CATALOG = os.path.join(ROOT, "plugins", "catalog")
LEGACY = os.path.join(ROOT, "plugins")
CORE_VERSION = (2, 0, 0)  # Plugin API compatibility, not the unreleased product version.
FORMAT = "jarvis.plugin"
SUPPORTED_KINDS = {"action", "tts", "stt", "trigger", "widget", "reaction"}
PERMISSIONS = {"network": "Доступ в интернет", "files": "Чтение и запись файлов", "keyboard": "Нажатие клавиш",
               "clipboard": "Буфер обмена", "processes": "Запуск программ", "microphone": "Микрофон", "screen": "Снимок экрана"}
MAX_PACKAGE = 20 * 1024 * 1024
MAX_UNPACKED = 100 * 1024 * 1024
MAX_RESPONSE = 8 * 1024 * 1024
TIMEOUT = 30
MEMORY_LIMIT_MB = 512
ID_RE = re.compile(r"^[a-z][a-z0-9_-]{2,40}$")
VERSION_RE = re.compile(r"[0-9]+(?:\.[0-9]+){0,2}(?:[-+][0-9A-Za-z][0-9A-Za-z.-]*)?")

_lock = threading.RLock()


class PluginError(ValueError):
    pass


def _version(text):
    parts = re.findall(r"\d+", str(text or "0"))[:3]
    return tuple(int(p) for p in parts + ["0"] * (3 - len(parts)))


def _compatible(spec):
    """«>=2.0» / «>=2.0,<3» — совместимость с версией ядра."""
    for clause in str(spec or "").split(","):
        clause = clause.strip()
        match = re.fullmatch(r"(>=|<=|>|<|==)?\s*([\d.]+)", clause)
        if not clause:
            continue
        if not match:
            return False
        op, version = match[1] or ">=", _version(match[2])
        ok = {">=": CORE_VERSION >= version, "<=": CORE_VERSION <= version, ">": CORE_VERSION > version,
              "<": CORE_VERSION < version, "==": CORE_VERSION[:len(version)] == version}[op]
        if not ok:
            return False
    return True


def validate_manifest(manifest):
    """Список причин, почему плагин нельзя ставить; пусто — можно."""
    problems = []
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        return ["это не плагин Джарвиса (нет format: jarvis.plugin)"]
    if int(manifest.get("format_version", 1)) > 1:
        problems.append("плагин для более новой версии формата — обновите Джарвиса")
    if not ID_RE.fullmatch(str(manifest.get("id", ""))):
        problems.append("id: латиница, цифры, - и _, от 3 до 40 знаков")
    for key in ("name", "version", "author", "entry"):
        if not str(manifest.get(key) or "").strip():
            problems.append(f"в манифесте нет поля {key}")
    if not VERSION_RE.fullmatch(str(manifest.get("version", ""))) or len(str(manifest.get("version", ""))) > 64:
        problems.append("version: номер версии, например 1.0.0; пути и специальные имена запрещены")
    kinds = set(manifest.get("kinds") or ["action"])
    unsupported = kinds - SUPPORTED_KINDS
    if unsupported:
        problems.append("тип расширения пока не поддерживается: " + ", ".join(sorted(unsupported)))
    if not _compatible(manifest.get("core", ">=2.0")):
        problems.append(f"несовместим с этой версией Джарвиса (нужно {manifest.get('core')})")
    platform = "windows" if os.name == "nt" else "linux"
    if manifest.get("platforms") and platform not in manifest["platforms"]:
        problems.append("не работает на этой системе")
    unknown = set(manifest.get("permissions") or []) - set(PERMISSIONS)
    if unknown:
        problems.append("неизвестные права: " + ", ".join(sorted(unknown)))
    entry = str(manifest.get("entry") or "")
    if entry and (not entry.endswith(".py") or os.path.isabs(entry) or ".." in entry.replace("\\", "/").split("/")):
        problems.append("entry — .py файл внутри пакета")
    for action in manifest.get("actions") or []:
        if not isinstance(action, dict) or not re.fullmatch(r"[a-z_][a-z0-9_]{0,40}", str(action.get("id", ""))):
            problems.append("у действия плагина нужен id латиницей")
    return problems


# ------------------------------------------------------------- состояние

def _state():
    try:
        with open(STATE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(data):
    os.makedirs(DIR, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=DIR, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temporary, STATE)


def _manifest_at(folder):
    with open(os.path.join(folder, "plugin.json"), encoding="utf-8") as f:
        return json.load(f)


def installed():
    """Установленные плагины: активная версия, прежние версии, включён ли, проблемы."""
    out = []
    state = _state()
    for plugin_id, entry in sorted(state.items()):
        folder = os.path.join(DIR, plugin_id, entry.get("current", ""))
        try:
            manifest = _manifest_at(folder)
        except (OSError, ValueError):
            out.append({"id": plugin_id, "name": plugin_id, "broken": True, "enabled": False, "problems": ["файлы плагина повреждены"]})
            continue
        out.append({**{k: manifest.get(k) for k in ("id", "name", "version", "author", "description", "license", "source",
                                                     "permissions", "actions", "core", "platforms", "kinds", "settings_schema")},
                    "enabled": entry.get("enabled", True), "previous": entry.get("previous", []),
                    "problems": validate_manifest(manifest), "trusted_source": entry.get("trusted", False)})
    # Старые плагины — одиночные .py в plugins/ без манифеста.
    if os.path.isdir(LEGACY):
        for name in sorted(os.listdir(LEGACY)):
            if name.endswith(".py") and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.py", name):
                out.append({"id": name[:-3], "name": name[:-3], "version": "файл", "author": "вы", "legacy": True,
                            "enabled": True, "permissions": [], "actions": [], "problems": [],
                            "description": "Одиночный файл без манифеста. Работает как раньше, в отдельном процессе."})
    return out


# ----------------------------------------------------------------- пакет

def inspect(path):
    """Проверка пакета без установки -> манифест и сведения для окна подтверждения."""
    if os.path.getsize(path) > MAX_PACKAGE:
        raise PluginError("пакет больше 20 МБ")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) > 1000 or len({n.casefold().rstrip('/') for n in names}) != len(names):
            raise PluginError("слишком много файлов или повторяющиеся пути в пакете")
        for name in names:
            if name.startswith(("/", "\\")) or ".." in name.split("/") or ":" in name or "\\" in name:
                raise PluginError(f"небезопасный путь в архиве: {name}")
            if (archive.getinfo(name).external_attr >> 16) & 0o170000 == 0o120000:
                raise PluginError("символические ссылки в пакете запрещены")
        if "plugin.json" not in names:
            raise PluginError("в пакете нет plugin.json")
        manifest = json.loads(archive.read("plugin.json"))
        problems = validate_manifest(manifest)
        if manifest.get("entry") not in names:
            problems.append(f"в пакете нет файла {manifest.get('entry')}")
        size = sum(archive.getinfo(n).file_size for n in names)
        if size > MAX_UNPACKED:
            raise PluginError("распакованный плагин больше 100 МБ")
        with open(path, "rb") as f:
            digest = hashlib.file_digest(f, "sha256").hexdigest()
    current = _state().get(manifest.get("id", ""), {})
    return {"manifest": manifest, "problems": problems, "size": size, "sha256": digest,
            "permissions": [PERMISSIONS.get(p, p) for p in manifest.get("permissions") or []],
            "update_from": current.get("current", ""), "files": len(names)}


def install(path, trusted=False):
    """Поставить или обновить. Рабочая версия меняется только после успешной распаковки."""
    info = inspect(path)
    if info["problems"]:
        raise PluginError("; ".join(info["problems"]))
    manifest = info["manifest"]
    plugin_id, version = manifest["id"], str(manifest["version"])
    target = os.path.join(DIR, plugin_id, version)
    with _lock:
        if os.path.exists(target):
            existing = _state().get(plugin_id, {})
            if existing.get("current") == version and existing.get("sha256") == info["sha256"]:
                return info
            raise PluginError("эта версия уже установлена; для обновления нужен новый номер версии")
        os.makedirs(os.path.join(DIR, plugin_id), exist_ok=True)
        staging = tempfile.mkdtemp(dir=os.path.join(DIR, plugin_id), prefix=".install-")
        try:
            with zipfile.ZipFile(path) as archive:
                archive.extractall(staging)
            os.replace(staging, target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        state = _state()
        entry = state.get(plugin_id, {})
        previous = [v for v in entry.get("previous", []) if v != version]
        if entry.get("current") and entry["current"] != version:
            previous = [entry["current"]] + previous
        state[plugin_id] = {"current": version, "previous": previous[:3], "enabled": entry.get("enabled", True),
                            "trusted": trusted, "sha256": info["sha256"], "installed": time.time()}
        _save_state(state)
    return {"id": plugin_id, "version": version, "updated_from": info["update_from"]}


def rollback(plugin_id):
    with _lock:
        state = _state()
        entry = state.get(plugin_id)
        if not entry or not entry.get("previous"):
            raise PluginError("нет прежней версии для отката")
        back = entry["previous"].pop(0)
        if not os.path.isdir(os.path.join(DIR, plugin_id, back)):
            raise PluginError("файлы прежней версии не найдены")
        entry["previous"].insert(0, entry["current"])
        entry["current"] = back
        _save_state(state)
    return {"id": plugin_id, "version": back}


def set_enabled(plugin_id, enabled):
    with _lock:
        state = _state()
        if plugin_id not in state:
            raise PluginError("плагин не установлен")
        state[plugin_id]["enabled"] = bool(enabled)
        _save_state(state)


def remove(plugin_id):
    with _lock:
        state = _state()
        if plugin_id not in state:
            raise PluginError("плагин не установлен")
        del state[plugin_id]
        _save_state(state)
        shutil.rmtree(os.path.join(DIR, plugin_id), ignore_errors=True)


def catalog():
    """Встроенный проверенный каталог: пакеты в plugins/catalog/*.jarvis-plugin.zip."""
    out = []
    if not os.path.isdir(CATALOG):
        return out
    state = _state()
    for name in sorted(os.listdir(CATALOG)):
        if not name.endswith(".zip"):
            continue
        path = os.path.join(CATALOG, name)
        try:
            info = inspect(path)
        except Exception as error:
            out.append({"file": name, "problems": [str(error)]})
            continue
        manifest = info["manifest"]
        out.append({"file": name, "id": manifest.get("id"), "name": manifest.get("name"), "version": manifest.get("version"),
                    "author": manifest.get("author"), "description": manifest.get("description", ""),
                    "license": manifest.get("license", ""), "source": "встроенный каталог (проверен)",
                    "permissions": info["permissions"], "size": info["size"], "changes": manifest.get("changes", ""),
                    "problems": info["problems"], "installed": state.get(manifest.get("id"), {}).get("current", "")})
    return out


def install_from_catalog(file_name):
    if not re.fullmatch(r"[\w.-]+\.zip", file_name or ""):
        raise PluginError("неверное имя пакета")
    return install(os.path.join(CATALOG, file_name), trusted=True)


# ---------------------------------------------------------------- запуск

def _entry(plugin_id):
    state = _state().get(plugin_id)
    if state:
        if not state.get("enabled", True):
            raise PluginError(f"плагин {plugin_id} выключен")
        folder = os.path.join(DIR, plugin_id, state["current"])
        manifest = _manifest_at(folder)
        problems = validate_manifest(manifest)
        if problems:
            raise PluginError("; ".join(problems))
        return os.path.join(folder, manifest["entry"]), manifest
    legacy = os.path.join(LEGACY, plugin_id + ".py")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", plugin_id or "") and os.path.isfile(legacy):
        return legacy, {"id": plugin_id, "settings": {}}
    raise PluginError(f"плагин не найден: {plugin_id}")


def call(plugin_id, action="", params=None, settings=None, timeout=TIMEOUT, token=None, strict=False):
    """Вызов в отдельном процессе. -> результат плагина или PluginError с причиной.

    Плагину передаются только его параметры и его настройки — не весь конфиг с ключами."""
    entry, manifest = _entry(plugin_id)
    settings = checked_settings(manifest.get("settings_schema") or {}, settings or {})
    log_dir = os.path.join(ROOT, "logs", "plugins")
    os.makedirs(log_dir, exist_ok=True)
    request = {"entry": entry, "action": action, "strict": strict, "params": params or {},
               "context": {"plugin": plugin_id, "settings": settings or {}, "data_dir": os.path.join(DIR, plugin_id, "data")}}
    with open(os.path.join(log_dir, plugin_id + ".log"), "a", encoding="utf-8") as log:
        log.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} {action or 'run'}\n")
        log.flush()
        process = subprocess.Popen([sys.executable, "-I", os.path.join(ROOT, "plugin_host.py")], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8",
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + timeout
        try:
            import psutil
            watched = psutil.Process(process.pid)
        except Exception:
            watched = None
        payload = json.dumps(request) + "\n"
        try:
            while True:
                reason = ""
                if time.monotonic() > deadline:
                    reason = f"плагин не ответил за {timeout} с — остановлен"
                elif token is not None and token.is_set():
                    reason = "остановлено"
                elif watched is not None:
                    try:
                        if watched.memory_info().rss > MEMORY_LIMIT_MB * 1024 * 1024:
                            reason = f"плагин занял больше {MEMORY_LIMIT_MB} МБ памяти — остановлен"
                    except Exception:
                        pass
                if reason:
                    raise PluginError(reason)
                try:
                    # communicate одновременно читает stdout: большой ответ не блокирует
                    # плагин на заполненной трубе до истечения таймаута.
                    stdout, _ = process.communicate(input=payload, timeout=.1)
                    break
                except subprocess.TimeoutExpired:
                    payload = None
            if len(stdout.encode("utf-8")) > MAX_RESPONSE:
                raise PluginError("ответ плагина больше 8 МБ")
            output = stdout.strip().splitlines()
        finally:
            if process.poll() is None:
                if watched is not None:
                    try:
                        for child in watched.children(recursive=True):
                            try:
                                child.kill()
                            except Exception:
                                pass
                    except Exception:
                        pass
                process.kill()
                process.wait(timeout=5)
            for pipe in (process.stdin, process.stdout):
                if pipe is not None:
                    pipe.close()
    if not output:
        raise PluginError(f"плагин аварийно завершился (код {process.returncode}) — подробности в logs/plugins/{plugin_id}.log")
    reply = json.loads(output[-1])
    if not reply.get("ok"):
        raise PluginError(f"ошибка плагина: {reply.get('error')}")
    return reply.get("result")


def checked_settings(schema, values):
    """Small, documented JSON-schema subset shared by all extension kinds."""
    if not isinstance(values, dict):
        raise PluginError("Настройки дополнения должны быть объектом")
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        return values
    result = dict(values)
    for key, spec in properties.items():
        if not isinstance(spec, dict):
            raise PluginError("Неверное описание параметра дополнения")
        if key not in result and "default" in spec:
            result[key] = copy.deepcopy(spec["default"])
        if key not in result:
            if key in schema.get("required", []):
                raise PluginError(f"Заполните параметр дополнения: {spec.get('title', key)}")
            continue
        value = result[key]
        kind = spec.get("type")
        expected = {"string": lambda: isinstance(value, str), "boolean": lambda: type(value) is bool,
                    "integer": lambda: type(value) is int,
                    "number": lambda: type(value) in (int, float) and math.isfinite(value)}
        if kind in expected and not expected[kind]():
            raise PluginError(f"Неверный тип параметра дополнения: {key}")
        if "enum" in spec and value not in spec["enum"]:
            raise PluginError(f"Недопустимое значение параметра дополнения: {key}")
        if kind in ("number", "integer") and not spec.get("minimum", float("-inf")) <= value <= spec.get("maximum", float("inf")):
            raise PluginError(f"Параметр дополнения вне допустимого диапазона: {key}")
        if isinstance(value, str) and len(value) > min(4000, spec.get("maxLength", 4000)):
            raise PluginError(f"Параметр дополнения слишком длинный: {key}")
    return result
