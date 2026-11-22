import base64
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
from scipy.io import wavfile

from shelter_core import cloud_media
from shelter_core import game_assist
from shelter_core import live_facts
from shelter_core import llm_connections
from shelter_core import main
from shelter_core import minecraft_intents
from shelter_core import personas
from shelter_core import screen
from shelter_core import voice
from shelter_core.audio import LISTENING


class BuiltinModelTests(unittest.TestCase):
    def test_builtin_route_is_available_without_saving_a_connection(self):
        cfg = {"provider": "openai", "api_key": "fixture", "api_key_env": "FIXTURE_API_KEY",
               "connections": {"cloud": {"provider": "openai", "url": "https://example.invalid/v1", "model": "custom"}},
               "routes": {"conversation": "builtin_gemma_e4b", "task": "cloud"}}
        llm_connections.validate(cfg)
        local = llm_connections.resolve(cfg)
        self.assertEqual((local["provider"], local["model"], local["url"]),
                         ("ollama", "gemma4:e4b", "http://127.0.0.1:11434"))
        self.assertFalse(local.get("api_key") or local.get("api_key_env"))
        self.assertEqual(llm_connections.resolve(cfg, "task")["model"], "custom")
        self.assertEqual(set(cfg["connections"]), {"cloud"})


class FactsTests(unittest.TestCase):
    def test_weather_resolves_the_inflected_city_before_geocoding(self):
        from urllib.parse import parse_qs, urlsplit
        from shelter_core import tools
        geocoding = {"results": [{"name": "Амстердам", "latitude": 52.37, "longitude": 4.89}]}
        forecast = {"current": {"temperature_2m": 10, "apparent_temperature": 10, "weather_code": 0,
                                "wind_speed_10m": 2}, "daily": {}}
        with patch.object(tools, "_geo_cache", {}), patch.object(tools, "_get", side_effect=map(json.dumps, (geocoding, forecast))) as get:
            answer = live_facts.answer("Погода в амстердаме", {})
        self.assertIn("Амстердам", answer)
        query = parse_qs(urlsplit(get.call_args_list[0].args[0]).query)
        self.assertEqual(query["name"], ["Амстердам"])

    def test_explicit_bitcoin_currency_and_stale_price(self):
        response = {"bitcoin": {"rub": 4_237_125.2, "last_updated_at": time.time()}}
        with patch.object(live_facts.tools, "_get", return_value=json.dumps(response)) as read:
            answer = live_facts.answer("Назови курс биткоина в рублях", {})
            self.assertIn("4 237 125 ₽", answer)
            self.assertIn("vs_currencies=rub", read.call_args.args[0])
            response["bitcoin"]["last_updated_at"] -= 3600
            read.return_value = json.dumps(response)
            self.assertNotIn("4 237 125", live_facts.answer("Курс BTC в рублях", {}))

    def test_ethereum_quotes_route_directly_in_requested_currency(self):
        response = {"ethereum": {"rub": 253_134, "eur": 2515, "usd": 2833, "last_updated_at": time.time()}}
        with patch.object(live_facts.tools, "_get", return_value=json.dumps(response)) as read:
            for phrase, code, shown in (
                ("Сколько сейчас стоит эфир в рублях?", "rub", "253 134 ₽"),
                ("Назови курс Ethereum в евро сегодня", "eur", "2 515 €"),
                ("Покажи цену эфира в рублях на сегодня", "rub", "253 134 ₽"),
                ("Почём эфир в рублях?", "rub", "253 134 ₽"),
                ("ETH/USD", "usd", "2 833 $"),
                ("what is the price of ETH in EUR", "eur", "2 515 €"),
                ("Курс эфириума в долларах США", "usd", "2 833 $"),
            ):
                with self.subTest(phrase=phrase):
                    result = live_facts.answer(phrase, {})
                    self.assertIn("Ethereum (ETH)", result)
                    self.assertIn(shown, result)
                    self.assertIn("ids=ethereum", read.call_args.args[0])
                    self.assertIn(f"vs_currencies={code}", read.call_args.args[0])
        self.assertIsNone(live_facts.answer("Включи эфир", {}))

    def test_ethereum_stale_or_missing_quote_keeps_currency(self):
        with patch.object(live_facts.tools, "_get", return_value='{"ethereum":{"usd":2222,"last_updated_at":0}}'):
            answer = live_facts.answer("Цена ETH в USD", {})
            self.assertIn("ETH) в долларах", answer)
            self.assertNotIn("2222", answer)
            self.assertIn("ETH) в евро", live_facts.answer("Цена ETH в евро", {}))

    def test_country_resolves_to_its_capital_instead_of_country_centroid(self):
        for country, capital, code in (("Японии", "Tokyo", "JP"), ("Германии", "Berlin", "DE"),
                                       ("Бразилии", "Brasilia", "BR")):
            with self.subTest(country=country):
                result = {"current": {"temperature_2m": 10, "apparent_temperature": 10, "weather_code": 0,
                                      "wind_speed_10m": 2}, "daily": {}}
                with patch.object(live_facts.tools, "_locate", return_value=(capital, 1, 2)) as locate, \
                     patch.object(live_facts.tools, "_get", return_value=json.dumps(result)):
                    text = live_facts.answer(f"Какая сейчас погода в {country}", {})
                self.assertIn(f"{capital}, сейчас", text)
                self.assertIn("столице", text)
                locate.assert_called_once_with(capital, code)


