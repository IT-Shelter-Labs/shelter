"""Режимы окна голосом, переезд HUD, полноэкранный режим, голос робота, контроль дублей клона."""

import os
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shelter_core import display  # noqa: E402
from shelter_core import fastpath  # noqa: E402
from shelter_core import voice  # noqa: E402


def calls(text, mode="hud"):
    done = []
    reply = fastpath.handle(text, {"ui": {"mode": mode}, "llm": {"tools": ["media", "pc"]}},
                            run_tool=lambda name, arg: done.append((name, arg)) or ("done", ""))
    return done, reply


class DisplayCommands(unittest.TestCase):
    def test_modes_by_voice(self):
        for text, mode in (("работай без окна", "hidden"), ("режим кругляша", "orb"),
                           ("включи режим большое окно", "full"), ("покажи окно", "auto"),
                           ("автоматический режим", "auto")):
            self.assertEqual(display.mode_command(text)[0], mode, text)

    def test_minimize_window_is_not_hiding_jarvis(self):
        self.assertIsNone(display.mode_command("сверни окно"))
        self.assertEqual(calls("сверни окно")[0], [("pc", "minimize | окно")])

    def test_jarvis_hud_moves_between_monitors(self):
        self.assertEqual(calls("перейди на второй монитор")[0], [("display", "move | 2 | ")])
        self.assertEqual(calls("встань в левый угол")[0], [("display", "move | 0 | bottom-left")])

    def test_avatar_still_walks_itself(self):
        self.assertEqual(calls("перейди на второй монитор", mode="avatar")[0][0][0], "avatar")


class Fullscreen(unittest.TestCase):
    def test_exit_fullscreen_and_combined_command(self):
        self.assertEqual(calls("выйди из полноэкранного режима")[0], [("pc", "fullscreen | off")])
        plan = fastpath.plan("поставь на паузу и выйди из полноэкранного режима",
                             {"ui": {"mode": "hud"}, "llm": {"tools": ["media", "pc"]}})
        self.assertEqual([c for c, _ in plan], [[("media", "pause")], [("pc", "fullscreen | off")]])

    @unittest.skipUnless(os.name == "nt", "Windows fullscreen shortcut")
    def test_fullscreen_sends_escape(self):
        from shelter_core import main
        with patch.object(main.pc, "send_keys") as keys:
            main.pc_tool({}, "выйди из полноэкранного | off")
        keys.assert_called_once_with("esc")


class RobotVoice(unittest.TestCase):
    def test_robot_changes_sound_and_keeps_length(self):
        rate = 24000
        tone = (np.sin(2 * np.pi * 220 * np.arange(rate) / rate) * 8000).astype(np.int16)
        effect = voice.make_effect("robot")
        out = np.concatenate([effect(rate, tone[:9000]), effect(rate, tone[9000:])])
        self.assertEqual(len(out), len(tone))
        self.assertEqual(out.dtype, np.int16)
        self.assertFalse(np.array_equal(out, tone))
        self.assertIsNone(voice.make_effect(""))


class CleanTakes(unittest.TestCase):
    def speech(self, seconds, rate=24000):
        t = np.arange(int(seconds * rate)) / rate
        return (np.sin(2 * np.pi * 180 * t) * 6000).astype(np.int16)

    def test_take_with_long_pause_is_rejected(self):
        rate = 24000
        broken = np.concatenate([self.speech(1.2), np.zeros(int(1.6 * rate), np.int16), self.speech(1.5)])
        self.assertFalse(voice.clean_take("Хорошо, хозяин! Теперь я Юки, ваша помощница.", rate, broken))

    def test_normal_take_is_kept(self):
        self.assertTrue(voice.clean_take("Хорошо, хозяин! Теперь я Юки, ваша помощница.", 24000, self.speech(3.4)))


