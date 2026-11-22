"""Пакет персонажа: экспорт без секретов и личных путей, импорт с проверкой, удаление без поломки соседей."""

import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import persona_package as package  # noqa: E402
import personas  # noqa: E402


class PersonaPackage(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.user = os.path.join(self.dir, "user")
        self.patch = patch.object(personas, "USER_DIR", self.user)
        self.patch.start()
        outside = os.path.join(self.dir, "private", "C-Users-me")
        os.makedirs(outside)
        self.model = os.path.join(outside, "girl.vrm")
        with open(self.model, "wb") as f:
            f.write(b"glTF" + os.urandom(2000))
        self.voice = os.path.join(outside, "voice.wav")
        with open(self.voice, "wb") as f:
            f.write(b"RIFF" + os.urandom(1000))
        personas.save({"id": "mika", "name": "Мика", "gender": "f", "address": "хозяин",
                       "voice": {"reference": self.voice, "pitch": 1.1, "api_key": "sk-secret"},
                       "avatar": {"type": "vrm", "model": self.model, "credit": "VRoid, CC-BY"}})

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def export(self, **kw):
        return package.export("mika", os.path.join(self.dir, "mika.zip"), **kw)

    def test_export_has_no_secrets_paths_or_voice_by_default(self):
        result = self.export(author="Я", license_text="CC-BY")
        with zipfile.ZipFile(result["path"]) as z:
            persona = json.loads(z.read("persona.json"))
            manifest = json.loads(z.read("manifest.json"))
            text = z.read("persona.json").decode() + z.read("manifest.json").decode()
        self.assertNotIn("sk-secret", text)
        self.assertNotIn(self.dir.replace("\\", "\\\\"), text)
        self.assertNotIn("reference", persona["voice"])
        self.assertFalse(manifest["voice_included"])
        self.assertTrue(persona["avatar"]["model"].startswith("assets/"))
        self.assertTrue(any("образец голоса" in n for n in result["notes"]))

    def test_round_trip_on_clean_profile(self):
        path = self.export(include_voice=True)["path"]
        clean = os.path.join(self.dir, "clean")
        with patch.object(personas, "USER_DIR", clean):
            installed = package.install(path)
            persona = personas.get(installed["id"])
            self.assertEqual(persona["name"], "Мика")
            self.assertEqual(persona["voice"]["pitch"], 1.1)
            self.assertTrue(os.path.isfile(personas.resolve(persona, persona["avatar"]["model"])))
            self.assertTrue(os.path.isfile(personas.resolve(persona, persona["voice"]["reference"])))
            again = package.install(path)
            self.assertNotEqual(again["id"], installed["id"], "повторный импорт не затирает")

    def test_missing_voice_gets_visible_status(self):
        path = self.export()["path"]
        with patch.object(personas, "USER_DIR", os.path.join(self.dir, "clean2")):
            persona = personas.get(package.install(path)["id"])
        self.assertIn("запасной", persona["voice"]["status"])

    def test_unsafe_or_corrupted_archives_rejected(self):
        bad = os.path.join(self.dir, "bad.zip")
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("manifest.json", json.dumps({"format": package.FORMAT, "version": 1, "files": []}))
            z.writestr("persona.json", "{}")
            z.writestr("../evil.vrm", b"x")
        with self.assertRaises(ValueError):
            package.install(bad)
        path = self.export()["path"]
        broken = os.path.join(self.dir, "broken.zip")
        with zipfile.ZipFile(path) as src, zipfile.ZipFile(broken, "w") as dst:
            for name in src.namelist():
                data = src.read(name)
                dst.writestr(name, data[:-10] + b"0123456789" if name.endswith(".vrm") else data)
        with self.assertRaisesRegex(ValueError, "контрольная сумма"):
            package.install(broken)
        newer = os.path.join(self.dir, "newer.zip")
        with zipfile.ZipFile(newer, "w") as z:
            z.writestr("manifest.json", json.dumps({"format": package.FORMAT, "version": 9}))
            z.writestr("persona.json", "{}")
        with self.assertRaisesRegex(ValueError, "новой версии"):
            package.install(newer)
        self.assertFalse([d for d in os.listdir(self.user) if d.startswith(".import")], "оборванная установка не оставляет мусор")

    def test_delete_refuses_when_variant_points_here(self):
        os.makedirs(os.path.join(self.user, "mika-alt"))
        with open(os.path.join(self.user, "mika-alt", "persona.json"), "w", encoding="utf-8") as f:
            json.dump({"redirect": "mika"}, f)
        with self.assertRaisesRegex(ValueError, "ссылается"):
            personas.delete("mika")


if __name__ == "__main__":
    unittest.main()
