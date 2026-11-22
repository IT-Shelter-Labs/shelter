"""Подавление эха: звук колонок вычитается, голос в микрофоне остаётся."""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import echo  # noqa: E402


class Rates(unittest.TestCase):
    def test_unsupported_rate_is_refused(self):
        if not echo.available():
            self.skipTest("нет livekit/soundcard")
        with self.assertRaises(ValueError):
            echo.Canceller(44100, loopback=False)


@unittest.skipUnless(echo.available(), "нет livekit/soundcard")
class Cancel(unittest.TestCase):
    R = 16000

    def run_scene(self, near):
        rng = np.random.default_rng(0)
        n = self.R * 6
        render = (rng.normal(0, 0.15, n)).astype(np.float32)               # «то, что играет»
        delay = int(0.05 * self.R)
        echo_sig = np.concatenate([np.zeros(delay, np.float32), 0.4 * render[:-delay]])
        mic = echo_sig + near
        c = echo.Canceller(self.R, loopback=False)
        out = []
        for i in range(0, n - 1000, 1000):                               # блоки не кратны 10 мс
            c.render(render[i:i + 1000])
            out.append(c.process(mic[i:i + 1000]))
        return mic, np.concatenate(out)

    def test_echo_is_removed(self):
        n = self.R * 6
        mic, out = self.run_scene(np.zeros(n, np.float32))
        tail = slice(self.R * 3, len(out))
        reduction = 10 * np.log10(np.mean(mic[tail] ** 2) / (np.mean(out[tail] ** 2) + 1e-12))
        self.assertGreater(reduction, 15)

    def test_output_keeps_block_alignment(self):
        c = echo.Canceller(self.R, loopback=False)
        sizes = [len(c.process(np.zeros(1000, np.float32))) for _ in range(5)]
        self.assertEqual(sum(sizes), 4960, "весь звук выходит кадрами по 10 мс")
        self.assertTrue(all(s % 160 == 0 for s in sizes))


if __name__ == "__main__":
    unittest.main()
