"""Персонажи: команда «стань аниме-тянкой», голос, характер и окно — на лету."""

import copy
import os
import sys
import tempfile
import unittest
import json
import wave
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shelter_core import bus  # noqa: E402
from shelter_core import personas  # noqa: E402


def builtin_fixture(test):
    """Synthetic assets keep behavior tests independent of private model/voice files."""
    folder = tempfile.TemporaryDirectory()
    test.addCleanup(folder.cleanup)
    target = Path(folder.name)
    for name in ("jarvis", "anime"):
        value = json.loads((Path(personas.BUILTIN_DIR)/name/"persona.json").read_text(encoding="utf8"))
        if name == "anime":
            value["avatar"] = {"type":"vrm", "model":"models/avatars/anime.vrm"}
            value.setdefault("voice",{})["reference"] = "voice.wav"
            value["voice"]["reference_text"] = "Синтетическая проверочная фраза."
        dest = target/name; dest.mkdir()
        (dest/"persona.json").write_text(json.dumps(value,ensure_ascii=False),encoding="utf8")
        if name == "anime":
            with wave.open(str(dest/"voice.wav"),"wb") as out:
                out.setparams((1,2,16000,0,"NONE","not compressed")); out.writeframes(b"\0\0"*1600)
    (target/"sounds").mkdir()
    (target/"sounds/can_opened.wav").write_bytes((target/"anime/voice.wav").read_bytes())
    for context in (patch.object(personas,"BUILTIN_DIR",str(target)),patch.object(personas,"ROOT",str(target)),
                    patch.object(personas,"ensure_model"),patch("shelter_core.setup_tool.install")):
        context.start(); test.addCleanup(context.stop)


def config():
    return {"llm": {"system": "Ты Джарвис.", "tools": ["app"]},
            "tts": {"engine": "piper", "speaker": "aidar", "piper": {"voice": "ruslan"},
                    "clone": {"reference": "sounds/can_opened.wav", "reference_text": "Команда"}},
            "ui": {"mode": "hud"},
            "wake": {"words": ["джарвис"], "actions": [{"type": "say", "text": "Да, сэр.", "file": "sounds/yes.wav"}]}}


class Personas(unittest.TestCase):
    def setUp(self):
        builtin_fixture(self)
        self.active_path = personas.ACTIVE_PATH
        self.user_dir = personas.USER_DIR
        personas.USER_DIR = tempfile.mkdtemp()          # только встроенные персонажи
        personas.ACTIVE_PATH = os.path.join(tempfile.mkdtemp(), "persona.json")
        personas._base = None
        personas._active = None

    def tearDown(self):
        from shelter_core.avatar import AVATAR
        AVATAR.config = {}
        personas.ACTIVE_PATH = self.active_path
        personas.USER_DIR = self.user_dir
        personas._base = None
        personas._active = None

    def test_voice_command_finds_persona(self):
        for phrase in ("стань аниме-тянкой", "превратись в аниме тян", "включи режим аниме", "стань юки"):
            self.assertEqual(personas.find_switch(phrase), "anime", phrase)
        for phrase in ("стань джарвисом", "верни джарвиса", "вернись к джарвису"):
            self.assertEqual(personas.find_switch(phrase), "jarvis", phrase)
        for phrase in ("стань собакой", "открой браузер", "включи музыку"):
            self.assertIsNone(personas.find_switch(phrase), phrase)

    def test_anime_changes_character_voice_and_window_in_place(self):
        cfg = config()
        actions = cfg["wake"]["actions"]
        words = cfg["wake"]["words"]
        personas.apply(cfg)                                   # активный — Джарвис
        self.assertEqual(cfg["llm"]["system"], "Ты Джарвис.")
        personas.switch(cfg, "anime")
        self.assertIn("Юки", cfg["llm"]["system"])
        self.assertEqual(cfg["ui"]["mode"], "avatar")
        self.assertEqual(cfg["tts"]["speaker"], "xenia")
        self.assertTrue(cfg["tts"]["clone"]["reference"].endswith("voice.wav"))
        self.assertIs(cfg["wake"]["actions"], actions, "потоки ядра держат тот же список")
        self.assertEqual(actions[0]["text"], "Да, хозяин?")
        self.assertIs(cfg["wake"]["words"], words)
        self.assertEqual(words, ["юки"])
        self.assertEqual(personas.runtime_call_words(cfg), ["юки"])
        self.assertNotIn("file", actions[0], "запись голоса Джарвиса ей не подходит")
        personas.switch(cfg, "jarvis")
        self.assertEqual(cfg["llm"]["system"], "Ты Джарвис.")
        self.assertEqual(cfg["ui"]["mode"], "hud")
        self.assertEqual(words, ["джарвис"])
        self.assertEqual(cfg["wake"]["actions"][0], {"type": "say", "text": "Да, сэр.", "file": "sounds/yes.wav"})

    def test_rewrite_address_and_gender(self):
        personas.switch(config(), "anime")
        self.assertEqual(personas.rewrite("Запомнил, сэр."), "Запомнила, хозяин.")
        self.assertEqual(personas.rewrite("Простите, сэр, не расслышал."), "Простите, хозяин, не расслышала.")
        personas.switch(config(), "jarvis")
        self.assertEqual(personas.rewrite("Запомнил, сэр."), "Запомнил, сэр.")

    def test_fastpath_switch_shows_avatar(self):
        from shelter_core import fastpath
        from shelter_core import main
        from shelter_core import voice
        cfg = config()
        personas.apply(cfg)
        events = []
        old_publish, old_prepare = bus.publish, voice.prepare
        bus.publish = lambda kind, **data: events.append((kind, data))
        voice.prepare = lambda texts: None
        try:
            from unittest.mock import patch
            with patch("shelter_core.gaming.busy", return_value=False):
                reply, done = fastpath.handle("стань аниме-тянкой", cfg)
        finally:
            bus.publish, voice.prepare = old_publish, old_prepare
            main.switch_persona.__globals__["voice"].PITCH = 1.0
            voice.CLONE_REF = {}
        self.assertTrue(done)
        self.assertIn("Юки", reply)
        kinds = [k for k, _ in events]
        self.assertIn("persona", kinds)
        shown = [d for k, d in events if k == "avatar" and d.get("state") == "show"]
        self.assertTrue(shown and shown[0]["model"].endswith("anime.vrm"))
        personas.switch(copy.deepcopy(cfg), "jarvis")


