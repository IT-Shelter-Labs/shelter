"""Переносимые персонажи: пакет .jarvis-persona.zip.

В пакете: manifest.json (формат, версия, автор, лицензии, файлы с SHA-256),
persona.json (характер, обращения, голосовые настройки, облики, анимации)
и файлы моделей. Не экспортируются: ключи, личная память, профиль голоса
хозяина и приватные абсолютные пути. Образец голоса для клона — только по
явному выбору («у меня есть права на этот голос»).

Импорт проверяет манифест, безопасные пути архива, типы и размеры файлов,
контрольные суммы и сам персонаж, а затем атомарно кладёт его в
data/personas/<id>. Недоступный голос не подменяется молча: в персонаже
появляется voice.status с понятной причиной.
"""

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import zipfile

import personas

FORMAT = "jarvis.persona"
VERSION = 1
LIMITS = {".vrm": 128, ".vrma": 32, ".glb": 16, ".png": 4, ".wav": 32, ".json": 1, ".md": 1, ".txt": 1}   # МБ
TOTAL_LIMIT = 400 * 1024 * 1024
SECRET_KEYS = re.compile(r"(token|password|secret|api[_-]?key)", re.I)


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if not SECRET_KEYS.search(str(k))}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def export(persona_id, target, include_voice=False, author="", license_text=""):
    persona = personas.get(persona_id)
    if persona is None:
        raise ValueError("нет такого персонажа")
    data = _clean(copy.deepcopy({k: v for k, v in persona.items() if k not in ("folder", "builtin", "active")}))
    files = {}          # имя в архиве -> путь на диске
    notes = []

    def take(holder, key, folder="assets"):
        path = holder.get(key)
        if not path:
            return
        source = personas.resolve(persona, path)
        if not os.path.isfile(source):
            notes.append(f"нет файла {os.path.basename(str(path))} — пропущен")
            holder.pop(key, None)
            return
        ext = os.path.splitext(source)[1].lower()
        if ext not in LIMITS:
            notes.append(f"{os.path.basename(source)}: тип файла не переносится")
            holder.pop(key, None)
            return
        name = f"{folder}/{_sha(source)[:16]}{ext}"
        files[name] = source
        holder[key] = name                      # относительный путь вместо личного абсолютного

    voice = data.get("voice") or {}
    if voice.get("reference") and include_voice:
        take(voice, "reference", "voice")
    elif voice.get("reference"):
        voice.pop("reference", None)
        voice.pop("reference_text", None)
        notes.append("образец голоса для клона не включён — на другом компьютере будет запасной голос")
    avatar = data.get("avatar") or {}
    take(avatar, "model")
    take(avatar, "preview")
    for item in avatar.get("accessories") or []:
        take(item, "file")
    for item in data.get("animations") or []:
        take(item, "file", "animations")
    for style in data.get("appearances") or []:
        take(style, "model")
        take(style, "preview")
    manifest = {"format": FORMAT, "version": VERSION, "id": persona["id"], "name": persona.get("name", ""),
                "author": author or "", "license": license_text or "", "created": time.time(),
                "credits": [c for c in [avatar.get("credit")] + [s.get("credit") for s in data.get("appearances") or []] if c],
                "voice_included": bool(include_voice and voice.get("reference")),
                "files": [{"path": n, "sha256": _sha(p), "size": os.path.getsize(p)} for n, p in sorted(files.items())]}
    if not target.lower().endswith(".zip"):
        target += ".zip"
    temporary = target + ".tmp"
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("persona.json", json.dumps(data, ensure_ascii=False, indent=2))
        for name, path in files.items():
            archive.write(path, name)
    os.replace(temporary, target)
    return {"path": target, "files": len(files), "notes": notes}


def _safe(name):
    if not name or name.startswith(("/", "\\")) or ":" in name or "\\" in name:
        return False
    parts = name.split("/")
    return all(p not in ("", ".", "..") for p in parts)


def inspect(path):
    """Проверка пакета без установки -> (manifest, persona, проблемы)."""
    problems = []
    if os.path.getsize(path) > TOTAL_LIMIT:
        raise ValueError("пакет больше 400 МБ")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        for name in names:
            if not _safe(name):
                raise ValueError(f"небезопасный путь в архиве: {name}")
        if "manifest.json" not in names or "persona.json" not in names:
            raise ValueError("это не пакет персонажа Джарвиса (нет manifest.json или persona.json)")
        manifest = json.loads(archive.read("manifest.json"))
        persona = json.loads(archive.read("persona.json"))
        if manifest.get("format") != FORMAT:
            raise ValueError("неизвестный формат пакета")
        if int(manifest.get("version", 0)) > VERSION:
            raise ValueError("пакет из более новой версии Джарвиса — обновите программу")
        listed = {f["path"]: f for f in manifest.get("files") or []}
        total = 0
        for name in names:
            if name in ("manifest.json", "persona.json"):
                continue
            info = archive.getinfo(name)
            ext = os.path.splitext(name)[1].lower()
            if ext not in LIMITS:
                raise ValueError(f"недопустимый тип файла: {name}")
            if info.file_size > LIMITS[ext] * 1024 * 1024:
                raise ValueError(f"{name}: больше {LIMITS[ext]} МБ")
            total += info.file_size
            if name not in listed:
                raise ValueError(f"{name} нет в манифесте")
            if hashlib.sha256(archive.read(name)).hexdigest() != listed[name].get("sha256"):
                raise ValueError(f"{name}: файл повреждён (контрольная сумма)")
        if total > TOTAL_LIMIT:
            raise ValueError("распакованный пакет больше 400 МБ")
        missing = [p for p in listed if p not in names]
        if missing:
            raise ValueError("в пакете не хватает файлов: " + ", ".join(missing[:3]))
    return manifest, persona, problems


def install(path):
    manifest, persona, _ = inspect(path)
    base = re.sub(r"[^a-z0-9_-]", "", str(manifest.get("id") or "persona").lower())[:30] or "persona"
    persona_id = base
    counter = 2
    while personas.get(persona_id) is not None or os.path.exists(os.path.join(personas.USER_DIR, persona_id)):
        persona_id = f"{base}-{counter}"
        counter += 1
    voice = persona.setdefault("voice", {})
    if not voice.get("reference"):
        voice["status"] = "Голос по образцу не входит в пакет — звучит запасной голос. Запишите образец в редакторе."
    os.makedirs(personas.USER_DIR, exist_ok=True)
    staging = tempfile.mkdtemp(dir=personas.USER_DIR, prefix=".import-")
    try:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name == "manifest.json":
                    continue
                target = os.path.join(staging, *name.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with archive.open(name) as source, open(target, "wb") as out:
                    shutil.copyfileobj(source, out)
        persona.pop("id", None)
        persona.pop("redirect", None)
        personas._validate(persona)
        if not str(persona.get("name") or "").strip():
            raise ValueError("у персонажа нет имени")
        with open(os.path.join(staging, "persona.json"), "w", encoding="utf-8") as f:
            json.dump(persona, f, ensure_ascii=False, indent=2)
        os.replace(staging, os.path.join(personas.USER_DIR, persona_id))   # атомарно: всё или ничего
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {"id": persona_id, "name": persona.get("name"), "voice_included": bool(manifest.get("voice_included")),
            "license": manifest.get("license", ""), "credits": manifest.get("credits", [])}
