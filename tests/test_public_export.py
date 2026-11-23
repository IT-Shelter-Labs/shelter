import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shelter_core import personas

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location("public_export",ROOT/"tools/export_public.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class PublicExport(unittest.TestCase):
    def test_personal_and_generated_paths_never_enter_source_manifest(self):
        paths={str(p.relative_to(ROOT)).replace("\\","/") for p in module.selected()}
        self.assertIn("main.py",paths);self.assertIn("native/src/lib.rs",paths)
        self.assertIn("shelter_core/control.py", paths)
        self.assertNotIn("control.py", paths)
        self.assertIn("docs/README.md", paths)
        self.assertIn("docs/GUIDE.md", paths)
        for language in ("ru", "ja", "zh-CN"):
            for name in ("README.md", "GUIDE.md", "CONTRIBUTING.md", "SECURITY.md", "THIRD_PARTY.md"):
                self.assertIn(f"docs/{language}/{name}", paths)
        for path in paths:
            self.assertFalse(path.startswith(("data/","models/","datasets/","reports/",".git/","DwnldedModels/",".review_tools/")),path)
            self.assertNotIn("node_modules",path.split("/"));self.assertNotIn("target",path.split("/"))
        self.assertNotIn("config.yaml",paths)
        self.assertNotIn("android/local.properties",paths)

    def test_existing_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):module.export(Path(folder))

    def test_public_catalog_defaults_to_jarvis_and_keeps_saved_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "snapshot"
            module.export(target)
            state = target / "data/persona.json"
            with patch.object(personas, "ROOT", str(target)), \
                    patch.object(personas, "BUILTIN_DIR", str(target / "personas")), \
                    patch.object(personas, "USER_DIR", str(target / "data/personas")), \
                    patch.object(personas, "ACTIVE_PATH", str(state)):
                self.assertEqual(personas.active_id(), "jarvis")
                catalog = [p["id"] for p in personas.all_personas()]
                self.assertEqual(catalog[:3], ["jarvis", "pippa", "anime"])
                self.assertEqual(set(catalog), set(module.PUBLIC_PRESETS))
                self.assertEqual(personas.call_words(personas.get("pippa"), {}), ["пиппа", "пипа"])
                self.assertEqual(Path(personas.public(personas.get("pippa"))["voice"]["reference"]),
                                 target / "personas/anime/voice.wav")
                personas._save_active("pippa")
                self.assertEqual(personas.active_id(), "pippa")
                self.assertEqual(personas.all_personas()[0]["id"], "jarvis")
            self.assertEqual(set((target / "personas").rglob("*.vrm")),
                             {target / "personas" / persona_id / "appearance.vrm" for persona_id in module.PUBLIC_MODELS})
            self.assertTrue((target / "personas/jarvis/voice.wav").is_file())
            self.assertFalse(any((target / "personas").rglob("*.safetensors")))
            for preset in (target / "personas").glob("*/persona.json"):
                voice = json.loads(preset.read_text(encoding="utf8")).get("voice", {})
                self.assertEqual(voice.get("reference"), "voice.wav" if preset.parent.name == "anime" else None)
