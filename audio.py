"""Захват с микрофона: кольцевой буфер + очередь блоков для vosk."""

import queue
import threading
import time

import numpy as np
import sounddevice as sd
import native_runtime

BLOCK_SIZE = 1024
BUFFER_SECONDS = 4.0

# Пока установлен — играет TTS или музыка, детекторы должны игнорировать вход,
# иначе ассистент услышит сам себя.
SPEAKING = threading.Event()

# Поднят, пока открыт интерфейс. Только в это время принимаются команды
# без обращения: иначе любое "музыка" в разговоре срабатывало бы.
LISTENING = threading.Event()
THINKING = threading.Event()


class AudioCapture:
    def __init__(self, sample_rate=32000, device=None, queue_blocks=64, detector_enabled=True):
        self.sample_rate = sample_rate
        self.device = device
        self.buffer_len = int(BUFFER_SECONDS * sample_rate)
        self.stream = None

        self._native_ring = native_runtime.Ring(self.buffer_len) if native_runtime.LIBRARY else None
        self._buf = None if self._native_ring else np.zeros(self.buffer_len, dtype=np.float32)
        self.detector_enabled = detector_enabled
        self._write = 0                  # куда писать следующий блок
        self._lock = threading.Lock()

        # Две очереди: у vosk и у детектора свои читатели, общую разобрали бы
        # наперегонки. Переполнилась — дропаем блоки, а не копим.
        self.vosk_queue = queue.Queue(maxsize=queue_blocks)
        self.det_queue = queue.Queue(maxsize=queue_blocks)
        self.dropped = 0
        self.overflows = 0               # сколько раз PortAudio сообщил о потере входа
        self.last_block = time.monotonic()
        self.echo = None                 # echo.Canceller, если включено «пользуюсь колонками»

    def _callback(self, indata, frames, time_info, status):
        # Колбэк не должен блокироваться и не должен делать I/O, поэтому
        # проблемы только считаем — печатает их уже основной поток.
        if status:
            self.overflows += 1
        self.last_block = time.monotonic()

        block = indata[:, 0].copy()
        if self.echo is not None:
            try:
                block = self.echo.process(block)
            except Exception:
                self.echo = None         # сломалось — лучше слышать с эхом, чем не слышать
            frames = len(block)
            if not frames:
                return

        with self._lock:
            if self._native_ring:
                self._native_ring.write(block)
            else:
                tail = block[-self.buffer_len:]
                end = self._write + len(tail)
                head = min(len(tail), self.buffer_len - self._write)
                self._buf[self._write:self._write + head] = tail[:head]
                self._buf[:len(tail)-head] = tail[head:]
                self._write = end % self.buffer_len

        for q in ((self.vosk_queue, self.det_queue) if self.detector_enabled else (self.vosk_queue,)):
            try:
                q.put_nowait(block)
            except queue.Full:
                self.dropped += 1
                try:
                    q.get_nowait()
                    q.put_nowait(block)
                except (queue.Empty, queue.Full):
                    pass

    def start(self):
        # A saved name survives index changes after unplugging USB devices.
        if isinstance(self.device, dict):
            wanted = self.device.get("name")
            matches = [i for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0 and d["name"] == wanted]
            self.device = matches[0] if matches else None
        options = dict(device=self.device, channels=1, dtype="float32", blocksize=BLOCK_SIZE, callback=self._callback)
        try:
            self.stream = sd.InputStream(samplerate=self.sample_rate, **options)
        except sd.PortAudioError:
            native = int(sd.query_devices(self.device, "input")["default_samplerate"])
            if native == self.sample_rate:
                raise
            with self._lock:
                self.sample_rate = native
                self.buffer_len = int(BUFFER_SECONDS * native)
                self._native_ring = native_runtime.Ring(self.buffer_len) if native_runtime.LIBRARY else None
                self._buf = None if self._native_ring else np.zeros(self.buffer_len, np.float32)
                self._write = 0
            self.stream = sd.InputStream(samplerate=native, **options)
        self.stream.start()
        self.last_block = time.monotonic()

    def stop(self):
        if self.echo is not None:
            self.echo.close()
            self.echo = None
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def get_window(self, seconds_before, seconds_after):
        """Окно вокруг события, которое случилось seconds_after секунд назад.

        Заглядывать в будущее буфер не умеет, поэтому вызывать нужно уже после
        того, как эти seconds_after реально прошли: возвращаются последние
        (before + after) секунд записи.
        """
        n = min(int((seconds_before + seconds_after) * self.sample_rate), self.buffer_len)
        if n <= 0:
            return np.zeros(0, dtype=np.float32)

        with self._lock:
            if self._native_ring:
                return self._native_ring.read(n)
            end = self._write
            start = (end - n) % self.buffer_len
            if start < end:
                return self._buf[start:end].copy()
            # окно перехлёстывает через стык кольца
            return np.concatenate((self._buf[start:], self._buf[:end]))
