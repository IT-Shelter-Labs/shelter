"""Диктовка, источники поиска и кнопка «говорить» — без сети и без реального ввода."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shelter_core import fastpath  # noqa: E402
from shelter_core import llm  # noqa: E402
from shelter_core import tools  # noqa: E402


class DictationTag(unittest.TestCase):
    def test_type_tag_keeps_text_with_punctuation(self):
        self.assertEqual(llm.parse_tag("type: Привет, как дела?"), ("tool", ("type", "Привет, как дела?")))

    def test_type_belongs_to_pc_tool(self):
        self.assertEqual(llm.TAG_TOOL["type"], "pc")


class SearchSources(unittest.TestCase):
    def test_duckduckgo_redirect_is_unwrapped(self):
        href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fru.wikipedia.org%2Fwiki%2F%D0%9A&amp;rut=abc"
        self.assertEqual(tools._ddg_url(href), "https://ru.wikipedia.org/wiki/К")

    def test_remember_keeps_only_web_links(self):
        lines = tools._remember([("A", "https://a.ru", "текст"), ("B", "javascript:x", "b")])
        self.assertEqual(lines, ["A: текст", "B: b"])
        self.assertEqual(tools.SOURCES, [("A", "https://a.ru")])

    def test_open_source_without_search_explains(self):
        tools.SOURCES[:] = []
        reply, done = fastpath.handle("открой источник", {}, run_tool=lambda *a: ("done", ""))
        self.assertFalse(done)
        self.assertIn("Источников пока нет", reply)

    def test_open_wikipedia_prefers_wiki_source(self):
        tools.SOURCES[:] = [("Сайт", "https://site.ru"), ("Википедия «Казань»", "https://ru.wikipedia.org/wiki/Казань")]
        with mock.patch("os.startfile", create=True) as start:
            reply, done = fastpath.handle("открой википедию", {}, run_tool=lambda *a: ("done", ""))
        start.assert_called_once_with("https://ru.wikipedia.org/wiki/Казань")
        self.assertTrue(done)
        self.assertIn("Казань", reply)


class PushToTalk(unittest.TestCase):
    def test_voice_exposes_arm_event(self):
        from shelter_core import voice
        voice.ARM.clear()
        voice.ARM.set()
        self.assertTrue(voice.ARM.is_set())
        voice.ARM.clear()


if __name__ == "__main__":
    unittest.main()
