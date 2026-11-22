import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import browser_episode
import media
import neural
import setup_tool
import startup_assets
import tts_server
import voice_assets


class RecoveryTests(unittest.TestCase):
    def test_partial_hub_snapshot_repairs_only_missing_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in voice_assets.REQUIRED:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"{}")
            victim = voice_assets.REQUIRED[-1]
            (root / victim).unlink()
            self.assertEqual(voice_assets.missing(root), [victim])

            def download(model, name, **kwargs):
                self.assertEqual(model, voice_assets.BASE)
                self.assertEqual(kwargs["endpoint"], "https://huggingface.co")
                (root / name).write_bytes(b"{}")

            with patch.object(voice_assets, "cached", return_value=None), patch.dict("sys.modules", {"huggingface_hub": SimpleNamespace(
                snapshot_download=lambda *args, **kwargs: str(root), hf_hub_download=download
            )}):
                self.assertEqual(tts_server.resolve(voice_assets.BASE), str(root))
            self.assertFalse(voice_assets.missing(root))

    def test_ollama_retries_handshake_and_skips_an_installed_latest_tag(self):
        timeout = RuntimeError("pull model manifest: net/http: TLS handshake timeout")
        with (
            patch.object(setup_tool, "_ollama_alive", return_value=True),
            patch.object(setup_tool, "ollama_models", side_effect=[[], ["embeddinggemma:latest"]]),
            patch.object(setup_tool, "_pull_model_once", side_effect=[timeout, None]) as pull,
            patch.object(setup_tool.time, "sleep"),
            patch.object(setup_tool, "emit") as emit,
        ):
            setup_tool.pull_model("embeddinggemma")
            setup_tool.pull_model("embeddinggemma")
        self.assertEqual(pull.call_count, 2)
        self.assertEqual(emit.call_args.kwargs["stage"], "retry")

    def test_missing_custom_recording_is_not_downloaded_or_overwritten(self):
        voice = SimpleNamespace(CLONE_URL="")
        with patch.object(neural, "_python") as runtime:
            neural.boot({"tts": {"clone": {"reference": "missing-sample.wav"}}}, voice, lambda: None)
            self.assertEqual(neural.status(), {"phase": "error", "reason": "reference"})
            runtime.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "embedded runtime is Windows only")
    def test_missing_windows_runtime_is_repaired_before_launch(self):
        voice = SimpleNamespace(CLONE_URL="", clone_health=lambda _: {"error": "test exit"})
        child = SimpleNamespace(returncode=0, poll=lambda: 0)
        with tempfile.TemporaryDirectory() as temp, patch.object(neural, "ROOT", temp), \
                patch.object(neural, "_installer", None), patch.object(neural, "_python", side_effect=[None, "python", "python"]), \
                patch.object(neural, "_healthy", return_value=True), patch.object(neural, "_nvidia", return_value=True), \
                patch.object(neural, "loading", return_value=True), patch.object(neural, "start", return_value="http://voice") as start, \
                patch.object(neural.subprocess, "Popen", return_value=child) as install:
            neural.boot({"tts": {"clone": {"speaker": "test"}}}, voice, lambda: None)
            self.assertEqual(install.call_args.args[0][-2:], ["install", "clone-runtime"])
            start.assert_called_once()
            self.assertEqual(neural.status(), {"phase": "error", "reason": "model"})

    def test_custom_model_paths_are_not_replaced(self):
        config = {"wake": {"model_path": "my-vosk", "vad": {"model": "my-vad"}},
                  "asr": {"engine": "gigaam", "model": "my-gigaam"}}
        self.assertEqual(startup_assets.needed(config), [])

    def test_recognition_starts_after_repair_and_optional_failures_do_not_prevent_it(self):
        calls = []

        def installer(component):
            calls.append(component)
            if component == "kws":
                raise OSError("offline")

        with patch.object(startup_assets, "needed", return_value=["vosk", "kws"]), \
                patch.object(startup_assets.setup_tool, "install", side_effect=installer):
            startup_assets.listen(lambda *_: calls.append("listening"), None, {}, None, threading.Event(), calls.append)
        self.assertEqual(calls, ["repairing", "vosk", "repairing", "kws", "running", "listening"])


class MediaTests(unittest.TestCase):
    def test_only_the_browser_session_gets_next_and_change_is_observed(self):
        previous = {"source": "Firefox", "title": "Серия 1", "next_enabled": True}
        after = {**previous, "title": "Серия 2"}
        with patch.object(media, "_browser_session", side_effect=[previous, after]), \
                patch.object(media, "control", return_value=True) as control:
            self.assertEqual(media.next_episode()[0], "done")
            control.assert_called_once_with("next", source="Firefox")

    def test_no_blind_next_on_absent_or_unsupported_player(self):
        with patch.object(media, "control") as control:
            for session in (None, {"source": "Firefox", "next_enabled": False}):
                with patch.object(media, "_browser_session", return_value=session):
                    self.assertEqual(media.next_episode()[0], "fail")
            control.assert_not_called()
        self.assertFalse(browser_episode.matches("следующий трек"))
        self.assertTrue(browser_episode.matches("перейди на следующий эпизод"))