class AnimeDefault(unittest.TestCase):
    def test_own_persona_wins_alias_tie(self):
        from shelter_core import personas
        builtin = {"id": "anime", "name": "Юки", "aliases": ["аниме тянка"], "builtin": True}
        own = {"id": "pippa", "name": "Пиппа", "aliases": ["аниме тянка"], "builtin": False}
        with patch.object(personas, "all_personas", return_value=[builtin, own]):
            self.assertEqual(personas.find_switch("стань аниме-тянкой"), "pippa")
        with patch.object(personas, "all_personas", return_value=[builtin]):
            self.assertEqual(personas.find_switch("стань аниме-тянкой"), "anime")


if __name__ == "__main__":
    unittest.main()


class ReliablePause(unittest.TestCase):
    def test_pause_retried_until_player_stops(self):
        from shelter_core import media
        # Первая проверка — есть ли плеер, потом 4 проверки после паузы: всё ещё играет.
        states = iter([True] * 5 + [False])
        sent = []
        with patch.object(media, "now_playing", side_effect=lambda: {"playing": next(states, False)}), \
             patch.object(media, "control", side_effect=lambda action: sent.append(action) or True), \
             patch.object(media, "_media_key", side_effect=AssertionError("клавиша не нужна")), \
             patch("time.sleep"):
            self.assertTrue(media.ensure("pause"))
        self.assertEqual(sent[0], "pause")
        self.assertIn("toggle", sent, "не встала пауза — повторить переключателем")

    def test_already_paused_is_not_toggled_back(self):
        from shelter_core import media
        sent = []
        with patch.object(media, "now_playing", return_value={"playing": False}), \
             patch.object(media, "control", side_effect=lambda action: sent.append(action) or False), \
             patch.object(media, "_media_key", side_effect=AssertionError("клавиша не нужна")):
            self.assertTrue(media.ensure("pause"))
        self.assertNotIn("toggle", sent)

    def test_nothing_playing_is_reported(self):
        from shelter_core import media
        with patch.object(media, "now_playing", return_value=None):
            self.assertFalse(media.ensure("pause"))


class ImportedPersonaLines(unittest.TestCase):
    def test_lines_are_full_sentences_with_clean_name(self):
        from shelter_core import personas
        lines = personas.character_lines("Яманэко — белая", "f", "хозяин")
        self.assertEqual(lines["switch_reply"], "Хорошо, хозяин! Теперь я Яманэко, ваша помощница. Чем займёмся?")
        self.assertEqual(lines["wake_reply"], "Да, хозяин?")
        self.assertIn("женском роде", lines["system"])
        self.assertNotIn("белая", lines["system"], "приписка варианта модели — не часть имени")


class Presence(unittest.TestCase):
    def test_dismiss_and_appear(self):
        for text in ("исчезни", "пропади", "скройся", "спрячься", "исчезни с экрана", "уйди с экрана"):
            self.assertEqual(calls(text)[0], [("display", "dismiss")], text)
        self.assertEqual(calls("появись")[0], [("display", "appear")])

    def test_dismiss_hides_avatar_even_if_always_on_screen(self):
        from shelter_core.avatar import AVATAR
        published = []
        old = AVATAR.config
        AVATAR.config = {"mode": "avatar", "persona": {"always": True, "options": {}}}
        try:
            with patch.object(AVATAR, "_publish", side_effect=published.append):
                AVATAR.dismiss()
        finally:
            AVATAR.config = old
        self.assertEqual(published, ["hide"])


class AllWindows(unittest.TestCase):
    def test_minimize_all_shows_desktop(self):
        for text in ("сверни все окна", "сверни всё", "покажи рабочий стол", "разверни все окна"):
            self.assertEqual(calls(text)[0], [("pc", "desktop")], text)

    def test_single_window_still_minimized(self):
        self.assertEqual(calls("сверни телеграм")[0], [("pc", "minimize | телеграм")])

    def test_close_all_is_refused_safely(self):
        done, reply = calls("закрой все окна")
        self.assertEqual(done, [])
        self.assertIn("свернуть", reply[0])
