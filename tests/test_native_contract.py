"""The development bridge must not hide production IPC route regressions."""
import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent


class NativeContract(unittest.TestCase):
    def test_all_control_post_routes_except_launcher_stop_are_reachable(self):
        tree = ast.parse((ROOT / "shelter_core/control.py").read_text(encoding="utf-8"))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "do_POST")
        routes = set()
        for node in ast.walk(method):
            if isinstance(node, ast.Compare) and ast.unparse(node.left) == "self.path":
                for value in node.comparators:
                    for string in ast.walk(value):
                        if isinstance(string, ast.Constant) and isinstance(string.value, str) and string.value.startswith("/api/"):
                            routes.add(string.value)
        source = (ROOT / "app/src-tauri/src/routes.rs").read_text(encoding="utf-8").split("#[cfg(test)]")[0]
        allowed = set(re.findall(r'"(/api/[^" ]+)"', source.split("pub fn post_allowed")[0]))
        self.assertGreater(len(routes), 20)
        self.assertEqual(routes - {"/api/stop"}, allowed)

    def test_native_timeouts_cover_recording_and_catalog_review(self):
        source = (ROOT / "app/src-tauri/src/routes.rs").read_text(encoding="utf-8")
        long = source.split("pub fn long_request")[1].split("#[cfg(test)]")[0]
        self.assertIn('"/api/audio/test"', long)
        self.assertIn('"/api/plugins"', long)
