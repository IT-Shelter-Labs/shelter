"""«Покажу один раз»: события программ и окон -> шаги без координат и без ввода."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shelter_core import demo_recorder  # noqa: E402
from shelter_core import scenarios  # noqa: E402


class Demo(unittest.TestCase):
    def session(self, events):
        session = object.__new__(demo_recorder.Session)
        session.events = events
        return session

    def test_steps_use_stable_identifiers(self):
        home = os.path.expanduser("~")
        exe = os.path.join(home, "AppData", "Roaming", "Telegram Desktop", "Telegram.exe")
        events = [(1, "opened", {"process": "telegram", "title": "Telegram", "hwnd": 10, "exe": exe}),
                  (2, "focus", {"process": "telegram", "title": "Telegram", "hwnd": 10}),
                  (3, "opened", {"process": "obs64", "title": "OBS 30", "hwnd": 20, "exe": ""}),
                  (4, "focus", {"process": "obs64", "title": "OBS 30", "hwnd": 20})]
        with patch("os.path.isfile", return_value=True), \
             patch.object(demo_recorder, "_place", side_effect=lambda hwnd: (2, "right") if hwnd == 10 else None):
            steps, notes = self.session(events).steps()
        kinds = [(s["type"], s.get("action")) for s in steps]
        self.assertEqual(steps[0], {"type": "launch", "path": exe.replace(home, "%USERPROFILE%")})
        self.assertIn({"type": "window", "action": "place", "title": "telegram", "monitor": 2, "position": "right"}, steps)
        self.assertEqual(steps[-1], {"type": "window", "action": "focus", "title": "obs64"}, "в конце — последнее активное окно")
        self.assertEqual(kinds.count(("window", "focus")), 1)
        self.assertTrue(any("obs64" in n for n in notes), "окно без места объяснено")
        self.assertTrue(any("не записываются" in n for n in notes))
        self.assertFalse(any("x" in s or "y" in s for s in steps), "никаких координат")
        problems = scenarios.validate(scenarios.normalize({"name": "Демо", "phrases": ["демо"], "steps": steps}))
        self.assertEqual(problems, [], "черновик сразу годится для конструктора")


if __name__ == "__main__":
    unittest.main()
