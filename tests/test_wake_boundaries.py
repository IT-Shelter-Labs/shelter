import json
import queue
import threading
import types
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import numpy as np

import asr
import personas
import voice


class WakeBoundary(unittest.TestCase):
    def test_partial_wake_cannot_reuse_an_older_final_transcript(self):
        for giga, refined in ((None,''), (object(),'привет как дела'), (object(),'')):
            with self.subTest(refinement=giga is not None,empty=not refined), ExitStack() as stack:
                stop = threading.Event()
                class Input:
                    count = 0
                    def get(self, timeout):
                        self.count += 1
                        if self.count == 2: stop.set()
                        return np.ones(voice.CHUNK, dtype=np.float32)*.1
                source = Input()
                class Recognizer:
                    def __init__(self, *args): pass
                    def AcceptWaveform(self, pcm): return source.count == 2
                    def PartialResult(self): return json.dumps({'partial':'привет как дела джарвис'})
                    def Result(self): return json.dumps({'text':'привет как дела'})
                    def Reset(self): pass
                fake=types.SimpleNamespace(Model=lambda _:None,KaldiRecognizer=Recognizer,SetLogLevel=lambda _:None)
                stack.enter_context(patch.dict('sys.modules',{'vosk':fake}))
                stack.enter_context(patch.object(asr,'load',return_value=giga))
                stack.enter_context(patch.object(asr,'transcribe',return_value=refined))
                for name in ('LISTENING','SPEAKING','THINKING','ARM','RESUME','HEARING'):
                    stack.enter_context(patch.object(voice,name,threading.Event()))
                stack.enter_context(patch.object(voice,'INBOX',queue.Queue()))
                events=queue.Queue()
                cfg={'wake':{'model_path':'unused','words':['джарвис'],'vad':False,'barge_in':False},'llm':{'enabled':True}}
                voice.listen(types.SimpleNamespace(vosk_queue=source,sample_rate=32000),cfg,events,stop)
                result=list(events.queue)
                self.assertTrue(any(k=='wake' for k,_ in result),result)
                self.assertFalse(any(k in ('ask','command') for k,_ in result),result)

    def test_text_before_call_never_becomes_a_command(self):
        for text in ("привет как дела джарвис", "я рассказывал что случилось а потом сказал джарвис"):
            called, command, rest = voice.match(text, ["джарвис"], [])
            self.assertTrue(called)
            self.assertIsNone(command)
            self.assertEqual(rest, "")
            self.assertEqual(asr.strip_wake(text, ["джарвис"]), ("", True))

    def test_only_words_after_call_are_used_even_in_a_long_utterance(self):
        text = "привет как дела до этого разговор джарвис поставь таймер"
        self.assertEqual(voice.match(text, ["джарвис"], [])[2], "поставь таймер")
        self.assertEqual(asr.strip_wake(text, ["джарвис"]), ("поставь таймер", True))

    def test_inflected_persona_name_is_not_a_wake_word(self):
        self.assertFalse(voice.match("стань джарвисом", ["джарвис"], [])[0])
        self.assertFalse(voice.match("я читал о джарвисе", ["джарвис"], [])[0])
        self.assertEqual(voice.match("джарвис стань джарвисом", ["джарвис"], [])[2], "стань джарвисом")

    def test_kws_hit_does_not_authorize_transcript_without_a_call(self):
        self.assertEqual(asr.called_transcript("привет как дела", ["джарвис"]), "джарвис")
        self.assertEqual(asr.called_transcript("привет как дела джарвиз", ["джарвис"]), "джарвис")
        self.assertEqual(asr.called_transcript("вот длинная фраза джарвиз который час", ["джарвис"]), "джарвис который час")

    def test_short_names_do_not_fuzzily_match_common_words(self):
        self.assertEqual(asr.strip_wake("ну ты как дела", ["юки"]), ("ну ты как дела", False))
        self.assertEqual(asr.strip_wake("пипа который час", ["пиппа", "пипа"]), ("который час", True))


class PersonaIntent(unittest.TestCase):
    def test_call_names_follow_persona_and_allow_explicit_variants(self):
        config={"wake":{"words":["джарвис"]}}
        self.assertEqual(personas.call_words({"id":"pippa","name":"Пиппа"},config),["пиппа","пипа"])
        self.assertEqual(personas.call_words({"id":"yuki","name":"Юки"},config),["юки"])
        self.assertEqual(personas.call_words({"id":"pippa","name":"Пиппа","wake_words":["Пятница"]},config),["пятница"])
        self.assertEqual(personas.call_words({"id":"jarvis","name":"Джарвис"},config),["джарвис"])
    def test_name_alone_or_negation_cannot_switch(self):
        for text in ("жарис", "джарвис", "Пиппа", "как зовут Джарвиса", "не становись Джарвисом", "давай поговорим о Джарвисе", "включи музыку Джарвиса"):
            self.assertFalse(personas.switch_requested(text), text)
            self.assertIsNone(personas.find_switch(text), text)
        for text in ("стань котом", "верни привычного помощника", "переключись на Пиппу", "хочу сменить персонажа на Юки"):
            self.assertTrue(personas.switch_requested(text), text)

    def test_model_cannot_switch_on_misheard_call(self):
        import main
        seen = []
        def respond(question, config, commands, run_tool, **kwargs):
            seen.append(run_tool("persona", "jarvis")[0])
            yield "text", "Слушаю."
        with patch.object(main,"switch_persona",side_effect=AssertionError("unsolicited switch")), \
             patch.object(main.llm,"respond",side_effect=respond),patch.object(main,"run_action"), \
             patch.object(main.gaming,"busy",return_value=False),patch.object(voice,"speak_stream",side_effect=lambda s:list(s)):
            main.answer({"llm":{"enabled":True,"tools":[],"semantic_input":False}},"жарис")
        self.assertEqual(seen,["fail"])
