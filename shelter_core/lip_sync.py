"""Local mouth cues: cached phonetic alignment and bounded, low latency audio fallback.

No text is sent outside the machine. Rhubarb's phonetic recognizer works without
English transcripts. Live fallback estimates vowel colour; it is not an ASR.
"""
from shelter_core.paths import ROOT_PATH

import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading

import numpy as np
from shelter_core import audio_io as wavfile

ROOT = ROOT_PATH
RATE = 50
SHAPES = ("aa", "ih", "ou", "ee", "oh")
_jobs = queue.Queue(maxsize=4)
_pending = set()
_lock = threading.Lock()
_worker = None


def pcm(rate, samples):
    x = np.asarray(samples)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if x.dtype == np.uint8:
        return (x.astype(np.float32)-128)/128
    if np.issubdtype(x.dtype, np.integer):
        x = x.astype(np.float32) / max(abs(np.iinfo(x.dtype).min), np.iinfo(x.dtype).max)
    return np.nan_to_num(x.astype(np.float32)).clip(-1, 1)


def acoustic(rate, samples):
    """Deterministic spectral vowel mixtures with silence and fricative gating."""
    x = pcm(rate, samples)
    step = max(1, round(rate / RATE))
    result = []
    for i in range(0, len(x), step):
        frame = x[max(0, i - step):i + step]
        rms = float(np.sqrt(np.mean(frame * frame))) if len(frame) else 0
        opening = min(.9, max(0., (rms - .006) * 7))
        weights = np.zeros(5)
        if opening > .01 and len(frame) > 16:
            # A spectral envelope avoids following individual pitch harmonics.
            spectrum = abs(np.fft.rfft(frame * np.hanning(len(frame)), n=2048)) ** 2
            hz = np.fft.rfftfreq(2048, 1 / rate)
            bands = np.array([spectrum[(hz >= a) & (hz < b)].sum() for a, b in
                              [(200, 500), (500, 900), (900, 1400), (1400, 2200), (2200, 3200)]])
            bands /= max(float(bands.sum()), 1e-12)
            weights = np.array([bands[1] + .4 * bands[2], bands[4],
                                bands[0] * (1 - bands[3] - bands[4]), bands[3], bands[2] * .7])
            weights = (weights ** 2) / max(float((weights ** 2).sum()), 1e-12)
            # Hiss should not force an open vowel mouth.
            hiss = spectrum[hz > 4000].sum() / max(spectrum.sum(), 1e-12)
            opening *= max(.2, 1 - hiss * 2)
        result.append([round(float(w * opening), 4) for w in weights])
    return result


def _key(rate, x):
    data = (x * 32767).astype('<i2')
    digest = hashlib.sha256(str(rate).encode() + data.tobytes()).hexdigest()
    return data, ROOT / 'models' / 'lip_cache' / (digest + '.json')


def prepare(rate, samples):
    data, path = _key(rate, pcm(rate, samples))
    if not path.exists() and .4 <= len(data)/rate <= 30:
        schedule(rate, data, path)


def frames(rate, samples, prepare=True):
    x = pcm(rate, samples)
    data, path = _key(rate, x)
    try:
        cached = json.loads(path.read_text(encoding='utf8'))
        if cached.get('version') == 1 and cached.get('samples') == len(x):
            return cached['frames'], 'phonetic'
    except (OSError, ValueError):
        pass
    if prepare and .4 <= len(x) / rate <= 30:
        schedule(rate, data, path)
    return acoustic(rate, x), 'acoustic'


def executable():
    name = 'rhubarb.exe' if os.name == 'nt' else 'rhubarb'
    path = ROOT / 'models' / 'rhubarb' / name
    return path if path.is_file() else None


def schedule(rate, data, path):
    global _worker
    if not executable():
        return
    with _lock:
        if path in _pending or _jobs.full():
            return
        _pending.add(path)
        _jobs.put_nowait((rate, data.copy(), path))
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, daemon=True, name='lip-align')
            _worker.start()


def align(rate, data):
    """Offline phonetic analysis; never called on the audio output thread."""
    exe = executable()
    if exe is None:
        raise RuntimeError('Rhubarb не установлен в models/rhubarb')
    with tempfile.TemporaryDirectory(prefix='jarvis-lip-') as directory:
        source = Path(directory) / 'speech.wav'
        wavfile.write(source, rate, data)
        completed = subprocess.run([str(exe), '-r', 'phonetic', '-f', 'json', '--threads', '1', str(source)],
                                   capture_output=True, timeout=60,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if completed.returncode:
            raise RuntimeError('Не удалось разметить артикуляцию')
        cues = json.loads(completed.stdout)['mouthCues']
    mapping = {'A': [0, 0, 0, 0, 0], 'B': [0, .22, 0, 0, 0],
               'C': [.35, 0, 0, .4, 0], 'D': [.85, 0, 0, 0, 0],
               'E': [0, 0, 0, 0, .7], 'F': [0, 0, .7, 0, 0],
               'G': [0, .12, 0, 0, 0], 'H': [.15, .15, 0, 0, 0], 'X': [0]*5}
    result = acoustic(rate, data)
    for cue in cues:
        for i in range(max(0, int(cue['start'] * RATE)), min(len(result), int(np.ceil(cue['end'] * RATE)))):
            # Keep bilabial closures; retain audio silence even inside a recognizer cue.
            result[i] = mapping.get(cue['value'], [0]*5).copy() if any(result[i]) else [0]*5
    return result


def _work():
    while True:
        rate, data, path = _jobs.get()
        try:
            result = align(rate, data)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf8') as f:
                    json.dump({'version': 1, 'samples': len(data), 'frames': result}, f)
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        except Exception as error:
            print('[avatar] артикуляция:', error)
        finally:
            with _lock:
                _pending.discard(path)
            _jobs.task_done()
