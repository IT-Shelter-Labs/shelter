"""Сценарии: перенос команд, исполнитель (ветвления, таймаут, отмена, ошибка),
события без дублей, импорт/экспорт без секретов, проверка фразы без выполнения."""

import copy
import datetime
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shelter_core import main  # noqa: E402
from shelter_core import scenarios  # noqa: E402
from shelter_core import tasks  # noqa: E402
from shelter_core import triggers  # noqa: E402

LEGACY = [
    {"keywords": ["пока", "закрой", "до свидания"], "whole": True, "description": "попрощаться",
     "actions": [{"type": "say", "text": "Всего доброго, сэр."}, {"type": "close"}]},
    {"keywords": ["телеграм*"], "description": "открыть Telegram",
     "actions": [{"type": "launch", "path": "C:/nowhere/Telegram.exe"}]},
    {"keywords": ["выключи компьютер"], "description": "выключить компьютер", "confirm": {"text": "Вы уверены, сэр?"},
     "actions": [{"type": "shell", "cmd": "shutdown /s /t 30"}]},
]


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.patches = [patch.object(scenarios, "STORE", os.path.join(self.dir, "scenarios.json")),
                        patch.object(scenarios, "BACKUPS", os.path.join(self.dir, "backups")),
                        patch.object(triggers, "STATE", os.path.join(self.dir, "triggers.json"))]
        for p in self.patches:
            p.start()
        self.config = {"commands": copy.deepcopy(LEGACY), "wake": {"words": ["джарвис"]}, "llm": {"enabled": True},
                       "triggers": {"can_opened": [{"type": "say", "text": "Заряжаемся"}]}}
        scenarios.configure(self.config)
        scenarios.RECENT.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        scenarios._config = {}
        scenarios._persist = False
        shutil.rmtree(self.dir, ignore_errors=True)


class Migration(Sandbox):
    def test_old_commands_become_scenarios_with_backup(self):
        items = scenarios.load()
        self.assertEqual(len(items), 3)
        bye = items[0]
        self.assertEqual(bye["phrases"], ["пока", "закрой", "до свидания"])
        self.assertEqual(bye["match"], "whole")
        self.assertEqual(bye["steps"][0]["text"], "Всего доброго, сэр.")
        self.assertEqual(items[2]["confirm"], "Вы уверены, сэр?")
        backup = scenarios.backups()
        self.assertEqual(len(backup), 1)
        self.assertEqual(backup[0]["count"], 3)

    def test_voice_matcher_still_sees_commands(self):
        from shelter_core import voice
        commands = self.config["commands"]
        self.assertTrue(all(c.get("scenario") for c in commands))
        self.assertEqual(voice.find_command("пока", commands)["scenario"], scenarios.load()[0]["id"])
        # «закрой телеграм» — не прощание и не открытие Telegram.
        self.assertIsNone(voice.find_command("закрой телеграм", commands))

    def test_ids_are_stable_and_restart_does_not_duplicate(self):
        first = [i["id"] for i in scenarios.load()]
        scenarios.configure(self.config)
        self.assertEqual([i["id"] for i in scenarios.load()], first)

    def test_new_command_in_config_is_added_not_lost(self):
        scenarios.load()
        self.config["legacy_commands"].append({"keywords": ["калькулятор"], "actions": [{"type": "say", "text": "ок"}]})
        items = scenarios.load()
        self.assertEqual(items[-1]["phrases"], ["калькулятор"])
        self.assertEqual(len(items), 4)

    def test_restore_from_backup(self):
        scenarios.load()
        scenarios.delete(scenarios.load()[0]["id"])
        self.assertEqual(len(scenarios.load()), 2)
        backup = next(b for b in scenarios.backups() if "удален" in b["reason"])
        self.assertEqual(scenarios.restore(backup["id"]), 3)
        self.assertEqual(len(scenarios.load()), 3)

    def test_obsolete_video_scenario_stays_hidden_in_an_old_store(self):
        items = scenarios.load()
        scenarios.save_all([*items, {"id": "personal_can_opened", "name": "Old recording"}])
        self.assertEqual([item["id"] for item in scenarios.load()], [item["id"] for item in items])

    def test_newer_or_foreign_format_is_rejected_with_reason(self):
        problems = scenarios.validate({"format": scenarios.FORMAT, "version": 99, "name": "x", "steps": [{"type": "say", "text": "a"}]})
        self.assertTrue(any("новой версии" in p for p in problems))
        problems = scenarios.validate(scenarios.normalize({"name": "x", "phrases": ["x"], "steps": [{"type": "teleport"}]}))
        self.assertTrue(any("неизвестное действие" in p for p in problems))


