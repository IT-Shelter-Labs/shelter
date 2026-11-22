"""Versioned, optional Rust C ABI; sources still work without a compiled library."""
import ctypes as c
import json
import math
import os
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
LIBRARY = None
ERROR = ""
try:
    name = "jarvis_native.dll" if os.name == "nt" else "libjarvis_native.so"
    path = ROOT / "bin" / name
    if path.is_file() and os.environ.get("JARVIS_NATIVE", "1") != "0":
        lib = c.CDLL(str(path))
        lib.jarvis_native_version.restype = c.c_uint
        if lib.jarvis_native_version() != 1: raise RuntimeError("Unsupported native ABI")
        lib.jarvis_resample.argtypes = [c.c_void_p,c.c_size_t,c.c_void_p,c.c_size_t,c.c_size_t,c.c_size_t]
        lib.jarvis_resample.restype = c.c_ssize_t
        lib.jarvis_ring_new.argtypes = [c.c_size_t]; lib.jarvis_ring_new.restype = c.c_void_p
        lib.jarvis_ring_free.argtypes = [c.c_void_p]; lib.jarvis_ring_free.restype = None
        for fn in (lib.jarvis_ring_write,lib.jarvis_ring_read):
            fn.argtypes = [c.c_void_p,c.c_void_p,c.c_size_t]; fn.restype = c.c_int
        lib.jarvis_media_snapshot.argtypes = [c.c_void_p,c.c_size_t]; lib.jarvis_media_snapshot.restype = c.c_ssize_t
        lib.jarvis_media_control.argtypes = [c.c_uint,c.c_char_p,c.c_size_t]; lib.jarvis_media_control.restype = c.c_int
        LIBRARY = lib
except (OSError, AttributeError, RuntimeError) as error:
    ERROR = str(error)


def resample_poly(samples, up, down):
    if up < 1 or down < 1: raise ValueError("positive resampling ratio required")
    if LIBRARY is None or np.asarray(samples).ndim != 1 or max(up,down)//math.gcd(up,down)>4096:
        from scipy.signal import resample_poly as fallback
        return fallback(samples,up,down)
    x = np.ascontiguousarray(samples,dtype=np.float32)
    result = np.empty((len(x)*up+down-1)//down,dtype=np.float32)
    count = LIBRARY.jarvis_resample(x.ctypes.data,len(x),result.ctypes.data,len(result),up,down)
    if count < 0: raise RuntimeError("Native resampling failed")
    return result


class Ring:
    def __init__(self, size):
        self.pointer = LIBRARY.jarvis_ring_new(size) if LIBRARY else None
        if not self.pointer: raise RuntimeError("Native ring unavailable")
    def write(self, samples):
        x = np.ascontiguousarray(samples,dtype=np.float32)
        if LIBRARY.jarvis_ring_write(self.pointer,x.ctypes.data,len(x)): raise RuntimeError("Native ring write failed")
    def read(self, count):
        out = np.empty(count,dtype=np.float32)
        if LIBRARY.jarvis_ring_read(self.pointer,out.ctypes.data,count): raise RuntimeError("Native ring read failed")
        return out
    def __del__(self):
        if getattr(self,"pointer",None): LIBRARY.jarvis_ring_free(self.pointer)


def media_sessions():
    if LIBRARY is None or os.name != "nt": return None
    buf = c.create_string_buffer(65536)
    size = LIBRARY.jarvis_media_snapshot(buf,len(buf))
    return json.loads(buf.raw[:size]) if size >= 0 else None


def media_control(action, source):
    if LIBRARY is None or os.name != "nt": return None
    actions = ["pause","play","toggle","next","previous","stop"]
    if action not in actions: return False
    encoded = source.encode("utf-8")
    result = LIBRARY.jarvis_media_control(actions.index(action),encoded,len(encoded))
    return result > 0 if result >= 0 else None
