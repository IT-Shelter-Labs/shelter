"""Read Windows per-user DPAPI secrets written by the desktop settings app."""
import ctypes
import os
from ctypes import wintypes


def decode(value):
    if isinstance(value, dict):
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    if not isinstance(value, str) or not value.startswith("dpapi:"):
        return value
    if os.name != "nt":
        raise ValueError("Введите секрет заново на Linux: он защищён учётной записью Windows")
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    raw = bytes.fromhex(value[6:])
    buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    source, target = Blob(len(raw), buffer), Blob()
    crypt = ctypes.windll.crypt32.CryptUnprotectData
    crypt.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                      ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt.restype = wintypes.BOOL
    if not crypt(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError("Не удалось открыть секрет текущего пользователя Windows")
    try:
        return ctypes.string_at(target.data, target.size).decode("utf-8")
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(target.data)
