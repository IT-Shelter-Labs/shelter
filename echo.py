"""Подавление эха для колонок (по желанию: audio.echo_cancel).

С колонками микрофон слышит всё, что играет компьютер: друзей в Discord,
YouTube, игру и ответы самого Джарвиса — и чужое «Джарвис» из колонок будит
его. Здесь звук, уходящий в колонки по умолчанию (WASAPI loopback, пакет
soundcard), вычитается из микрофона модулем обработки звука WebRTC (AEC3,
пакет livekit) — тот же, что в браузерных звонках.

На проверке (игра + друг в колонках, задержка 90 мс): эхо тише на 24–28 дБ,
голос друга распознаватель больше не слышит, команда хозяина остаётся;
нагрузка — меньше 1 % ядра. С наушниками не нужно.
"""

import threading
import time
import warnings

import numpy as np

RATES = (16000, 32000, 48000)       # частоты, с которыми работает WebRTC APM


def available():
    try:
        import soundcard  # noqa: F401
        from livekit import rtc  # noqa: F401
    except Exception:
        return False
    return True


class Canceller:
    """Чистит блоки микрофона от звука колонок. process() зовётся из колбэка захвата."""

    def __init__(self, rate, loopback=True):
        from livekit import rtc

        if rate not in RATES:
            raise ValueError(f"частота микрофона {rate} Гц не подходит (нужна {', '.join(map(str, RATES))})")
        self._rtc = rtc
        self.rate = rate
        self.frame = rate // 100                    # APM работает кадрами по 10 мс
        # Без шумодава: он портит начало слов, и «Джарвис» узнаётся хуже, а эхо
        # (голос друга из колонок) гасится и без него.
        self._apm = rtc.AudioProcessingModule(echo_cancellation=True, noise_suppression=False,
                                              high_pass_filter=True)
        self._lock = threading.Lock()
        self._pending = np.zeros(0, dtype=np.float32)
        self._render_pending = np.zeros(0, dtype=np.float32)
        self._stop = threading.Event()
        self.speaker = None                         # откуда берём «то, что играет»
        self.error = None
        self.render_frames = 0
        if loopback:
            threading.Thread(target=self._loopback, name="echo-loopback", daemon=True).start()

    def _frame(self, samples):
        frame = self._rtc.AudioFrame.create(self.rate, 1, self.frame)
        np.frombuffer(frame.data, dtype=np.int16)[:] = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
        return frame

    def render(self, samples):
        """Опорный сигнал: то, что сейчас звучит из колонок (моно, self.rate)."""
        data = np.concatenate((self._render_pending, samples)) if len(self._render_pending) else samples
        usable = len(data) - len(data) % self.frame
        self._render_pending = data[usable:].copy()
        for i in range(0, usable, self.frame):
            frame = self._frame(data[i:i + self.frame])
            with self._lock:
                self._apm.process_reverse_stream(frame)
            self.render_frames += 1

    def process(self, block):
        """Блок микрофона -> очищенный звук. Хвост короче 10 мс ждёт следующего блока."""
        data = np.concatenate((self._pending, block)) if len(self._pending) else block
        usable = len(data) - len(data) % self.frame
        self._pending = data[usable:].copy()
        if not usable:
            return np.zeros(0, dtype=np.float32)
        out = np.empty(usable, dtype=np.float32)
        for i in range(0, usable, self.frame):
            frame = self._frame(data[i:i + self.frame])
            with self._lock:
                self._apm.process_stream(frame)
            out[i:i + self.frame] = np.frombuffer(frame.data, dtype=np.int16) / 32768.0
        return out

    def _loopback(self):
        """Пишем колонки по умолчанию; сменили устройство — переподключаемся."""
        warnings.filterwarnings("ignore", module="soundcard")   # «data discontinuity» в тишине
        import soundcard as sc

        while not self._stop.is_set():
            try:
                speaker = sc.default_speaker()
                loop = sc.get_microphone(str(speaker.id), include_loopback=True)
                self.speaker, self.error = speaker.name, None
                checked = time.monotonic()
                with loop.recorder(samplerate=self.rate, blocksize=self.frame) as recorder:
                    while not self._stop.is_set():
                        data = recorder.record(numframes=self.frame * 5)
                        if data.ndim > 1:
                            data = data.mean(axis=1)
                        self.render(data.astype(np.float32))
                        if time.monotonic() - checked > 3:
                            checked = time.monotonic()
                            if sc.default_speaker().id != speaker.id:
                                break                               # пользователь сменил колонки
            except Exception as error:
                self.error = str(error)[:200]
                self._stop.wait(3)

    def close(self):
        self._stop.set()
