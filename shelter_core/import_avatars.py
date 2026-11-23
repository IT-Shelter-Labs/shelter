"""Локальный импорт VRM из файлов/ZIP/RAR. Архивные программы и скрипты не запускаются.

python import_avatars.py DwnldedModels --install
Повторный запуск сохраняет пользовательские правки и активного персонажа.
"""
import argparse
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import zipfile

from shelter_core import personas

LIMIT = 128 * 1024 * 1024
REQUIRED_BONES = ("hips", "spine", "head", "leftUpperArm", "leftLowerArm", "leftHand",
                  "rightUpperArm", "rightLowerArm", "rightHand", "leftUpperLeg", "leftLowerLeg",
                  "leftFoot", "rightUpperLeg", "rightLowerLeg", "rightFoot")


def archive_name(name):
    try:
        return name.encode("cp437").decode("cp932")
    except UnicodeError:
        return name


def _document(stream, size=None):
    if size is None:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(0)
    header = stream.read(20)
    if len(header) != 20:
        raise ValueError("неполный заголовок GLB")
    magic, version, total, length, kind = struct.unpack("<4sIIII", header)
    if magic != b"glTF" or version != 2 or total != size or kind != 0x4E4F534A:
        raise ValueError("повреждённый GLB или неверный формат")
    if size > LIMIT or not 0 < length <= min(8 * 1024 * 1024, size - 20):
        raise ValueError("превышен размер модели/описания")
    try:
        doc = json.loads(stream.read(length))
    except (UnicodeError, ValueError) as error:
        raise ValueError("повреждённый JSON модели") from error
    if not isinstance(doc, dict):
        raise ValueError("описание модели должно быть объектом")
    return doc


def inspect_vrm(stream, size=None):
    doc = _document(stream, size)
    extensions = doc.get("extensions", {})
    version = "1.0" if "VRMC_vrm" in extensions else "0.x"
    vrm = extensions.get("VRMC_vrm", extensions.get("VRM"))
    if not isinstance(vrm, dict):
        raise ValueError("файл не содержит VRM")
    for item in [*doc.get("buffers", []), *doc.get("images", [])]:
        if item.get("uri") and not str(item["uri"]).lower().startswith("data:"):
            raise ValueError("внешние ресурсы: нужен цельный VRM")
    source_bones = vrm.get("humanoid", {}).get("humanBones", {})
    bones = source_bones if isinstance(source_bones, dict) else {item["bone"]: item for item in source_bones}
    missing = set(REQUIRED_BONES) - bones.keys()
    if missing:
        raise ValueError("неполный скелет: " + ", ".join(sorted(missing)))
    for bone in bones.values():
        index = bone.get("node")
        if type(index) is not int or not 0 <= index < len(doc.get("nodes", [])):
            raise ValueError("неверный индекс кости")
    meta = vrm.get("meta") or {}
    triangles = sum(doc["accessors"][primitive["indices"]]["count"] // 3
                    for mesh in doc.get("meshes", []) for primitive in mesh.get("primitives", [])
                    if "indices" in primitive and primitive.get("mode", 4) == 4)
    expressions = list((vrm.get("expressions") or {}).get("preset", {})) if version == "1.0" else [
        item.get("presetName") for item in (vrm.get("blendShapeMaster") or {}).get("blendShapeGroups", [])]
    return {"version": version, "title": meta.get("name", meta.get("title", "")),
            "author": meta.get("authors", meta.get("author", "")), "meta": meta,
            "triangles": triangles, "materials": len(doc.get("materials", [])),
            "bones": list(bones), "expressions": expressions}


def _sevenzip():
    path = shutil.which("7z") or "C:/Program Files/7-Zip/7z.exe"
    if not Path(path).is_file():
        raise ValueError("для чтения RAR нужен установленный 7-Zip")
    return path


def _entries(path):
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            return [(item.filename, item.file_size) for item in archive.infolist() if not item.is_dir()]
    if path.suffix.lower() == ".rar":
        result = subprocess.run([_sevenzip(), "l", "-slt", "-ba", "-sccUTF-8", "--", str(path.resolve())],
                                check=True, capture_output=True, encoding="utf-8", timeout=30)
        entries = []
        for block in result.stdout.split("\n\n"):
            fields = dict(line.split(" = ", 1) for line in block.splitlines() if " = " in line)
            if fields.get("Folder") == "-":
                entries.append((fields["Path"], int(fields["Size"])))
        return entries
    return [("", path.stat().st_size)]


