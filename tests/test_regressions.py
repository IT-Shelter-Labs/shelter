import io
import json
import queue
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import actions
import fastpath
import llm
import main
import policy
import scheduler
import smarthome
import speech_text
import tasks
import voice
from audio import LISTENING, SPEAKING


class Regressions(unittest.TestCase):
    def tearDown(self):
        LISTENING.clear()
        SPEAKING.clear()
        policy.CONFIRMATIONS.clear()

    def test_prose_never_executes_tags(self):
        events = list(llm._split(iter(["Пример: [pc: shutdown | 60]."])))
        self.assertTrue(all(k == "text" for k, _ in events))
        self.assertEqual(list(llm._split(iter(["[timer: 300][pc: status] Готово."])))[:2],
                         [("tool", ("timer", "300")), ("tool", ("pc", "status"))])

    def test_disabled_command_router(self):
        cfg = {"llm": {"commands": False, "tools": []}}
        with patch.object(llm, "_provider", return_value=lambda *a: iter(["[1] Ответ."])):
            events = list(llm.respond("тест", cfg, [{"keywords": ["тест"]}]))
        self.assertFalse(any(k == "command" for k, _ in events))

    def test_disabled_fastpath_has_no_side_effects(self):
        with patch.object(scheduler, "add_timer") as add:
            reply, did = fastpath.handle("таймер на пять минут", {"llm": {"tools": []}})
        self.assertFalse(did)
        self.assertIn("выключена", reply)
        add.assert_not_called()

    def test_offline_timer_and_no_llm_call(self):
        cfg = {"llm": {"enabled": False, "tools": ["timer"]}, "commands": []}
        with patch.object(scheduler, "add_timer") as add, patch.object(voice, "speak_stream"), \
             patch.object(main, "run_action"), patch.object(main.gaming, "busy", return_value=False), \
             patch.object(llm, "respond", side_effect=AssertionError("LLM called")):
            main.answer(cfg, "таймер на пять минут")
            add.assert_called_once_with(300.0, "")
            main.answer(cfg, "незнакомый вопрос")

    def test_ambiguous_device(self):
        with patch.object(smarthome, "_devices", [{"name": "лампа кухня"}, {"name": "лампа спальня"}]):
            with self.assertRaises(smarthome.AmbiguousDevice):
                smarthome.find("лампа")
            self.assertEqual(smarthome.find("лампа кухня")["name"], "лампа кухня")

    def test_confirm_expiry_and_negation(self):
        store = policy.Confirmations()
        store.request({"actions": []}, timeout=-1)
        self.assertTrue(store.expire())
        self.assertFalse(store.active())
        store.request({"actions": []})
        self.assertEqual(store.resolve("нет не надо", {})[0], "cancelled")
        store.request({"actions": []})
        self.assertEqual(store.resolve("да нет", {}), (None, None))
        kind, cmd = store.resolve("да", {})
        self.assertEqual(kind, "command")
        self.assertTrue(cmd["_confirmed"])

    def test_power_requires_confirmation(self):
        with patch.object(main.pc, "power") as power:
            result = main.run_tool({"llm": {"tools": ["pc"]}}, "pc", "shutdown | 60")
        power.assert_not_called()
        self.assertEqual(result[0], "say")
        self.assertTrue(policy.CONFIRMATIONS.active())

    def test_clock_rejects_invalid_values(self):
        self.assertIsNone(scheduler.parse_clock("25:99"))
        self.assertEqual(scheduler.parse_clock("09:30"), (9, 30))

    def test_cache_changes_with_reference_and_speed(self):
        with tempfile.TemporaryDirectory() as folder:
            reference = Path(folder) / "reference.wav"
            reference.write_bytes(b"first")
            cfg = {"tts": {"clone": {"reference": str(reference)}}}
            with patch.object(voice, "ENGINE", "clone"):
                voice.configure_cache(cfg)
                first = voice._cache_path("Здравствуйте")
                reference.write_bytes(b"second")
                voice.configure_cache(cfg)
                self.assertNotEqual(first, voice._cache_path("Здравствуйте"))
            with patch.object(voice, "PIPER_SPEED", 1.4):
                self.assertNotEqual(first, voice._cache_path("Здравствуйте"))

    def test_speech_cancellation_while_producer_waits(self):
        entered, release = threading.Event(), threading.Event()
        def chunks(text):
            yield 16000, np.zeros(160, np.int16)
            entered.set()
            release.wait(3)
        output = types.SimpleNamespace(write=lambda *a: None, close=lambda: None)
        with patch.object(voice, "synthesize_chunks", chunks), patch.object(voice, "_Output", return_value=output), \
             patch.object(voice, "speaking_flag"), patch.object(voice.sd, "stop"):
            worker = threading.Thread(target=voice.speak_stream, args=(["тест"],), daemon=True)
            worker.start()
            self.assertTrue(entered.wait(2))
            voice.stop_speaking()
            worker.join(0.5)
            release.set()
            self.assertFalse(worker.is_alive())

    def test_runner_stop_discards_queued_actions(self):
        started, release = threading.Event(), threading.Event()
        seen = []
        def execute(action):
            seen.append(action["type"])
            started.set()
            release.wait(1)
        with patch.object(actions, "run_action", execute):
            runner = actions.ActionRunner()
            runner.submit([{"type": "first"}])
            self.assertTrue(started.wait(1))
            runner.submit([{"type": "second"}])
            stopper = threading.Thread(target=runner.stop)
            stopper.start()
            time.sleep(0.05)
            release.set()
            stopper.join(2)
        self.assertEqual(seen, ["first"])
        self.assertFalse(runner.submit([{"type": "third"}]))

    def test_cancel_before_first_llm_token_frees_action_runner(self):
        entered, release, next_job = threading.Event(), threading.Event(), threading.Event()
        def delayed(*args, **kwargs):
            entered.set()
            release.wait(3)
            yield "text", "Старый ответ"
        cfg = {"llm": {"enabled": True, "tools": []}, "commands": []}
        output = types.SimpleNamespace(write=lambda *a: None, close=lambda: None)
        with patch.object(llm, "respond", delayed), patch.object(main, "run_action"), \
             patch.object(main.gaming, "busy", return_value=False), patch.object(voice, "_Output", return_value=output), \
             patch.object(voice, "speaking_flag"), patch.object(voice.sd, "stop"):
            runner = actions.ActionRunner()
            try:
                runner.submit_lazy(lambda: main.answer(cfg, "длинный вопрос"))
                self.assertTrue(entered.wait(2))
                runner.cancel_current()
                voice.stop_speaking()
                runner.submit_lazy(lambda: next_job.set())
                self.assertTrue(next_job.wait(0.5))
            finally:
                release.set()
                runner.stop()

    def test_long_utterance_keeps_session_open(self):
        clock = [100.0]
        stop = threading.Event()
        class Input:
            count = 0
            def get(self, timeout):
                self.count += 1
                clock[0] += 0.5
                if self.count >= 50:
                    stop.set()
                return np.ones(voice.CHUNK, np.float32) * 0.1
        source = Input()
        class Recognizer:
            def __init__(self, *args): pass
            def AcceptWaveform(self, pcm): return source.count >= 50
            def PartialResult(self): return json.dumps({"partial": "джарвис"})
            def Result(self): return json.dumps({"text": "джарвис длинная просьба"})
        fake = types.SimpleNamespace(Model=lambda p: None, KaldiRecognizer=Recognizer, SetLogLevel=lambda n: None)
        import asr
        config = {"wake": {"model_path": "unused", "words": ["джарвис"], "vad": False, "follow_up": 3},
                  "asr": {"engine": "vosk"}, "llm": {"enabled": False}}
        events = queue.Queue()
        with patch.dict("sys.modules", {"vosk": fake}), patch.object(asr, "load", return_value=None), \
             patch.object(voice.time, "monotonic", side_effect=lambda: clock[0]), patch.object(voice, "_save_speech_levels"):
            voice.listen(types.SimpleNamespace(vosk_queue=source, sample_rate=32000), config, events, stop)
        got = list(events.queue)
        self.assertFalse(any(k == "listen_timeout" for k, _ in got), got)
        self.assertIn(("ask", "длинная просьба"), got)

    def test_russian_speech_preparation(self):
        self.assertEqual(speech_text.prepare_for_speech("30%"), "тридцать процентов")
        self.assertIn("час", speech_text.prepare_for_speech("09:30"))
        self.assertEqual(speech_text.prepare_for_speech("1 ГБ"), "один гигабайт")
        self.assertTrue(all(len(s) <= 450 for s in speech_text.split_for_speech("Привет. " * 300)))

    def test_bad_settings_root_rejected(self):
        with self.assertRaises(ValueError):
            main._merge({}, [])

    def test_mobile_and_typed_commands_require_confirmation(self):
        action = {"confirm": "Вы уверены?", "actions": [{"type": "shell", "cmd": "never execute"}]}
        result = main.actions_for({}, "command", action)
        self.assertFalse(any(a["type"] == "shell" for a in result))
        self.assertTrue(policy.CONFIRMATIONS.active())
        kind, approved = policy.CONFIRMATIONS.resolve("да", {})
        self.assertEqual(main.actions_for({}, kind, approved), action["actions"])

    def test_cancelled_tool_never_executes(self):
        token = tasks.Token()
        token.cancel()
        with patch.object(main.tools, "open_app") as open_app, tasks.scope(token):
            with self.assertRaises(tasks.Cancelled):
                main.run_tool({}, "app", "browser")
        open_app.assert_not_called()

    def test_device_unknown_action_rejected(self):
        with self.assertRaises(ValueError):
            smarthome.parse_action("garbage")
        self.assertEqual(smarthome.parse_action("set 22.5"), ("set", 22.5))

    def test_prepare_dates_and_feminine_units(self):
        self.assertIn("четырнадцатое ноября", speech_text.prepare_for_speech("14.11.2026"))
        self.assertEqual(speech_text.prepare_for_speech("1 мин"), "одна минута")
        self.assertEqual(speech_text.prepare_for_speech("1.5 ГБ"), "одна целая пять десятых гигабайта")

    def test_unverified_home_state_is_not_reported_as_done(self):
        config = {"llm": {"tools": ["home"]}}
        with patch.object(smarthome, "needs_confirmation", return_value=False), \
             patch.object(smarthome, "act", side_effect=smarthome.StateUnverified("Состояние не подтверждено")):
            self.assertEqual(main.run_tool(config, "home", "лампа | on")[0], "say")

    def test_native_sample_rate_fallback(self):
        import audio
        stream = types.SimpleNamespace(start=lambda: None)
        with patch.object(audio.sd, "InputStream", side_effect=[audio.sd.PortAudioError("rate"), stream]), \
             patch.object(audio.sd, "query_devices", return_value={"default_samplerate": 48000}):
            cap = audio.AudioCapture(32000)
            cap.start()
            self.assertEqual(cap.sample_rate, 48000)
            self.assertEqual(cap.buffer_len, 192000)

    def test_control_rejects_nonobject_and_oversized_body(self):
        import http.client
        import control
        with patch.object(control, "_token", return_value="unit-test-token"):
            server = control.ControlServer({"control": {"port": 0}}, queue.Queue(), None, lambda: {"ok": True})
            server.start()
        try:
            for body, extra, expected in [("[]", {}, 400), ("", {"Content-Length": "65537"}, 413)]:
                connection = http.client.HTTPConnection("127.0.0.1", server.server.server_port, timeout=2)
                connection.request("POST", "/api/ask", body, {"X-Jarvis-Token": "unit-test-token", **extra})
                response = connection.getresponse()
                self.assertEqual(response.status, expected)
                response.read()
                connection.close()
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
