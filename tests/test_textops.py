"""Действия с текстом: не подставлять чужой текст, показывать результат до замены, не вставлять в чужое окно."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fastpath  # noqa: E402
import textops  # noqa: E402


class TextOps(unittest.TestCase):
    def setUp(self):
        textops.STATE.update(id="", source="", window=None, text="", result="", op="", status="empty", error="")

    @unittest.skipUnless(os.name == "nt", "захват выделения — Windows")
    def test_failed_capture_does_not_fall_back_to_clipboard(self):
        import pc
        with patch.object(textops, "_foreground", return_value={"hwnd": 5, "title": "Блокнот", "process": "notepad"}), \
             patch.object(pc, "clipboard_text", return_value="старый буфер с паролем"), \
             patch.object(pc, "send_keys"), patch.object(textops, "_sequence", return_value=7):
            with self.assertRaisesRegex(RuntimeError, "не удалось взять выделение"):
                textops.capture_selection()
        self.assertEqual(textops.STATE["text"], "", "буфер не подставлен вместо выделения")

    def test_result_shown_before_replace(self):
        textops.manual("превет как дила")
        state = textops.run("fix", {"llm": {}}, generate=lambda cfg, system, text: "Привет, как дела?")
        self.assertEqual(state["result"], "Привет, как дела?")
        self.assertEqual(state["status"], "ready")
        self.assertEqual(state["text"], "превет как дила", "исходник сохранён")

    def test_model_failure_is_not_success(self):
        textops.manual("текст")
        def broken(*a):
            raise OSError("connection refused")
        state = textops.run("translate", {"llm": {}}, generate=broken)
        self.assertEqual(state["status"], "failed")
        self.assertIn("не ответила", state["error"])

    @unittest.skipUnless(os.name == "nt", "вставка — Windows")
    def test_apply_refuses_other_window(self):
        import pc
        textops.STATE.update(source="selection", window={"hwnd": 111, "title": "Word"}, text="a", result="b", status="ready")
        with patch.object(pc.user32, "IsWindow", return_value=True), patch.object(pc, "_focus"), \
             patch.object(pc.user32, "GetForegroundWindow", return_value=222), \
             patch.object(pc, "type_text", side_effect=AssertionError("нельзя печатать в чужое окно")), \
             patch("time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "неожиданное поле"):
                textops.apply()

    def test_manual_text_cannot_be_pasted_somewhere(self):
        textops.manual("текст")
        textops.STATE["result"] = "результат"
        with self.assertRaisesRegex(RuntimeError, "не из выделения"):
            textops.apply()

    def test_voice_phrases(self):
        calls = []
        tool = lambda name, arg: calls.append((name, arg)) or ("done", "")
        for phrase, op in (("исправь выделенное", "fix"), ("переведи это", "translate"), ("сократи выделенный текст", "shorten"),
                           ("вставь", "apply")):
            fastpath.handle(phrase, {"llm": {"tools": ["pc"]}}, run_tool=tool)
            self.assertEqual(calls[-1], ("textops", op), phrase)


if __name__ == "__main__":
    unittest.main()
