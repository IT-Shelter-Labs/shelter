import base64
import collections
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np
from shelter_core import remote_audio as audio
from shelter_core import tasks


class RemoteAudio(unittest.TestCase):
    def setUp(self):
        self.state = patch.object(audio, "_streams", collections.OrderedDict())
        self.state.start()

    def tearDown(self):
        self.state.stop()

    def test_audio_belongs_only_to_paired_device_and_preserves_pcm(self):
        audio.open_stream("owner", "request")
        token = tasks.Token()
        token.remote = {"device": "owner", "request": "request"}
        with tasks.scope(tasks.Token(token)):
            self.assertTrue(audio.write(16000, np.array([0., .5, -1.], np.float32)))
        with self.assertRaises(ValueError):
            audio.read("another", "request", wait=0)
        result = audio.read("owner", "request", wait=0)
        self.assertEqual(np.frombuffer(base64.b64decode(result["chunks"][0]["pcm"]), dtype="<i2").tolist(), [0, 16383, -32767])
        audio.finish(token)
        self.assertTrue(audio.read("owner", "request", after=result["after"], wait=0)["done"])

    def test_no_remote_target_does_not_capture_desktop_voice(self):
        with tasks.scope(tasks.Token()):
            self.assertFalse(audio.write(16000, np.zeros(30)))
        self.assertFalse(audio._streams)

    def test_overrun_and_memory_limit_are_explicit(self):
        audio.open_stream("owner", "request")
        token = tasks.Token()
        token.remote = {"device": "owner", "request": "request"}
        with patch.object(audio, "MAX_BYTES", 8), tasks.scope(token):
            with self.assertRaisesRegex(RuntimeError, "длинный"):
                audio.write(16000, np.zeros(10))
        self.assertTrue(audio.read("owner", "request", wait=0)["done"])

    def test_stop_cancels_queued_queries_and_finishes_their_audio(self):
        from shelter_core.actions import ActionRunner
        runner = ActionRunner()
        started = threading.Event()
        ran = []
        def first():
            started.set()
            while True:
                tasks.check()
                time.sleep(.01)
        try:
            runner.submit_lazy(first)
            self.assertTrue(started.wait(2))
            audio.open_stream("owner", "queued")
            runner.submit_lazy(lambda: ran.append(True) or [], context={"device": "owner", "request": "queued"})
            runner.cancel_current()
            result = audio.read("owner", "queued", wait=0)
            self.assertTrue(result["done"])
            self.assertEqual(result["error"], "остановлено")
            self.assertEqual(ran, [])
        finally:
            runner.stop()
