"""Узнавание хозяина: выключено — слушаемся всех; гостю — только безопасные инструменты."""

import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402
import speaker  # noqa: E402


class OwnerVoice(unittest.TestCase):
    def test_disabled_check_trusts_everyone(self):
        self.assertTrue(speaker.is_owner(np.zeros(16000, np.float32), {"wake": {"owner": {"enabled": False}}}))

    def test_without_enrollment_everyone_is_owner(self):
        old = speaker.OWNER
        speaker.OWNER = os.path.join(tempfile.mkdtemp(), "owner.json")
        speaker._owner = None
        try:
            self.assertTrue(speaker.is_owner(np.zeros(16000, np.float32), {"wake": {"owner": {"enabled": True}}}))
        finally:
            speaker.OWNER = old
            speaker._owner = None

    def test_guest_config_keeps_only_safe_tools_and_no_commands(self):
        config = {"llm": {"tools": ["app", "pc", "weather", "search", "memory", "media", "screen"]},
                  "commands": [{"keywords": ["выключи"]}]}
        guest = main.guest_config(config)
        self.assertEqual(guest["llm"]["tools"], ["weather", "search", "media"])
        self.assertEqual(guest["commands"], [])
        self.assertIn("memory", config["llm"]["tools"], "настройки хозяина не меняются")

    @unittest.skipUnless(speaker.available(), "нет модели узнавания голоса")
    def test_short_phrase_gives_benefit_of_doubt(self):
        self.assertIsNone(speaker.score(np.zeros(8000, np.float32)))


if __name__ == "__main__":
    unittest.main()
