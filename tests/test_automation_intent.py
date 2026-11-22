import json
import unittest
from unittest.mock import patch

import automation_intent as auto
import scenarios
import tasks


APPS = [{"name": "Telegram", "id": "telegram"}, {"name": "Calculator", "id": "calculator"},
        {"name": "Windows Terminal", "id": "terminal"}, {"name": "Notepad", "id": "notepad"}]


class AutomationTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("tools.load_apps", return_value=APPS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_existing_actions_are_composed_offline_in_order(self):
        text = "Можешь открыть калькулятор и поставить громкость на тридцать, потом напомни через три минуты выпить воды"
        request = auto.inspect(text)
        self.assertTrue(request.chain)
        with patch.object(auto, "_model", side_effect=AssertionError("not needed")):
            steps = auto.compile_steps(request, {"llm": {"enabled": False}})
        self.assertEqual(steps, [
            {"type": "open_app", "target": "Calculator"}, {"type": "volume", "value": 30},
            {"type": "timer", "minutes": 3.0, "label": "выпить воды"}
        ])

    def test_followup_window_refers_to_intended_app_and_episode_is_a_skill(self):
        request = auto.inspect("Открой Телеграм, затем сверни его, потом следующая серия")
        self.assertEqual(auto.compile_steps(request, {}), [
            {"type": "open_app", "target": "Telegram"}, {"type": "window", "action": "minimize", "title": "Telegram"},
            {"type": "browser_episode"}
        ])

    def test_one_open_verb_can_apply_to_two_apps(self):
        steps = auto.compile_steps(auto.inspect("Открой блокнот и калькулятор"), {})
        self.assertEqual([step["target"] for step in steps], ["Notepad", "Calculator"])
        self.assertFalse(auto.inspect('Открой «Война и мир»').chain)

    def test_model_only_gets_unresolved_clauses_and_binds_the_original_value(self):
        request = auto.inspect("Открой телеграм, потом убавь звук до сорока")
        with patch.object(auto, "_model", return_value='{"steps":[{"op":"volume","value":"сорока"}]}') as model:
            steps = auto.compile_steps(request, {"llm": {"enabled": True}})
            self.assertEqual(steps[1], {"type": "volume", "value": 40})
            model.assert_called_once()
            self.assertEqual(model.call_args.args[0], ["убавь звук до сорока"])
        request = auto.inspect("Открой телеграм, потом дай музыке передышку")
        with patch.object(auto, "_model", return_value='{"steps":[{"op":"pause","value":""}]}'):
            self.assertEqual(auto.compile_steps(request, {"llm": {"enabled": True}})[1],
                             {"type": "media", "key": "pause"})

    def test_natural_volume_requires_grounded_value_not_model_guess(self):
        request = auto.inspect("открой телеграм и сделай звук потише, до сорока")
        for result in ('{"steps":[{"op":"volume","value":"70"}]}', '{"steps":[{"op":"shell","value":""}]}',
                       '{"steps":[{"op":"volume","value":"","cmd":"x"}]}', '{"steps":[]}'):
            with self.subTest(result=result), patch.object(auto, "_model", return_value=result):
                with self.assertRaises(auto.PlanError):
                    auto.compile_steps(request, {"llm": {"enabled": True}})

    def test_partial_plan_does_not_execute(self):
        phrases = ("открой калькулятор и отправь сообщение", "открой калькулятор и напиши громкость 40",
                   "открой калькулятор и только не выключай музыку",
                   "открой калькулятор, затем открой терминал",
                   "открой калькулятор, затем открой C:/Temp/test.exe",
                   "открой калькулятор, затем открой несуществующую программу")
        with patch("scenarios.execute") as execute:
            for text in phrases:
                with self.subTest(text=text):
                    self.assertIn("Ничего не выполнял", auto.run(auto.inspect(text), {})[0])
            self.assertIn("отключена", auto.run(auto.inspect("открой калькулятор, поставь громкость на 40"),
                                              {"llm": {"tools": ["app"]}})[0])
            execute.assert_not_called()

    def test_dictated_text_not_a_workflow_and_quoted_label_is_literal(self):
        for text in ('напиши «открой телеграм и поставь громкость 40»', 'как открыть калькулятор и поставить таймер?',
                     'не открывай калькулятор', 'включи свет', 'покажи погоду', 'скажи какие таймеры'):
            self.assertIsNone(auto.inspect(text))
        request = auto.inspect('открой калькулятор, потом напомни через три минуты «позвонить и отправь черновик»')
        self.assertEqual(auto.compile_steps(request, {})[1]["label"], "позвонить и отправь черновик")

    def test_executor_stop_on_failure_and_save_only_success_same_conversation(self):
        request = auto.inspect("открой калькулятор, потом поставь громкость на тридцать")
        events = []
        with patch.object(scenarios, "_config", {}), patch.object(scenarios, "RECENT", []), \
                patch.object(auto, "launch_exact", side_effect=lambda app: events.append(("open", app)) or "принято"), \
                patch("pc.set_volume", side_effect=lambda value: events.append(("volume", value)) or value), \
                patch("pc.get_volume", return_value=30), patch.object(auto, "_remembered", {}), \
                patch("scenarios.load", return_value=[]), patch("scenarios.save", side_effect=lambda item: item) as save:
            with tasks.scope(tasks.Token(session_id="test-a")):
                self.assertEqual(auto.save("Мой вечер"), "В этом разговоре нет недавней успешной цепочки для сохранения.")
                self.assertTrue(auto.run(request, {})[1])
                self.assertEqual(events, [("open", "Calculator"), ("volume", 30)])
            with tasks.scope(tasks.Token(session_id="test-b")):
                self.assertIn("нет недавней", auto.save("Мой вечер"))
                save.assert_not_called()
            with tasks.scope(tasks.Token(session_id="test-a")):
                self.assertIn("Сохранил", auto.save("Мой вечер"))
                self.assertEqual(save.call_args.args[0]["match"], "whole")
                with patch.object(auto, "launch_exact", side_effect=auto.PlanError("ярлык удалён")):
                    self.assertIn("Успел выполнить 0 из 2", auto.run(request, {})[0])
                    self.assertIn("нет недавней", auto.save("Моя работа"))
            self.assertEqual(len(events), 2)

    def test_journal_keeps_the_entire_workflow_and_can_restore_it(self):
        steps = [{"type": "volume", "value": 55}, {"type": "browser_episode"}]
        detail = {"status": "done", "question": "Громкость 55, потом следующая серия", "steps": [
            {"name": "voice_plan", "argument": json.dumps(steps), "outcome": "done"},
            {"name": "media", "argument": "next", "outcome": "done"},
        ]}
        draft = scenarios.from_run(detail)["draft"]
        self.assertEqual(draft["steps"], steps)
        self.assertEqual(draft["origin"], "voice_plan")
        self.assertEqual(draft["triggers"], [{"type": "button"}])
        detail["steps"][0]["argument"] = '[{"type":"shell","cmd":"echo not allowed"}]'
        with self.assertRaises(scenarios.ScenarioError):
            scenarios.from_run(detail)

    def test_real_request_does_not_fall_through_to_dialogue_on_bad_chain(self):
        import main
        import voice
        text = "открой калькулятор и отправь сообщение"
        command = {"keywords": ["калькулятор"], "actions": []}
        self.assertIsNone(voice.find_command(text, [command]))
        with patch("voice.speak_stream") as speak, patch("main.run_tool") as execute, patch("llm.respond") as model, \
                patch("main.LISTENING"), patch("voice.RESUME"):
            self.assertEqual(main._answer({}, text), [])
            self.assertIn("Ничего не выполнял", speak.call_args.args[0][0])
            execute.assert_not_called()
            model.assert_not_called()
