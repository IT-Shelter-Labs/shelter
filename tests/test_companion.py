import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from shelter_core import lip_sync
from shelter_core import personas


class LipSync(unittest.TestCase):
    def test_silence_and_invalid_audio_close_mouth(self):
        for x in [np.zeros(1600, np.int16), np.full(1600, np.nan), np.full(1600, 128, np.uint8)]:
            frames = lip_sync.acoustic(16000, x)
            self.assertTrue(frames)
            self.assertFalse(np.any(frames))

    def test_live_analysis_is_bounded_deterministic_and_colours_vowels(self):
        t = np.arange(16000) / 16000
        low = .15 * np.sin(t*2*np.pi*350)
        high = .15 * np.sin(t*2*np.pi*2600)
        a = lip_sync.acoustic(16000, low)
        b = lip_sync.acoustic(16000, high)
        self.assertEqual(len(a), 50)
        self.assertEqual(a, lip_sync.acoustic(16000, low))
        self.assertTrue(np.isfinite(a).all())
        self.assertLessEqual(np.max(np.sum(a,axis=1)), 1)
        self.assertNotEqual(np.argmax(np.mean(a,axis=0)),np.argmax(np.mean(b,axis=0)))

    def test_phonetic_closures_and_round_vowels_follow_timestamps(self):
        fake = type('Result', (), {'returncode':0,'stdout':json.dumps({'mouthCues':[
            {'start':0,'end':.25,'value':'A'}, {'start':.25,'end':.5,'value':'F'},
            {'start':.5,'end':1,'value':'D'}]}).encode()})()
        audio = (np.sin(np.arange(16000)*.3)*8000).astype(np.int16)
        with patch.object(lip_sync,'executable',return_value=Path('rhubarb.exe')), patch.object(lip_sync.subprocess,'run',return_value=fake) as process:
            frames=lip_sync.align(16000,audio)
        self.assertEqual(frames[0], [0]*5)
        self.assertEqual(frames[15][2], .7)
        self.assertEqual(frames[30][0], .85)
        self.assertIn('phonetic', process.call_args.args[0])
        self.assertEqual(process.call_args.kwargs['timeout'],60)

    def test_cache_does_not_depend_on_text_or_voice_name(self):
        with tempfile.TemporaryDirectory() as root, patch.object(lip_sync,'ROOT',Path(root)):
            x=np.zeros(8000,np.int16)
            data,path=lip_sync._key(16000,lip_sync.pcm(16000,x))
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'version':1,'samples':len(x),'frames':[[0,.2,0,0,0]]}),encoding='utf8')
            self.assertEqual(lip_sync.frames(16000,x)[1],'phonetic')
            self.assertEqual(lip_sync.frames(24000,x,prepare=False)[1],'acoustic')


class AccessoryValidation(unittest.TestCase):
    def test_rejects_invalid_transforms_and_file_types_before_save(self):
        base={'id':'test','name':'Test','avatar':{'type':'vrm','accessories':[{'id':'glasses',
              'bone':'head','builtin':'glasses','position':[0,0,0],'rotation':[0,0,0],'scale':1}]}}
        personas._validate(base)
        for field,value in [('scale',float('nan')),('scale',True),('position',[0,0]),('bone','not-a-bone'),('builtin','script')]:
            bad=copy.deepcopy(base);bad['avatar']['accessories'][0][field]=value
            with self.subTest(field=field,value=value), self.assertRaises(ValueError):
                personas._validate(bad)
        bad=copy.deepcopy(base);bad['avatar']['accessories']*=2
        with self.assertRaises(ValueError): personas._validate(bad)


class SeatedLifecycle(unittest.TestCase):
    def test_seated_visibility_survives_temporary_gesture_and_dialogue_end(self):
        from shelter_core.avatar import AvatarController
        from shelter_core import bus
        avatar=AvatarController()
        avatar.config={'mode':'avatar','persona':{'always':False,'options':{}}}
        with patch.object(bus,'publish') as publish:
            avatar.set_seated(True)
            avatar.hold_motion(0)
            avatar.hide()
            self.assertTrue(avatar._visible)
            self.assertTrue(avatar.motion_active)
            avatar._motion_id='wave'; avatar._motion_until=0
            with patch('shelter_core.gaming.busy',return_value=False): avatar.tick({})
            self.assertTrue(any(call.kwargs.get('preserve_seat') is True for call in publish.call_args_list))
            avatar.set_seated(False); avatar.hold_motion(0)
            self.assertFalse(avatar.motion_active)


if __name__=='__main__': unittest.main()
