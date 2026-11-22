"""«Закрой телеграм» закрывает окно, а не Джарвиса и не открывает Telegram заново."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import voice  # noqa: E402

COMMANDS = [
    {"keywords": ["пока", "закрой", "скрой"], "whole": True, "description": "bye", "actions": [{"type": "close"}]},
    {"keywords": ["телеграм*", "телега"], "description": "tg", "actions": [{"type": "launch", "path": "tg"}]},
    {"keywords": ["музык*"], "description": "music", "actions": [{"type": "url"}, {"type": "media"}]},
]


def found(text):
    cmd = voice.find_command(text, COMMANDS)
    return cmd and cmd["description"]


class CloseCommands(unittest.TestCase):
    def test_close_with_object_is_not_goodbye(self):
        self.assertIsNone(found("закрой телеграм"))
        self.assertIsNone(found("сверни телеграм"))
        self.assertIsNone(found("выключи музыку"))

    def test_bare_goodbye_still_works(self):
        for text in ("закрой", "закрой пожалуйста", "пока", "пока сэр", "скрой"):
            self.assertEqual(found(text), "bye", text)

    def test_open_commands_still_work(self):
        self.assertEqual(found("открой телеграм"), "tg")
        self.assertEqual(found("включи музыку"), "music")


if __name__ == "__main__":
    unittest.main()
