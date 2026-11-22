"""Озвучка чисел: падеж, род, порядковые, даты, деньги; клон голоса и кэш."""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shelter_core import speech_text  # noqa: E402
from shelter_core import voice  # noqa: E402

say = speech_text.prepare_for_speech


@unittest.skipUnless(speech_text.morph(), "нет pymorphy3")
class Grammar(unittest.TestCase):
    def check(self, text, expected):
        self.assertEqual(say(text), expected)

    def test_case_follows_preposition(self):
        self.check("С 3 до 5 часов дождь.", "С трёх до пяти часов дождь.")
        self.check("Около 40 км.", "Около сорока километров.")
        self.check("из 12 ГБ", "из двенадцати гигабайт")
        self.check("К 3 часам.", "К трём часам.")

    def test_gender_and_case_follow_noun(self):
        self.check("В 1 комнате 2 лампы.", "В одной комнате две лампы.")
        self.check("Нашёл 22 папки.", "Нашёл двадцать две папки.")
        self.check("Я с 2 друзьями.", "Я с двумя друзьями.")
        self.check("Таймер на 1 минуту.", "Таймер на одну минуту.")

    def test_ordinals_dates_years(self):
        self.check("до 1 декабря", "до первого декабря")
        self.check("В 2026 году.", "В две тысячи двадцать шестом году.")
        self.check("Уже 2026 год.", "Уже две тысячи двадцать шестой год.")
        self.check("1-й раз, 3-я попытка", "первый раз, третья попытка")
        self.check("в 1990-х годах", "в тысяча девятьсот девяностых годах")
        self.check("Посмотри 2 серию.", "Посмотри вторую серию.")
        self.check("На 5 этаже.", "На пятом этаже.")

    def test_units_and_money(self):
        self.check("-3°C, ветер 5 м/с", "минус три градуса Цельсия, ветер пять метров в секунду")
        self.check("Курс 92,45 ₽.", "Курс девяносто два рубля сорок пять копеек.")
        self.check("Билет $25.", "Билет двадцать пять долларов.")
        self.check("Цена 1 500 000 рублей.", "Цена один миллион пятьсот тысяч рублей.")
        self.check("1000 ночей", "тысяча ночей")
        self.check("Погода +5.", "Погода плюс пять.")

    def test_counts_stay_cardinal(self):
        self.check("Нас 5 человек.", "Нас пять человек.")
        self.check("Ему 21 год.", "Ему двадцать один год.")

    def test_stress_mark_is_removed(self):
        self.assertEqual(say("замо́к"), "замок")


class CloneVoice(unittest.TestCase):
    def setUp(self):
        self.engine = voice.ENGINE

    def tearDown(self):
        voice.ENGINE = self.engine
        voice.configure_cache({})

    def test_clone_cache_ignores_unrelated_voice_settings(self):
        voice.ENGINE = "clone"
        base = {"tts": {"clone": {"model": "m", "reference_text": "т"}, "piper": {"voice": "ruslan"}}}
        voice.configure_cache(base)
        first = voice._cache_path("Да, сэр.")
        voice.configure_cache({"tts": {**base["tts"], "piper": {"voice": "denis", "speed": 1.2}, "speaker": "baya"}})
        self.assertEqual(voice._cache_path("Да, сэр."), first, "смена запасного голоса не сбрасывает кэш клона")
        voice.configure_cache({"tts": {"clone": {"model": "m", "reference_text": "другой"}}})
        self.assertNotEqual(voice._cache_path("Да, сэр."), first, "другой образец — другой голос")

    def test_dead_clone_is_not_awaited(self):
        from shelter_core import neural
        old = neural._process
        neural._process = None
        try:
            started = time.monotonic()
            self.assertFalse(voice._wait_for_clone())
            self.assertLess(time.monotonic() - started, 2.0)
        finally:
            neural._process = old


if __name__ == "__main__":
    unittest.main()
