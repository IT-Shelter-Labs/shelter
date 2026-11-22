"""Что на экране: снимок активного окна -> текст (Windows OCR) -> ответ модели.

«Прочитай, что на экране», «переведи это», «что за ошибка на экране».
Распознавание — встроенное в Windows (Windows.Media.Ocr): локально, без
скачиваний, русский и английский. Снимается окно, с которым вы работаете, —
через PrintWindow, поэтому HUD Джарвиса поверх него в текст не попадает.
"""

import asyncio
import ctypes
import os
import re
import struct
import zlib
from ctypes import wintypes

user32 = ctypes.windll.user32 if os.name == "nt" else None
gdi32 = ctypes.windll.gdi32 if os.name == "nt" else None


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


def _own_window(hwnd):
    """Окна самого Джарвиса (HUD, приложение) снимать не нужно."""
    title = ctypes.create_unicode_buffer(64)
    user32.GetWindowTextW(hwnd, title, 64)
    return title.value in ("JARVIS", "Джарвис")


def target_window():
    """Окно, с которым работает человек: активное, а если это сам Джарвис — следующее под ним."""
    if os.name != "nt":
        from desktop_linux import wayland, foreground
        return None if wayland() else (foreground() or {}).get("hwnd")
    hwnd = user32.GetForegroundWindow()
    while hwnd and (_own_window(hwnd) or not user32.IsWindowVisible(hwnd)):
        hwnd = user32.GetWindow(hwnd, 2)          # GW_HWNDNEXT — ниже по Z-порядку
    return hwnd


def capture(hwnd=None):
    """(ширина, высота, BGRA-байты, заголовок окна) снимка окна."""
    if os.name != "nt":
        from desktop_linux import capture as grab
        return grab(hwnd or target_window())
    user32.SetProcessDPIAware()
    hwnd = hwnd or target_window()
    if not hwnd:
        raise RuntimeError("нет активного окна")
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width < 20 or height < 20:
        raise RuntimeError("окно слишком маленькое")
    title = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title, 256)

    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    old = gdi32.SelectObject(memory_dc, bitmap)
    try:
        # PW_RENDERFULLCONTENT (2): содержимое даже под другими окнами, включая браузеры.
        if not user32.PrintWindow(hwnd, memory_dc, 2):
            gdi32.BitBlt(memory_dc, 0, 0, width, height, window_dc, 0, 0, 0x00CC0020)
        header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        buffer = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0)
        return width, height, buffer.raw, title.value
    finally:
        gdi32.SelectObject(memory_dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)


async def _recognize(width, height, pixels):
    if os.name != "nt":
        from desktop_linux import ocr
        return ocr(width, height, pixels).splitlines()
    from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter
    writer = DataWriter()
    writer.write_bytes(pixels)
    bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.BGRA8,
                                                    width, height, BitmapAlphaMode.PREMULTIPLIED)
    # Языки профиля Windows: обычно русский и английский — смешанный текст читается целиком.
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError("в Windows нет языка распознавания текста")
    result = await engine.recognize_async(bitmap)
    return [line.text for line in result.lines]


def read_text(hwnd=None):
    """(заголовок окна, распознанный текст)."""
    width, height, pixels, title = capture(hwnd)
    lines = asyncio.run(_recognize(width, height, pixels))
    return title, "\n".join(lines)


# «Прочитай/переведи/что за ошибка» — хватит текста; остальное («что на экране»,
# «что это за игра», «опиши») — модели нужен и сам снимок.
TEXT_ONLY = ("прочита", "прочти", "переведи", "перевод", "что написано", "текст", "ошибк", "скопируй",
             "озвучь", "зачитай")


def snapshot(question="", *, expected_title=None):
    """{"title", "text", "image": PNG | None} — снимок окна с текстом."""
    width, height, pixels, title = capture()
    if expected_title and not re.search(expected_title, title, re.I):
        raise ValueError("Активное окно не соответствует выбранной игре.")
    lines = asyncio.run(_recognize(width, height, pixels))
    wants_text = any(word in question.lower() for word in TEXT_ONLY)
    image = None if wants_text else png(width, height, pixels, max_side=1024)
    return {"title": title, "text": "\n".join(lines), "image": image}


def png(width, height, pixels, max_side=1280):
    """PNG без сторонних библиотек — для модели, которая видит картинки."""
    step = max(1, -(-max(width, height) // max_side))
    out_w, out_h = width // step, height // step
    rows = []
    for y in range(out_h):
        row = pixels[(y * step) * width * 4:((y * step) * width + width) * 4]
        rgb = bytearray(out_w * 3)
        for x in range(out_w):
            b, g, r = row[x * step * 4], row[x * step * 4 + 1], row[x * step * 4 + 2]
            rgb[x * 3:x * 3 + 3] = bytes((r, g, b))
        rows.append(b"\x00" + bytes(rgb))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", out_w, out_h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + chunk(b"IEND", b""))
