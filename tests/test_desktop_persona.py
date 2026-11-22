import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import agent_runtime
import avatar_motion
import bus
import llm
import main
import persona_groups
import personas
import tasks
import voice
import fastpath
from audio import LISTENING


class DesktopCommands(unittest.TestCase):
    def test_natural_wave_variants_and_negation(self):
        for phrase in ("помахай мне ручкой, милашка", "помаши мне своей кистью", "пожалуйста помахай рукой"):
            self.assertEqual(avatar_motion.command(phrase, {})["animation"], "wave")
        for phrase in ("не помахай рукой", "как помахать рукой", "помаши и выключи компьютер"):
            self.assertIsNone(avatar_motion.command(phrase, {}))

    def test_screen_positions(self):
        self.assertEqual(avatar_motion.movement("перейди на второй монитор"), {"monitor": 2, "position": "bottom-right"})
        self.assertEqual(avatar_motion.movement("перейди в левый верхний угол монитора"), {"monitor": 0, "position": "top-left"})
        self.assertEqual(avatar_motion.movement("переместись по центру"), {"monitor": 0, "position": "center"})
        self.assertIsNone(avatar_motion.movement("не переходи на второй монитор"))

    def test_long_walk_remains_visible_until_arrival_and_does_not_open_a_dialogue(self):
        with patch("avatar.AVATAR") as controller, patch.object(bus, "publish") as publish, patch.object(avatar_motion.BEAT, "stop"):
            controller.builtin = True
            avatar_motion.move({}, 2, "center")
            controller.start.assert_called_once_with(dialogue=False)
            seconds, token = controller.hold_motion.call_args.args
            self.assertGreaterEqual(seconds, 120)
            self.assertEqual(publish.call_args.kwargs["motion_id"], token)
            controller.reset_mock(); publish.reset_mock()
            with self.assertRaises(ValueError): avatar_motion.move({}, 17, "center")
            controller.hold_motion.assert_not_called(); publish.assert_not_called()

    def test_planning_a_combination_does_not_execute_the_gesture(self):
        config = {"ui": {"mode": "avatar"}, "llm": {"tools": ["timer"]}}
        with patch.object(avatar_motion, "perform", side_effect=AssertionError("planning must not execute")):
            plan = fastpath.plan("помаши рукой и поставь таймер на пять минут", config)
        self.assertIsNotNone(plan)
        self.assertEqual([calls[0][0] for calls, _ in plan], ["avatar", "timer"])

    def test_llm_gets_custom_motions_and_cannot_invent_one(self):
        config = {"ui": {"mode": "avatar"}, "llm": {"tools": []}, "persona": {"animations": [
            {"id": "heart", "name": "Сердечко", "phrases": ["покажи любовь"]}]}}
        specs, handlers = agent_runtime.definitions(config, [], [])
        animation = next(s for s in specs if s["function"]["name"] == "avatar")
        self.assertIn("heart", animation["function"]["parameters"]["properties"]["action"]["enum"])
        self.assertEqual(handlers["avatar_move"][0], "avatar")
        with patch("avatar.AVATAR") as controller, self.assertRaises(ValueError):
            controller.builtin = True
            avatar_motion.execute(config, "nonexistent_motion")

    def test_tag_llm_can_select_a_motion_by_meaning(self):
        config = {"ui": {"mode": "avatar"}, "llm": {"tools": [], "provider": "test", "agent": {"protocol": "tags"}}}
        with patch.object(llm, "_provider", return_value=lambda *args: iter(["[avatar: wave] Привет!"])), \
             patch.object(llm, "_background", side_effect=lambda run, name, arg: lambda: run(name, arg)), \
             patch.object(llm, "_history", []):
            calls = []
            list(llm.respond("поприветствуй меня жестом", config, [], lambda n, a: (calls.append((n,a)) or ("done", ""))))
        self.assertEqual(calls, [("avatar", "wave")])

    def test_switch_continues_conversation_even_when_actions_close_window(self):
        cfg = {"llm": {"enabled": False}, "wake": {"close_after_action": True}, "commands": []}
        def switch():
            tasks.continue_dialogue()
            return "Снова к вашим услугам, сэр.", True
        with patch("fastpath.handle", side_effect=lambda *a, **k: switch()), patch("fastpath.plan", return_value=None), \
             patch.object(main, "run_action") as action, patch.object(main.gaming, "busy", return_value=False), \
             patch.object(voice, "speak_stream"), patch.object(bus, "publish"), tasks.scope(tasks.Token()):
            tasks.run(lambda: main.answer(cfg, "стань Джарвисом"))
        self.assertTrue(LISTENING.is_set())
        self.assertTrue(voice.RESUME.is_set())
        self.assertNotIn("close", [c.args[0]["type"] for c in action.call_args_list])
        LISTENING.clear(); voice.RESUME.clear()


class GroupedLooks(unittest.TestCase):
    def test_group_keeps_active_look_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(personas, "ROOT", str(root)), patch.object(personas, "USER_DIR", str(root / "data/personas")), \
                 patch.object(personas, "BUILTIN_DIR", str(root / "personas")), patch.object(personas, "ACTIVE_PATH", str(root / "data/persona.json")):
                for identifier, name in (("look-a", "Цукуёми — стандартная, с контуром"), ("look-b", "Цукуёми — без контура")):
                    model = root / (identifier + ".vrm"); model.write_bytes(identifier.encode())
                    personas.save({"id": identifier, "name": name, "imported": {"source": "tyc-3d-a.zip"},
                                   "avatar": {"type": "vrm", "model": str(model)}})
                personas._save_active("look-b")
                persona_groups.consolidate(); persona_groups.consolidate()
                self.assertEqual(len(personas.all_personas()), 1)
                parent = personas.get("look-b")
                self.assertEqual(parent["name"], "Цукуёми")
                self.assertEqual(len(parent["appearances"]), 2)
                self.assertEqual(parent["appearance"], "look-b")
                parent["appearance"] = "look-a"
                updated = personas.save(personas.public(parent))
                self.assertEqual(Path(personas.resolve(updated, updated["avatar"]["model"])).read_bytes(), b"look-a")
                self.assertEqual(personas.get("look-a")["id"], "look-b")