class Executor(Sandbox):
    def run_item(self, steps, **extra):
        item = scenarios.normalize({"name": "Тест", "phrases": ["тест"], "steps": steps, **extra})
        with tasks.scope(tasks.Token()):
            return scenarios.execute(item)

    def test_branch_by_condition(self):
        said = []
        with patch("shelter_core.actions.run_action", side_effect=lambda a: said.append(a.get("text"))):
            result = self.run_item([{"type": "if", "condition": {"type": "time_between", "from": "00:00", "to": "23:59"},
                                     "then": [{"type": "say", "text": "да"}], "else": [{"type": "say", "text": "нет"}]}])
        self.assertEqual(result["status"], "done")
        self.assertEqual(said, ["да"])

    def test_bounded_repeat(self):
        said = []
        with patch("shelter_core.actions.run_action", side_effect=lambda a: said.append(a.get("text"))):
            result = self.run_item([{"type": "repeat", "times": 3, "steps": [{"type": "say", "text": "раз"}]}])
        self.assertEqual(said, ["раз"] * 3)
        self.assertEqual(result["status"], "done")

    def test_failed_step_is_not_done(self):
        result = self.run_item([{"type": "launch", "path": "C:/no/such/file.exe"}, {"type": "say", "text": "готово"}])
        self.assertEqual(result["status"], "failed")
        self.assertIn("нет файла", result["error"])
        self.assertEqual([s["status"] for s in result["steps"]], ["failed"])

    def test_continue_on_error_marks_partial(self):
        with patch("shelter_core.actions.run_action"):
            result = self.run_item([{"type": "launch", "path": "C:/no/such.exe"}, {"type": "say", "text": "дальше"}],
                                   on_error="continue")
        self.assertEqual(result["status"], "partial")
        self.assertEqual([s["status"] for s in result["steps"]], ["failed", "done"])

    def test_timeout_stops_scenario(self):
        result = self.run_item([{"type": "wait", "seconds": 30}], timeout=1)
        self.assertEqual(result["status"], "cancelled")
        self.assertIn("истекло", result["error"])

    def test_cancel_by_run_id_stops_waiting_and_skips_rest(self):
        said = []
        box = {}
        item = scenarios.normalize({"name": "Долгий", "phrases": ["д"], "steps": [{"type": "wait", "seconds": 30},
                                                                               {"type": "say", "text": "после"}]})

        def worker():
            with tasks.scope(tasks.Token()):
                box["result"] = scenarios.execute(item, run_id="run_test")
        with patch("shelter_core.actions.run_action", side_effect=lambda a: said.append(a)):
            thread = threading.Thread(target=worker)
            thread.start()
            time.sleep(0.3)
            self.assertEqual(scenarios.cancel("run_test"), ["run_test"])
            thread.join(3)
        self.assertEqual(box["result"]["status"], "cancelled")
        self.assertEqual(said, [], "после отмены продолжение не выполняется")

    def test_general_stop_cancels_parent_task(self):
        token = tasks.Token()
        box = {}
        item = scenarios.normalize({"name": "Ждёт", "phrases": ["ж"], "steps": [{"type": "wait", "seconds": 30}]})
        thread = threading.Thread(target=lambda: box.update(r=self._in(token, item)))
        thread.start()
        time.sleep(0.2)
        token.cancel()                               # «стоп» отменяет задачу исполнителя
        thread.join(3)
        self.assertEqual(box["r"]["status"], "cancelled")

    @staticmethod
    def _in(token, item):
        with tasks.scope(token):
            return scenarios.execute(item)

    def test_scenario_cannot_call_itself(self):
        item = scenarios.save({"name": "Петля", "phrases": ["петля"], "steps": [{"type": "say", "text": "x"}]})
        item["steps"] = [{"type": "scenario", "id": item["id"]}]
        scenarios.save(item)
        with patch("shelter_core.actions.run_action"):
            with tasks.scope(tasks.Token()):
                result = scenarios.execute(scenarios.get(item["id"]))
        self.assertEqual(result["status"], "failed")
        self.assertIn("сам себя", result["error"])

    def test_condition_not_met_skips(self):
        result = self.run_item([{"type": "say", "text": "x"}],
                               conditions=[{"type": "app_running", "app": "nonexistent-app-xyz"}])
        self.assertEqual(result["status"], "skipped")

    def test_plan_does_not_execute(self):
        with patch("shelter_core.actions.run_action", side_effect=AssertionError("план ничего не выполняет")):
            plan = scenarios.plan({"name": "П", "phrases": ["п"], "steps": [
                {"type": "say", "text": "привет"}, {"type": "launch", "path": "C:/no/x.exe"},
                {"type": "shell", "cmd": "echo"}]})
        self.assertEqual(len(plan["steps"]), 3)
        self.assertEqual(plan["steps"][1]["note"], "файл не найден")
        self.assertTrue(plan["steps"][2]["irreversible"])


