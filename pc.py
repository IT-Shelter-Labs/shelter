"""Управление Windows голосом: окна, громкость, настройки, питание, Discord.

Всё — системные вызовы без фоновых потоков. Опасное (выключение,
перезагрузка) делается с отсрочкой в минуту и отменяется фразой «отмени
выключение».
"""

import ctypes
import difflib
import os
import re
import subprocess
import time
from ctypes import wintypes

user32 = ctypes.windll.user32 if os.name == "nt" else None
if user32 is not None:
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetShellWindow.argtypes = []
    user32.GetShellWindow.restype = wintypes.HWND
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# --------------------------------------------------------------- клавиши

VK = {"ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B,
      "enter": 0x0D, "esc": 0x1B, "tab": 0x09, "space": 0x20, "printscreen": 0x2C,
      "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "insert": 0x2D, "delete": 0x2E}
VK.update({"backspace":0x08,"left":0x25,"up":0x26,"right":0x27,"down":0x28})
VK.update({f"f{i}": 0x6F + i for i in range(1, 25)})


def send_keys(combo):
    """«ctrl+shift+f9» — нажать сочетание (для Discord, Game Bar, NVIDIA)."""
    if os.name != "nt":
        from desktop_linux import send_keys as send
        return send(combo)
    keys = []
    for part in combo.lower().replace(" ", "").split("+"):
        if part in VK:
            keys.append(VK[part])
        elif len(part) == 1:
            keys.append(ord(part.upper()))
        else:
            raise ValueError(f"неизвестная клавиша «{part}»")
    events = [_INPUT(type=1, ki=_KEYBDINPUT(wVk=key)) for key in keys]
    events += [_INPUT(type=1, ki=_KEYBDINPUT(wVk=key,dwFlags=2)) for key in reversed(keys)]
    if not _send_input(events):
        # A partial injection must not leave a modifier pressed.
        _send_input([_INPUT(type=1,ki=_KEYBDINPUT(wVk=key,dwFlags=2)) for key in reversed(keys)])
        raise RuntimeError("Система не приняла сочетание клавиш")
    return True


# ------------------------------------------------------------- диктовка

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx",wintypes.LONG),("dy",wintypes.LONG),("mouseData",wintypes.DWORD),
                ("dwFlags",wintypes.DWORD),("time",wintypes.DWORD),("dwExtraInfo",ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


if user32 is not None:
    user32.SendInput.argtypes = [wintypes.UINT,ctypes.POINTER(_INPUT),ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT


def _send_input(events):
    if not events: return True
    array = (_INPUT * len(events))(*events)
    return user32.SendInput(len(events),array,ctypes.sizeof(_INPUT)) == len(events)


def mouse_click(button="left", count=1):
    """Click at the current pointer position; no coordinate guessing."""
    if button not in ("left","right","middle") or type(count) is not int or count not in (1,2):
        raise ValueError("Нужна кнопка left/right/middle и один или два клика")
    if os.name != "nt":
        from desktop_linux import mouse_click as click
        return click(button,count)
    down,up = {"left":(2,4),"right":(8,16),"middle":(32,64)}[button]
    events = [_INPUT(type=0,mi=_MOUSEINPUT(dwFlags=flag)) for _ in range(count) for flag in (down,up)]
    if not _send_input(events):
        _send_input([_INPUT(type=0,mi=_MOUSEINPUT(dwFlags=up))])
        raise RuntimeError("Система не приняла клик мыши")
    return True


def scroll_wheel(steps):
    if type(steps) is not int or not 1 <= abs(steps) <= 20:
        raise ValueError("Прокрутка: от одного до двадцати шагов")
    if os.name != "nt":
        from desktop_linux import scroll_wheel as scroll
        return scroll(steps)
    if not _send_input([_INPUT(type=0,mi=_MOUSEINPUT(mouseData=ctypes.c_uint32(120*steps).value,dwFlags=0x0800))]):
        raise RuntimeError("Система не приняла прокрутку")
    return True


def type_text(text):
    """Напечатать текст в активное окно. Юникод напрямую — раскладка клавиатуры
    не важна; переводы строк — Enter."""
    if os.name != "nt":
        from desktop_linux import type_text as write
        return write(text)
    events = []
    for char in text:
        if char == "\n":
            for flags in (0, 2):
                events.append(_INPUT(type=1, ki=_KEYBDINPUT(wVk=0x0D, dwFlags=flags)))
            continue
        units = char.encode("utf-16-le")
        for i in range(0, len(units), 2):        # символы вне BMP — два кода
            code = int.from_bytes(units[i:i + 2], "little")
            for flags in (0x0004, 0x0004 | 0x0002):   # KEYEVENTF_UNICODE, + KEYUP
                events.append(_INPUT(type=1, ki=_KEYBDINPUT(wScan=code, dwFlags=flags)))
    return _send_input(events)


# ----------------------------------------------------------------- окна

def _windows():
    """Видимые окна верхнего уровня: (hwnd, заголовок, процесс)."""
    if os.name != "nt":
        from desktop_linux import windows
        return windows()
    import psutil
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):    # есть владелец — не главное
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            process = psutil.Process(pid.value).name().lower().removesuffix(".exe")
        except Exception:
            process = ""
        if title.value not in ("Program Manager", "JARVIS", "Settings") and process not in ("jarvis-hud",):
            found.append((hwnd, title.value, process))
        return True
    user32.EnumWindows(callback, 0)
    return found


def find_window(name):
    """Окно по названию программы или заголовку; пусто — активное окно."""
    name = (name or "").strip().lower()
    if not name or name in ("это", "текущее", "активное", "окно", "это окно", "текущее окно"):
        if os.name != "nt":
            from desktop_linux import foreground
            info = foreground()
            return (info["hwnd"], info["title"], info["process"]) if info else None
        hwnd = user32.GetForegroundWindow()
        return (hwnd, "", "") if hwnd else None
    try:
        import tools
        app = tools.find_app(name)
        if app:
            name = app["name"].lower()
    except Exception:
        pass
    windows = _windows()
    for hwnd, title, process in windows:
        if name in process or process in name.replace(" ", "") and process:
            return hwnd, title, process
    for hwnd, title, process in windows:
        if name in title.lower():
            return hwnd, title, process
    best = difflib.get_close_matches(name, [w[2] for w in windows] + [w[1].lower() for w in windows], n=1, cutoff=0.6)
    if best:
        return next(w for w in windows if best[0] in (w[2], w[1].lower()))
    return None


def _focus(hwnd):
    if os.name != "nt":
        from desktop_linux import focus
        return focus(hwnd)
    user32.ShowWindow(hwnd, 9)                       # SW_RESTORE
    # Windows не отдаёт фокус фоновому процессу; нажатие Alt снимает запрет.
    user32.keybd_event(0x12, 0, 0, 0)
    user32.SetForegroundWindow(hwnd)
    user32.keybd_event(0x12, 0, 2, 0)


def window(action, name=""):
    """close | minimize | maximize | focus. Возвращает название окна или None."""
    found = find_window(name)
    if not found:
        return None
    hwnd, title, process = found
    if os.name != "nt":
        from desktop_linux import window as apply
        apply(action, hwnd)
        return process or title or "окно"
    if action == "close":
        user32.PostMessageW(hwnd, 0x0010, 0, 0)         # WM_CLOSE — как крестик, с вопросом о сохранении
    elif action == "minimize":
        user32.ShowWindow(hwnd, 6)
    elif action == "maximize":
        user32.ShowWindow(hwnd, 3)
    elif action == "focus":
        _focus(hwnd)
    return process or title or "окно"


def show_desktop():
    send_keys("win+d")


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def monitors():
    """Мониторы слева направо: [{"index": 1, "primary": bool, "work": (x, y, w, h)}]."""
    if user32 is None:
        from desktop_linux import monitors as screens
        return screens()
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HANDLE, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    def callback(handle, _dc, _rect, _):
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(_MonitorInfo)
        if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            work = info.rcWork
            found.append({"primary": bool(info.dwFlags & 1),
                          "work": (work.left, work.top, work.right - work.left, work.bottom - work.top)})
        return True
    user32.EnumDisplayMonitors(None, None, callback, 0)
    # Основной монитор — первый, остальные слева направо: так же нумерует HUD.
    found.sort(key=lambda m: (not m["primary"], m["work"][0]))
    for index, item in enumerate(found, 1):
        item["index"] = index
    return found


POSITIONS = ("full", "left", "right", "top-left", "top-right", "bottom-left", "bottom-right", "center")


def place_window(name, monitor=1, position="full"):
    """Поставить окно на монитор и в часть экрана.

    -> (название, номер_монитора, заметка). Монитора с таким номером нет —
    окно встаёт на основной, а заметка объясняет почему (а не молча «готово»).
    """
    found = find_window(name)
    if not found:
        return None
    hwnd, title, process = found
    screens = monitors()
    if not screens:
        raise RuntimeError("не удалось получить список мониторов")
    note = ""
    chosen = next((m for m in screens if m["index"] == int(monitor or 1)), None)
    if chosen is None:
        chosen = screens[0]
        note = f"монитора {monitor} сейчас нет — поставил на основной"
    x, y, w, h = chosen["work"]
    position = position if position in POSITIONS else "full"
    half_w, half_h = w // 2, h // 2
    rect = {"full": (x, y, w, h), "left": (x, y, half_w, h), "right": (x + half_w, y, w - half_w, h),
            "top-left": (x, y, half_w, half_h), "top-right": (x + half_w, y, w - half_w, half_h),
            "bottom-left": (x, y + half_h, half_w, h - half_h),
            "bottom-right": (x + half_w, y + half_h, w - half_w, h - half_h),
            "center": (x + w // 6, y + h // 6, w * 2 // 3, h * 2 // 3)}[position]
    if os.name != "nt":
        from desktop_linux import place
        place(hwnd, rect, position == "full")
        return process or title or "окно", chosen["index"], note
    user32.ShowWindow(hwnd, 9)                       # из свёрнутого/развёрнутого — в обычное
    # SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW
    if not user32.SetWindowPos(hwnd, None, *rect, 0x0004 | 0x0010 | 0x0040):
        raise RuntimeError("Windows не дал переместить окно")
    if position == "full":
        user32.ShowWindow(hwnd, 3)
    return process or title or "окно", chosen["index"], note


# -------------------------------------------------------------- громкость

def _endpoint():
    from pycaw.pycaw import AudioUtilities
    speakers = AudioUtilities.GetSpeakers()
    if hasattr(speakers, "EndpointVolume"):
        return speakers.EndpointVolume
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume
    interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return ctypes.cast(interface, ctypes.POINTER(IAudioEndpointVolume))


def get_volume():
    if os.name != "nt":
        result = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], capture_output=True, text=True, timeout=3, check=True)
        return int(re.search(r"(\d+)%", result.stdout)[1])
    return round(_endpoint().GetMasterVolumeLevelScalar() * 100)


def set_volume(percent):
    percent = max(0, min(100, float(percent)))
    if os.name != "nt":
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent:g}%"], timeout=3, check=True)
        return round(percent)
    volume = _endpoint()
    volume.SetMute(0, None)
    volume.SetMasterVolumeLevelScalar(max(0.0, min(1.0, float(percent) / 100)), None)
    return round(float(percent))


def mute(on=True):
    if os.name != "nt":
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if on else "0"], timeout=3, check=True)
        return
    _endpoint().SetMute(1 if on else 0, None)


