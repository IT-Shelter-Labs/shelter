"""Дополнения: несовместимое отклоняется, авария и зависание не валят ядро, обновление с откатом."""

import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shelter_core import plugins_manager as pm  # noqa: E402


def package(folder, manifest, code):
    path = os.path.join(folder, f"{manifest['id']}-{manifest['version']}.zip")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("plugin.json", json.dumps(manifest))
        z.writestr("main.py", code)
    return path


def manifest(**extra):
    return {"format": "jarvis.plugin", "id": "demo-plugin", "name": "Демо", "version": "1.0.0", "author": "тест",
            "entry": "main.py", "core": ">=2.0", "kinds": ["action"], "permissions": [], **extra}


class Plugins(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.patches = [patch.object(pm, "DIR", os.path.join(self.dir, "plugins")),
                        patch.object(pm, "STATE", os.path.join(self.dir, "plugins", "state.json")),
                        patch.object(pm, "LEGACY", os.path.join(self.dir, "legacy"))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_example_action_runs_in_separate_process(self):
        pm.install(package(self.dir, manifest(), "import os\ndef run(params, context):\n    return {'pid': os.getpid(), 'x': params['x']}\n"))
        result = pm.call("demo-plugin", params={"x": 5})
        self.assertEqual(result["x"], 5)
        self.assertNotEqual(result["pid"], os.getpid())

    def test_incompatible_rejected_before_run(self):
        for bad, reason in ((manifest(core=">=9.0"), "несовместим"), (manifest(kinds=["unknown-kind"]), "не поддерживается"),
                            (manifest(permissions=["root"]), "неизвестные права"), (manifest(format="x"), "не плагин")):
            with self.assertRaisesRegex(pm.PluginError, reason):
                pm.install(package(self.dir, bad, "def run(p, c): pass\n"))

    def test_crash_and_hang_do_not_stop_core(self):
        pm.install(package(self.dir, manifest(), "import os\ndef run(p, c):\n    os._exit(3)\n"))
        with self.assertRaisesRegex(pm.PluginError, "аварийно"):
            pm.call("demo-plugin")
        pm.install(package(self.dir, manifest(version="1.0.1"), "import time\ndef run(p, c):\n    time.sleep(60)\n"))
        with self.assertRaisesRegex(pm.PluginError, "не ответил"):
            pm.call("demo-plugin", timeout=1.5)
        pm.install(package(self.dir, manifest(version="1.0.2"), "def run(p, c):\n    raise ValueError('сломан')\n"))
        with self.assertRaisesRegex(pm.PluginError, "сломан"):
            pm.call("demo-plugin")

    def test_update_rollback_and_broken_update_keeps_current(self):
        pm.install(package(self.dir, manifest(), "def run(p, c):\n    return 'v1'\n"))
        pm.install(package(self.dir, manifest(version="2.0.0"), "def run(p, c):\n    return 'v2'\n"))
        self.assertEqual(pm.call("demo-plugin"), "v2")
        pm.rollback("demo-plugin")
        self.assertEqual(pm.call("demo-plugin"), "v1")
        broken = os.path.join(self.dir, "broken.zip")
        with open(broken, "wb") as f:
            f.write(b"PK\x03\x04 not really a zip")
        with self.assertRaises(Exception):
            pm.install(broken)
        self.assertEqual(pm.call("demo-plugin"), "v1", "оборванная установка не повредила рабочую версию")

    def test_disabled_and_removed(self):
        pm.install(package(self.dir, manifest(), "def run(p, c):\n    return 1\n"))
        pm.set_enabled("demo-plugin", False)
        with self.assertRaisesRegex(pm.PluginError, "выключен"):
            pm.call("demo-plugin")
        pm.remove("demo-plugin")
        with self.assertRaisesRegex(pm.PluginError, "не найден"):
            pm.call("demo-plugin")

    def test_plugin_gets_only_its_settings(self):
        pm.install(package(self.dir, manifest(), "def run(p, c):\n    return sorted(c)\n"))
        self.assertEqual(pm.call("demo-plugin", settings={"a": 1}), ["data_dir", "plugin", "settings"])

    def test_builtin_catalog_is_valid(self):
        with patch.object(pm, "CATALOG", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins", "catalog")):
            items = pm.catalog()
        self.assertGreaterEqual(len(items), 2)
        self.assertTrue(all(not i["problems"] for i in items))

    def test_version_cannot_escape_install_folder(self):
        pm.install(package(self.dir, manifest(), "def run(p, c): return 'working'\n"))
        path = os.path.join(self.dir, "untrusted.zip")
        for version in ("..", "../..", "/tmp", "C:\\plugins"):
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("plugin.json", json.dumps(manifest(version=version)))
                archive.writestr("main.py", "def run(p, c): return 'bad'\n")
            with self.assertRaises(pm.PluginError):
                pm.install(path)
            self.assertEqual(pm.call("demo-plugin"), "working")

    def test_same_version_cannot_replace_working_code(self):
        original = package(self.dir, manifest(), "def run(p, c): return 'original'\n")
        pm.install(original)
        pm.install(original)
        changed = package(self.dir, manifest(), "def run(p, c): return 'changed'\n")
        with self.assertRaisesRegex(pm.PluginError, "новый номер"):
            pm.install(changed)
        self.assertEqual(pm.call("demo-plugin"), "original")

    def test_response_larger_than_pipe_buffer_does_not_deadlock(self):
        pm.install(package(self.dir, manifest(), "def run(p, c): return 'z' * 262144\n"))
        self.assertEqual(len(pm.call("demo-plugin", timeout=5)), 262144)

    def test_typed_extensions_and_missing_handlers(self):
        from shelter_core import plugin_extensions as ext
        import numpy as np
        config = {"security": {"allow_plugins": True}}
        code = """import base64
def tts(p, c): return {'encoding':'pcm_s16le', 'sample_rate':16000, 'audio':base64.b64encode(b'\\0\\0'*320).decode()}
def stt(p, c): return {'text':'Проверка русского голоса'}
def widget(p, c): return {'title':'Часы', 'text':'<script>не HTML</script>', 'rows':[{'label':'Время','value':'12:00'}]}
def trigger(p, c): return {'active':True, 'key':p['event']}
def reaction(p, c): return {'animation':'nod'}
"""
        pm.install(package(self.dir, manifest(kinds=["tts", "stt", "widget", "trigger", "reaction"]), code))
        with patch.object(ext, "_config", config):
            rate, audio = ext.synthesize("Здравствуйте", {"id": "demo-plugin"})
            self.assertEqual((rate, len(audio)), (16000, 320))
            self.assertEqual(ext.transcribe(np.zeros(4000), {"id": "demo-plugin"}), "Проверка русского голоса")
            self.assertEqual(ext.widgets(config)[0]["rows"][0]["value"], "12:00")
            self.assertEqual(ext.poll("demo-plugin", "minute", config), (True, "minute"))
        with self.assertRaises(pm.PluginError):
            ext.invoke("tts", "demo-plugin", {}, config={})
        pm.install(package(self.dir, manifest(version="1.0.1", kinds=["tts"]), "def run(p,c): return 'wrong'\n"))
        with patch.object(ext, "_config", config), self.assertRaisesRegex(pm.PluginError, "нет функции"):
            ext.synthesize("Текст", {"id": "demo-plugin"})

    def test_settings_schema_rejects_wrong_types_before_start(self):
        schema = {"type": "object", "required": ["api_key"], "properties": {
            "api_key": {"type": "string"}, "speed": {"type": "number", "minimum": .5, "maximum": 2, "default": 1}}}
        self.assertEqual(pm.checked_settings(schema, {"api_key": "test"})["speed"], 1)
        for values in ({}, {"api_key": "test", "speed": True}, {"api_key": "test", "speed": 4}):
            with self.assertRaises(pm.PluginError): pm.checked_settings(schema, values)


if __name__ == "__main__":
    unittest.main()
