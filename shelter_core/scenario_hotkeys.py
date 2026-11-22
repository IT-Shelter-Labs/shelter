"""Windows scenario shortcuts. Dedicated message thread, no keyboard hook/recording."""
import os
import re
import threading


def parse(combo):
    mods, key = 0, None
    for part in str(combo).lower().replace(" ", "").split("+"):
        if part in ("ctrl", "control", "alt", "shift", "win", "super", "meta"):
            mods |= {"ctrl": 2, "control": 2, "alt": 1, "shift": 4, "win": 8, "super": 8, "meta": 8}[part]
        else:
            if key is not None:
                raise ValueError("В сочетании должна быть одна основная клавиша")
            if re.fullmatch(r"[a-z0-9]", part): key = ord(part.upper())
            elif part in ("space", "пробел"): key = 32
            elif re.fullmatch(r"f(?:[1-9]|1\d|2[0-4])", part): key = 0x6f + int(part[1:])
            else: raise ValueError("Неизвестная клавиша. Пример: Ctrl+Alt+F9")
    if key is None or not mods and not 0x70 <= key <= 0x87:
        raise ValueError("Без модификатора можно использовать только F1–F24")
    return mods, key


class Hotkeys:
    def __init__(self, callback):
        self.callback = callback
        self.lock = threading.Lock()
        self.wanted = ()
        self.stopping = threading.Event()
        self.thread = None
        self.armed = False

    def update(self, pairs):
        with self.lock:
            self.wanted = tuple(pairs)
        if self.armed and self.wanted:
            self.start()

    def start(self):
        self.armed = True
        if os.name != "nt": return
        if not self.wanted: return
        if self.thread and self.thread.is_alive(): return
        self.stopping.clear()
        self.thread = threading.Thread(target=self._loop, name="scenario-hotkeys", daemon=True)
        self.thread.start()

    def stop(self):
        self.armed = False
        self.stopping.set()
        if self.thread: self.thread.join(timeout=1)

    def _loop(self):
        import ctypes
        from ctypes import wintypes
        api = ctypes.windll.user32
        api.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        api.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        active, previous = {}, None
        message = wintypes.MSG()
        try:
            while not self.stopping.wait(.04):
                with self.lock: wanted = self.wanted
                if wanted != previous:
                    for code in active: api.UnregisterHotKey(None, code)
                    active = {}; previous = wanted
                    parsed, counts = [], {}
                    for tag, combo in wanted[:255]:
                        try:
                            shortcut = parse(combo)
                            parsed.append((tag, combo, shortcut)); counts[shortcut] = counts.get(shortcut, 0) + 1
                        except ValueError as error: self.callback(tag, str(error))
                    for i, (tag, combo, shortcut) in enumerate(parsed):
                        code = 0x5000 + i
                        if counts[shortcut] > 1:
                            self.callback(tag, f"{combo}: сочетание указано в нескольких сценариях")
                        elif api.RegisterHotKey(None, code, shortcut[0] | 0x4000, shortcut[1]):
                            active[code] = tag
                        else:
                            self.callback(tag, f"{combo}: занято другим приложением или системной командой")
                while api.PeekMessageW(ctypes.byref(message), None, 0x0312, 0x0312, 1):
                    tag = active.get(int(message.wParam))
                    if tag: self.callback(tag, "")
        finally:
            for code in active: api.UnregisterHotKey(None, code)