@contextmanager
def _open(path, member=""):
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive, archive.open(member) as stream:
            yield stream
    elif path.suffix.lower() == ".rar":
        result = subprocess.run([_sevenzip(), "x", "-so", "-spd", "--", str(path.resolve()), member],
                                check=True, capture_output=True, timeout=60)
        yield io.BytesIO(result.stdout)
    else:
        with path.open("rb") as stream:
            yield stream


def _thumbnail(model, target):
    with model.open("rb") as stream:
        doc = _document(stream)
        bin_start = stream.tell() + 8
        extensions = doc["extensions"]
        if "VRMC_vrm" in extensions:
            index = extensions["VRMC_vrm"].get("meta", {}).get("thumbnailImage")
        else:
            texture = extensions["VRM"].get("meta", {}).get("texture")
            index = doc["textures"][texture].get("source") if isinstance(texture, int) and texture >= 0 else None
        if not isinstance(index, int) or index < 0:
            return
        image = doc["images"][index]
        if image.get("mimeType") != "image/png" or "bufferView" not in image:
            return
        view = doc["bufferViews"][image["bufferView"]]
        size = view["byteLength"]
        offset = view.get("byteOffset", 0)
        if view["buffer"] == 0 and 0 <= offset and 0 < size <= 4 * 1024**2:
            stream.seek(bin_start + offset)
            data = stream.read(size)
            if len(data) == size and data.startswith(b"\x89PNG\r\n\x1a\n"):
                target.write_bytes(data)


def attach_builtin(persona_id, filename):
    """Keep the preset's identity and voice while installing an author's VRM."""
    if persona_id not in personas.IMPORTED_PRESETS:
        raise ValueError("Выберите встроенного персонажа с отдельной 3D-моделью")
    preset = personas.get(persona_id)
    if not preset or not preset["builtin"]:
        raise ValueError("Встроенный персонаж не найден")
    source = Path(filename)
    if source.suffix.lower() not in (".vrm", ".zip") or not source.is_file():
        raise ValueError("Выберите скачанный файл VRM или ZIP")
    entries = [(member, size) for member, size in _entries(source)
               if 0 < size <= LIMIT and (not member or member.lower().endswith(".vrm"))]
    if len(entries) > 1 and persona_id == "pippa":
        entries = [(member, size) for member, size in entries if Path(member).name.lower() == "08_pippa.vrm"]
    if len(entries) != 1:
        raise ValueError("Распакуйте архив и выберите нужный файл VRM")
    member, size = entries[0]
    with tempfile.TemporaryDirectory(prefix="shelter-avatar-") as work, _open(source, member) as stream:
        model = Path(work) / "appearance.vrm"
        with model.open("wb") as file:
            shutil.copyfileobj(stream, file, length=1024**2)
        with model.open("rb") as file:
            inspect_vrm(file, size)
        profile = personas.public(preset)
        profile["id"] = personas.IMPORTED_PRESETS[persona_id]
        avatar = profile["avatar"]
        avatar.update(type="vrm", model=str(model))
        with model.open("rb") as file:
            original = hashlib.file_digest(file, "sha256").hexdigest().startswith(profile["id"][9:])
        if not original or not avatar.get("preview"):
            avatar.pop("preview", None)
            portrait = Path(work) / "preview.png"
            try:
                _thumbnail(model, portrait)
            except (KeyError, TypeError, IndexError, ValueError):
                pass  # Thumbnail metadata is optional.
            if portrait.is_file():
                avatar["preview"] = str(portrait)
        with personas._storage_lock:
            return personas.get(profile["id"]) or personas.save(profile)


def scan(folder):
    result = []
    for path in sorted(Path(folder).iterdir()):
        if not path.is_file():
            continue
        for member, size in _entries(path):
            name = archive_name(member) if member else path.name
            extension = Path(name).suffix.lower()
            if extension not in (".vrm", ".pmx", ".pmd", ".vroid", ".fbx", ".blend", ".unitypackage", ".vsfavatar", ".png", ".jpg"):
                continue
            record = {"source": path.name, "member": member, "display_file": name, "bytes": size, "extension": extension}
            if extension != ".vrm":
                record.update(status="unsupported", reason="нужен экспорт в VRM" if extension not in (".png", ".jpg") else "изображение, не модель")
            else:
                try:
                    if size > LIMIT:
                        raise ValueError("файл больше 128 МБ")
                    with _open(path, member) as stream:
                        record.update(inspect_vrm(stream, size))
                    record["status"] = "ready"
                except (ValueError, KeyError, TypeError, IndexError, OSError) as error:
                    record.update(status="invalid", reason=str(error))
            result.append(record)
    return result


