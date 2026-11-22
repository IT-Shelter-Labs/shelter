"""User regressions: stopping a dance, persona speech, sizes and startup helpers."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from shelter_core import avatar_motion
from shelter_core.avatar import AvatarController
from shelter_core import bus
from shelter_core import fastpath
from shelter_core import main
from shelter_core import personas
from shelter_core import voice
from shelter_core.audio import LISTENING


class InteractionCommands(unittest.TestCase):
    def test_llm_persona_switch_also_continues_dialogue(self):
        from shelter_core import tasks
        def switch(*args):
            tasks.continue_dialogue()
            return "Снова к вашим услугам."
        def respond(question, cfg, commands, run_tool, **kwargs):
            _, reply = run_tool("persona", "jarvis")
            yield "text", reply
        cfg = {"llm": {"enabled": True, "semantic_input":False}, "wake": {"close_after_action": True}}
        with patch.object(fastpath, "handle", return_value=None), patch.object(fastpath, "plan", return_value=None), \
                patch.object(main, "switch_persona", side_effect=switch), patch.object(main.llm, "respond", side_effect=respond), \
                patch.object(voice, "speak_stream", side_effect=lambda s: list(s)), patch.object(main, "run_action") as action, \
                patch("shelter_core.gaming.busy", return_value=False), patch.object(bus, "publish"), tasks.scope(tasks.Token()):
            tasks.run(lambda: main.answer(cfg, "верни привычного помощника"))
        self.assertTrue(voice.RESUME.is_set())
        self.assertNotIn("close", [c.args[0]["type"] for c in action.call_args_list])
        LISTENING.clear(); voice.RESUME.clear()

    def test_stop_cancels_dance_instead_of_legacy_farewell(self):
        config = {"ui": {"mode": "avatar"}, "persona": {"id": "pippa"}}
        controller = AvatarController()
        with patch("shelter_core.avatar.AVATAR", controller), patch("shelter_core.gaming.busy", return_value=False), \
                patch.object(bus, "publish") as publish, patch.object(voice, "stop_speaking"), \
                patch.object(avatar_motion.BEAT, "stop"):
            controller.configure(config)
            avatar_motion.perform(config, "dance")
            self.assertTrue(avatar_motion.active_stop("Стоп!"))
            legacy = {"keywords": ["стоп"], "actions": [{"type": "say", "text": "Пока"}, {"type": "close"}]}
            self.assertIsNone(voice.find_command("стоп", [legacy]))
            runner = Mock()
            main.interrupt(config, runner)
            self.assertFalse(controller.motion_active)
            self.assertTrue(controller._visible)
            self.assertTrue(LISTENING.is_set())
            self.assertTrue(voice.RESUME.is_set())
            runner.cancel_current.assert_called_once()
            self.assertTrue(any(c.kwargs.get("animation") == "stop" for c in publish.call_args_list))
        LISTENING.clear(); voice.RESUME.clear()

    def test_return_home_and_resize_variants(self):
        for q in ("встань в исходное положение", "вернись на свое место", "перейди на место по умолчанию"):
            self.assertEqual(avatar_motion.movement(q), {"monitor": 1, "position": "home"})
        for q in ("увеличь себя", "стань больше", "сделай себя чуть больше"):
            self.assertEqual(avatar_motion.resize_command(q), {"delta": 0.1})
        for q in ("стань меньше", "уменьши модельку"):
            self.assertEqual(avatar_motion.resize_command(q), {"delta": -0.1})
        self.assertIsNone(avatar_motion.resize_command("не становись больше"))

    def test_how_are_you_never_requests_a_briefing(self):
        for gender, ready in (("f", "готова"), ("m", "готов")):
            calls = Mock(side_effect=AssertionError("No tools for smalltalk"))
            for text in ("как дела", "как у тебя дела?", "че как дела", "как ты"):
                result = fastpath.handle(text, {"persona": {"gender": gender, "address": "хозяин"}}, calls)
                self.assertIn(ready, result[0]); self.assertFalse(result[1])

    def test_asr_joined_and_misheard_persona_names(self):
        profiles = [{"id": "anime", "name": "Юки", "aliases": ["аниме тянка"], "builtin": True},
                    {"id": "pippa", "name": "Пиппа", "aliases": ["аниме тянка"], "builtin": False},
                    {"id": "jarvis", "name": "Джарвис", "aliases": []}]
        with patch.object(personas, "all_personas", return_value=profiles):
            for text in ("стань аниметянкой", "стань аниме-тянкой", "стань аниматянкой", "станя немотянкой"):
                self.assertEqual(personas.find_switch(text), "pippa", text)
            for text in ("стань джарвис", "стань джарвисом", "стань обратно джарвисом"):
                called, cmd, rest = voice.match("джарвис " + text, ["джарвис"], [])
                self.assertTrue(called); self.assertIsNone(cmd)
                self.assertEqual(personas.find_switch(rest), "jarvis")
            for text in ("не стань аниметянкой", "расскажи об аниметянке", "стань больше"):
                self.assertIsNone(personas.find_switch(text))

    def test_native_persona_tool_has_a_real_executor(self):
        with patch.object(main, "switch_persona", return_value="Переключено") as switch:
            self.assertEqual(main._run_tool({}, "persona", "jarvis"), ("done", "Переключено"))
            switch.assert_called_once_with({}, "jarvis")
            self.assertEqual(main._run_tool({}, "persona", "../../invalid")[0], "fail")


class PersonaSize(unittest.TestCase):
    def test_size_persists_per_persona_and_editor_can_update_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(personas, "USER_DIR", str(root / "personas")), \
                    patch.object(personas, "BUILTIN_DIR", str(root / "builtin")), \
                    patch.object(personas, "ACTIVE_PATH", str(root / "active.json")):
                p = personas.save({"id": "pippa", "name": "Pippa", "avatar": {"type": "vrm", "scale": 1}})
                config = {"persona": personas.public(p)}
                with patch("shelter_core.avatar.AVATAR") as controller, patch.object(bus, "publish"):
                    controller.builtin = True
                    avatar_motion.resize(config, .1)
                    self.assertEqual(config["persona"]["avatar"]["scale"], 1.1)
                    personas._save_active("jarvis")
                    self.assertEqual(personas.get("pippa")["avatar"]["scale"], 1.1)
                    config["persona"]["avatar"]["scale"] = 1.5
                    avatar_motion.resize(config, .1)
                    self.assertEqual(personas.get("pippa")["avatar"]["scale"], 1.6)
                    with self.assertRaises(ValueError): avatar_motion.resize(config, float("nan"))
                edited = personas.public(personas.get("pippa")); edited["avatar"]["scale"] = .8
                personas.save(edited)
                self.assertEqual(personas.get("pippa")["avatar"]["scale"], .8)

    def test_absolute_relative_and_multiplicative_size(self):
        examples = {"размер 200%": {"scale": 2}, "размер двести процентов": {"scale": 2},
                    "установи размер 250 процентов": {"scale": 2.5}, "увеличь себя до 200%": {"scale": 2},
                    "стань больше в два раза": {"factor": 2}, "стань вдвое больше": {"factor": 2},
                    "увеличь себя в полтора раза": {"factor": 1.5}, "уменьши в два раза": {"factor": .5},
                    "будь вдвое крупнее": {"factor": 2}, "увеличься в два раза": {"factor": 2},
                    "размер 200%, пожалуйста": {"scale": 2},
                    "стань в два раза меньше": {"factor": .5}, "увеличь на 50%": {"factor": 1.5},
                    "уменьши себя на пятьдесят процентов": {"factor": .5}}
        for phrase, expected in examples.items():
            self.assertEqual(avatar_motion.resize_command(phrase), expected, phrase)
        for phrase in ("не увеличивай себя до 200%", "как изменить размер 200%", "размер экрана 200%"):
            self.assertIsNone(avatar_motion.resize_command(phrase))

    def test_size_200_then_double_is_persisted_and_limits_are_explicit(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(personas, "ACTIVE_PATH", str(Path(temp)/"active.json")), \
                patch("shelter_core.avatar.AVATAR") as controller, patch.object(bus, "publish"), patch.object(personas, "get", return_value={"id":"test","name":"Test"}):
            controller.builtin=True
            config={"persona":{"id":"test","avatar":{"scale":1}}}
            avatar_motion.resize(config, scale=2)
            avatar_motion.resize(config, factor=2)
            self.assertEqual(config["persona"]["avatar"]["scale"], 4)
            with self.assertRaises(ValueError): avatar_motion.resize(config, scale=5)
            with self.assertRaises(ValueError): avatar_motion.resize(config, factor=-2)
            with self.assertRaises(ValueError): avatar_motion.resize(config, .1, scale=2)
            self.assertEqual(config["persona"]["avatar"]["scale"], 4)


class Startup(unittest.TestCase):
    def test_cancelled_clone_does_not_switch_to_fallback(self):
        from shelter_core import tasks
        for broken in (False, True):
            token = tasks.Token()
            def cancelled(*args):
                token.cancel()
                if broken:
                    raise OSError("response closed")
                return
                yield
            with patch.object(voice, "ENGINE", "clone"), patch.object(voice, "clone_ready", return_value=True), \
                    patch.object(voice, "_cache_path", return_value="missing-cache.wav"), \
                    patch.object(voice, "_clone_chunks", side_effect=cancelled), \
                    patch.object(voice, "_fallback", side_effect=AssertionError("must not synthesize after cancellation")), tasks.scope(token):
                with self.assertRaises(tasks.Cancelled):
                    voice.synthesize("Фраза")

    def test_background_voice_preparation_can_be_preempted(self):
        calls = []
        def synthesize(text):
            calls.append(text)
            voice.cancel_preparation()
            from shelter_core import tasks
            tasks.check()
        with patch.object(voice, "_cache_path", return_value="missing-cache.wav"), \
                patch.object(voice, "synthesize", side_effect=synthesize), \
                patch.object(voice.THINKING, "is_set", return_value=False), \
                patch.object(voice.SPEAKING, "is_set", return_value=False):
            voice.prepare(["Первая фраза", "Вторая фраза"])
        self.assertEqual(calls, ["Первая фраза"])
        self.assertFalse(voice._preparing)

    @unittest.skipUnless(os.name == "nt", "Windows console behaviour")
    def test_os_popen_probe_does_not_create_a_console(self):
        code = ("from shelter_core.background_process import hide_child_consoles; hide_child_consoles(); "
                "import os,subprocess,sys; "
                "cmd=subprocess.list2cmdline([sys.executable,'-c','import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())']); "
                "print(os.popen(cmd).read().strip())")
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")