class CloudMediaTests(unittest.TestCase):
    config = {"llm": {"connections": {"provider": {"provider": "openai", "url": "https://example.com/v1",
                                                   "api_key": "test-key"}}},
              "tts": {"cloud": {"connection": "provider", "model": "tts", "voice": "voice"}},
              "image_generation": {"connection": "provider", "model": "images"}}

    def test_dedicated_speech_route_sends_only_spoken_text(self):
        audio = io.BytesIO()
        wavfile.write(audio, 24000, np.array([3, -5], dtype=np.int16))
        with patch.object(cloud_media, "_read", return_value=audio.getvalue()) as request:
            rate, samples = cloud_media.speech("Проверка.", self.config)
        self.assertEqual((rate, samples.tolist()), (24000, [3, -5]))
        url, payload, _ = request.call_args.args
        self.assertEqual(url, "https://example.com/v1/audio/speech")
        self.assertEqual(payload, {"model": "tts", "voice": "voice", "input": "Проверка.", "response_format": "wav"})

    def test_image_creation_persists_png(self):
        image = screen.png(1, 1, bytes([255, 0, 0, 0]))
        response = json.dumps({"data": [{"b64_json": base64.b64encode(image).decode()}]})
        with tempfile.TemporaryDirectory() as folder, patch.object(cloud_media, "ROOT", Path(folder)), \
                patch.object(cloud_media, "_read", return_value=response):
            output = cloud_media.image("Один пиксель", self.config)
            self.assertEqual(Path(output["file"]).read_bytes(), image)

    def test_alibaba_workspace_requests_base64_images(self):
        from copy import deepcopy

        config = deepcopy(self.config)
        url = "https://workspace.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
        config["llm"]["connections"]["provider"]["url"] = url
        picture = base64.b64encode(screen.png(1, 1, bytes([255, 0, 0, 0]))).decode()
        response = json.dumps({"data": [{"b64_json": picture}]})
        with tempfile.TemporaryDirectory() as folder, patch.object(cloud_media, "ROOT", Path(folder)), \
                patch.object(cloud_media, "_read", return_value=response) as request:
            cloud_media.image("Один пиксель", config)
        self.assertEqual(request.call_args.args[0], url + "/images/generations")
        self.assertEqual(request.call_args.args[1]["response_format"], "b64_json")


class InteractionTests(unittest.TestCase):
    def test_exact_preset_phrase_preserves_legacy_alias_priority(self):
        builtin = {"id": "anime", "name": "Юки", "aliases": ["аниме тянка"], "builtin": True,
                   "switch_hint": "Стань аниме-тянкой", "switch_forms": ["аниме тянкой"]}
        custom = {"id": "custom", "name": "Мой образ", "aliases": ["аниме тянка"], "builtin": False}
        with patch.object(personas, "all_personas", return_value=[builtin, custom]):
            self.assertEqual(personas.find_switch(builtin["switch_hint"]), "anime")
            self.assertEqual(personas.find_switch("стань аниме тянка"), "custom")
            self.assertEqual(personas.find_switch("Переключись на «Мой образ»"), "custom")

    def test_dashboard_stop_disarms_voice_and_closes_dialogue(self):
        from unittest.mock import Mock

        runner = Mock()
        voice.ARM.set()
        voice.RESUME.set()
        LISTENING.set()
        try:
            with patch("shelter_core.minecraft_companion.MINECRAFT.interrupt"), patch.object(voice, "stop_speaking"), \
                    patch("shelter_core.scenarios.cancel"), patch.object(main, "close_overlay") as close:
                main.interrupt({}, runner, dismiss_dialogue=True)
            self.assertFalse(any(flag.is_set() for flag in (voice.ARM, voice.RESUME, LISTENING)))
            self.assertTrue(voice.STOP_LISTENING.is_set())
            runner.cancel_current.assert_called_once()
            close.assert_called_once()
        finally:
            voice.STOP_LISTENING.clear()

    def test_factorio_reads_mod_items_and_research(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / game_assist.SNAPSHOT
            path.write_text(json.dumps({"format": "shelter-factorio-1", "player": "Player", "surface": "nauvis",
                                        "inventory": [{"name": "modded-item", "count": 12}], "research": "automation",
                                        "x": 1, "y": 2, "progress": .28}), encoding="utf-8")
            cfg = {"factorio": {"snapshot": str(path)}}
            self.assertIn("modded-item: 12", game_assist.answer("Что у меня в инвентаре в Factorio?", cfg))
            os.utime(path, (time.time() - 70, time.time() - 70))
            self.assertIn("По последнему снимку", game_assist.answer("Factorio, какое сейчас исследование?", cfg))

    def test_minecraft_preserves_namespace(self):
        self.assertEqual(minecraft_intents.desktop("В Майнкрафте скрафти 2 create:copper_sheet.", False),
                         {"op": "craft", "item": "create:copper_sheet", "count": 2})
        self.assertEqual(minecraft_intents.desktop("В Майнкрафте подготовь и принеси 2 create:copper_sheet.", False),
                         {"op": "deliver", "item": "create:copper_sheet", "count": 2})
