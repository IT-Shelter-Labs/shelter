"""Linux desktop adapters. X11 automation is never advertised for Wayland.

All external programs receive argument arrays, never shell text. Missing
permissions/tools are surfaced to the caller instead of reporting success.
"""
from shelter_core.paths import ROOT_PATH

import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path


def wayland():
    return os.environ.get("XDG_SESSION_TYPE") == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))


def capabilities():
    x11 = bool(os.environ.get("DISPLAY")) and not wayland()
    return {"session": "wayland" if wayland() else "x11" if x11 else "headless",
            "windows": x11 and bool(shutil.which("wmctrl")) and bool(shutil.which("xdotool")),
            "keys": x11 and bool(shutil.which("xdotool")),
            "clipboard": bool(shutil.which("wl-paste") and shutil.which("wl-copy")) if wayland() else x11 and bool(shutil.which("xclip")),
            "monitors": x11 and bool(shutil.which("xrandr")),
            "screenshot": bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")) if wayland() else x11,
            "volume": bool(shutil.which("pactl"))}


def _require(feature):
    if not capabilities().get(feature):
        if wayland() and feature in ("keys", "windows", "monitors"):
            raise RuntimeError("Wayland ограничивает управление чужими окнами и вводом. Используйте сеанс X11 для этой команды.")
        tools = {"windows": "wmctrl и xdotool", "keys": "xdotool", "clipboard": "wl-clipboard (Wayland) или xclip (X11)", "monitors": "xrandr"}
        raise RuntimeError(f"В этом сеансе недоступна функция «{feature}». Нужны графический сеанс и {tools.get(feature, 'соответствующая системная служба')}.")


