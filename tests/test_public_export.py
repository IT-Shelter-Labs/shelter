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
        for path in paths:
            self.assertFalse(path.startswith(("data/","models/","datasets/","reports/",".git/","DwnldedModels/",".review_tools/")),path)
            self.assertNotIn("node_modules",path.split("/"));self.assertNotIn("target",path.split("/"))
        self.assertNotIn("config.yaml",paths)
        self.assertNotIn("android/local.properties",paths)

    def test_existing_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):module.export(Path(folder))

    def test_public_catalog_defaults_to_pippa_and_keeps_saved_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "snapshot"
            module.export(target)
            state = target / "data/persona.json"
            with patch.object(personas, "BUILTIN_DIR", str(target / "personas")), \
                    patch.object(personas, "USER_DIR", str(target / "data/personas")), \
                    patch.object(personas, "ACTIVE_PATH", str(state)):
                self.assertEqual(personas.active_id(), "pippa")
                self.assertEqual({p["id"] for p in personas.all_personas()}, set(module.PUBLIC_PRESETS))
                self.assertEqual(personas.call_words(personas.get("pippa"), {}), ["пиппа", "пипа"])
                personas._save_active("jarvis")
                self.assertEqual(personas.active_id(), "jarvis")
            self.assertEqual(list((target / "personas").rglob("*.vrm")), [target / "personas/manju/appearance.vrm"])
            for preset in (target / "personas").glob("*/persona.json"):
                self.assertNotIn("reference", json.loads(preset.read_text(encoding="utf8")).get("voice", {}))