class ImportExport(Sandbox):
    def test_export_strips_secrets_and_user_paths(self):
        home = os.path.expanduser("~")
        scenarios.save({"name": "С ключом", "phrases": ["ключ"], "steps": [
            {"type": "launch", "path": os.path.join(home, "app.exe")},
            {"type": "plugin", "name": "x", "params": {"api_key": "sk-secretsecretsecret", "room": "1"}}]})
        exported = scenarios.export()
        text = json.dumps(exported, ensure_ascii=False)
        self.assertNotIn("sk-secret", text)
        self.assertNotIn(home, text)
        self.assertIn("%USERPROFILE%", text)
        self.assertTrue(exported["removed"])

    def test_reimport_keeps_meaning_and_rejects_bad(self):
        scenarios.save({"name": "Музыка", "phrases": ["моя музыка"], "steps": [{"type": "media", "key": "play"},
                                                                          {"type": "volume", "value": 40}]})
        payload = scenarios.export()
        payload["items"].append({"format": scenarios.FORMAT, "version": 1, "name": "Плохой", "steps": [{"type": "nope"}]})
        result = scenarios.import_items(payload)
        self.assertIn("Музыка", result["added"])
        self.assertEqual(result["rejected"][0]["name"], "Плохой")
        copies = [i for i in scenarios.load() if i["name"] == "Музыка"]
        self.assertEqual(len(copies), 2)
        self.assertEqual(copies[0]["steps"], copies[1]["steps"])
        self.assertNotEqual(copies[0]["id"], copies[1]["id"])

    def test_newer_file_rejected(self):
        with self.assertRaises(scenarios.ScenarioError):
            scenarios.import_items({"format": scenarios.LIST_FORMAT, "version": 5, "items": []})


class Triggers(Sandbox):
    def engine(self, items):
        scenarios.save_all([scenarios.normalize(i) for i in items])
        events = __import__("queue").Queue()
        return triggers.Engine(events, self.config), events

    def test_headphones_fire_exactly_once_with_debounce(self):
        engine, events = self.engine([{"id": "phones", "name": "Наушники", "phrases": [], "cooldown": 60,
                                       "triggers": [{"type": "audio_added", "name": "наушники"}],
                                       "steps": [{"type": "say", "text": "ок"}]}])
        snapshots = iter([{"audio": {"Динамики"}}, {"audio": {"Динамики", "Наушники AirPods"}},
                          {"audio": {"Динамики", "Наушники AirPods"}}, {"audio": {"Динамики", "Наушники AirPods"}}])
        with patch.object(engine, "measure", side_effect=lambda: next(snapshots)):
            fired = [engine.step() for _ in range(4)]
        self.assertEqual(fired, [[], [], ["phones"], []])
        self.assertEqual(events.qsize(), 1)

    def test_flicker_is_ignored(self):
        engine, events = self.engine([{"id": "phones", "name": "Наушники", "phrases": [],
                                       "triggers": [{"type": "audio_added"}], "steps": [{"type": "say", "text": "ок"}]}])
        snapshots = iter([{"audio": {"A"}}, {"audio": {"A", "B"}}, {"audio": {"A"}}, {"audio": {"A"}}])
        with patch.object(engine, "measure", side_effect=lambda: next(snapshots)):
            for _ in range(4):
                engine.step()
        self.assertEqual(events.qsize(), 0)

    def test_restart_does_not_duplicate_schedule(self):
        items = [{"id": "morning", "name": "Утро", "phrases": [],
                  "triggers": [{"type": "schedule", "time": "08:30", "days": list(range(7))}], "steps": [{"type": "say", "text": "x"}]}]
        engine, events = self.engine(items)
        now = datetime.datetime.now().replace(hour=8, minute=30, second=20)
        self.assertEqual(engine.schedule_step(now), ["morning"])
        self.assertEqual(engine.schedule_step(now + datetime.timedelta(seconds=10)), [])
        again, events2 = triggers.Engine(events, self.config), None     # «перезапуск»: новое состояние с диска
        self.assertEqual(again.schedule_step(now + datetime.timedelta(seconds=20)), [])
        self.assertEqual(events.qsize(), 1)

    def test_missed_schedule_policy(self):
        items = [{"id": "missed", "name": "М", "phrases": [], "cooldown": 1,
                  "triggers": [{"type": "schedule", "time": "08:00", "days": list(range(7)), "missed": "skip"}],
                  "steps": [{"type": "say", "text": "x"}]}]
        engine, events = self.engine(items)
        day = datetime.datetime.now().replace(hour=8, minute=0, second=10)
        engine.schedule_step(day)                                 # отработало вчера…
        later = day + datetime.timedelta(days=1, hours=2)           # …а сегодня компьютер включили в 10:00
        self.assertEqual(engine.schedule_step(later), [], "skip — пропущенный не запускается")
        items[0]["triggers"][0]["missed"] = "run"
        os.remove(triggers.STATE)
        engine2, events2 = self.engine(items)
        engine2.schedule_step(day)
        self.assertEqual(engine2.schedule_step(later), ["missed"])

    def test_chain_of_autoruns_is_cut(self):
        items = [{"id": f"sc{i}", "name": f"S{i}", "phrases": [], "cooldown": 0,
                  "triggers": [{"type": "app_started", "app": f"app{i}"}], "steps": [{"type": "say", "text": "x"}]}
                 for i in range(5)]
        engine, events = self.engine(items)
        for i in range(5):
            engine.fire(scenarios.get(f"sc{i}"), {"type": "app_started"}, "x")
        self.assertEqual(events.qsize(), triggers.MAX_CHAIN)

    def test_engine_start_is_idempotent(self):
        engine, events = self.engine([])
        with patch.object(triggers, "_engine", None):
            first = triggers.start(events, self.config)
            second = triggers.start(events, self.config)
            self.assertIs(first, second)
            names = [t.name for t in threading.enumerate()].count("triggers")
            self.assertEqual(names, 1)
            first.stop()


