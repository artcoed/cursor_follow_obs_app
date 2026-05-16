"""Захват 800×800 вокруг курсора + отрисовка системного курсора, 60 FPS."""

import math
from ctypes import Structure, byref, c_long, sizeof, windll, wintypes

import mss
import win32con
import win32gui
import win32ui
from PIL import Image

VIEW_SIZE = 800
DEAD_ZONE = 80
LERP = 0.12
CURSOR_SHOWING = 0x00000001
CURSOR_SIZE = 32


class POINT(Structure):
    _fields_ = [("x", c_long), ("y", c_long)]


class RECT(Structure):
    _fields_ = [("left", c_long), ("top", c_long), ("right", c_long), ("bottom", c_long)]


class MONITORINFO(Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class CURSORINFO(Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hCursor", wintypes.HANDLE),
        ("ptScreenPos", POINT),
    ]


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _lerp(a, b, t):
    return a + (b - a) * t


PRESETS = {
    "stream": {"dead_zone": 80, "lerp": 0.12},
    "snappy": {"dead_zone": 55, "lerp": 0.2},
    "smooth": {"dead_zone": 110, "lerp": 0.08},
}


class CursorSpriteCache:
    """Кэш bitmap текущей формы курсора (меняется редко)."""

    def __init__(self):
        self._hcursor = None
        self._image = None
        self._hotspot = (0, 0)

    def get(self, hcursor):
        if hcursor == self._hcursor and self._image is not None:
            return self._image, self._hotspot
        self._hcursor = hcursor
        self._image, self._hotspot = self._render(hcursor)
        return self._image, self._hotspot

    def _render(self, hcursor):
        hdc = win32gui.GetDC(0)
        try:
            info = win32gui.GetIconInfo(hcursor)
            hotspot = (info[1], info[2])
            if info[3]:
                win32gui.DeleteObject(info[3])
            if info[4]:
                win32gui.DeleteObject(info[4])

            dc = win32ui.CreateDCFromHandle(hdc)
            memdc = dc.CreateCompatibleDC()
            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(dc, CURSOR_SIZE, CURSOR_SIZE)
            memdc.SelectObject(bmp)
            memdc.FillSolidRect((0, 0, CURSOR_SIZE, CURSOR_SIZE), 0x00000000)
            win32gui.DrawIconEx(
                memdc.GetSafeHdc(),
                0,
                0,
                hcursor,
                CURSOR_SIZE,
                CURSOR_SIZE,
                0,
                0,
                win32con.DI_NORMAL,
            )
            bits = bmp.GetBitmapBits(True)
            img = Image.frombuffer(
                "RGBA",
                (CURSOR_SIZE, CURSOR_SIZE),
                bits,
                "raw",
                "BGRA",
                0,
                1,
            )
            memdc.DeleteDC()
            dc.DeleteDC()
            return img, hotspot
        finally:
            win32gui.ReleaseDC(0, hdc)


_cursor_cache = CursorSpriteCache()


def _cursor_screen_pos():
    ci = CURSORINFO()
    ci.cbSize = sizeof(CURSORINFO)
    if not windll.user32.GetCursorInfo(byref(ci)):
        return None
    if not (ci.flags & CURSOR_SHOWING):
        return None
    return ci.hCursor, ci.ptScreenPos.x, ci.ptScreenPos.y


def paint_cursor(img: Image.Image, region_left: int, region_top: int, mon_ox: int, mon_oy: int) -> Image.Image:
    cur = _cursor_screen_pos()
    if not cur:
        return img
    hcursor, sx, sy = cur
    lx = sx - mon_ox - region_left
    ly = sy - mon_oy - region_top
    sprite, (hx, hy) = _cursor_cache.get(hcursor)
    px = int(lx - hx)
    py = int(ly - hy)
    base = img.convert("RGBA")
    base.paste(sprite, (px, py), sprite)
    return base.convert("RGB")


class ScreenFollower:
    def __init__(self, dead_zone=DEAD_ZONE, lerp=LERP, view_size=VIEW_SIZE):
        self.dead_zone = dead_zone
        self.lerp = lerp
        self.view_size = view_size
        self.mon_ox = 0
        self.mon_oy = 0
        self.screen_w = 1920
        self.screen_h = 1080
        self.center_x = 960.0
        self.center_y = 540.0
        self._sct = mss.mss()

    def refresh_monitor(self):
        pt = wintypes.POINT(0, 0)
        hmon = windll.user32.MonitorFromPoint(pt, 1)
        mi = MONITORINFO()
        mi.cbSize = sizeof(MONITORINFO)
        if windll.user32.GetMonitorInfoW(hmon, byref(mi)):
            r = mi.rcMonitor
            self.mon_ox = int(r.left)
            self.mon_oy = int(r.top)
            self.screen_w = int(r.right - r.left)
            self.screen_h = int(r.bottom - r.top)
        else:
            self.mon_ox = self.mon_oy = 0
            self.screen_w = 1920
            self.screen_h = 1080
        self.center_x = self.screen_w / 2
        self.center_y = self.screen_h / 2

    def cursor_local(self):
        try:
            p = POINT()
            windll.user32.GetCursorPos(byref(p))
            return p.x - self.mon_ox, p.y - self.mon_oy
        except Exception:
            return self.screen_w // 2, self.screen_h // 2

    def _max_offset(self):
        return max(0, self.screen_w - self.view_size), max(0, self.screen_h - self.view_size)

    def _target_center(self, cx, cy):
        ml, mt = self._max_offset()
        left = _clamp(cx - self.view_size / 2, 0, ml)
        top = _clamp(cy - self.view_size / 2, 0, mt)
        return left + self.view_size / 2, top + self.view_size / 2

    def tick(self):
        cx, cy = self.cursor_local()
        if math.hypot(cx - self.center_x, cy - self.center_y) > self.dead_zone:
            tx, ty = self._target_center(cx, cy)
            self.center_x = _lerp(self.center_x, tx, self.lerp)
            self.center_y = _lerp(self.center_y, ty, self.lerp)

    def _crop_origin(self):
        ml, mt = self._max_offset()
        left = int(_clamp(self.center_x - self.view_size / 2, 0, ml))
        top = int(_clamp(self.center_y - self.view_size / 2, 0, mt))
        return left, top

    def grab_frame(self) -> Image.Image:
        left, top = self._crop_origin()
        region = {
            "left": self.mon_ox + left,
            "top": self.mon_oy + top,
            "width": self.view_size,
            "height": self.view_size,
        }
        shot = self._sct.grab(region)
        img = Image.frombytes("RGB", (self.view_size, self.view_size), shot.bgra, "raw", "BGRX")
        return paint_cursor(img, left, top, self.mon_ox, self.mon_oy)

    def snap_to_cursor(self):
        cx, cy = self.cursor_local()
        self.center_x, self.center_y = self._target_center(cx, cy)

    def close(self):
        self._sct.close()
