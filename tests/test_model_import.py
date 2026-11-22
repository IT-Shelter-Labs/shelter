import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from shelter_core import import_avatars
from shelter_core import personas


def model(external=False):
    bones = [{"bone": name, "node": i} for i, name in enumerate(import_avatars.REQUIRED_BONES)]
    document = {"asset": {"version": "2.0"}, "nodes": [{} for _ in bones],
                "extensions": {"VRM": {"humanoid": {"humanBones": bones}, "meta": {"title": "Test", "author": "Author"}}},
                "images": [{"uri": "https://example.com/image.png"}] if external else []}
    data = json.dumps(document).encode()
    data += b" " * (-len(data) % 4)
    return struct.pack("<4sIIII", b"glTF", 2, 20 + len(data), len(data), 0x4E4F534A) + data


class ImportModels(unittest.TestCase):
    def test_checks_format_and_external_resources_before_import(self):
        info = import_avatars.inspect_vrm(io.BytesIO(model()))
        self.assertEqual(info["title"], "Test")
        self.assertEqual(info["version"], "0.x")
        for data in (b"not a model", model(True), model()[:-4]):
            with self.assertRaises(ValueError):
                import_avatars.inspect_vrm(io.BytesIO(data))

    def test_japanese_legacy_zip_names_are_recovered(self):
        original = "通常版/輪郭線あり.vrm"
        garbled = original.encode("cp932").decode("cp437")
        self.assertEqual(import_avatars.archive_name(garbled), original)
        self.assertEqual(import_avatars.archive_name("Already Unicode 猫.vrm"), "Already Unicode 猫.vrm")

    def test_rejects_accessory_with_no_humanoid_skeleton(self):
        document = {"asset": {"version": "2.0"}, "extensions": {"VRM": {"meta": {"title": "Hat"}}}}
        data = json.dumps(document).encode()
        data += b" " * (-len(data) % 4)
        binary = struct.pack("<4sIIII", b"glTF", 2, 20 + len(data), len(data), 0x4E4F534A) + data
        with self.assertRaisesRegex(ValueError, "скелет"):
            import_avatars.inspect_vrm(io.BytesIO(binary))

    def test_reimport_does_not_overwrite_edited_profile_or_active_choice(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "download").mkdir()
            with zipfile.ZipFile(root / "download/models.zip", "w") as archive:
                archive.writestr("nested/character.vrm", model())
                archive.writestr("../../bad.exe", b"not extracted")
                archive.writestr("readme.txt", "Author's terms")
            with patch.object(personas, "ROOT", str(root)), patch.object(personas, "USER_DIR", str(root / "data/personas")), \
                 patch.object(personas, "BUILTIN_DIR", str(root / "personas")), patch.object(personas, "ACTIVE_PATH", str(root / "data/persona.json")):
                personas._save_active("jarvis")
                records = import_avatars.scan(root / "download")
                imported = import_avatars.install(records, root / "download")
                saved = personas.get(imported[0]["persona_id"])
                self.assertEqual(Path(personas.resolve(saved, saved["avatar"]["model"])).read_bytes(), model())
                self.assertTrue((Path(saved["folder"]) / "licenses").is_dir())
                saved["name"] = "Моё имя"
                personas.save(saved)
                again = import_avatars.install(import_avatars.scan(root / "download"), root / "download")
                self.assertEqual(again[0]["status"], "existing")
                self.assertEqual(personas.get(saved["id"])["name"], "Моё имя")
                self.assertEqual(json.loads(Path(personas.ACTIVE_PATH).read_text())["active"], "jarvis")
                self.assertFalse((root / "bad.exe").exists())
