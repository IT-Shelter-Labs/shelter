import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location("public_export",ROOT/"tools/export_public.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class PublicExport(unittest.TestCase):
    def test_personal_and_generated_paths_never_enter_source_manifest(self):
        paths={str(p.relative_to(ROOT)).replace("\\","/") for p in module.selected()}
        self.assertIn("main.py",paths);self.assertIn("native/src/lib.rs",paths)
        for path in paths:
            self.assertFalse(path.startswith(("data/","models/","datasets/","reports/",".git/","DwnldedModels/",".review_tools/")),path)
            self.assertNotIn("node_modules",path.split("/"));self.assertNotIn("target",path.split("/"))
        self.assertNotIn("config.yaml",paths)
        self.assertNotIn("android/local.properties",paths)

    def test_existing_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):module.export(Path(folder))
