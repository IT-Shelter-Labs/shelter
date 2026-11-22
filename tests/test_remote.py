"""Телефон и Telegram: сопряжение, отзыв доступа, защита от повтора, чужие не командуют."""

import http.client
import json
import os
import queue
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shelter_core import companion  # noqa: E402
from shelter_core import companion_devices as devices  # noqa: E402
from shelter_core import telegram_bot  # noqa: E402


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = patch.object(devices, "STORE", os.path.join(self.dir, "devices.json"))
        self.store.start()
        devices._requests.clear()
        devices._codes.clear()

    def tearDown(self):
        self.store.stop()
        shutil.rmtree(self.dir, ignore_errors=True)


class Pairing(Sandbox):
    def test_code_is_one_time_and_token_hash_only_on_disk(self):
        code = devices.pairing_code()["code"]
        device_id, token = devices.pair(code, "Мой телефон")
        self.assertEqual(devices.verify(token)["id"], device_id)
        with self.assertRaises(ValueError):
            devices.pair(code, "Второй")             # код одноразовый
        with open(devices.STORE, encoding="utf-8") as f:
            self.assertNotIn(token, f.read())

    def test_revoked_device_is_refused(self):
        device_id, token = devices.pair(devices.pairing_code()["code"], "Телефон")
        devices.revoke(device_id)
        self.assertIsNone(devices.verify(token))

    def test_legacy_key_can_be_revoked(self):
        self.assertEqual(devices.verify("old", legacy="old")["id"], "legacy")
        devices.revoke("legacy")
        self.assertIsNone(devices.verify("old", legacy="old"))

    def test_repeated_request_runs_once(self):
        calls = []
        first, repeated1 = devices.remember("dev", "req-1", lambda: calls.append(1) or {"accepted": True})
        second, repeated2 = devices.remember("dev", "req-1", lambda: calls.append(1) or {"accepted": True})
        self.assertEqual(calls, [1])
        self.assertFalse(repeated1)
        self.assertTrue(repeated2)


class CompanionHttp(Sandbox):
    def setUp(self):
        super().setUp()
        self.events = queue.Queue()
        with patch.object(companion, "_token", return_value="legacy-token"):
            self.server = companion.CompanionServer({"companion": {"enabled": True, "host": "127.0.0.1", "port": 0}}, self.events)
            self.server.start()

    def tearDown(self):
        self.server.stop()
        super().tearDown()

    def post(self, path, body, token=None):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server.server_port, timeout=3)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        client.request("POST", path, json.dumps(body), headers)
        response = client.getresponse()
        data = json.loads(response.read() or b"{}")
        client.close()
        return response.status, data

    def test_pair_then_ask_once_even_if_resent(self):
        code = devices.pairing_code()["code"]
        status, data = self.post("/api/pair", {"code": code, "name": "Телефон"})
        self.assertEqual(status, 200)
        token = data["token"]
        for _ in range(2):                     # обрыв связи — телефон отправил ещё раз
            status, data = self.post("/api/ask", {"text": "выключи свет", "request_id": "abc"}, token)
            self.assertEqual(status, 202)
        self.assertTrue(data["repeated"])
        self.assertEqual(self.events.qsize(), 1)

    def test_stranger_and_revoked_cannot_run(self):
        self.assertEqual(self.post("/api/interrupt", {}, "guess")[0], 401)
        self.assertEqual(self.post("/api/pair", {"code": "000000", "name": "x"})[0], 400)
        device_id, token = devices.pair(devices.pairing_code()["code"], "Телефон")
        devices.revoke(device_id)
        self.assertEqual(self.post("/api/ask", {"text": "привет"}, token)[0], 401)
        self.assertTrue(self.events.empty())


class Telegram(Sandbox):
    def setUp(self):
        super().setUp()
        self.events = queue.Queue()
        self.bot = telegram_bot.Bot({"telegram": {"token": "1:x"}}, self.events)
        self.sent = []
        patch.object(self.bot, "send", side_effect=lambda chat, text, buttons=None: self.sent.append((chat, text))).start()
        patch.object(telegram_bot, "_save_state").start()

    def tearDown(self):
        patch.stopall()
        super().tearDown()

    def msg(self, chat, text):
        return {"update_id": 1, "message": {"chat": {"id": chat}, "from": {"username": "owner"}, "text": text}}

    def test_only_paired_owner_is_obeyed(self):
        self.assertEqual(self.bot.handle(self.msg(5, "выключи компьютер")), "чужой")
        self.assertTrue(self.events.empty())
        code = devices.pairing_code()["code"]
        self.assertEqual(self.bot.handle(self.msg(7, f"/start {code}")), "подключено")
        with patch("shelter_core.assistant_store.session_for", return_value="s"):
            self.assertEqual(self.bot.handle(self.msg(7, "который час")), "передано")
        self.assertEqual(self.events.get_nowait()[1]["text"], "который час")
        self.assertEqual(self.bot.handle(self.msg(5, "/stop")), "чужой", "чужой не останавливает")

    def test_stop_and_revoke(self):
        devices.pair_chat(devices.pairing_code()["code"], 7, "Telegram")
        self.assertEqual(self.bot.handle(self.msg(7, "/stop")), "стоп")
        self.assertEqual(self.events.get_nowait()[0], "interrupt")
        device = devices.chat_device(7)
        devices.revoke(device["id"])
        self.assertEqual(self.bot.handle(self.msg(7, "открой браузер")), "чужой")

    def test_duplicate_update_is_skipped_by_offset(self):
        devices.pair_chat(devices.pairing_code()["code"], 7, "Telegram")
        update = {"update_id": 42, "message": {"chat": {"id": 7}, "text": "привет"}}
        calls = iter([[update], [update]])
        handled = []
        self.bot.state = {"offset": 0}

        def fake_call(method, wait=35, **params):
            batch = next(calls, None)
            if batch is None:
                self.bot.stop_event.set()
                return []
            return [u for u in batch if u["update_id"] >= params["offset"]]
        with patch.object(self.bot, "call", side_effect=fake_call), \
             patch.object(self.bot, "handle", side_effect=lambda u: handled.append(u["update_id"])):
            self.bot.poll()
        self.assertEqual(handled, [42])


if __name__ == "__main__":
    unittest.main()
