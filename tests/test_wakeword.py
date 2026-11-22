"""Слово-обращение KWS: строки ключевых слов, порог, работа на звуке."""

import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wakeword  # noqa: E402


class Threshold(unittest.TestCase):
    def test_middle_sensitivity_is_the_tuned_threshold(self):
        self.assertEqual(wakeword.threshold(0.5), 0.1)

    def test_more_sensitive_means_lower_threshold_and_stays_positive(self):
        self.assertLess(wakeword.threshold(0.9), wakeword.threshold(0.2))
        self.assertGreater(wakeword.threshold(5), 0)


@unittest.skipUnless(wakeword.available(), "нет модели слова-обращения (models/kws-ru)")
class Keywords(unittest.TestCase):
    def test_jarvis_variants_share_one_tag(self):
        lines = wakeword.keyword_lines(["джарвис", "джарвес"])
        tags = {line.rsplit("@", 1)[1] for line in lines}
        self.assertEqual(tags, {"w:джарвис"})
        self.assertGreaterEqual(len(lines), 6)

    def test_custom_word_and_quick_phrases(self):
        lines = wakeword.keyword_lines(["пятница"], ["следующий трек"])
        self.assertTrue(any(line.endswith("@w:пятница") for line in lines))
        quick = [line for line in lines if "@q:" in line]
        self.assertEqual(quick[0].rsplit("@", 1)[1], "q:следующий_трек")
        self.assertIn("#0.25", quick[0], "быстрым словам порог строже")

    def test_latin_word_is_rejected(self):
        with self.assertRaises(RuntimeError):
            wakeword.Spotter(["jarvis"], keywords_file=os.path.join(tempfile.mkdtemp(), "kw.txt"))

    def test_silence_does_not_wake(self):
        spotter = wakeword.Spotter(["джарвис"], keywords_file=os.path.join(tempfile.mkdtemp(), "kw.txt"))
        stream = spotter.stream()
        noise = np.random.default_rng(0).normal(0, 0.01, 16000 * 3).astype(np.float32)
        self.assertEqual(spotter.feed(stream, noise), [])


if __name__ == "__main__":
    unittest.main()
