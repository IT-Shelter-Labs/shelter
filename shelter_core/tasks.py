"""Cooperative cancellation shared by actions, LLM, tools and speech workers."""
import contextlib
import threading
import time

_local = threading.local()


class Cancelled(Exception):
    pass


def continue_dialogue():
    token = current()
    if token:
        _root(token).continue_dialogue = True


def end_dialogue():
    """«Исчезни»: после ответа окно закрыть, а не показать снова."""
    token = current()
    if token:
        _root(token).end_dialogue = True


def dialogue_ends():
    token = current()
    return bool(token and getattr(_root(token), "end_dialogue", False))


def dialogue_continues():
    token = current()
    return bool(token and getattr(_root(token), "continue_dialogue", False))


class Token:
    def __init__(self, parent=None, run_id=None, session_id=None, timeout=180):
        self.parent = parent
        self.run_id = run_id or (parent.run_id if parent else None)
        self.session_id = session_id or (parent.session_id if parent else None)
        self.deadline = parent.deadline if parent else time.monotonic() + timeout
        self.reply = ""
        self.error = ""
        self.event = threading.Event()
        self._lock = threading.Lock()
        self._closers = []
        if parent:
            parent.register(self.cancel)

    def is_set(self):
        return self.event.is_set() or bool(self.parent and self.parent.is_set())

    def check(self):
        if time.monotonic() >= self.deadline:
            _root(self).error = "Время выполнения задачи истекло"
            self.cancel()
        if self.is_set():
            raise Cancelled()

    def cancel(self):
        self.event.set()
        with self._lock:
            closers, self._closers = self._closers, []
        # Closing a socket while another thread reads can itself block.
        for close in closers:
            threading.Thread(target=self._close, args=(close,), daemon=True).start()

    @staticmethod
    def _close(close):
        try:
            close()
        except Exception:
            pass

    def register(self, close):
        with self._lock:
            self._closers.append(close)
        if self.is_set():
            self.cancel()

    def unregister(self, close):
        with self._lock:
            if close in self._closers:
                self._closers.remove(close)


def current():
    return getattr(_local, "token", None)


def _root(token):
    while token.parent:
        token = token.parent
    return token


def _set_result(field, text):
    token = current()
    if token:
        setattr(_root(token), field, str(text))


def check():
    token = current()
    if token:
        token.check()


def reply(text):
    _set_result("reply", text)


def fail(error):
    _set_result("error", error)


def step(name, argument, outcome, result):
    from shelter_core import bus
    bus.publish("tool_result", name=name, ok=outcome == "done", outcome=outcome)
    token = current()
    if token and token.run_id:
        from shelter_core import assistant_store as store
        store.add_step(token.run_id, name, argument, outcome, result)
    if outcome == "fail":
        fail(result)


def run(function):
    """Wait cancellably for a blocking helper; it inherits execution checks."""
    token = current()
    if token is None:
        return function()
    ready = threading.Event()
    box = {}
    def worker():
        with scope(token):
            try:
                token.check()
                box["value"] = function()
            except Exception as error:
                box["error"] = error
            finally:
                ready.set()
    threading.Thread(target=worker, name="task-helper", daemon=True).start()
    while not ready.wait(0.05):
        token.check()
    token.check()
    if "error" in box:
        raise box["error"]
    return box["value"]


@contextlib.contextmanager
def scope(token):
    previous = current()
    _local.token = token
    try:
        yield token
    finally:
        _local.token = previous
