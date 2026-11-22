"""Лента событий ассистента: что услышал, что ответил, что сделал.

Её показывает приложение «Джарвис» (через control.py). Последние события
хранятся в памяти, чтобы только что открытое окно сразу видело разговор.
"""

import collections
import queue
import threading
import time

_history = collections.deque(maxlen=120)
_subscribers = []
_lock = threading.Lock()


# Частые служебные события (губы персонажа) не копятся в истории для новых окон.
TRANSIENT = {"mouth", "avatar", "avatar_motion", "avatar_beat", "avatar_move"}


def publish(kind, **data):
    if kind == "reply" and isinstance(data.get("text"), str):
        from shelter_core import personas
        data["text"] = personas.rewrite(data["text"])        # «сэр» -> обращение персонажа
    event = {"kind": kind, "time": time.time(), **data}
    with _lock:
        if kind not in TRANSIENT:
            _history.append(event)
        for subscriber in list(_subscribers):
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                pass
    return event


def subscribe():
    """Очередь новых событий и копия недавних."""
    subscriber = queue.Queue(maxsize=500)
    with _lock:
        _subscribers.append(subscriber)
        return subscriber, list(_history)


def unsubscribe(subscriber):
    with _lock:
        if subscriber in _subscribers:
            _subscribers.remove(subscriber)