def display_name(record):
    file, source = record["display_file"], record["source"]
    if source == "08_Pippa.zip":
        return "Пиппа — серебристая" if "Pippa_2" in file else "Пиппа — блондинка"
    if source == "tyc-3d-a.zip":
        variant = "стандартная"
        for marker, name in (("02 ", "в шортах"), ("03 ", "Recotte"), ("04 ", "для переодевания"), ("05 ", "лёгкая")):
            if marker in file:
                variant = name
        outline = "контур лица" if "顔だけ" in file else "без контура" if "輪郭線なし" in file else "с контуром"
        return f"Цукуёми — {variant}, {outline}"
    known = {"Cute_Model.vrm": "Кьют — Jessair", "AKAI_by_Shugan_v15.zip": "Акай",
             "MP-Vain_ver1.01.zip": "Вейн — робот", "MW_Miku.rar": "Мику",
             "yamaneko_white.zip": "Яманэко — белая", "まんじゅうにゃんこ_満足の紅.vrm": "Мандзю — кот"}
    return known.get(source, record.get("title") or Path(file).stem)


def _keep_terms(folder, source):
    terms = []
    for member, size in _entries(source):
        if not member or not 0 < size <= 1024 * 1024 or Path(member).suffix.lower() not in (".txt", ".md"):
            continue
        if len(terms) >= 32:
            break
        with _open(source, member) as stream:
            data = stream.read(1024 * 1024 + 1)
        target = folder / "licenses" / f"{len(terms) + 1:02d}.txt"
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(data)
        terms.append({"original": archive_name(member), "saved": target.name})
    if terms:
        personas._write_json(str(folder / "licenses/index.json"), terms)


def install(records, source_folder):
    for record in records:
        if record["status"] != "ready":
            continue
        source = Path(source_folder) / record["source"]
        with _open(source, record["member"]) as stream, tempfile.TemporaryDirectory(prefix="jarvis-avatar-") as temp:
            path = Path(temp) / "model.vrm"
            with path.open("wb") as destination:
                shutil.copyfileobj(stream, destination, length=1024 * 1024)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            persona_id = "download-" + digest[:20]
            record.update(persona_id=persona_id, sha256=digest, name=display_name(record))
            if personas.get(persona_id):
                record["status"] = "existing"
                continue
            robot = record["source"] == "MP-Vain_ver1.01.zip"
            cat = record.get("title") == "MeowManju"
            gender = "m" if robot or cat else "f"
            title = "Робот-автоматон: спокойный голос и чёткие ответы" if robot else "Кот-компаньон" if cat else ""
            template = personas.get("anime")
            voice = personas.public(template).get("voice", {}) if template and gender == "f" else {}
            name = record["name"]
            address = "сэр" if robot else "хозяин"
            profile = {"id": persona_id, "name": name, "title": title, "gender": gender,
                       "aliases": [" ".join(name.lower().replace("—", " ").replace(",", " ").split())],
                       "address": address, **personas.character_lines(name, gender, address), "voice": voice,
                       "avatar": {"type": "vrm", "model": str(path), "framing": "full" if cat else "portrait",
                                  "fps": 20 if record["triangles"] > 100000 else 30, "motion": 0.5 if cat else 1,
                                  "credit": "Автор модели: " + str(record.get("author", ""))},
                       "imported": {"source": record["source"], "member": record["display_file"], "sha256": digest}}
            saved = personas.save(profile)
            folder = Path(saved["folder"])
            _keep_terms(folder, source)
            personas._write_json(str(folder / "model-info.json"), record)
            record["status"] = "installed"
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("reports/downloaded-models.json"))
    args = parser.parse_args()
    records = scan(args.folder)
    if args.install:
        install(records, args.folder)
    personas._write_json(str(args.report.resolve()), records)
    counts = {status: sum(r["status"] == status for r in records) for status in ("ready", "installed", "existing", "invalid", "unsupported")}
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
