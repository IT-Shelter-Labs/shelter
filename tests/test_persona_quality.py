"""Поведение редактора персонажей и безопасная деградация голоса."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shelter_core import personas
from shelter_core import voice
from shelter_core import tasks
from shelter_core import avatar_motion
from shelter_core.avatar import AvatarController
import numpy as np


class PersonaStorage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, value in (("ROOT", str(self.root)), ("USER_DIR", str(self.root / "data/personas")),
                            ("BUILTIN_DIR", str(self.root / "personas")),
                            ("ACTIVE_PATH", str(self.root / "data/persona.json"))):
            p = patch.object(personas, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.builtin = self.root / "personas/jarvis"
        self.builtin.mkdir(parents=True)
        (self.builtin / "persona.json").write_text('{"name":"Jarvis"}', encoding="utf-8")

    def test_builtin_cannot_be_shadowed_by_editing(self):
        with self.assertRaises(ValueError):
            personas.save({"id": "jarvis", "name": "Другой"})
        self.assertEqual(personas.get("jarvis")["name"], "Jarvis")

    def test_copy_owns_its_assets_even_from_sibling_folder(self):
        source = self.root / "data/personas/custom-other"
        source.mkdir(parents=True)
        model = source / "model.vrm"
        model.write_bytes(b"model")
        portrait = source / "preview.png"
        portrait.write_bytes(b"preview")
        saved = personas.save({"id": "custom", "name": "Юки", "avatar": {"type": "vrm", "model": str(model), "preview": str(portrait)}})
        stored = Path(personas.resolve(saved, saved["avatar"]["model"]))
        self.assertTrue(stored.is_relative_to(Path(saved["folder"])))
        self.assertEqual(stored.read_bytes(), b"model")
        copied_preview = Path(personas.public(saved)["avatar"]["preview"])
        self.assertTrue(copied_preview.is_relative_to(Path(saved["folder"])))
        self.assertEqual(copied_preview.read_bytes(), b"preview")
        again = personas.save(personas.public(saved))
        self.assertEqual(again["avatar"]["model"], saved["avatar"]["model"])

    def test_delete_active_persists_default(self):
        personas.save({"id": "custom", "name": "Юки"})
        personas._save_active("custom")
        personas.delete("custom")
        self.assertEqual(json.loads(Path(personas.ACTIVE_PATH).read_text())["active"], "jarvis")

    def test_invalid_fields_do_not_damage_existing_character(self):
        valid = {"id": "custom", "name": "Юки", "voice": {"pitch": 1.1}}
        personas.save(valid)
        for changed in ({"voice": {"pitch": float("nan")}}, {"avatar": []},
                        {"voice": {"reference": str(self.builtin / "persona.json")}},
                        {"avatar": {"type": "vrm", "model": "missing.vrm"}}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                personas.save({**copy.deepcopy(valid), **changed})
            self.assertEqual(personas.get("custom")["voice"]["pitch"], 1.1)

    def test_invalid_id_cannot_escape_folder(self):
        for name in ("../escape", "good\n", "/abs", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                personas.save({"id": name, "name": "Юки"})

    def test_custom_animation_is_copied_and_resolved_for_renderer(self):
        clip = self.root / "wave.vrma"
        clip.write_bytes(b"animation")
        saved = personas.save({"id": "custom", "name": "Юки", "animations": [
            {"id": "heart", "name": "Сердечко", "file": str(clip), "phrases": ["покажи сердечко"]}]})
        public = personas.public(saved)
        self.assertEqual(Path(public["animations"][0]["file"]).read_bytes(), b"animation")
        self.assertEqual(avatar_motion.command("покажи сердечко", public)["animation"], "heart")

    def test_failed_write_preserves_saved_json(self):
        personas.save({"id": "custom", "name": "Юки"})
        with patch("shelter_core.personas.os.replace", side_effect=OSError("disk failure")), self.assertRaises(OSError):
            personas.save({"id": "custom", "name": "Другое имя"})
        self.assertEqual(personas.get("custom")["name"], "Юки")


class PersonaFallback(unittest.TestCase):
    def test_uses_installed_voice_while_preferred_is_downloading(self):
        def speak(text, name=None):
            if name != "ruslan":
                raise FileNotFoundError("irina downloading")
            return 16000, [1, 2]
        with patch.object(voice, "ENGINE", "piper"), patch.object(voice, "PIPER_VOICE", "irina"), \
             patch.object(voice, "_available_piper", return_value=["ruslan"]), \
             patch.object(voice, "_piper_say", side_effect=speak), \
             patch.object(voice, "_silero", side_effect=ImportError("no torch")):
            self.assertEqual(voice._fallback("Привет"), (16000, [1, 2]))

    def test_cancellation_is_not_treated_as_missing_voice(self):
        with patch.object(voice, "ENGINE", "clone"), \
             patch.object(voice, "_silero", side_effect=tasks.Cancelled()), \
             patch.object(voice, "_piper_say") as piper:
            with self.assertRaises(tasks.Cancelled):
                voice._fallback("Привет")
            piper.assert_not_called()


class AvatarBehavior(unittest.TestCase):
    def config(self):
        return {"ui": {"mode": "avatar", "avatar": {}}, "persona": {"id": "custom", "avatar": {"model": "x.vrm"}}}

    def test_exact_commands_only_not_negation_or_description(self):
        for text in ("не танцуй", "расскажи как танцуй под бит работает", "почему она танцует", "помаши рукой и выключи компьютер"):
            self.assertIsNone(avatar_motion.command(text, {}))
        self.assertEqual(avatar_motion.command("Танцуй под бит!", {}), {"animation": "dance", "beat": True})
        self.assertEqual(avatar_motion.command("танцуй в темпе 130", {})["bpm"], 130)
        self.assertIsNone(avatar_motion.command("танцуй в темпе 999", {}))

    def test_busy_hides_without_ending_desired_visibility(self):
        avatar = AvatarController()
        cfg = self.config()
        with patch("shelter_core.gaming.busy", return_value=False), patch("shelter_core.bus.publish") as publish:
            avatar.configure(cfg)
            avatar.start()
            with patch("shelter_core.gaming.busy", return_value=True):
                avatar._last_tick = 0
                avatar.tick(cfg)
                self.assertEqual(publish.call_args.kwargs["state"], "hide")
            avatar._last_tick = 0
            avatar.tick(cfg)
            self.assertEqual(publish.call_args.kwargs["state"], "show")

    def test_motion_remains_visible_after_command_and_expires(self):
        avatar = AvatarController()
        cfg = self.config()
        with patch("shelter_core.gaming.busy", return_value=False), patch("shelter_core.bus.publish") as publish:
            avatar.configure(cfg)
            avatar.start()
            avatar.hold_motion(3)
            avatar.hide()
            self.assertTrue(avatar._visible)
            avatar._motion_until = 0
            avatar._last_tick = 0
            avatar.tick(cfg)
            self.assertFalse(avatar._visible)
            self.assertEqual(publish.call_args.kwargs["state"], "hide")

    def test_motion_validation_precedes_start_or_loopback(self):
        with patch("shelter_core.avatar.AVATAR") as controller, patch.object(avatar_motion.BEAT, "start") as start:
            controller.builtin = True
            for name, bpm in (("missing", 120), ("dance", float("nan")), ("dance", 999)):
                with self.assertRaises(ValueError): avatar_motion.perform(self.config(), name, bpm)
            controller.hold_motion.assert_not_called()
            start.assert_not_called()

    def test_old_animation_completion_does_not_hide_new_motion(self):
        avatar = AvatarController()
        with patch("shelter_core.gaming.busy", return_value=False), patch("shelter_core.bus.publish"):
            avatar.configure(self.config())
            avatar.hold_motion(30, "new-motion")
            avatar.finish_motion("old-motion")
            self.assertTrue(avatar._visible)
            avatar.finish_motion("new-motion")
            self.assertFalse(avatar._visible)

    def test_beat_tracker_estimates_pulses_and_refuses_silence(self):
        silent, music = avatar_motion.BeatTracker(), avatar_motion.BeatTracker()
        result = None
        for i in range(200):
            self.assertIsNone(silent.feed(0))
            result = music.feed(0.3 if i % 10 == 0 else 0.01) or result
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["bpm"], 120, delta=1)

    def test_persona_prompt_does_not_teach_old_address(self):
        from shelter_core import llm
        with patch.object(personas, "_active", {"id": "custom", "address": "капитан", "gender": "f"}):
            prompt = llm._system_prompt({"system": "Ты помощница капитана."}, [{"keywords": ["привет"]}])
        self.assertNotIn("сэр", prompt.lower())
        self.assertIn("капитан", prompt)
