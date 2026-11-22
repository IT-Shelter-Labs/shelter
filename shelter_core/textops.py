"""Быстрые действия с текстом: исправь, переведи, сократи, объясни, подготовь ответ, прочитай.

Источник всегда явный: выделение в окне (Ctrl+C от имени человека), буфер
обмена или текст, вставленный в окне Джарвиса. Если выделение взять не
удалось, другой текст молча не подставляется: возвращается понятная ошибка.

Результат сначала показывается. Замена — отдельным действием: Джарвис
возвращает фокус окну-источнику, проверяет, что это то же окно, и печатает
результат поверх выделения. Если окно закрыто или сменилось, ничего не
вставляет. Прежний буфер обмена восстанавливается после захвата выделения,
исходный текст хранится до следующего действия («вернуть исходный»).
"""

import ctypes
import os
import secrets
import threading
import time

from shelter_core import bus
from shelter_core import tasks

OPS = {
    "fix": ("Исправить", "Исправь орфографию, пунктуацию и грамматику. Сохрани смысл, стиль и язык. Верни только исправленный текст."),
    "translate": ("Перевести", "Переведи текст: русский — на английский, любой другой язык — на русский. Верни только перевод."),
    "shorten": ("Сократить", "Сократи текст примерно вдвое, сохранив главное. Верни только сокращённый текст."),
    "explain": ("Объяснить", "Объясни простыми словами, о чём этот текст и что в нём важно. 3–6 предложений по-русски."),
    "reply": ("Подготовить ответ", "Это сообщение, на которое нужно ответить. Напиши вежливый короткий ответ от первого лица на языке сообщения. Верни только текст ответа."),
    "read": ("Прочитать вслух", ""),
}
LIMIT = 12000
STATE = {"id": "", "source": "", "window": None, "text": "", "result": "", "op": "", "status": "empty", "error": "",
         "model": "", "local": True}
_lock = threading.Lock()
_token = None


def _publish():
    bus.publish("textops", **{k: v for k, v in snapshot().items() if k in ("id", "status", "op", "source", "error")})


def snapshot():
    with _lock:
        data = dict(STATE)
    window = data.pop("window", None)
    data["window_title"] = (window or {}).get("title", "")
    data["ops"] = {k: v[0] for k, v in OPS.items()}
    return data


# ------------------------------------------------------------ буфер обмена

def _set_clipboard(text):
    if os.name != "nt":
        from shelter_core.desktop_linux import set_clipboard
        return set_clipboard(text)
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    data = (text or "").encode("utf-16-le") + b"\0\0"
    for _ in range(10):
        if user32.OpenClipboard(0):
            break
        time.sleep(0.05)
    else:
        return False
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(0x0002, len(data))          # GMEM_MOVEABLE
        pointer = kernel32.GlobalLock(handle)
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        return bool(user32.SetClipboardData(13, handle))           # CF_UNICODETEXT
    finally:
        user32.CloseClipboard()


def _sequence():
    return ctypes.windll.user32.GetClipboardSequenceNumber() if os.name == "nt" else 0


def _foreground():
    if os.name != "nt":
        from shelter_core.desktop_linux import foreground
        return foreground()
    from shelter_core import pc
    hwnd = pc.user32.GetForegroundWindow()
    if not hwnd:
        return None
    for handle, title, process in pc._windows():
        if handle == hwnd:
            return {"hwnd": int(hwnd), "title": title, "process": process}
    return {"hwnd": int(hwnd), "title": "", "process": ""}


def _start(source, text, window=None):
    text = (text or "").strip()
    if not text:
        raise ValueError("пустой текст")
    if len(text) > LIMIT:
        raise ValueError(f"текст длиннее {LIMIT} знаков — выделите часть")
    with _lock:
        STATE.update(id="t_" + secrets.token_hex(3), source=source, window=window, text=text, result="", op="",
                     status="captured", error="")
    _publish()
    return snapshot()


def capture_selection():
    """Ctrl+C в активном окне. Не вышло — ошибка, а не чужой текст из буфера."""
    if os.name != "nt":
        from shelter_core.desktop_linux import capture_selection as capture
        text, window = capture()
        return _start("selection", text, window)
    from shelter_core import pc
    window = _foreground()
    if window is None or window.get("process") in ("jarvis", "jarvis-hud"):
        raise RuntimeError("не вижу окно с выделенным текстом — переключитесь в нужную программу")
    previous = pc.clipboard_text()
    before = _sequence()
    pc.send_keys("ctrl+c")
    deadline = time.monotonic() + 0.8
    while _sequence() == before and time.monotonic() < deadline:
        time.sleep(0.03)
    if _sequence() == before:
        raise RuntimeError("не удалось взять выделение: программа не скопировала текст. Выделите текст и повторите или выберите «Буфер обмена»")
    time.sleep(0.05)
    text = pc.clipboard_text()
    _set_clipboard(previous)                        # восстановить и пустой буфер
    if not text.strip():
        raise RuntimeError("выделение пустое или это не текст")
    return _start("selection", text, window)


