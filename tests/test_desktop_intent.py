import json
import unittest
from unittest.mock import patch

from shelter_core import desktop_intent as intent

CONFIG = {"llm": {"enabled": True, "tools": ["pc"], "provider": "ollama", "model": "test"}}


def decision(command, confidence=0.98):
    return json.dumps({"decision": "execute", "confidence": confidence,
                       "command": command, "question": ""}, ensure_ascii=False)


class SemanticInput(unittest.TestCase):
    def tearDown(self):
        intent.clear_clarification()

    def classify(self, phrase, command, **kwargs):
        with patch.object(intent, "_generate", return_value=decision(command, **kwargs)):
            return intent.classify(phrase, CONFIG)

    def test_paraphrases_use_model_not_another_phrase_list(self):
        for phrase, command in [
            ("Тыкни, пожалуйста, правой мышкой", {"operation": "click", "button": "right", "count": 1}),
            ("Опусти страничку чуть ниже", {"operation": "scroll", "steps": -3}),
            ("Отошли уже набранное", {"operation": "send"}),
            ("В это поле впиши: Встречаемся в семь!", {"operation": "write", "text": "Встречаемся в семь!"}),
        ]:
            self.assertEqual(self.classify(phrase, command)["command"], command)

    def test_literal_payload_is_grounded_in_current_utterance(self):
        result = self.classify("Впиши в поле: Как дела?", {"operation": "write", "text": "Как дела?"})
        self.assertEqual(result["command"]["text"], "Как дела?")
        for command in ({"operation": "write", "text": "Секрет из предыдущего сообщения"},
                        {"operation": "rewrite", "instruction": "добавь выдуманные факты"}):
            self.assertNotEqual(self.classify("Впиши в поле: Как дела?", command)["decision"], "execute")

    def test_low_confidence_asks_instead_of_guessing(self):
        result = self.classify("Нажми ту кнопку", {"operation": "click", "button": "left"}, confidence=0.5)
        self.assertEqual(result["decision"], "clarify")
        self.assertTrue(result["question"])

    def test_invalid_arguments_never_reach_execution(self):
        for command in ({"operation": "shell", "text": "whoami"},
                        {"operation": "click", "button": "right", "count": True},
                        {"operation": "scroll", "steps": 100},
                        {"operation": "key", "key": "alt+f4"},
                        {"operation": "send", "recipient": "somebody"},
                        {"operation": "write", "text": "Привет\n"}):
            self.assertNotEqual(self.classify("Привет\n", command)["decision"], "execute")

    def test_non_action_and_clarification_are_preserved(self):
        for choice in ("none", "clarify"):
            with patch.object(intent, "_generate", return_value=json.dumps({"decision": choice, "confidence": 0.9,
                    "command": {}, "question": "Какую кнопку мыши нажать?"})):
                self.assertEqual(intent.classify("Расскажи про кнопки", CONFIG)["decision"], choice)

    def test_disabled_capability_never_calls_model(self):
        with patch.object(intent, "_generate", side_effect=AssertionError("disabled")):
            self.assertEqual(intent.classify("Тыкни правой", {"llm": {"enabled": True, "tools": []}})["decision"], "none")

    def test_authorization_is_single_use_and_does_not_trust_proposed_arguments(self):
        with patch.object(intent, "_generate", return_value=decision({"operation": "click", "button": "right", "count": 1})) as model:
            request = intent.Request("Тыкни правой мышкой", CONFIG)
            status, value = request.authorize("click")
            self.assertEqual(status, "execute")
            self.assertEqual(value["button"], "right")
            self.assertEqual(request.authorize("click")[0], "fail")
            model.assert_called_once()

    def test_cached_preflight_does_not_repeat_generation_at_execution(self):
        with patch.object(intent, "_generate", return_value=decision({"operation":"key", "key":"tab"})) as model:
            request = intent.Request("Дай табом перейти к следующему полю", CONFIG)
            self.assertEqual(request.inspect()["decision"], "execute")
            self.assertEqual(request.authorize("key")[0], "execute")
            model.assert_called_once()

    def test_classifier_fits_short_commands_at_supported_2k_context(self):
        from shelter_core import llm
        from shelter_core import context_engine
        def provider(messages, cfg, timeout):
            context_engine.bound_messages(messages, cfg)
            self.assertEqual(cfg["context"], 2048)
            return iter([decision({"operation":"click", "button":"right", "count":1})])
        with patch.object(llm,"_provider",return_value=provider):
            result = intent.classify("Тыкни правой мышкой", {"llm":{**CONFIG["llm"], "context":2048}})
        self.assertEqual(result["decision"], "execute")

    def test_clarification_answer_gets_only_the_bounded_question_context(self):
        from shelter_core import desktop_input
        clarify=json.dumps({"decision":"clarify","confidence":0.9,"command":{},"question":"Левой или правой?"})
        with patch.object(intent,"_generate",return_value=clarify):
            self.assertEqual(intent.Request("Нажми ту кнопку",CONFIG).inspect()["decision"],"clarify")
        with patch.object(intent,"_generate",return_value=decision({"operation":"click","button":"right","count":1})) as model:
            self.assertEqual(intent.Request("правой",CONFIG).authorize("click")[0],"execute")
            self.assertEqual(model.call_args.args[2]["clarification"],{"utterance":"Нажми ту кнопку","question":"Левой или правой?"})
        intent._clarification={"utterance":"old","question":"old","owner":None,"at":intent.time.monotonic() - 61}
        self.assertIsNone(intent._take_clarification())
        intent._clarification={"utterance":"old","question":"old","owner":None,"at":intent.time.monotonic()}
        desktop_input.clear_pending()
        self.assertIsNone(intent._take_clarification())

    def test_clarification_does_not_cross_conversation_boundary(self):
        from shelter_core import tasks
        intent._clarification={"utterance":"old","question":"old","owner":"first", "at":intent.time.monotonic()}
        token=tasks.Token();token.session_id="second"
        with tasks.scope(token):self.assertIsNone(intent._take_clarification())

    def test_provider_receives_the_clarification_as_a_real_turn_not_nested_metadata(self):
        from shelter_core import llm
        from shelter_core import context_engine
        def provider(messages, cfg, timeout):
            self.assertEqual([m["role"] for m in messages], ["system","user","assistant","user"])
            self.assertEqual(json.loads(messages[2]["content"])["question"], "Левой или правой?")
            self.assertEqual(json.loads(messages[3]["content"])["utterance"], "правой")
            context_engine.bound_messages(messages, cfg)
            return iter([decision({"operation":"click","button":"right","count":1})])
        with patch.object(llm,"_provider",return_value=provider):
            result = intent.classify("правой", {"llm":{**CONFIG["llm"],"context":2048}},
                                     {"utterance":"Нажми ту кнопку","question":"Левой или правой?"})
        self.assertEqual(result["decision"], "execute")

    def test_preflight_handles_phrases_the_general_model_missed(self):
        from shelter_core import main
        from shelter_core import voice
        cases = [
            ("Дай табом перейти к следующему полю", {"operation":"key", "key":"tab"}),
            ("Вместо моего черновика поставь: Буду через час.", {"operation":"replace", "text":"Буду через час."}),
            ("Припиши к моему тексту: Спасибо за помощь!", {"operation":"append", "text":"Спасибо за помощь!"}),
            ("Передумал, отмени диктовку", {"operation":"cancel"}),
        ]
        for phrase, command in cases:
            with self.subTest(phrase=phrase), patch.object(intent,"_generate",return_value=decision(command)), \
                 patch.object(main,"run_tool",return_value=("done","Проверено")) as execute, \
                 patch.object(main,"run_action"), patch.object(main.gaming,"busy",return_value=False), \
                 patch.object(main.bus,"publish"), patch.object(voice,"speak_stream"), \
                 patch.object(main.llm,"respond",side_effect=AssertionError("input fell through to dialogue")):
                main.answer(CONFIG, phrase)
            self.assertEqual(json.loads(execute.call_args.args[2]), command)

    def test_malformed_provider_output_fails_closed(self):
        for output in ("не JSON", "[]", '{"decision":"execute","confidence":NaN,"command":{"operation":"send"}}'):
            with patch.object(intent, "_generate", return_value=output):
                self.assertNotEqual(intent.classify("Отошли набранное", CONFIG)["decision"], "execute")

    def test_dispatcher_accepts_meaning_without_exact_parser_match(self):
        from shelter_core import main
        from shelter_core import pc
        from shelter_core import voice
        from shelter_core import desktop_input
        phrase = "Тыкни, пожалуйста, правой мышкой"
        self.assertIsNone(desktop_input.resolve(phrase))
        def response(question, config, commands, run_tool, devices):
            outcome, text = run_tool("desktop", "click")
            self.assertEqual(outcome, "done")
            yield "text", text
        with patch.object(intent, "_generate", return_value=decision({"operation":"click","button":"right","count":1})), \
             patch.object(main, "run_action"), patch.object(main.gaming, "busy", return_value=False), \
             patch.object(main, "overlay_alive", return_value=False), patch.object(main.bus, "publish"), \
             patch.object(main.llm, "respond", side_effect=AssertionError("input preflight must resolve without main dialogue")), \
             patch.object(voice, "speak_stream", side_effect=lambda lines:list(lines)), \
             patch.object(pc, "mouse_click") as click:
            main.answer(CONFIG, phrase)
        click.assert_called_once_with("right", 1)

    def test_both_model_protocols_offer_semantic_desktop_tool(self):
        from shelter_core import agent_runtime
        from shelter_core import llm
        specs, handlers = agent_runtime.definitions(CONFIG, [], [])
        spec = next(x for x in specs if x["function"]["name"] == "desktop")
        self.assertIn("send", spec["function"]["parameters"]["properties"]["operation"]["enum"])
        self.assertEqual(handlers["desktop"][1]({"operation":"click"}), "click")
        self.assertEqual(llm.parse_tag("desktop: click"), ("tool", ("desktop", "click")))

    def test_phrase_preview_preserves_text_and_never_executes_semantic_action(self):
        from shelter_core import router_check
        from shelter_core import pc
        config = {**CONFIG, "commands":[], "wake":{"words":["джарвис"]}}
        with patch.object(intent, "_generate", return_value=decision({"operation":"click","button":"right","count":1})), \
             patch.object(pc, "mouse_click", side_effect=AssertionError("preview clicked")):
            result = router_check.explain("Тыкни правой мышкой", config, semantic=True)
        self.assertEqual(result["route"], "semantic")
        direct = router_check.explain("Напиши сообщение: До Встречи!", config)
        self.assertIn("До Встречи!", direct["calls"][0]["arg"])

    def test_microphone_calibration_uses_the_shared_resampler(self):
        from shelter_core import mic_check
        from shelter_core import native_runtime
        import numpy as np
        samples = np.zeros(320, dtype=np.float32)
        with patch.object(native_runtime, "resample_poly", return_value=samples[:160]) as resample:
            result = mic_check._to16k(samples, 32000)
        resample.assert_called_once_with(samples, 1, 2)
        self.assertEqual(len(result), 160)

    def test_tag_stream_releases_primary_model_before_intent_pass(self):
        from shelter_core import llm
        closed = []
        def stream(*args):
            try:
                yield "[desktop: click]"
                yield "Лишний ответ"
            finally:
                closed.append(True)
        def execute(*args):
            self.assertEqual(closed, [True])
            return "done", "Кликнул."
        config = {"llm": {**CONFIG["llm"], "agent":{"protocol":"tags"}}}
        with patch.object(llm, "_provider", return_value=stream), \
             patch.object(llm.context_engine, "build", return_value=([],[],"",{})):
            events = list(llm.respond("Тыкни правой мышкой", config, run_tool=execute))
        self.assertIn(("text", "Кликнул."), events)
        self.assertNotIn(("text", "Лишний ответ"), events)


if __name__ == "__main__":
    unittest.main()
