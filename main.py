"""
CursorFollow — окно 800×800 для OBS «Захват окна».
Ищите в списке: [python.exe]: CursorFollow — OBS Capture
"""

import argparse
import sys
import tkinter as tk
from ctypes import windll
from tkinter import messagebox

from PIL import ImageTk

from capture import PRESETS, VIEW_SIZE, ScreenFollower

# Уникальный заголовок — хорошо виден в списке окон OBS
WINDOW_TITLE = "CursorFollow — OBS Capture"
FPS_DEFAULT = 60
MUTEX_NAME = "CursorFollowAppMutex_v2"


def single_instance():
    try:
        err = windll.kernel32.GetLastError
        windll.kernel32.CreateMutexW(None, True, MUTEX_NAME)
        if err() == 183:
            return False
    except Exception:
        pass
    return True


def window_hwnd(root):
    root.update_idletasks()
    hwnd = windll.user32.GetParent(root.winfo_id())
    return hwnd if hwnd else root.winfo_id()


def apply_obs_window_title(root):
    hwnd = window_hwnd(root)
    windll.user32.SetWindowTextW(hwnd, WINDOW_TITLE)


def ensure_minimize_box(root):
    """Кнопка «свернуть» в заголовке (Windows)."""
    GWL_STYLE = -16
    WS_MINIMIZEBOX = 0x00020000
    hwnd = window_hwnd(root)
    style = windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
    windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style | WS_MINIMIZEBOX)


def default_position(screen_w, screen_h):
    x = max(0, screen_w - VIEW_SIZE - 48)
    y = max(0, screen_h - VIEW_SIZE - 96)
    return x, y


class App:
    def __init__(self, dead_zone, lerp, fps):
        self.tick_ms = max(8, int(1000 / min(fps, 60)))
        self.follower = ScreenFollower(dead_zone=dead_zone, lerp=lerp)
        self.follower.refresh_monitor()
        self.follower.snap_to_cursor()

        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.resizable(False, False)
        self.root.configure(bg="#000000", highlightthickness=0)

        px, py = default_position(self.follower.screen_w, self.follower.screen_h)
        self.root.geometry(f"+{px}+{py}")

        self.label = tk.Label(self.root, bd=0, highlightthickness=0, bg="#000000")
        self.label.pack(padx=0, pady=0)

        self._photo = None
        self._fitted = False
        self._running = True
        self._paused = False

        self.root.bind("<Escape>", lambda _: self.root.destroy())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Unmap>", self._on_unmap)
        self.root.bind("<Map>", self._on_map)

        self.root.update_idletasks()
        apply_obs_window_title(self.root)
        ensure_minimize_box(self.root)
        self._tick()

    def _is_iconic(self):
        try:
            return self.root.state() == "iconic"
        except tk.TclError:
            return False

    def _on_unmap(self, _event):
        if self._is_iconic():
            self._paused = True

    def _on_map(self, _event):
        if not self._is_iconic():
            self._paused = False
    def _fit_chrome(self):
        if self._fitted:
            return
        self.root.update_idletasks()
        bw = max(0, self.root.winfo_width() - self.label.winfo_width())
        bh = max(0, self.root.winfo_height() - self.label.winfo_height())
        x, y = self.root.winfo_x(), self.root.winfo_y()
        self.root.geometry(f"{VIEW_SIZE + bw}x{VIEW_SIZE + bh}+{x}+{y}")
        apply_obs_window_title(self.root)
        self._fitted = True

    def _on_close(self):
        self._running = False
        self.follower.close()
        self.root.destroy()

    def _tick(self):
        if not self._running:
            return
        if self._paused or self._is_iconic():
            self._paused = True
            self.root.after(250, self._tick)
            return
        try:
            self.follower.tick()
            img = self.follower.grab_frame()
            self._photo = ImageTk.PhotoImage(img)
            self.label.configure(image=self._photo)
            self._fit_chrome()
        except Exception as exc:
            print("frame error:", exc, file=sys.stderr)
        self.root.after(self.tick_ms, self._tick)

    def run(self):
        self.root.mainloop()


def parse_args():
    p = argparse.ArgumentParser(description="CursorFollow 800×800 для OBS")
    p.add_argument(
        "--preset",
        choices=PRESETS.keys(),
        default="stream",
        help="stream = вайбкодинг (по умолчанию)",
    )
    p.add_argument("--dead-zone", type=int, help="перекрывает preset")
    p.add_argument("--lerp", type=float, help="перекрывает preset")
    p.add_argument("--fps", type=int, default=FPS_DEFAULT, help="кадров/с (по умолчанию 60)")
    return p.parse_args()


def main():
    if not single_instance():
        r = tk.Tk()
        r.withdraw()
        messagebox.showwarning(
            WINDOW_TITLE,
            "Уже запущено.\nВ OBS выберите окно:\nCursorFollow — OBS Capture",
        )
        r.destroy()
        return 1

    args = parse_args()
    cfg = dict(PRESETS[args.preset])
    if args.dead_zone is not None:
        cfg["dead_zone"] = args.dead_zone
    if args.lerp is not None:
        cfg["lerp"] = args.lerp

    App(dead_zone=cfg["dead_zone"], lerp=cfg["lerp"], fps=args.fps).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