if __name__ == "__main__":
    unittest.main()


class WakeAtEnd(unittest.TestCase):
    """«Стань Джарвисом» — смена персонажа, а не пустое обращение."""
    W = ["джарвис", "джарвес", "жарвис"]

    def rest(self, text):
        from shelter_core import voice
        return voice.match(text, self.W, [])[2]

    def test_only_a_leading_call_keeps_the_command(self):
        self.assertEqual(self.rest("стань джарвисом"), "")
        self.assertEqual(self.rest("джарвис стань джарвисом"), "стань джарвисом")
        self.assertEqual(self.rest("открой браузер джарвис"), "")

    def test_plain_wake_and_talk_about_jarvis_stay_wake_only(self):
        for text in ("джарвис", "эй джарвис", "слушай джарвис", "я вчера настраивал джарвиса"):
            self.assertEqual(self.rest(text), "", text)

    def test_misheard_name_still_switches(self):
        self.assertEqual(personas.find_switch("стань джарлисом"), "jarvis")
        self.assertIsNone(personas.find_switch("стань дарвином"))


class VoiceFollowsPersona(unittest.TestCase):
    """После «стань Джарвисом» — голос Джарвиса, а не образец, с которым стартовал сервер."""

    def setUp(self):
        builtin_fixture(self)
        self.active_path = personas.ACTIVE_PATH
        self.user_dir = personas.USER_DIR
        personas.USER_DIR = tempfile.mkdtemp()          # только встроенные персонажи
        personas.ACTIVE_PATH = os.path.join(tempfile.mkdtemp(), "persona.json")
        personas._base = None
        personas._active = None

    def tearDown(self):
        from shelter_core import voice
        from shelter_core.avatar import AVATAR
        AVATAR.config = {}
        voice.CLONE_REF = {}
        personas.ACTIVE_PATH = self.active_path
        personas.USER_DIR = self.user_dir
        personas._base = None
        personas._active = None

    def test_jarvis_reference_is_sent_explicitly(self):
        from shelter_core import main
        from shelter_core import voice
        cfg = config()
        cfg["tts"]["engine"] = "clone"
        old_engine = voice.ENGINE
        voice.ENGINE = "clone"
        try:
            personas.switch(cfg, "anime")
            main.persona_runtime(cfg)
            self.assertTrue(voice.CLONE_REF["reference"].replace("\\", "/").endswith("anime/voice.wav"))
            yuki_key = voice._cache_path("Да.")
            personas.switch(cfg, "jarvis")
            main.persona_runtime(cfg)
            self.assertEqual(voice.CLONE_REF["reference"].replace("\\", "/"), "sounds/can_opened.wav")
            self.assertNotEqual(voice._cache_path("Да."), yuki_key, "у голосов разный кэш")
        finally:
            voice.ENGINE = old_engine

    def test_switch_stops_preparing_old_voice(self):
        from shelter_core import voice
        spoken = []
        old = voice.synthesize
        voice.synthesize = lambda text: (spoken.append(text), voice.set_voice({}, lambda: None))
        try:
            voice.prepare(["первая фраза для теста", "вторая фраза для теста"])
        finally:
            voice.synthesize = old
        self.assertEqual(spoken, ["первая фраза для теста"], "после смены голоса подготовка остановилась")


class AckEcho(unittest.TestCase):
    def test_ack_echo_removed_only_right_after_ack(self):
        import time
        from shelter_core import voice
        cfg = {"wake": {"actions": [{"type": "say", "text": "Да, сэр."}]}}
        voice.ACK_AT = time.monotonic()
        self.assertEqual(voice.strip_ack("да сэр открой браузер", cfg), "открой браузер")
        voice.ACK_AT = time.monotonic() - 60
        self.assertEqual(voice.strip_ack("да сэр открой браузер", cfg), "да сэр открой браузер")
