import contextlib
import threading
import types
import unittest
from unittest.mock import Mock, patch
import numpy as np
import voice
import tasks


class SpeechOutput(unittest.TestCase):
    def scope(self, output, chunks):
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(voice, "_speech_lock", threading.Lock()))
        stack.enter_context(patch.object(voice, "_sessions", set()))
        stack.enter_context(patch.object(voice, "_Output", return_value=output))
        stack.enter_context(patch.object(voice, "synthesize_chunks", side_effect=chunks))
        stack.enter_context(patch.object(voice, "_avatar", return_value=None))
        stack.enter_context(patch.object(voice, "cancel_preparation"))
        stack.enter_context(patch("bus.publish"))
        self.addCleanup(stack.close)
        return stack

    def test_float_wav_is_not_cast_to_silence(self):
        self.assertEqual(voice.pcm16(np.array([0., .5, -1.], np.float32)).tolist(), [0, 16383, -32767])
        self.assertEqual(voice.pcm16(np.array([128, 255, 0], np.uint8)).tolist(), [0, 32511, -32767])
        stereo = np.array([[10000, 5000], [-10000, -5000]], np.int16)
        self.assertTrue(np.allclose(voice.pcm16(stereo), [7500, -7500], atol=1))

    def test_stream_announces_speaking_once_not_for_every_audio_chunk(self):
        output = types.SimpleNamespace(write=Mock(), close=Mock())
        self.scope(output, lambda _: iter([(16000, np.ones(16000, np.int16))]))
        with patch.object(voice, "speaking_flag") as flag:
            voice.speak_stream(["Проверка"])
        self.assertEqual(flag.call_args_list, [unittest.mock.call(True), unittest.mock.call(False)])
        self.assertGreater(output.write.call_count, 4)

    def test_device_error_does_not_strand_the_next_reply(self):
        output = types.SimpleNamespace(write=Mock(side_effect=RuntimeError("device unplugged")), close=Mock(side_effect=RuntimeError("closed")))
        self.scope(output, lambda _: iter([(16000, np.ones(160, np.int16))]))
        root = tasks.Token()
        with tasks.scope(root), patch.object(voice, "speaking_flag"):
            voice.speak_stream(["Первая"])
            self.assertTrue(root.error)
        self.assertFalse(voice._speech_lock.locked())
        self.assertFalse(voice._sessions)
        output.write.side_effect = output.close.side_effect = None
        with patch.object(voice, "speaking_flag"):
            voice.speak_stream(["Вторая"])
        self.assertFalse(voice._speech_lock.locked())

    def test_empty_synthesis_is_an_error_not_a_successful_silent_answer(self):
        self.scope(types.SimpleNamespace(write=Mock(), close=Mock()), lambda _: iter([]))
        token = tasks.Token()
        with tasks.scope(token), patch.object(voice, "speaking_flag"):
            voice.speak_stream(["Не пустой ответ"])
        self.assertIn("пустой звук", token.error)

    def test_sentence_cleanup_error_finishes_the_queue(self):
        class Sentences:
            def __iter__(self):
                return iter(["Ответ"])
            def close(self):
                raise RuntimeError("sentence cleanup failed")
        self.scope(types.SimpleNamespace(write=Mock(), close=Mock()), lambda _: iter([(16000, np.ones(160, np.int16))]))
        root = tasks.Token()
        with tasks.scope(root), patch.object(voice, "speaking_flag"):
            voice.speak_stream(Sentences())
        self.assertIn("sentence cleanup failed", root.error)
        self.assertFalse(voice._speech_lock.locked())
        self.assertFalse(voice._sessions)

    def test_missing_recorded_file_uses_current_voice(self):
        with patch.object(voice, "ENGINE", "files"), patch("personas.active", return_value={"id":"jarvis"}), patch.object(voice, "speak_stream") as speak:
            voice.say("Здравствуйте", file="sounds/does-not-exist.wav")
        speak.assert_called_once_with(["Здравствуйте"])

    def test_capabilities_are_local_and_obey_enabled_tools(self):
        import fastpath
        tool = Mock(side_effect=AssertionError("help must not execute actions"))
        for phrase in ("что ты умеешь", "что ты можешь", "какие у тебя возможности", "умеешь"):
            reply, executed = fastpath.handle(phrase, {"llm":{"enabled":False,"tools":["pc"]}, "persona":{"address":"хозяин"}}, run_tool=tool)
            self.assertIn("окнами", reply)
            self.assertNotIn("сайты", reply)
            self.assertFalse(executed)