def _run(*args, data=None, timeout=4):
    try:
        result = subprocess.run(list(map(str, args)), input=data, capture_output=True, timeout=timeout, check=True)
        return result.stdout.decode("utf-8", "replace")
    except FileNotFoundError as exc:
        raise RuntimeError(f"Не установлена программа {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"{args[0]}: {exc.stderr.decode('utf-8', 'replace').strip()[:200] or 'действие отклонено'}") from exc


def windows():
    _require("windows")
    found = []
    # id desktop pid x y w h WM_CLASS host title
    for line in _run("wmctrl", "-lpGx").splitlines():
        values = line.split(None, 9)
        if len(values) != 10:
            continue
        try:
            handle, pid = int(values[0], 16), int(values[2])
        except ValueError:
            continue
        process = values[7].split(".")[-1].lower()
        try:
            process = Path(f"/proc/{pid}/comm").read_text().strip().lower() or process
        except OSError:
            pass
        if process not in ("jarvis", "jarvis-hud"):
            found.append((handle, values[9], process))
    return found


def foreground():
    _require("windows")
    try:
        handle = int(_run("xdotool", "getactivewindow").strip())
    except ValueError:
        return None
    found = next((w for w in windows() if w[0] == handle), None)
    return {"hwnd": handle, "title": found[1] if found else "", "process": found[2] if found else ""}


def focus(handle):
    _require("windows")
    _run("wmctrl", "-ia", hex(int(handle)))


def window(action, handle):
    _require("windows")
    handle = hex(int(handle))
    if action == "close":
        _run("wmctrl", "-ic", handle)
    elif action == "minimize":
        _run("xdotool", "windowminimize", handle)
    elif action == "maximize":
        _run("wmctrl", "-ir", handle, "-b", "add,maximized_vert,maximized_horz")
    elif action == "focus":
        focus(int(handle, 16))
    else:
        raise ValueError("Неизвестное действие с окном")


def monitors():
    _require("monitors")
    result = []
    pattern = re.compile(r"\s\d+:\s+([+*]*)(\S+)\s+(\d+)(?:/\d+)?x(\d+)(?:/\d+)?([+-]\d+)([+-]\d+)")
    for line in _run("xrandr", "--listactivemonitors").splitlines():
        match = pattern.search(line)
        if match:
            flags, name, width, height, x, y = match.groups()
            result.append({"primary": "*" in flags, "name": name, "work": (int(x), int(y), int(width), int(height))})
    result.sort(key=lambda m: (not m["primary"], m["work"][0]))
    for i, item in enumerate(result, 1):
        item["index"] = i
    return result


def place(handle, rect, maximize=False):
    _require("windows")
    window_id = hex(int(handle))
    _run("wmctrl", "-ir", window_id, "-b", "remove,maximized_vert,maximized_horz")
    _run("wmctrl", "-ir", window_id, "-e", "0," + ",".join(str(int(n)) for n in rect))
    if maximize:
        window("maximize", handle)


def send_keys(combo):
    _require("keys")
    aliases = {"win": "super", "control": "ctrl", "esc": "Escape", "enter": "Return", "printscreen": "Print",
               "pageup": "Prior", "pagedown": "Next", "delete": "Delete", "space": "space", "tab": "Tab",
               "home": "Home", "end": "End", "insert": "Insert"}
    aliases.update({"backspace":"BackSpace","left":"Left","right":"Right","up":"Up","down":"Down"})
    parts = combo.lower().replace(" ", "").split("+")
    if not parts or any(not re.fullmatch(r"[a-z0-9]+", p) for p in parts):
        raise ValueError("Некорректное сочетание клавиш")
    _run("xdotool", "key", "--clearmodifiers", "+".join(aliases.get(p, p.upper() if re.fullmatch(r"f\d+", p) else p) for p in parts))


def clipboard_text():
    _require("clipboard")
    if wayland():
        return _run("wl-paste", "--no-newline", "--type", "text")
    return _run("xclip", "-selection", "clipboard", "-out", "-target", "UTF8_STRING")


def set_clipboard(text):
    _require("clipboard")
    args = ["wl-copy", "--type", "text/plain;charset=utf-8"] if wayland() else ["xclip", "-selection", "clipboard", "-in"]
    # Clipboard owners fork: do not capture inherited stdout pipes.
    subprocess.run(args, input=str(text).encode("utf-8"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=True)
    return True


def type_text(text):
    _require("keys")
    # stdin avoids command line limits and keeps dictated text out of process lists.
    if text:
        _run("xdotool", "type", "--clearmodifiers", "--delay", "0", "--file", "-", data=str(text).encode("utf-8"), timeout=15)
    return True


def mouse_click(button, count=1):
    _require("keys")
    number = {"left":"1","middle":"2","right":"3"}.get(button)
    if not number or type(count) is not int or count not in (1,2): raise ValueError("Некорректный клик")
    _run("xdotool","click","--clearmodifiers","--repeat",str(count),"--delay","90",number)
    return True


def scroll_wheel(steps):
    _require("keys")
    if type(steps) is not int or not 1 <= abs(steps) <= 20: raise ValueError("Некорректная прокрутка")
    _run("xdotool","click","--clearmodifiers","--repeat",str(abs(steps)),"--delay","35","4" if steps>0 else "5")
    return True


def capture_selection():
    _require("windows")
    _require("clipboard")
    source = foreground()
    if not source or source.get("process") in ("jarvis", "jarvis-hud"):
        raise RuntimeError("Переключитесь в окно с выделенным текстом")
    try:
        previous = clipboard_text()
    except RuntimeError as exc:
        raise RuntimeError("Буфер не содержит текста. Сначала сохраните его содержимое или вставьте текст вручную.") from exc
    marker = "jarvis-selection-" + uuid.uuid4().hex
    set_clipboard(marker)
    captured = marker
    try:
        send_keys("ctrl+c")
        deadline = time.monotonic() + .9
        while time.monotonic() < deadline:
            captured = clipboard_text()
            if captured != marker:
                break
            time.sleep(.04)
    finally:
        if clipboard_text() == captured:
            set_clipboard(previous)
    if captured == marker or not captured.strip():
        raise RuntimeError("Программа не скопировала выделение. Выделите текст и повторите.")
    return captured, source


def apply_text(source, text):
    _require("windows")
    handle = int(source["hwnd"])
    found = next((w for w in windows() if w[0] == handle), None)
    if not found or (source.get("process") and found[2] != source["process"]):
        raise RuntimeError("Исходное окно закрыто или изменилось — текст не вставлен")
    focus(handle)
    time.sleep(.12)
    if (foreground() or {}).get("hwnd") != handle:
        raise RuntimeError("Не удалось вернуть фокус в исходное окно — текст не вставлен")
    return type_text(text)


def capture(handle=None):
    from PIL import Image, ImageGrab
    if wayland():
        helper = ROOT_PATH / "tools" / "portal_screenshot.py"
        path = _run("/usr/bin/python3", helper, timeout=35).strip()
        with Image.open(path) as source:
            image = source.convert("RGB")
        title = "Экран (выбран через системный диалог)"
    else:
        _require("screenshot")
        image = ImageGrab.grab(xdisplay=os.environ.get("DISPLAY"))
        title = "Экран"
        if handle:
            values = _run("xdotool", "getwindowgeometry", "--shell", int(handle))
            geometry = dict(re.findall(r"^(X|Y|WIDTH|HEIGHT)=(-?\d+)$", values, re.M))
            if len(geometry) != 4:
                raise RuntimeError("Не удалось определить границы окна")
            x, y, w, h = (int(geometry[k]) for k in ("X", "Y", "WIDTH", "HEIGHT"))
            image = image.crop((x, y, x + w, y + h))
            title = next((w[1] for w in windows() if w[0] == int(handle)), title)
    image.thumbnail((4096, 4096))
    return image.width, image.height, image.convert("RGBA").tobytes("raw", "BGRA"), title


def ocr(width, height, pixels):
    import io
    from PIL import Image
    if not shutil.which("tesseract"):
        raise RuntimeError("Для чтения экрана установите tesseract-ocr и языки rus/eng")
    image = Image.frombytes("RGBA", (width, height), pixels, "raw", "BGRA").convert("RGB")
    data = io.BytesIO()
    image.save(data, format="PNG")
    return _run("tesseract", "stdin", "stdout", "-l", "rus+eng", data=data.getvalue(), timeout=30).strip()
