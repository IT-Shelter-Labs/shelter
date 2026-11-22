"""Джарвис не молчит, пока нейросеть загружается или видеокарта занята."""

import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shelter_core import main  # noqa: E402


def slow(delay, items):
    time.sleep(delay)
    yield from items


class Patience(unittest.TestCase):
    def test_slow_model_gets_a_hint_then_answer(self):
        with patch.object(main, "LLM_HINT_AFTER", 0.2), patch.object(main, "LLM_GIVE_UP_AFTER", 5):
            got = list(main.patient(slow(0.6, [("text", "Париж, сэр.")]), None))
        self.assertEqual(got[0][0], "hint")
        self.assertEqual(got[-1], ("text", "Париж, сэр."))

    def test_fast_model_has_no_hint(self):
        got = list(main.patient(iter([("text", "Да, сэр.")]), None))
        self.assertEqual(got, [("text", "Да, сэр.")])

    def test_silent_model_reports_and_frees_the_queue(self):
        with patch.object(main, "LLM_HINT_AFTER", 0.1), patch.object(main, "LLM_GIVE_UP_AFTER", 0.4):
            started = time.monotonic()
            got = list(main.patient(slow(30, []), None))
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(got[-1][0], "error")
        self.assertIn("видеокарта", got[-1][1])

    def test_stop_is_not_a_goodbye(self):
        from shelter_core import voice
        config = main.load_config()
        self.assertIsNone(voice.find_command("стоп", config["commands"]))
