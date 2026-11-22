"""Длинные фразы не запускают мгновенные команды; ошибки плеера не роняют цепочку."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shelter_core import voice  # noqa: E402

COMMANDS = [
    {"keywords": ["привет*", "здравствуй*"], "description": "hello", "keep_listening": True,
     "actions": [{"type": "say", "text": "Здравствуйте, сэр."}]},
    {"keywords": ["дальше", "следующ*", "переключи"], "description": "next",
     "actions": [{"type": "media", "key": "next"}]},
    {"keywords": ["музык*"], "description": "music", "actions": [{"type": "url", "url": "x"}]},
]


def found(text):
    cmd = voice.find_command(text, COMMANDS)
    return cmd and cmd["description"]


class LongPhrases(unittest.TestCase):
    def test_role_play_instructions_reach_the_model(self):
        # Реальные фразы из логов: раньше «следующей» включало следующий трек в Spotify.
        for text in ("следующей фразой я скажу слово бегемот а ты мне ответь на нее словом крокодил",
                     "следующей фразой я скажу что я хочу поесть супчика а ты ответь что включил мультиварку",
                     "следующей фразой я скажу привет а ты мне ответь привет я зайчик",
                     "следующей фразой я скажу привет"):
            self.assertIsNone(found(text), text)

    def test_short_commands_still_instant(self):
        self.assertEqual(found("следующий трек"), "next")
        self.assertEqual(found("дальше"), "next")
        self.assertEqual(found("привет"), "hello")
        self.assertEqual(found("включи музыку пожалуйста"), "music")


class AvatarGestures(unittest.TestCase):
    def test_wave_inside_instruction_is_not_a_gesture(self):
        from shelter_core import avatar_motion
        self.assertIsNone(avatar_motion.command("когда я скажу пока ты мне помаши", {}))
        self.assertEqual(avatar_motion.command("помаши мне рукой", {})["animation"], "wave")

    def test_jarvis_mode_does_not_intercept_gestures(self):
        from shelter_core import fastpath
        calls = []
        fastpath.handle("перейди на второй монитор", {"llm": {"tools": []}, "ui": {"mode": "hud"}},
                        run_tool=lambda name, arg: calls.append(name) or ("done", ""))
        self.assertEqual(calls, ["display"], "у Джарвиса переезжает окно HUD, а не 3D-персонаж")
        self.assertIsNone(fastpath.handle("помаши мне рукой", {"llm": {"tools": []}, "ui": {"mode": "hud"}},
                                          run_tool=lambda name, arg: ("done", "")), "жест без тела — разговор")


class FallbackVoice(unittest.TestCase):
    def test_female_persona_prefers_silero_to_male_piper(self):
        used = []
        with patch.object(voice, "PIPER_VOICE", "irina"), patch.object(voice, "ENGINE", "piper"), \
             patch.object(voice, "_available_piper", lambda: ["denis", "ruslan"]), \
             patch.object(voice, "_piper_say", lambda text, name=None: used.append(name) or (_ for _ in ()).throw(FileNotFoundError()) if name == "irina" else used.append(name) or (22050, b"")), \
             patch.object(voice, "_silero", lambda text: used.append("silero") or (48000, b"")):
            voice._fallback("Привет")
        self.assertEqual(used, ["irina", "silero"])


class MediaFallback(unittest.TestCase):
    def test_missing_player_uses_system_media(self):
        from shelter_core import actions
        from shelter_core import media
        with patch.object(actions, "_send_app_command", side_effect=RuntimeError("окно процесса Spotify.exe не найдено")), \
             patch.object(media, "control", return_value=True) as control:
            actions.run_action({"type": "media", "key": "next"})
        control.assert_called_once_with("next")


if __name__ == "__main__":
    unittest.main()