class PhraseCheck(Sandbox):
    def explain(self, phrase, draft=None):
        from shelter_core import router_check
        return router_check.explain(phrase, self.config, draft)

    def test_close_telegram_does_not_close_jarvis(self):
        result = self.explain("закрой телеграм")
        self.assertEqual(result["route"], "builtin")
        self.assertEqual(result["calls"][0]["arg"], "close | телеграм")
        self.assertIn("а не Джарвиса", result["detail"])

    def test_how_are_you_is_a_reply_not_a_summary(self):
        result = self.explain("как дела")
        self.assertEqual(result["route"], "builtin")
        self.assertEqual(result["calls"], [])

    def test_scenario_phrase_and_stop(self):
        self.assertEqual(self.explain("пока")["route"], "scenario")
        self.assertEqual(self.explain("стоп")["route"], "stop")
        self.assertEqual(self.explain("джарвис")["route"], "wake")

    def test_persona_switch_not_executed(self):
        with patch("shelter_core.main.switch_persona", side_effect=AssertionError("проверка не переключает")):
            result = self.explain("стань джарвисом")
        self.assertIn(result["route"], ("persona", "builtin"))

    def test_draft_checked_separately_and_ambiguity_reported(self):
        draft = scenarios.normalize({"name": "Второе прощание", "phrases": ["пока"], "match": "whole",
                                     "steps": [{"type": "say", "text": "x"}]})
        result = self.explain("пока", draft)
        self.assertEqual(result["scenario"], draft["id"])
        self.assertTrue(result["ambiguous"])
        self.assertEqual(self.explain("пока")["scenario"], scenarios.load()[0]["id"], "сохранённые не изменились")

    def test_conflicts(self):
        from shelter_core import router_check
        draft = scenarios.normalize({"name": "X", "phrases": ["пока", "стоп", "джарвис включи"], "steps": [{"type": "say", "text": "x"}]})
        texts = " ".join(c["text"] for c in router_check.conflicts(self.config, draft))
        self.assertIn("уже есть", texts)
        self.assertIn("останавливает", texts)
        self.assertIn("обращения", texts)


class FromTask(unittest.TestCase):
    def test_only_verified_action_steps(self):
        draft = scenarios.from_run({"status": "done", "question": "открой телеграм и сделай громкость 30", "steps": [
            {"name": "app", "argument": "Telegram", "outcome": "done"},
            {"name": "search", "argument": "погода", "outcome": "data"},
            {"name": "pc", "argument": "volume | 30", "outcome": "done"},
            {"name": "home", "argument": "свет | on", "outcome": "fail"}]})
        self.assertEqual(draft["draft"]["steps"], [{"type": "open_app", "target": "Telegram"}, {"type": "volume", "value": 30}])
        self.assertEqual(len(draft["skipped"]), 2)

    def test_failed_task_cannot_be_saved(self):
        with self.assertRaises(scenarios.ScenarioError):
            scenarios.from_run({"status": "failed", "steps": []})


if __name__ == "__main__":
    unittest.main()
