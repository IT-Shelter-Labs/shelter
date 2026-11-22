import unittest
from unittest.mock import patch

from shelter_core import llm
from shelter_core import agent_runtime

MODELS = {"provider":"ollama", "model":"chat", "tools":["screen"], "api_key":"old-key",
          "routes":{"vision":"eyes"},
          "connections":{"eyes":{"provider":"openai","url":"https://example.test/v1","model":"vision", "share_context":False}}}


class VisionRouting(unittest.TestCase):
    def test_separate_vision_receives_only_requested_screen_not_history_or_old_credentials(self):
        cfg, messages = llm.screen_followup("Что это за ошибка?", {"text":"Ошибка 42", "images":["base64"]}, MODELS)
        self.assertEqual(cfg["model"], "vision")
        self.assertNotIn("api_key", cfg)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[-1]["images"], ["base64"])
        self.assertIn("Ошибка 42", messages[-1]["content"])

    def test_tag_protocol_uses_selected_vision_connection(self):
        requests = []
        def provider(cfg):
            def stream(messages, cfg, timeout):
                requests.append((cfg["model"], messages))
                yield "[screen]" if cfg["model"] == "chat" else "Это ошибка подключения."
            return stream
        config = {"llm":{**MODELS, "enabled":True, "agent":{"protocol":"tags"}}}
        with patch.object(llm, "_provider", side_effect=provider), \
             patch.object(llm.context_engine,"build",return_value=([],[],"private materials",{})):
            events = list(llm.respond("Объясни ошибку на экране", config,
                          run_tool=lambda *args:("data",{"text":"Ошибка", "images":["base64"]})))
        self.assertEqual([r[0] for r in requests], ["chat", "vision"])
        self.assertNotIn("private materials", str(requests[-1][1]))
        self.assertIn(("text", "Это ошибка подключения."), events)

    def test_native_protocol_converts_screen_to_observation_before_chat_continues(self):
        rounds = []
        def turn(messages, specs, cfg, timeout):
            rounds.append(str(messages))
            if len(rounds)==1:
                return {"role":"assistant", "content":"", "tool_calls":[{"function":{"name":"screen","arguments":{}}}]}, True
            return {"role":"assistant", "content":"Объяснение ошибки."}, True
        with patch.object(agent_runtime,"turn",side_effect=turn), \
             patch.object(llm,"_provider",return_value=lambda *args:iter(["Вижу ошибку подключения."])):
            list(agent_runtime.respond([{"role":"user","content":"Что на экране?"}], {"llm":MODELS}, [], [],
                 lambda *args:("data",{"text":"Окно", "images":["base64-secret"]})))
        self.assertNotIn("base64-secret", rounds[-1])
        self.assertIn("Вижу ошибку подключения.", rounds[-1])
