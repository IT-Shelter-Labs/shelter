"""Игровой режим и приглушение звука.

busy()   — на переднем плане полноэкранное окно без рамки или программа
           из ui.busy_apps.
duck()   — приглушить остальные программы, пока Джарвис слушает и говорит;
restore() — вернуть громкость. Исходные уровни сохраняются в файл, чтобы
           после аварийного завершения громкость вернулась при следующем запуске.
earcon() — короткий сигнал: «слышу» и «сделано» — вместо фраз во время игры.

Всё — несколько системных вызовов, без фоновых потоков.
"""

import ctypes
import json
import os
import threading
import time

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
DUCK_STATE = os.path.join(ROOT, "logs", "ducked.json")

_lock = threading.Lock()
_ducked = {}          # pid -> исходная громкость
_busy_cache = (0.0, False)


# ---------------------------------------------------------------- занятость

OWN_PROCESSES = {"jarvis.exe", "jarvis-hud.exe"}   # окна Джарвиса (персонаж, HUD)


def _fullscreen_foreground(process=None):
    if os.name != "nt":
        return False
    user32 = ctypes.windll.user32
    from ctypes import wintypes
    hwnd = user32.GetForegroundWindow()
    if not hwnd or hwnd == user32.GetShellWindow():
        return False
    if (process if process is not None else _foreground_process()) in OWN_PROCESSES:
        return False          # своё окно персонажа на весь рабочий стол — не игра
    name = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, name, 64)
    if name.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
        return False
    style = user32.GetWindowLongW(hwnd, -16) & 0xFFFFFFFF
    if style & 0x00C00000 == 0x00C00000 and style & 0x00040000:   # обычное окно с рамкой
        return False
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    monitor = user32.MonitorFromWindow(hwnd, 2)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return False
    m = info.rcMonitor
    return rect.left <= m.left and rect.top <= m.top and rect.right >= m.right and rect.bottom >= m.bottom


def _foreground_process():
    try:
        user32 = ctypes.windll.user32
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
        import psutil
        return psutil.Process(pid.value).name().lower()
    except Exception:
        return ""


def busy(config):
    """Занят ли человек игрой/видео. Кэш на секунду — дёргать можно часто."""
    global _busy_cache
    now = time.monotonic()
    if now - _busy_cache[0] < 1.0:
        return _busy_cache[1]
    result = False
    if os.name == "nt":
        # Windows can keep reporting BUSY while the user is back in a normal
        # window. Use the actual foreground window to decide whether to hide.
        foreground = _foreground_process()
        apps = [str(a).lower() for a in ((config.get("ui") or {}).get("busy_apps") or [])]
        result = foreground not in OWN_PROCESSES and (foreground in apps or _fullscreen_foreground(foreground))
    _busy_cache = (now, result)
    return result


# ------------------------------------------------------------- приглушение

def _sessions():
    from pycaw.pycaw import AudioUtilities
    own = os.getpid()
    for session in AudioUtilities.GetAllSessions():
        if session.Process and session.ProcessId != own and session.Process.name().lower() not in (
                "python.exe", "pythonw.exe", "jarvis-hud.exe"):
            yield session


def duck(level):
    """Приглушить другие программы до level (0..1 от их громкости). Повторный вызов — ничего."""
    if os.name != "nt" or level >= 1.0:
        return
    with _lock:
        if _ducked:
            return
        try:
            for session in _sessions():
                volume = session.SimpleAudioVolume
                current = volume.GetMasterVolume()
                if current > 0.01:
                    _ducked[session.ProcessId] = current
                    volume.SetMasterVolume(current * level, None)
        except Exception as error:
            print(f"[duck] {error}")
        if _ducked:
            _write_state()


def restore():
    """Вернуть громкость, которую убавил duck()."""
    with _lock:
        if not _ducked:
            return
        try:
            for session in _sessions():
                original = _ducked.get(session.ProcessId)
                if original is not None:
                    session.SimpleAudioVolume.SetMasterVolume(original, None)
        except Exception as error:
            print(f"[duck] {error}")
        _ducked.clear()
        _write_state()


def ducked():
    return bool(_ducked)


def _write_state():
    try:
        os.makedirs(os.path.dirname(DUCK_STATE), exist_ok=True)
        if _ducked:
            with open(DUCK_STATE, "w", encoding="utf-8") as file:
                json.dump({str(k): v for k, v in _ducked.items()}, file)
        elif os.path.exists(DUCK_STATE):
            os.remove(DUCK_STATE)
    except OSError:
        pass


def recover():
    """Прошлый запуск умер с приглушённым звуком — вернуть громкость."""
    try:
        with open(DUCK_STATE, encoding="utf-8") as file:
            saved = {int(k): float(v) for k, v in json.load(file).items()}
    except (OSError, ValueError):
        return
    with _lock:
        _ducked.update(saved)
    restore()


# ---------------------------------------------------------------- сигналы

_tones = {}


def _tone(kind, rate=48000):
    if kind not in _tones:
        # Две мягкие ноты: «слышу» — вверх, «сделано» — вниз, «ошибка» — низкая.
        notes = {"wake": (880.0, 1320.0), "done": (1320.0, 990.0), "error": (330.0, 262.0)}[kind]
        parts = []
        for freq in notes:
            t = np.arange(int(rate * 0.07)) / rate
            envelope = np.sin(np.pi * t / t[-1]) ** 2
            parts.append(0.18 * envelope * np.sin(2 * np.pi * freq * t))
        _tones[kind] = np.concatenate(parts).astype(np.float32)
    return _tones[kind]


def earcon(kind="wake"):
    """Сыграть сигнал, не дожидаясь конца (свой поток вывода, не мешает речи)."""
    def play():
        # Отдельный поток вывода: общий sd.play занят фразами голоса и оборвал бы их.
        try:
            import sounddevice as sd
            with sd.OutputStream(samplerate=48000, channels=1, dtype="float32") as stream:
                stream.write(_tone(kind).reshape(-1, 1))
        except Exception as error:
            print(f"[earcon] {error}")
    threading.Thread(target=play, name="earcon", daemon=True).start()
