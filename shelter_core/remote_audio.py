"""Bounded, device-scoped PCM delivery for paired clients. No disk recording."""
import base64
import collections
import threading
import time

_streams = collections.OrderedDict()
_changed = threading.Condition()
TTL = 180
MAX_STREAMS = 12
MAX_BYTES = 6 * 1024 * 1024
MAX_CHUNKS = 600


def open_stream(device, request):
    if not device or not isinstance(request, str) or not 1 <= len(request) <= 100:
        raise ValueError("для аудио нужен идентификатор запроса")
    with _changed:
        _expire()
        key = (device, request)
        if key in _streams:
            return
        if len(_streams) >= MAX_STREAMS:
            completed = next((k for k, v in _streams.items() if v["done"]), None)
            if completed is None:
                raise ValueError("слишком много голосовых ответов — дождитесь окончания")
            del _streams[completed]
        _streams[key] = {"chunks": collections.deque(maxlen=MAX_CHUNKS), "next": 1, "bytes": 0,
                         "done": False, "error": "", "updated": time.monotonic()}


def _expire():
    now = time.monotonic()
    for key in list(_streams):
        if now - _streams[key]["updated"] > TTL:
            del _streams[key]


def _target(token=None):
    from shelter_core import tasks
    token = token if token is not None else tasks.current()
    return getattr(tasks._root(token), "remote", None) if token is not None else None


def write(rate, samples):
    target = _target()
    if not target:
        return False
    import numpy as np
    audio = np.asarray(samples)
    if audio.ndim > 1:
        audio = audio[:, 0]
    if np.issubdtype(audio.dtype, np.floating):
        audio = np.clip(audio, -1, 1) * 32767
    elif audio.dtype.itemsize > 2:
        audio = audio / 2 ** (8 * (audio.dtype.itemsize - 2))
    raw = audio.astype("<i2").tobytes()
    key = (target["device"], target["request"])
    with _changed:
        stream = _streams.get(key)
        if stream is None or stream["done"]:
            raise RuntimeError("доставка аудио на телефон уже остановлена")
        if stream["bytes"] + len(raw) > MAX_BYTES:
            stream.update(done=True, error="слишком длинный голосовой ответ", updated=time.monotonic())
            _changed.notify_all()
            raise RuntimeError(stream["error"])
        # Максимум четверть секунды на пакет; Android отдаёт PCM в AudioTrack без
        # открытия отдельного плеера и пауз между WAV-файлами.
        size = max(2, int(rate) // 4 * 2)
        for start in range(0, len(raw), size):
            chunk = raw[start:start + size]
            stream["chunks"].append({"seq": stream["next"], "rate": int(rate), "pcm": base64.b64encode(chunk).decode("ascii")})
            stream["next"] += 1
        stream["bytes"] += len(raw)
        stream["updated"] = time.monotonic()
        _changed.notify_all()
    return True


def finish(token, error=""):
    target = _target(token)
    finish_target(target, error)


def finish_target(target, error=""):
    if not target:
        return
    with _changed:
        stream = _streams.get((target["device"], target["request"]))
        if stream:
            stream.update(done=True, error=str(error)[:250], updated=time.monotonic())
            _changed.notify_all()


def read(device, request, after=0, wait=8):
    after = int(after)
    if after < 0:
        raise ValueError("неверная позиция аудио")
    deadline = time.monotonic() + min(8, max(0, wait))
    with _changed:
        while True:
            _expire()
            stream = _streams.get((device, request))
            if stream is None:
                raise ValueError("аудио этого запроса не найдено или истекло")
            if stream["chunks"] and after < stream["chunks"][0]["seq"] - 1:
                raise ValueError("телефон слишком долго не получал звук; повторите запрос")
            chunks = [c for c in stream["chunks"] if c["seq"] > after][:16]
            if chunks or stream["done"] or time.monotonic() >= deadline:
                cursor = chunks[-1]["seq"] if chunks else after
                return {"chunks": chunks, "done": stream["done"] and cursor >= stream["next"] - 1,
                        "error": stream["error"], "after": cursor}
            _changed.wait(max(.01, deadline - time.monotonic()))
