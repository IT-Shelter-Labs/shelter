"""Identity and readable value of the focused input. No app-specific coordinates."""
import ctypes
from ctypes import wintypes
import os
import threading
import pc
import tasks

_local = threading.local()
OWN = {"jarvis","jarvis-hud","jarvis.exe","jarvis-hud.exe"}


class InputUncertain(RuntimeError):
    """Input may have partially happened: the draft must not be sent/retried blindly."""


def _uia():
    # COM pointers stay on the thread that created them.
    if not hasattr(_local,"automation"):
        import comtypes
        import comtypes.client
        comtypes.CoInitialize()
        module = comtypes.client.GetModule("UIAutomationCore.dll")
        _local.module = module
        _local.automation = comtypes.client.CreateObject(module.CUIAutomation,interface=module.IUIAutomation)
    return _local.automation,_local.module


class _GUIINFO(ctypes.Structure):
    _fields_ = [("cbSize",wintypes.DWORD),("flags",wintypes.DWORD),
                *[(name,wintypes.HWND) for name in ("active","focus","capture","menu","move","caret")],
                ("rect",wintypes.RECT)]


if pc.user32 is not None:
    pc.user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    pc.user32.GetWindowThreadProcessId.restype=wintypes.DWORD
    pc.user32.GetGUIThreadInfo.argtypes=[wintypes.DWORD,ctypes.POINTER(_GUIINFO)]
    pc.user32.GetGUIThreadInfo.restype=wintypes.BOOL
    pc.user32.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    pc.user32.GetWindowTextW.restype=ctypes.c_int


def _window():
    if os.name != "nt":
        from desktop_linux import foreground
        value = foreground()
        if not value: raise RuntimeError("Нет активного окна")
        if value.get("process") in OWN:raise RuntimeError("Сначала поставьте курсор в нужную программу")
        return {"window":value["hwnd"],"pid":value.get("pid",0),"focus":value["hwnd"],"title":value.get("title","")}
    hwnd = int(pc.user32.GetForegroundWindow() or 0)
    if not hwnd: raise RuntimeError("Нет активного окна")
    pid = wintypes.DWORD()
    thread = pc.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
    info = _GUIINFO(); info.cbSize=ctypes.sizeof(info)
    pc.user32.GetGUIThreadInfo(thread,ctypes.byref(info))
    title = ctypes.create_unicode_buffer(512);pc.user32.GetWindowTextW(hwnd,title,len(title))
    if pid.value == os.getpid() or title.value in ("Джарвис","JARVIS","JARVIS SETTINGS"):
        raise RuntimeError("Сначала поставьте курсор в поле нужной программы")
    return {"window":hwnd,"pid":pid.value,"focus":int(info.focus or hwnd),"title":title.value}


def same(a,b):
    keys=("window","pid","focus","runtime")
    return all(a.get(key)==b.get(key) for key in keys)


def capture():
    value = _window()
    value.update(runtime=None,value=None,editable=None)
    if os.name != "nt": return value
    try:
        automation,module=_uia()
        element=automation.GetFocusedElement()
        if element.CurrentIsPassword:
            raise PermissionError("Поле пароля не используется для диктовки сообщений")
        value["runtime"]=tuple(element.GetRuntimeId())
        kind=element.CurrentControlType
        value["editable"]=False if not element.CurrentIsEnabled or kind in (50000,50008,50011,50020,50023) else True if kind in (50004,50030) else None
        try:
            pattern=element.GetCurrentPattern(10002).QueryInterface(module.IUIAutomationValuePattern)
            value["editable"]=bool(element.CurrentIsEnabled and not pattern.CurrentIsReadOnly)
            if value["editable"]:
                content=pattern.CurrentValue
                value["value"]=content if len(content)<=12000 else None
        except Exception:
            if value["editable"]:
                try:
                    pattern=element.GetCurrentPattern(10014).QueryInterface(module.IUIAutomationTextPattern)
                    value["value"]=pattern.DocumentRange.GetText(12001)
                except Exception: pass
    except PermissionError: raise
    except Exception:
        # Providers can be unavailable. Typing still works; replacing unknown
        # text is refused rather than issuing Ctrl+A in an arbitrary view.
        pass
    latest=_window()
    if any(latest[key]!=value[key] for key in ("window","pid","focus")):
        raise RuntimeError("Активное окно изменилось. Повторите команду")
    return value


def verify(expected):
    current=capture()
    if not same(current,expected): raise RuntimeError("Окно или поле ввода сменилось. Верните курсор в исходное поле")
    if current.get("editable") is False: raise RuntimeError("Поставьте курсор в редактируемое поле")
    return current


def insert(text, expected):
    verify(expected)
    tasks.check()
    if not pc.type_text(text): raise InputUncertain("Система не приняла весь текст; проверьте поле перед повтором")
    try:return verify(expected)
    except (RuntimeError,OSError) as error:raise InputUncertain("После ввода поле изменилось; проверьте текст вручную") from error


def replace(text, expected, previous):
    current=verify(expected)
    if current.get("value") is None:
        raise RuntimeError("Программа не даёт прочитать поле. Выделите нужный текст и используйте «напечатай …»")
    if current["value"] != previous:
        raise RuntimeError("Текст поля изменился. Выделите нужный текст и используйте «напечатай …»")
    tasks.check();pc.send_keys("ctrl+a")
    verify(expected)
    return insert(text,expected)
