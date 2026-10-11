"""Windows helpers for screen sharing: list the open application windows and capture one window
(even when other windows cover it) using PrintWindow(PW_RENDERFULLCONTENT)."""
from __future__ import annotations

import sys
from typing import List, Optional, Tuple

from PySide6.QtGui import QImage

AVAILABLE = sys.platform == "win32"

if AVAILABLE:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    HANDLE = ctypes.c_void_p

    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user32.IsWindowVisible.argtypes = [HANDLE]
    user32.IsWindow.argtypes = [HANDLE]
    user32.IsIconic.argtypes = [HANDLE]
    user32.GetWindow.argtypes = [HANDLE, ctypes.c_uint]
    user32.GetWindow.restype = HANDLE
    user32.GetWindowTextLengthW.argtypes = [HANDLE]
    user32.GetWindowTextW.argtypes = [HANDLE, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetWindowLongW.argtypes = [HANDLE, ctypes.c_int]
    user32.GetWindowRect.argtypes = [HANDLE, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowDC.argtypes = [HANDLE]
    user32.GetWindowDC.restype = HANDLE
    user32.ReleaseDC.argtypes = [HANDLE, HANDLE]
    user32.PrintWindow.argtypes = [HANDLE, HANDLE, ctypes.c_uint]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    gdi32.CreateCompatibleDC.argtypes = [HANDLE]
    gdi32.CreateCompatibleDC.restype = HANDLE
    gdi32.CreateCompatibleBitmap.argtypes = [HANDLE, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = HANDLE
    gdi32.SelectObject.argtypes = [HANDLE, HANDLE]
    gdi32.SelectObject.restype = HANDLE
    gdi32.DeleteObject.argtypes = [HANDLE]
    gdi32.DeleteDC.argtypes = [HANDLE]
    gdi32.BitBlt.argtypes = [HANDLE, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             HANDLE, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    gdi32.GetDIBits.argtypes = [HANDLE, HANDLE, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
                                ctypes.c_void_p, ctypes.c_uint]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                    ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16),
                    ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32),
                    ("biXPelsPerMeter", ctypes.c_int32), ("biYPelsPerMeter", ctypes.c_int32),
                    ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]

    _ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _title(hwnd) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def window_rect(hwnd) -> Optional[Tuple[int, int, int, int]]:
    if not AVAILABLE:
        return None
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def list_windows(exclude_titles=()) -> List[Tuple[int, str]]:
    """Visible top-level application windows: [(hwnd, title)]."""
    if not AVAILABLE:
        return []
    out = []

    def cb(hwnd, _lp):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):    # 4 = GW_OWNER
                return True
            if user32.GetWindowLongW(hwnd, -20) & 0x80:                        # WS_EX_TOOLWINDOW
                return True
            cloaked = ctypes.c_int(0)
            try:
                ctypes.windll.dwmapi.DwmGetWindowAttribute(ctypes.c_void_p(hwnd), 14, ctypes.byref(cloaked), 4)
            except Exception:
                pass
            if cloaked.value:
                return True
            title = _title(hwnd)
            if not title or title in ("Program Manager",) or title in exclude_titles:
                return True
            rect = window_rect(hwnd)
            if not rect or rect[2] < 80 or rect[3] < 60:
                return True
            out.append((int(hwnd), title))
        except Exception:
            pass
        return True

    user32.EnumWindows(_ENUM_PROC(cb), 0)
    return out


def is_alive(hwnd) -> bool:
    return AVAILABLE and bool(user32.IsWindow(hwnd))


def capture_window(hwnd) -> Optional[QImage]:
    """Capture one window's content (works when it is behind other windows; not when minimized)."""
    if not AVAILABLE or not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):
        return None
    rect = window_rect(hwnd)
    if not rect:
        return None
    _x, _y, w, h = rect
    if w <= 0 or h <= 0:
        return None
    win_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(win_dc)
    bmp = gdi32.CreateCompatibleBitmap(win_dc, w, h)
    old = gdi32.SelectObject(mem_dc, bmp)
    def read():
        bmi = BITMAPINFOHEADER(40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)  # top-down 32-bit
        buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0):
            return None
        return QImage(buf.raw, w, h, w * 4, QImage.Format.Format_RGB32).copy()

    try:
        img = None
        if user32.PrintWindow(hwnd, mem_dc, 2):                     # 2 = PW_RENDERFULLCONTENT
            img = read()
        if img is None or _blank(img):                              # some apps/drivers give black
            gdi32.BitBlt(mem_dc, 0, 0, w, h, win_dc, 0, 0, 0x00CC0020)   # SRCCOPY from the window
            img = read()
        if img is None or _blank(img):                              # last resort: that area of the screen
            img = _screen_area(*rect)
        return img
    finally:
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd, win_dc)


def _blank(img: QImage) -> bool:
    w, h = img.width(), img.height()
    for i in range(1, 8):
        for j in range(1, 8):
            if img.pixel(w * i // 8, h * j // 8) & 0xFFFFFF:
                return False
    return True


def _screen_area(x, y, w, h) -> Optional[QImage]:
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtCore import QPoint
    scr = QGuiApplication.screenAt(QPoint(x + w // 2, y + h // 2)) or QGuiApplication.primaryScreen()
    if scr is None:
        return None
    g = scr.geometry()
    pm = scr.grabWindow(0, x - g.x(), y - g.y(), w, h)
    return None if pm.isNull() else pm.toImage()


def cursor_pos() -> Optional[Tuple[int, int]]:
    if not AVAILABLE:
        return None
    p = wintypes.POINT()
    return (p.x, p.y) if user32.GetCursorPos(ctypes.byref(p)) else None
