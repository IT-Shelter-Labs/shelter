import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from shelter_core import main
from shelter_core import personas
from shelter_core import tts_server
from shelter_core import voice


class ProfileRouting(unittest.TestCase):
    def test_only_jarvis_selects_adapter_and_uses_separate_cache(self):
        cfg={"tts":{"clone":{"model":"base","jarvis_adapter":"models/new-voice",
                                "reference":"sounds/can_opened.wav","reference_text":"Команда"}}}
        with patch.object(voice,"ENGINE","clone"),patch.object(voice,"CLONE_REF",{}), \
             patch.object(voice,"CACHE_PROFILE",""),patch("shelter_core.tts_profiles.revision",return_value="revision-one"):
            with patch.object(personas,"active",return_value={"id":"jarvis"}):
                main.persona_runtime(cfg)
                self.assertEqual(voice.CLONE_REF['model_profile'],'jarvis')
                trained=voice.CACHE_PROFILE
            with patch.object(personas,"active",return_value={"id":"anime"}):
                main.persona_runtime(cfg)
                self.assertEqual(voice.CLONE_REF['model_profile'],'default')
                self.assertNotEqual(voice.CACHE_PROFILE,trained)
                original=voice.CACHE_PROFILE
                cfg['tts']['clone'].pop('jarvis_adapter')
                main.persona_runtime(cfg)
                self.assertEqual(voice.CACHE_PROFILE,original)

    def test_new_adapter_revision_invalidates_only_jarvis_audio(self):
        cfg={"tts":{"clone":{"model":"base","jarvis_adapter":"models/new-voice"}}}
        with patch.object(voice,"ENGINE","clone"),patch.object(voice,"CLONE_REF",{'model_profile':'jarvis'}), \
             patch.object(voice,"CACHE_PROFILE",""),patch("shelter_core.tts_profiles.revision",side_effect=['one','two']):
            voice.configure_cache(cfg);first=voice.CACHE_PROFILE
            voice.configure_cache(cfg);self.assertNotEqual(voice.CACHE_PROFILE,first)

    def test_server_profile_is_an_allowlist_not_a_client_file_path(self):
        self.assertEqual(tts_server.sampling_from({'model_profile':'jarvis'})['model_profile'],'jarvis')
        self.assertEqual(tts_server.sampling_from({})['model_profile'],'default')
        for value in ('../../model',None,[],{}):
            with self.subTest(value=value),self.assertRaises(ValueError):
                tts_server.sampling_from({'model_profile':value})


    def test_tested_jarvis_sampling_does_not_change_other_characters(self):
        args=SimpleNamespace(reference='ref.wav',reference_text='Образец',language='Russian',temperature=.7,top_p=1.)
        profiles=SimpleNamespace(sampling={'temperature':.7,'top_p':.9,'chunk':12})
        with patch.object(tts_server,'ARGS',args),patch.object(tts_server,'PROFILES',profiles):
            self.assertEqual(tts_server.clone_args('Тест',{'model_profile':'jarvis'})['top_p'],.9)
            self.assertEqual(tts_server.clone_args('Тест',{'model_profile':'default'})['top_p'],1.)
            self.assertEqual(tts_server.clone_args('Тест',{'model_profile':'jarvis','top_p':.8})['top_p'],.8)


if __name__=='__main__':unittest.main()