def from_clipboard():
    from shelter_core import pc
    return _start("clipboard", pc.clipboard_text())


def manual(text):
    return _start("manual", text)


# ---------------------------------------------------------------- модель

def _route(config):
    from shelter_core import llm_connections
    cfg = llm_connections.resolve(config.get("llm") or {}, "task")
    url = str(cfg.get("url", "") or "http://127.0.0.1:11434")
    local = any(h in url for h in ("127.0.0.1", "localhost", "[::1]"))      # иначе текст уйдёт на внешний сервер
    return cfg, local


def run(op, config, generate=None):
    """Выполнить действие над захваченным текстом. generate(cfg, system, text) — для тестов."""
    global _token
    if op not in OPS:
        raise ValueError("неизвестное действие")
    with _lock:
        text = STATE["text"]
    if not text:
        raise ValueError("сначала возьмите текст: выделение, буфер обмена или вставьте вручную")
    if op == "read":
        from shelter_core import voice
        threading.Thread(target=voice.speak_stream, args=([text[:3000]],), daemon=True).start()
        with _lock:
            STATE.update(op=op, status="done", result="")
        _publish()
        return snapshot()
    cfg, local = _route(config)
    with _lock:
        STATE.update(op=op, status="running", error="", model=str(cfg.get("model", "")), local=local)
    _publish()
    token = tasks.Token(timeout=120)
    _token = token
    try:
        with tasks.scope(token):
            result = (generate or _generate)(cfg, OPS[op][1], text)
        with _lock:
            STATE.update(result=result.strip(), status="ready")
    except tasks.Cancelled:
        with _lock:
            STATE.update(status="cancelled", error="остановлено")
    except Exception as error:
        with _lock:
            STATE.update(status="failed", error=f"модель не ответила: {error}")
    finally:
        _token = None
    _publish()
    return snapshot()


def _generate(cfg, system, text):
    from shelter_core import llm
    cfg = {**cfg, "max_tokens": max(400, min(4000, len(text) // 2 + 300)), "temperature": 0.3}
    messages = [{"role": "system", "content": system}, {"role": "user", "content": text}]
    return "".join(llm._provider(cfg)(messages, cfg, 120))


def cancel():
    if _token is not None:
        _token.cancel()


def apply():
    """Заменить выделение в окне-источнике результатом. Только если это то же окно."""
    from shelter_core import pc
    with _lock:
        window, result, source = STATE["window"], STATE["result"], STATE["source"]
    if not result:
        raise RuntimeError("нечего вставлять — сначала выполните действие")
    if source != "selection" or not window:
        raise RuntimeError("текст взят не из выделения — скопируйте результат и вставьте сами")
    if os.name != "nt":
        from shelter_core.desktop_linux import apply_text
        apply_text(window, result)
        with _lock:
            STATE["status"] = "applied"
        _publish()
        return snapshot()
    hwnd = window["hwnd"]
    if not pc.user32.IsWindow(hwnd):
        raise RuntimeError("окно-источник закрыто — не вставляю в другое место")
    pc._focus(hwnd)
    time.sleep(0.25)
    if int(pc.user32.GetForegroundWindow() or 0) != hwnd:
        raise RuntimeError("не удалось вернуть фокус окну-источнику — не вставляю в неожиданное поле")
    pc.type_text(result)
    with _lock:
        STATE["status"] = "applied"
    _publish()
    return snapshot()


def copy_result():
    with _lock:
        result = STATE["result"]
    if not result or not _set_clipboard(result):
        raise RuntimeError("не удалось скопировать")
    return snapshot()


VOICE = {"исправь": "fix", "переведи": "translate", "сократи": "shorten", "объясни": "explain",
         "подготовь ответ": "reply", "ответь на это": "reply", "прочитай": "read"}


def voice_command(op, config):
    """«Джарвис, переведи выделенное»: захват → действие → результат в окне Джарвиса."""
    try:
        capture_selection()
    except RuntimeError as error:
        return "fail", str(error).capitalize() + "."
    state = run(op, config)
    if state["status"] == "failed":
        return "fail", state["error"].capitalize() + "."
    if op == "read":
        return "done", ""
    bus.publish("open", page="home", card="text")
    return "done", ("Готово. Результат в окне Джарвиса: скажите «вставь», чтобы заменить выделенное."
                    if op in ("fix", "translate", "shorten", "reply") else state["result"][:400])
