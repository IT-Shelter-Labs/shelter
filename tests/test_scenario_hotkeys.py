import queue
import types
import unittest
from unittest.mock import patch
from shelter_core import scenario_hotkeys
from shelter_core import triggers


class ScenarioHotkeys(unittest.TestCase):
    def test_parser_reserves_normal_typing_and_accepts_function_keys(self):
        self.assertEqual(scenario_hotkeys.parse("ctrl + alt + F9"), (3, 0x78))
        self.assertEqual(scenario_hotkeys.parse("F24"), (0, 0x87))
        for value in ("J", "Ctrl+J+K", "", "Ctrl+F25", "Ctrl+;whoami"):
            with self.assertRaises(ValueError): scenario_hotkeys.parse(value)

    def test_hotkey_uses_normal_event_queue_and_deleted_rules_do_not_fire(self):
        item = {"id":"demo", "name":"Демо", "enabled":True, "cooldown":30, "triggers":[{"type":"hotkey","combo":"Ctrl+F9"}]}
        events = queue.Queue()
        with patch.object(triggers.scenarios, "load", return_value=[item]), patch.object(triggers.scenarios, "PLATFORM", "windows"), \
             patch.object(triggers.Engine, "_load_state", return_value={}), patch.object(triggers.Engine, "_save_state"), patch("shelter_core.bus.publish"):
            engine = triggers.Engine(events, {})
            engine._hotkey("demo:Ctrl+F9", ""); engine.hotkey_step()
            self.assertEqual(events.get_nowait()[1]["id"], "demo")
            engine._hotkey("demo:Ctrl+F9", ""); engine.hotkey_step()
            self.assertTrue(events.empty())  # cooldown
            engine.rules = []
            engine._hotkey("demo:Ctrl+F9", ""); engine.hotkey_step()
            self.assertTrue(events.empty())

    def test_registration_error_is_visible_and_does_not_execute(self):
        events = queue.Queue()
        with patch.object(triggers.scenarios, "load", return_value=[]), patch.object(triggers.Engine, "_load_state", return_value={}):
            engine = triggers.Engine(events, {})
        engine.rules = [({"id":"demo","name":"Демо"}, {"type":"hotkey","combo":"Ctrl+F9"})]
        with patch("shelter_core.bus.publish"):
            engine._hotkey("demo:Ctrl+F9", "Сочетание занято"); engine.hotkey_step()
        self.assertIn("занято", engine.log[0]["result"])
        self.assertTrue(events.empty())

    def test_audio_events_have_fallback_without_optional_soundcard(self):
        device = types.SimpleNamespace(query_devices=lambda:[{"name":"Mic", "max_input_channels":1, "max_output_channels":0}])
        with patch.dict("sys.modules", {"soundcard":None, "sounddevice":device}):
            self.assertEqual(triggers._audio_devices(), {"Mic"})
