"""Косвенные просьбы: модель предлагает действие, «да» его выполняет."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shelter_core import llm  # noqa: E402
from shelter_core import main  # noqa: E402
from shelter_core.policy import CONFIRMATIONS  # noqa: E402

CONFIG = {"llm": {"tools": ["app", "search", "weather"], "commands": True},
          "commands": [{"keywords": ["музык*"], "description": "включить плейлист", "actions": [{"type": "say", "text": "x"}]}],
          "confirm": {"accept": ["да", "давай", "конечно", "включай"], "reject": ["нет", "не надо"], "timeout": 20}}


class Offers(unittest.TestCase):
    def tearDown(self):
        CONFIRMATIONS.clear()

    def test_offer_tag_is_parsed(self):
        self.assertEqual(llm.parse_tag("offer: app: Spotify"), ("tool", ("offer", "app: Spotify")))

    def test_accepted_offer_runs_the_action(self):
        self.assertEqual(main._offer(CONFIG, "app: Spotify")[0], "done")
        kind, command = CONFIRMATIONS.resolve("да, давай", CONFIG)
        self.assertEqual(kind, "command")
        self.assertEqual(command["actions"][0], {"type": "tool", "name": "app", "arg": "Spotify", "confirmed": True})

    def test_offered_scenario(self):
        main._offer(CONFIG, "1")
        kind, command = CONFIRMATIONS.resolve("конечно", CONFIG)
        self.assertEqual(command["actions"][0]["name"], "scenario")

    def test_search_offer_becomes_a_question(self):
        main._offer(CONFIG, "search: идеи для выходных")
        _, command = CONFIRMATIONS.resolve("да", CONFIG)
        self.assertEqual(command["actions"], [{"type": "ask", "text": "идеи для выходных"}])

    def test_disabled_tool_is_not_offered(self):
        self.assertEqual(main._offer(CONFIG, "pc: shutdown")[0], "fail")
        self.assertFalse(CONFIRMATIONS.active())

    def test_no_with_new_request_passes_through(self):
        main._offer(CONFIG, "app: Spotify")
        self.assertEqual(CONFIRMATIONS.resolve("нет лучше включи ютуб", CONFIG), (None, None))
        self.assertFalse(CONFIRMATIONS.active(), "предложение снято, а фраза идёт дальше как просьба")

    def test_unrelated_phrase_drops_the_offer(self):
        main._offer(CONFIG, "app: Spotify")
        self.assertEqual(CONFIRMATIONS.resolve("какая погода завтра", CONFIG), (None, None))
        self.assertFalse(CONFIRMATIONS.active())

    def test_safety_confirmation_still_needs_a_clear_yes(self):
        CONFIRMATIONS.request({"actions": [{"type": "tool", "name": "pc", "arg": "shutdown"}]})
        self.assertEqual(CONFIRMATIONS.resolve("какая погода", CONFIG), (None, None))
        self.assertTrue(CONFIRMATIONS.active(), "опасное действие не снимается посторонней фразой")
        self.assertEqual(CONFIRMATIONS.resolve("да не надо", CONFIG)[0], None)
        self.assertEqual(CONFIRMATIONS.resolve("нет", CONFIG)[0], "cancelled")


if __name__ == "__main__":
    unittest.main()
