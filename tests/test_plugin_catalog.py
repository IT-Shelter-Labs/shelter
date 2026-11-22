import hashlib
import json
import os
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
from unittest.mock import patch

import plugin_catalog as catalog
import plugins_manager as plugins
from tests.test_plugins import package, manifest


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = package(cls.temp.name, manifest(), "def run(p,c): return 'ok'\n")
        with open(cls.path, "rb") as stream:
            cls.sha = hashlib.sha256(stream.read()).hexdigest()
        with open(os.path.join(cls.temp.name, "index.json"), "w") as stream:
            json.dump({"format": "jarvis.catalog", "version": 1, "packages": [{"id": "demo-plugin", "version": "1.0.0", "sha256": cls.sha, "file": os.path.basename(cls.path)}]}, stream)
        class Quiet(SimpleHTTPRequestHandler):
            def log_message(self, *_): pass
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=cls.temp.name))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.source = f"http://127.0.0.1:{cls.server.server_port}/index.json"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()
        cls.temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patches = [patch.object(catalog, "CACHE", self.temp.name), patch.object(catalog, "_pending", {})]
        for p in self.patches: p.start(); self.addCleanup(p.stop)

    def test_source_load_never_installs(self):
        with patch.object(plugins, "install") as install:
            self.assertEqual(catalog.fetch(self.source, local=True)["packages"][0]["sha256"], self.sha)
            install.assert_not_called()

    def test_http_is_never_enabled_implicitly(self):
        with self.assertRaises(plugins.PluginError): catalog.fetch(self.source)
        with self.assertRaises(plugins.PluginError): catalog._url("http://example.org/index.json", local=True)
        with self.assertRaises(plugins.PluginError): catalog._url("https://user:password@example.org/index.json")

    def test_preview_then_exact_reviewed_bytes(self):
        with patch.object(plugins, "install", return_value={"ok": True}) as install:
            info = catalog.prepare(self.source, "demo-plugin", "1.0.0", self.sha, local=True)
            self.assertEqual(info["manifest"]["name"], "Демо")
            install.assert_not_called()
            self.assertEqual(catalog.install(info["ticket"]), {"ok": True})
            install.assert_called_once()
            self.assertFalse(os.path.exists(install.call_args.args[0]))

    def test_tampered_download_cannot_be_installed(self):
        with patch.object(catalog, "_read", side_effect=[json.dumps({"format":"jarvis.catalog","version":1,"packages":[{"id":"demo-plugin","version":"1.0.0","file":"p.zip","sha256":self.sha}]}).encode(), b"different"]):
            with self.assertRaisesRegex(plugins.PluginError, "сумма"):
                catalog.prepare(self.source, "demo-plugin", "1.0.0", self.sha, local=True)
        self.assertFalse(catalog._pending)

    def test_archive_cannot_change_after_preview(self):
        info = catalog.prepare(self.source, "demo-plugin", "1.0.0", self.sha, local=True)
        record = catalog._pending[info["ticket"]]
        with open(record["path"], "wb") as stream: stream.write(b"tamper")
        with patch.object(plugins, "install") as install:
            with self.assertRaises(plugins.PluginError): catalog.install(info["ticket"])
            install.assert_not_called()

    def test_catalog_cannot_silently_change_reviewed_hash(self):
        with self.assertRaisesRegex(plugins.PluginError, "изменился"):
            catalog.prepare(self.source, "demo-plugin", "1.0.0", "0"*64, local=True)
