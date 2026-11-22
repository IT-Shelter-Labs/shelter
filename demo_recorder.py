"""«Покажу один раз»: ограниченная запись демонстрации -> черновик сценария.

Запись включается и выключается только явно, идёт не дольше LIMIT секунд и
видна в окне Джарвиса. Записываются только программы и окна: что запустили,
на какое окно переключились, куда в итоге поставили окно (монитор и часть
экрана). Нажатия клавиш, текст и координаты кликов НЕ записываются — пароли и
ввод в защищённые поля в запись не попадают в принципе.

Шаги сохраняются по устойчивым признакам (путь программы, процесс и заголовок
окна, номер монитора и место), а не по координатам, поэтому сценарий работает
и после перемещения окон. Чего записать нельзя (клики внутри программы),
окно объясняет: такие действия добавляются в конструкторе вручную.
"""

import os
import threading
import time

import bus

LIMIT = 300
POLL = 0.4
IGNORED = {"jarvis", "jarvis-hud", "explorer", "searchhost", "shellexperiencehost", "startmenuexperiencehost",
           "applicationframehost", "textinputhost", "lockapp", "systemsettings"}

_lock = threading.Lock()
_session = None


def _snapshot():
    import pc
    windows = {}
    for hwnd, title, process in pc._windows():
        if process and process not in IGNORED:
            windows.setdefault(process, (hwnd, title))
    foreground = pc.user32.GetForegroundWindow()
    return windows, int(foreground or 0)


def _exe(hwnd):
    import ctypes
    import psutil
    from ctypes import wintypes
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        return psutil.Process(pid.value).exe()
    except Exception:
        return ""


def _place(hwnd):
    """Окно -> (монитор, место) по его прямоугольнику: устойчиво к точным пикселям."""
    import ctypes
    from ctypes import wintypes
    import pc
    rect = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    if ctypes.windll.user32.IsZoomed(hwnd):
        position = "full"
    else:
        position = None
    cx, cy = (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2
    for monitor in pc.monitors():
        x, y, w, h = monitor["work"]
        if x <= cx < x + w and y <= cy < y + h:
            if position:
                return monitor["index"], position
            width, height = rect.right - rect.left, rect.bottom - rect.top
            left_half, top_half = cx < x + w / 2, cy < y + h / 2
            if width > w * 0.85 and height > h * 0.85:
                return monitor["index"], "full"
            if height > h * 0.8:
                return monitor["index"], "left" if left_half else "right"
            if width < w * 0.6 and height < h * 0.6:
                return monitor["index"], ("top-" if top_half else "bottom-") + ("left" if left_half else "right")
            return monitor["index"], "center"
    return None


class Session:
    def __init__(self):
        self.started = time.time()
        self.events = []                 # [(время, вид, данные)]
        self.stop_event = threading.Event()
        self.initial, self.last_foreground = _snapshot()
        self.thread = threading.Thread(target=self.loop, name="demo-recorder", daemon=True)

    def loop(self):
        seen = dict(self.initial)
        while not self.stop_event.wait(POLL):
            if time.time() - self.started > LIMIT:
                bus.publish("demo", state="limit")
                stop()
                return
            try:
                windows, foreground = _snapshot()
            except Exception:
                continue
            for process, (hwnd, title) in windows.items():
                if process not in seen:
                    self.events.append((time.time(), "opened", {"process": process, "title": title, "hwnd": hwnd, "exe": _exe(hwnd)}))
                    bus.publish("demo", state="step", text=f"Открыто: {title or process}")
            if foreground and foreground != self.last_foreground:
                process = next((p for p, (h, _) in windows.items() if h == foreground), "")
                if process:
                    self.events.append((time.time(), "focus", {"process": process, "title": windows[process][1], "hwnd": foreground}))
            self.last_foreground = foreground
            seen.update(windows)

    def steps(self):
        """События -> шаги сценария без лишнего: повторные переключения схлопнуты, места окон — в конце."""
        steps, notes, touched = [], [], {}
        home = os.path.expanduser("~")
        for _, kind, data in self.events:
            process = data["process"]
            touched[process] = data
            if kind == "opened":
                exe = data.get("exe") or ""
                if exe and "WindowsApps" not in exe and os.path.isfile(exe):
                    path = exe.replace(home, "%USERPROFILE%") if exe.lower().startswith(home.lower()) else exe
                    steps.append({"type": "launch", "path": path})
                else:
                    steps.append({"type": "open_app", "target": data.get("title") or process})
                steps.append({"type": "wait_for", "what": "window", "value": process, "timeout": 30})
            elif kind == "focus":
                if steps and steps[-1].get("type") == "window" and steps[-1].get("action") == "focus":
                    steps.pop()                          # переключились ещё раз — оставить последнее
                steps.append({"type": "window", "action": "focus", "title": process})
        for process, data in touched.items():
            place = None
            try:
                place = _place(data["hwnd"])
            except Exception:
                pass
            if place:
                steps.append({"type": "window", "action": "place", "title": process, "monitor": place[0], "position": place[1]})
            else:
                notes.append(f"Окно {process} закрыто до конца записи — его место не сохранено")
        # Фокус в самом конце — на окне, которое было активным последним.
        if steps and steps[-1].get("action") != "focus":
            last_focus = next((s for s in reversed(steps) if s.get("action") == "focus"), None)
            steps = [s for s in steps if s.get("action") != "focus"]
            if last_focus:
                steps.append(last_focus)
        notes.append("Клики и ввод внутри программ не записываются — добавьте такие шаги вручную (например, «Нажать клавиши»).")
        return steps, notes


def start():
    global _session
    if os.name != "nt":
        raise RuntimeError("запись демонстрации пока есть только в Windows")
    with _lock:
        if _session is not None:
            raise RuntimeError("запись уже идёт")
        _session = Session()
        _session.thread.start()
    bus.publish("demo", state="recording", limit=LIMIT)
    return {"recording": True, "limit": LIMIT}


def stop():
    global _session
    with _lock:
        session, _session = _session, None
    if session is None:
        raise RuntimeError("запись не идёт")
    session.stop_event.set()
    steps, notes = session.steps()
    bus.publish("demo", state="stopped")
    if not steps:
        return {"draft": None, "notes": ["Ничего не записано: откройте или переключите программы во время записи."]}
    import scenarios
    draft = scenarios.normalize({"name": "Показанный сценарий", "phrases": [], "steps": steps, "origin": "demo",
                                 "description": f"Записано {time.strftime('%d.%m %H:%M')}: {len(steps)} шагов"})
    return {"draft": draft, "notes": notes}


def status():
    with _lock:
        session = _session
    if session is None:
        return {"recording": False}
    return {"recording": True, "seconds": round(time.time() - session.started), "limit": LIMIT, "events": len(session.events)}