# ------------------------------------------------------- параметры Windows

SETTINGS = {
    "звук": "sound", "громкост": "sound", "аудио": "sound", "блютуз": "bluetooth", "bluetooth": "bluetooth",
    "дисплей": "display", "экран": "display", "монитор": "display", "яркост": "display",
    "wi-fi": "network-wifi", "wifi": "network-wifi", "вайфай": "network-wifi", "сеть": "network",
    "интернет": "network", "обновлен": "windowsupdate", "приложени": "appsfeatures",
    "программ": "appsfeatures", "мыш": "mousetouchpad", "обо": "personalization-background",
    "фон": "personalization-background", "тем": "themes", "питани": "powersleep",
    "батаре": "batterysaver", "уведомлен": "notifications", "микрофон": "privacy-microphone",
    "камер": "privacy-webcam", "язык": "regionlanguage", "раскладк": "keyboard",
    "клавиатур": "keyboard", "игр": "gaming-gamemode", "ночн": "nightlight", "памят": "storagesense",
    "диск": "storagesense", "принтер": "printers", "дата": "dateandtime", "врем": "dateandtime",
    "по умолчанию": "defaultapps", "автозагруз": "startupapps", "систем": "about",
}


def open_settings(topic):
    """«звук», «блютуз», «обои» -> нужная страница Параметров Windows."""
    topic = (topic or "").lower()
    page = next((page for word, page in SETTINGS.items() if word in topic), "")
    if os.name != "nt":
        import shutil
        program = next((p for p in ("gnome-control-center", "systemsettings") if shutil.which(p)), None)
        if not program:
            raise RuntimeError("Не найдено приложение системных настроек GNOME/KDE")
        subprocess.Popen([program], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "параметры системы"
    os.startfile(f"ms-settings:{page}")
    return page or "главная"


# ------------------------------------------------------------------ питание

def power(action, delay=60):
    """shutdown | restart — через delay секунд (отменяется); lock | sleep — сразу."""
    if os.name != "nt":
        if action in ("shutdown", "restart"):
            subprocess.run(["shutdown", "-r" if action == "restart" else "-h", "+" + str(max(1, (int(delay) + 59) // 60))], timeout=5, check=True)
        elif action == "cancel":
            return subprocess.run(["shutdown", "-c"], timeout=5).returncode == 0
        else:
            command = {"lock": ["loginctl", "lock-session"], "sleep": ["systemctl", "suspend"]}.get(action)
            if not command:
                raise ValueError("Неизвестное действие питания")
            subprocess.run(command, timeout=5, check=True)
        return True
    if action == "lock":
        user32.LockWorkStation()
    elif action == "sleep":
        # SetSuspendState(гибернация=0): обычный сон, а не гибернация.
        ctypes.windll.powrprof.SetSuspendState(0, 1, 0)
    elif action in ("shutdown", "restart"):
        flag = "/s" if action == "shutdown" else "/r"
        subprocess.run(["shutdown", flag, "/t", str(int(max(30, delay))), "/c",
                        "Джарвис: скажите «отмени выключение», если передумали"],
                       creationflags=NO_WINDOW, check=False)
    elif action == "cancel":
        return subprocess.run(["shutdown", "/a"], creationflags=NO_WINDOW).returncode == 0
    return True


# ----------------------------------------------------------- буфер обмена

def clipboard_text():
    """Текст из буфера обмена (то, что скопировали) или пустая строка."""
    if os.name != "nt":
        from desktop_linux import clipboard_text as read
        return read()
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalLock.restype = ctypes.c_void_p
    user32.GetClipboardData.restype = ctypes.c_void_p
    if not user32.OpenClipboard(0):
        return ""
    try:
        handle = user32.GetClipboardData(13)             # CF_UNICODETEXT
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(ctypes.c_void_p(handle))
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(ctypes.c_void_p(handle))
    finally:
        user32.CloseClipboard()


# ---------------------------------------------------------------- скриншот

def screenshot():
    """Win+PrintScreen: Windows сама сохранит снимок в «Изображения\\Снимки экрана»."""
    if os.name != "nt":
        from pathlib import Path
        import datetime
        import screen
        width, height, pixels, _ = screen.capture()
        folder = Path.home() / "Pictures" / "Jarvis"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".png")
        path.write_bytes(screen.png(width, height, pixels, max_side=4096))
        return str(path)
    send_keys("win+printscreen")
    return os.path.join(os.path.expanduser("~"), "Pictures", "Screenshots")


# ---------------------------------------------------------- состояние ПК

def system_status():
    """Загрузка и температуры одной фразой."""
    import psutil
    parts = [f"процессор загружен на {psutil.cpu_percent(interval=0.3):.0f}%",
             f"память — {psutil.virtual_memory().percent:.0f}%"]
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3,
            creationflags=NO_WINDOW).stdout.strip().splitlines()
        if out:
            name, temp, load, used, total = [p.strip() for p in out[0].split(",")]
            parts.append(f"видеокарта {load}%, {temp} градусов, видеопамять {int(used) / 1024:.1f} "
                         f"из {int(total) / 1024:.0f} гигабайт")
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    disk = psutil.disk_usage(os.path.splitdrive(os.getcwd())[0] + "\\")
    parts.append(f"на диске свободно {disk.free / 2 ** 30:.0f} гигабайт")
    return "Сэр, " + ", ".join(parts) + "."


# -------------------------------------------------------------- Discord

def discord(action, config):
    """mute | deafen — горячие клавиши Discord (их один раз задают в Discord,
    см. README); по умолчанию Ctrl+Shift+F9 и Ctrl+Shift+F10."""
    cfg = config.get("discord") or {}
    combo = cfg.get("mute" if action == "mute" else "deafen",
                    "ctrl+shift+f9" if action == "mute" else "ctrl+shift+f10")
    send_keys(combo)
    return combo


# ------------------------------------------------------------- разбор тега

ACTION_WORDS = [
    ("cancel", ("отмен", "cancel")),
    ("shutdown", ("выключи комп", "выключить комп", "выключи пк", "shutdown", "выключение", "заверши работу")),
    ("restart", ("перезагр", "перезапусти комп", "restart")), ("lock", ("заблок", "lock")), ("sleep", ("сон", "спящ", "sleep")),
    # Раньше «сверн»/«разверн»: «выйди из полноэкранного», «на весь экран» — про режим видео, не про окно.
    ("fullscreen", ("полноэкран", "весь экран", "полный экран", "fullscreen")),
    ("close", ("закр", "close")), ("minimize", ("сверн", "minimize")), ("maximize", ("разверн", "maximize")),
    ("focus", ("переключ", "focus", "покажи", "перейди")), ("desktop", ("рабочий стол", "desktop")),
    ("settings", ("настройк", "параметр", "settings")), ("volume", ("громкость", "volume")),
    ("unmute", ("включи звук", "unmute")), ("mute", ("выключи звук", "без звука", "mute")),
    ("screenshot", ("скрин", "снимок", "screenshot")), ("status", ("состояни", "статус", "status", "температур")),
    ("discord_mute", ("discord_mute", "микрофон")), ("discord_deafen", ("discord_deafen", "наушник", "звук в дискорд")),
]


def parse(action):
    action = (action or "").strip().lower()
    names = [name for name, _ in ACTION_WORDS]
    if action in names:                    # точное имя важнее: discord_mute — не mute
        return action
    for name, words in ACTION_WORDS:
        if any(w in action for w in words):
            return name
    return action
