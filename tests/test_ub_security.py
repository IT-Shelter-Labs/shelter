"""Regression cases found during ub-mode review; devices and GPU are simulated."""
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import numpy as np
import smarthome
import tasks
import tts_server
import tts_auth
import voice


class DeviceBoundaryTests(unittest.TestCase):
    def test_invalid_set_never_turns_on_a_device(self):
        device = {"name": "Лампа", "via": "webhook"}
        config = {"llm": {"tools": ["home"]}, "smarthome": {"enabled": True, "devices": [device]}}
        with patch.object(smarthome, "_devices", [device]), patch.dict(smarthome.ADAPTERS, {"webhook": lambda *a: self.fail("Device changed on invalid input")}):
            for command in ("set", "set banana", "set NaN", "setting 50", "office", "online"):
                with self.subTest(command=command), self.assertRaises(ValueError):
                    smarthome.act("Лампа", command, config)

    def test_duplicate_exact_alias_requires_clarification(self):
        devices = [{"name": "Свет в кухне", "aliases": ["лампа"]},
                   {"name": "Свет в спальне", "aliases": ["лампа"]}]
        with patch.object(smarthome, "_devices", devices):
            with self.assertRaises(smarthome.AmbiguousDevice):
                smarthome.find("лампа")

    def test_same_device_aliases_do_not_create_false_ambiguity(self):
        device = {"name": "Свет", "aliases": ["свет", "свет!"]}
        with patch.object(smarthome, "_devices", [device]):
            self.assertIs(smarthome.find("свет"), device)

    def test_existing_device_actions_still_work(self):
        for text, expected in (("on", ("on", None)), ("off", ("off", None)),
                               ("toggle", ("toggle", None)), ("выключи", ("off", None)),
                               ("set 50", ("set", 50)), ("50", ("set", 50)),
                               ("половина", ("set", 50))):
            with self.subTest(text=text):
                self.assertEqual(smarthome.parse_action(text), expected)

    def test_misheard_device_name_is_resolved_only_when_unique(self):
        lamp = {"name": "Настольная лампа"}
        with patch.object(smarthome, "_devices", [lamp]):
            self.assertIs(smarthome.find("настольная лмпа"), lamp)
            self.assertIsNone(smarthome.find("полив"))
            self.assertIsNone(smarthome.find(""))
        with patch.object(smarthome, "_devices", []):
            self.assertIsNone(smarthome.find("лампа"))

    def test_misheard_risky_or_ambiguous_name_is_not_guessed(self):
        thermostat = {"name": "Термостат", "entity": "climate.room"}
        with patch.object(smarthome, "_devices", [thermostat]):
            self.assertIsNone(smarthome.find("термостад"))
        with patch.object(smarthome, "_devices", [{"name": "Лампа спальни"}, {"name": "Лампа спальня"}]):
            with self.assertRaises(smarthome.AmbiguousDevice):
                smarthome.find("лампа спальны")


class VoiceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.token = patch.object(tts_server, "AUTH_TOKEN", "test-voice-token-0123456789abcdef", create=True)
        self.state = patch.object(tts_server, "STATE", {"ready": True, "sample_rate": 16000})
        self.stream = patch.object(tts_server, "stream", return_value=iter([np.zeros(100, dtype=np.float32)]))
        self.token.start(); self.state.start(); self.fake_stream = self.stream.start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), tts_server.Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(1)
        self.stream.stop(); self.state.stop(); self.token.stop()

    def request(self, path, method="GET", token=None, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        headers = {"Content-Type": "text/plain"}  # Browser simple request, no CORS preflight.
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        connection.request(method, path, body, headers)
        response = connection.getresponse()
        status, data = response.status, response.read()
        connection.close()
        return status, data

    def test_website_cannot_trigger_synthesis_without_token(self):
        status, _ = self.request("/stream", "POST", body=json.dumps({"text": "Проверка"}))
        self.assertEqual(status, 403)
        self.fake_stream.assert_not_called()

    def test_wrong_token_cannot_trigger_synthesis(self):
        status, _ = self.request("/stream", "POST", "wrong", json.dumps({"text": "Проверка"}))
        self.assertEqual(status, 403)
        self.fake_stream.assert_not_called()

    def test_health_requires_authentication(self):
        self.assertEqual(self.request("/health")[0], 403)
        self.assertEqual(self.request("/health", token="test-voice-token-0123456789abcdef")[0], 200)

    def test_parent_can_still_synthesize(self):
        status, body = self.request("/stream", "POST", "test-voice-token-0123456789abcdef", json.dumps({"text": "Проверка"}))
        self.assertEqual(status, 200)
        self.assertEqual(len(body), 200)

    def test_audio_is_clipped_little_endian_pcm16(self):
        self.fake_stream.return_value = iter([np.array([-2, -1, -0.5, 0, 0.5, 1, 2], dtype=np.float32)])
        status, body = self.request("/stream", "POST", "test-voice-token-0123456789abcdef", json.dumps({"text": "Проверка"}))
        self.assertEqual(status, 200)
        self.assertEqual(np.frombuffer(body, dtype="<i2").tolist(), [-32767, -32767, -16383, 0, 16383, 32767, 32767])

    def test_assistant_client_authenticates(self):
        with patch.dict(os.environ, {tts_auth.TOKEN_ENV: "test-voice-token-0123456789abcdef"}), patch.object(voice, "CLONE_URL", f"http://127.0.0.1:{self.server.server_port}"):
            self.assertTrue(voice.clone_ready())
            parts = list(voice._clone_chunks("Проверка"))
        self.assertEqual(parts[0][0], 16000)
        self.assertEqual(len(parts[0][1]), 100)

    def test_invalid_local_credentials_report_voice_unavailable(self):
        with patch.object(voice, "CLONE_URL", "http://127.0.0.1:1"), patch.object(tts_auth, "headers", side_effect=RuntimeError("invalid token file")):
            self.assertFalse(voice.clone_ready())

    def test_empty_service_token_fails_closed(self):
        with patch.object(tts_server, "AUTH_TOKEN", ""):
            self.assertEqual(self.request("/health", token="")[0], 403)

    def test_unicode_wrong_token_is_rejected_normally(self):
        self.assertEqual(self.request("/health", token="caf\u00e9")[0], 403)

    def test_invalid_authorized_requests_never_reach_model(self):
        token = "test-voice-token-0123456789abcdef"
        for body in ("", "[]", "{", json.dumps({"text": ""}), json.dumps({"text": "a" * 601})):
            with self.subTest(body=body[:30]):
                self.assertEqual(self.request("/stream", "POST", token, body)[0], 400)
        self.fake_stream.assert_not_called()

    def test_maximum_valid_text_and_body_are_accepted(self):
        token = "test-voice-token-0123456789abcdef"
        self.fake_stream.side_effect = lambda text, sampling=None: iter([np.zeros(100, dtype=np.float32)])
        status, payload = self.request("/stream", "POST", token, json.dumps({"text": "a" * 600}))
        self.assertEqual(status, 200)
        self.assertEqual(len(payload), 200)
        body = json.dumps({"text": "valid"})
        self.assertEqual(self.request("/stream", "POST", token, body + " " * (65536 - len(body)))[0], 200)
        self.fake_stream.reset_mock()
        self.assertEqual(self.request("/stream", "POST", token, body + " " * (65537 - len(body)))[0], 400)
        self.fake_stream.assert_not_called()

    def test_not_ready_and_wrong_path_never_reach_model(self):
        token = "test-voice-token-0123456789abcdef"
        self.assertEqual(self.request("/missing", "POST", token, "{}")[0], 404)
        with patch.dict(tts_server.STATE, {"ready": False}):
            self.assertEqual(self.request("/stream", "POST", token, "{}")[0], 503)
        self.fake_stream.assert_not_called()


class VoiceTokenTests(unittest.TestCase):
    def test_token_reused_and_corruption_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {tts_auth.TOKEN_ENV: ""}), patch.object(tts_auth, "TOKEN_PATH", Path(temp) / "tts.token"):
            first = tts_auth.token()
            self.assertGreaterEqual(len(first), 32)
            self.assertEqual(tts_auth.token(), first)
            tts_auth.TOKEN_PATH.write_text("broken", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                tts_auth.token()
            self.assertEqual(tts_auth.TOKEN_PATH.read_text(), "broken")


if __name__ == "__main__":
    unittest.main()
