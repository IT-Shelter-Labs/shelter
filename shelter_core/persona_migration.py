"""Transfer character assets from a user-selected Shelter directory."""

import hashlib
import os
from pathlib import Path
import shutil
import tempfile

import yaml

from shelter_core import personas, tts_profiles, voice_assets


def _file(root, folder, name, suffix, limit):
    for base in (folder, root):
        candidate = (base / name).resolve()
        if not candidate.is_relative_to(root):
            continue
        if candidate.suffix.lower() == suffix and candidate.is_file() and 0 < candidate.stat().st_size <= limit * 1024**2:
            return candidate
    raise ValueError(f"В локальной версии отсутствует подходящий файл {suffix}")


def _profile(root, folder, persona_id):
    data = personas._read(folder / "persona.json")
    data["id"] = persona_id
    assets = [(data.get("voice") or {}, "reference", ".wav", 32)]
    for avatar in [data.get("avatar") or {}, *data.get("appearances", [])]:
        assets.extend(((avatar, "model", ".vrm", 128), (avatar, "preview", ".png", 4)))
        assets.extend((item, "file", ".glb", 16) for item in avatar.get("accessories", []))
    assets.extend((item, "file", ".vrma", 32) for item in data.get("animations", []))
    for section, key, suffix, limit in assets:
        if section.get(key):
            section[key] = str(_file(root, folder, section[key], suffix, limit))
    return data


def _jarvis_voice(source):
    with (source / "config.yaml").open(encoding="utf-8") as file:
        defaults = (yaml.safe_load(file) or {}).get("tts") or {}
    try:
        settings = personas._read(source / "data/settings.json").get("tts") or {}
    except FileNotFoundError:
        settings = {}
    clone = {**(defaults.get("clone") or {}), **(settings.get("clone") or {})}
    if not clone.get("reference"):
        return {}
    sample = _file(source, source, clone["reference"], ".wav", 32)
    target = Path(personas.ROOT) / "data/voice/restored"
    target.mkdir(parents=True, exist_ok=True)
    saved = target / personas._copy_asset(str(sample), str(target))
    result = {
        "reference": saved.relative_to(personas.ROOT).as_posix(),
        "reference_text": str(clone.get("reference_text", "")),
    }
    if clone.get("model") in voice_assets.OFFICIAL:
        result["model"] = clone["model"]
    if clone.get("jarvis_adapter"):
        folder = (source / clone["jarvis_adapter"]).resolve()
        manifest = _file(source, folder, "manifest.json", ".json", 1)
        weights = _file(source, folder, "adapter.safetensors", ".safetensors", 512)
        if manifest.parent != folder or weights.parent != folder:
            raise ValueError("Не найден полный набор файлов обученного голоса Джарвиса")
        with weights.open("rb") as file:
            if hashlib.file_digest(file, "sha256").hexdigest() != tts_profiles.manifest(folder).get("sha256"):
                raise ValueError("Контрольная сумма обученного голоса Джарвиса не совпадает")
        adapter = target / ("jarvis-" + tts_profiles.revision(folder)[:16])
        if not adapter.exists():
            with tempfile.TemporaryDirectory(dir=target) as staging:
                prepared = Path(staging) / "adapter"
                prepared.mkdir()
                for file in (manifest, weights):
                    shutil.copyfile(file, prepared / file.name)
                os.replace(prepared, adapter)
        result["jarvis_adapter"] = adapter.relative_to(personas.ROOT).as_posix()
    return result


def restore(directory, include_voice):
    source = Path(directory).resolve()
    if not directory or source == Path(personas.ROOT).resolve() or not (source / "config.yaml").is_file():
        raise ValueError("Выберите папку прежней установки Shelter, где находится config.yaml")
    with personas._storage_lock:
        profiles = []
        for character, persona_id in personas.IMPORTED_PRESETS.items():
            folder = source / "data/personas" / persona_id
            if personas.get(persona_id) or not (folder / "persona.json").is_file() or (folder / "persona.json").is_symlink():
                continue
            profiles.append((character, _profile(source, folder, persona_id)))
        clone = _jarvis_voice(source) if include_voice else {}
        restored = {character: personas.save(data)["id"] for character, data in profiles}
    return {"restored": restored, "clone": clone}
