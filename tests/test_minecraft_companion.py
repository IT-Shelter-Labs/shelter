import io
import json
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from shelter_core import minecraft_npc
from shelter_core.minecraft_companion import Companion, chat_lines, describe_job, describe_position, lan_port, validate
from shelter_core.minecraft_intents import desktop, model_command, parse, scoped


class MinecraftCompanionTests(unittest.TestCase):
    def test_inventory_extension_packages_are_opt_in_and_copied_to_their_own_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paper = root / "games" / "minecraft-inventory" / "distribution" / "shelter-inventory-0.1.0.jar"
            neo = root / "bin" / "minecraft" / "jarvis-companion-neoforge-1.21.1.jar"
            with patch.object(minecraft_npc, "ROOT", root):
                self.assertFalse(minecraft_npc.api({"op": "status"}, {})["neoforge_available"])
                for path, contents in ((paper, b"paper"), (neo, b"neoforge")):
                    path.parent.mkdir(parents=True)
                    path.write_bytes(contents)
                self.assertTrue(minecraft_npc.api({"op": "status"}, {})["neoforge_available"])
                paper_copy = Path(Companion(root).api({"op": "package_inventory"}, {}, None)["file"])
                neo_copy = Path(minecraft_npc.api({"op": "package", "platform": "neoforge"}, {})["file"])
            self.assertEqual(paper_copy, root / "data" / "game-mods" / "paper" / paper.name)
            self.assertEqual(neo_copy, root / "data" / "game-mods" / "neoforge-1.21.1" / neo.name)
            self.assertEqual((paper_copy.read_bytes(), neo_copy.read_bytes()), (b"paper", b"neoforge"))

    def test_desktop_scope_and_russian_inflections(self):
        self.assertEqual(scoped("В Minecraft, добудь восемь дубовых брёвен"), "добудь восемь дубовых брёвен")
        self.assertEqual(parse(scoped("добудь восемь дубовых брёвен в Майнкрафте")),
                         {"op": "mine", "item": "oak_log", "count": 8})
        self.assertEqual(parse("Скрафти 4 палки"), {"op": "craft", "item": "stick", "count": 4})
        self.assertEqual(parse("Передай два угля"), {"op": "give", "item": "coal", "count": 2})
        self.assertIsNone(scoped("помаши рукой"))
        self.assertIsNone(scoped("запусти Minecraft"))
        self.assertIsNone(parse("не добывай дуб"))
        self.assertIsNone(parse("как добыть дуб"))
        self.assertEqual(parse("добудь 17 песка")["error"], "count")
        self.assertEqual(parse("добудь bedrock")["error"], "item")

    def test_local_test_mode_does_not_apply_to_remote_servers(self):
        self.assertEqual(validate({"owner": "My_Name", "auth": "offline"})["account"], "JarvisCompanion")
        self.assertEqual(validate({"owner": "JarvisCompanion", "auth": "offline"})["account"], "JarvisHelper")
        for fields in ({"host": "myserver.example", "auth": "offline"}, {"host": "http://example.com"},
                       {"port": True}, {"port": 65536}, {"owner": "' bad"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                validate({"owner": "My_Name", **fields})
        self.assertTrue(validate({"owner": "My_Name", "trust_local_chat": True})["trust_local_chat"])
        self.assertFalse(validate({"owner": "My_Name", "trust_local_chat": True, "host": "example.org"})["trust_local_chat"])

    def test_new_commands_use_local_game_when_connected(self):
        cases = {
            "Скажи, где ты находишься": {"op": "position"},
            "Скажи свои координаты в Майнкрафте": {"op": "position"},
            "Правда ли прошлые координаты?": {"op": "position"},
            "Какой у тебя игровой режим сейчас выставлен?": {"op": "game_mode"},
            "Ты подключён к игре?": {"op": "connection"},
            "Дай мне доски": {"op": "give", "item": "planks", "count": 4},
            "Дай мне две доски": {"op": "give", "item": "planks", "count": 2},
            "Дай мне четыре каменных блока": {"op": "give", "item": "stone", "count": 4},
            "Смени игровой режим на выживание": {"op": "set_mode", "mode": "survival"},
            "Защищай меня": {"op": "guard"},
            "можешь, пожалуйста, телепортироваться ко мне": {"op": "teleport"},
            "телепортируйся ко мне": {"op": "teleport"},
            "покажи свой инвентарь в майнкрафте": {"op": "status"},
            "показать инвентарь": {"op": "status"},
            "сломай дерево": {"op": "mine", "item": "oak_log", "count": 1},
            "собери восемь досок": {"op": "obtain", "item": "planks", "count": 8},
            "добудь мне, пожалуйста, две дубовые доски": {"op": "obtain", "item": "oak_planks", "count": 2},
            "В Minecraft подготовь и принеси четыре дубовые доски": {"op": "deliver", "item": "oak_planks", "count": 4},
        }
        for phrase, expected in cases.items():
            with self.subTest(phrase):
                self.assertEqual(desktop(phrase, connected=True), expected)
        for phrase in ("не ломай дерево", "как добыть доски", "сделай скриншот", "добудь информацию", "стоп"):
            with self.subTest(phrase):
                self.assertIsNone(desktop(phrase, connected=True))
        self.assertIsNone(desktop("где ты находишься", connected=False))
        self.assertIsNone(desktop("телепортируйся ко мне", connected=True, allow_implicit=False))
        self.assertEqual(desktop("где ты находишься в Майнкрафте", connected=False), {"op": "position"})

    def test_position_and_async_result_use_observed_server_state(self):
        self.assertEqual(describe_position({"position": [-13, 71, 0], "dimension": "the_end"}),
                         "Мои координаты: икс -13, игрек 71, зет 0. Край.")
        companion = Companion()
        companion.process = object()
        companion.events = queue.Queue()
        companion.job_routes[5] = "desktop"
        reply = {"event": "job", "id": 5, "state": "done", "op": "obtain",
                 "result": {"count": 8, "item": "oak_planks"}}
        outgoing = queue.Queue()
        companion._receive(companion.process, outgoing, reply)
        self.assertEqual(companion.events.get_nowait(), ("minecraft_speech",
                         (companion.process, 0, "В моём инвентаре: 8 (дубовые доски).")))
        self.assertEqual(outgoing.get_nowait(), ("mirror", "В моём инвентаре: 8 (дубовые доски).", 0))

    def test_mode_and_reply_relay_are_tied_to_the_live_session(self):
        companion = Companion()
        companion.process = object()
        companion.phase = "ready"
        companion.messages = queue.Queue()
        with patch.object(companion, "request", return_value={"gameMode": "creative"}) as request:
            self.assertIn("творческий", companion.execute(parse("какой игровой режим")))
        self.assertEqual(request.call_args.args[0], {"op": "status"})
        session = companion.reply_session()
        companion.relay(session, "Погода в городе: +12.")
        self.assertEqual(companion.messages.get_nowait(), ("mirror", "Погода в городе: +12.", 0))
        companion.relay_replies = False
        companion.relay(session, "Погода в городе: +12.")
        self.assertTrue(companion.messages.empty())

        companion.relay(session, "Координаты", game=True)
        self.assertEqual(companion.messages.get_nowait()[1], "Координаты")
        companion.chat_epoch += 1
        companion.relay(session, "Запоздалый ответ", game=True)
        self.assertTrue(companion.messages.empty())

    def test_chat_uses_nickname_from_minecraft_and_cannot_send_slash_commands(self):
        self.assertEqual(list(chat_lines("Погода в Амстердаме.")), ["Погода в Амстердаме."])
        self.assertEqual(list(chat_lines("\u200b/op OtherPlayer")), ["› /op OtherPlayer"])

    def test_natural_language_can_resolve_inflected_items_from_the_client_dictionary(self):
        with patch("shelter_core.minecraft_intents.localized_items", return_value=({}, {"железный кирка": "iron_pickaxe",
                                                                         "еловый ступенька": "spruce_stairs"})):
            self.assertEqual(parse("экипируй железную кирку"), {"op": "equip", "item": "iron_pickaxe", "count": 1})
            self.assertEqual(parse("дай пять еловых ступенек"), {"op": "give", "item": "spruce_stairs", "count": 5})

    def test_semantic_plan_is_a_bounded_sequence_of_validated_operations(self):
        self.assertEqual(model_command("sequence obtain stone 6 | build wall stone 6"),
                         {"op": "sequence", "actions": [{"op": "obtain", "item": "stone", "count": 6},
                                                       {"op": "build", "shape": "wall", "item": "stone", "count": 6}]})
        self.assertIsNone(model_command("sequence guard | give planks 4"))
        self.assertIsNone(model_command("sequence equip sword 1 | say /op WorldOwner"))

    def test_fabric_response_must_match_request(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            response = directory / "response.json"
            response.write_text(json.dumps({"id": "stale", "state": "idle"}), encoding="utf-8")
            def finish_request(_seconds):
                payload = json.loads((directory / "request.json").read_text(encoding="utf-8"))
                self.assertEqual(payload["op"], "status")
                response.write_text(json.dumps({"id": payload["id"], "state": "ready", "x": 1,
                                                "y": 64, "z": 2, "gameMode": "survival"}), encoding="utf-8")
            with patch.object(minecraft_npc.time, "sleep", side_effect=finish_request):
                status = minecraft_npc._carpet_request(directory, "status", "fixture")
            self.assertEqual((status["platform"], status["gameMode"], status["y"]), ("fabric", "survival", 64))
            self.assertFalse((directory / "request.json").exists())

    def test_game_chat_command_does_not_wait_for_conversation_model(self):
        model_waiting = threading.Event()
        resume_model = threading.Event()
        spoken = queue.Queue()

        class TestCompanion(Companion):
            def _chat_reply(self, config, text, history):
                model_waiting.set()
                resume_model.wait(3)
                return "Модель ответила."

            def request(self, payload, *args, **kwargs):
                if payload["op"] == "status":
                    return {"gameMode": "survival", "position": [3, 64, -4]}
                if payload["op"] == "position":
                    return {"position": [3, 64, -4]}
                spoken.put(payload["text"])
                return {}

        companion = TestCompanion()
        process = companion.process = object()
        messages, ai = queue.Queue(6), queue.Queue(2)
        command_loop = threading.Thread(target=companion._chat_loop,
                                        args=(process, messages, ai, {"speak_chat": False}, queue.Queue()))
        ai_loop = threading.Thread(target=companion._chat_ai_loop, args=(process, messages, ai, {}))
        command_loop.start()
        ai_loop.start()
        try:
            messages.put(("chat", "Расскажи шутку", 0))
            self.assertTrue(model_waiting.wait(1))
            messages.put(("chat", "скажи координаты", 0))
            self.assertIn("игрек 64", spoken.get(timeout=1))
        finally:
            companion.process = None
            resume_model.set()
            command_loop.join(1)
            ai_loop.join(1)

    def test_lan_port_ignores_chat_and_closed_world(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "latest.log"
            log.write_text("[12:30:00] [Server thread/INFO]: Started serving on 48123\n"
                           "[12:30:01] [Render thread/INFO]: [CHAT] Started serving on 11111\n", encoding="utf-8")
            self.assertEqual(lan_port(log), 48123)
            with log.open("a", encoding="utf-8") as file:
                file.write("[12:32:00] [Server thread/INFO]: Stopping server\n")
            self.assertIsNone(lan_port(log))

    def test_stop_invalidates_received_game_chat(self):
        class Process:
            stdin = io.StringIO()

        companion = Companion()
        companion.process = Process()
        companion.phase = "ready"
        companion.messages = queue.Queue(6)
        companion.messages.put(("chat", "добудь дуб", 0))
        companion.interrupt()
        self.assertEqual(companion.chat_epoch, 1)
        self.assertTrue(companion.messages.empty())
        self.assertIn('"op": "stop"', companion.process.stdin.getvalue())
        with self.assertRaises(RuntimeError):
            companion.request({"op": "mine", "item": "oak_log", "count": 1}, epoch=0)

    def test_reports_only_observed_pickups(self):
        self.assertEqual(describe_job({"state": "done", "op": "mine",
                                       "result": {"broken": 2, "collected": 0, "item": "oak_log"}}),
                         "Сломано блоков: 2. Подобрано: 0 (дубовые брёвна).")
