"""Floating control panel: a small translucent black always-on-top window with two
switches, as the user asked for it:

    火控系统  fire control - tracking on/off (enable / disable)
    武器系统  weapons      - auto fire on/off

plus a status line, and a padlock: unlocked, the panel can be dragged anywhere;
click the padlock to pin it there. Position and lock are remembered
(logs/panel.json).

Clicking it does not take the focus from the game (WS_EX_NOACTIVATE), and it
stays out of the taskbar / Alt-Tab (WS_EX_TOOLWINDOW). A game that puts itself
on top when it gets the focus would cover it, so it is put back on top every
second - without activating it.

Tk runs on its own thread and is only touched there. The main loop reads the
switch clicks from `actions` - ("fire_control", bool) / ("weapons", bool) - and
reports the real state back with show(); the switches draw what show() said.
"""

from __future__ import annotations

import json
import queue
import threading
from pathlib import Path

BG = "#000000"
ALPHA = 0.78
FG = "#e8e8e8"
DIM = "#8a8a8a"
ON = "#2ecc71"
OFF = "#4a4a4a"
FONT = ("Microsoft YaHei UI", 11)
SMALL = ("Microsoft YaHei UI", 9)
SW_W, SW_H = 46, 22  # switch size


class ControlPanel:
    def __init__(self, state_file: Path):
        self.actions: queue.Queue[tuple[str, bool]] = queue.Queue()
        self._file = state_file
        self._lock = threading.Lock()
        self._shown = {"fire_control": False, "weapons": False, "status": "", "alert": False}
        self._closing = threading.Event()
        self.error: str | None = None
        self._thread = threading.Thread(target=self._run, name="control-panel", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------ main thread API

    def show(self, fire_control: bool, weapons: bool, status: str, alert: bool = False) -> None:
        with self._lock:
            self._shown = {"fire_control": fire_control, "weapons": weapons, "status": status, "alert": alert}

    def close(self) -> None:
        self._closing.set()
        self._thread.join(1)

    # ------------------------------------------------------------ Tk thread

    def _run(self) -> None:
        try:
            import tkinter as tk
        except ImportError as e:  # no Tk: run without the panel
            self.error = str(e)
            return
        try:
            saved = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        self._locked = bool(saved.get("locked", False))
        try:  # crisp text on a scaled 2560x1440 desktop
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass

        prev_front = self._foreground()  # the game, usually: give it back after showing
        root = self._root = tk.Tk()
        root.withdraw()  # built hidden, shown once it can't take the focus
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", ALPHA)
        root.configure(bg=BG)
        root.geometry(f"+{int(saved.get('x', 40))}+{int(saved.get('y', 200))}")

        frame = tk.Frame(root, bg=BG, padx=12, pady=8)
        frame.pack()
        head = tk.Frame(frame, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="AI 炮手", bg=BG, fg=DIM, font=SMALL).pack(side="left")
        self._padlock = tk.Canvas(head, width=16, height=18, bg=BG, highlightthickness=0, cursor="hand2")
        self._padlock.pack(side="right")
        self._padlock.bind("<Button-1>", lambda e: self._toggle_lock())

        self._switches = {}
        for key, label in (("fire_control", "火控系统"), ("weapons", "武器系统")):
            row = tk.Frame(frame, bg=BG, pady=3)
            row.pack(fill="x")
            tk.Label(row, text=label, bg=BG, fg=FG, font=FONT).pack(side="left", padx=(0, 18))
            sw = tk.Canvas(row, width=SW_W, height=SW_H, bg=BG, highlightthickness=0, cursor="hand2")
            sw.pack(side="right")
            sw.bind("<Button-1>", lambda e, k=key: self._click(k))
            self._switches[key] = sw
        self._status = tk.Label(frame, text="", bg=BG, fg=DIM, font=SMALL, anchor="w")
        self._status.pack(fill="x", pady=(4, 0))

        # Drag anywhere except on the switches / padlock.
        for w in (root, frame, head, self._status, *head.winfo_children()):
            if w is not self._padlock:
                w.bind("<ButtonPress-1>", self._drag_start, add="+")
                w.bind("<B1-Motion>", self._drag, add="+")
                w.bind("<ButtonRelease-1>", lambda e: self._save(), add="+")

        root.update_idletasks()
        self._hwnd = self._no_activate(root)
        root.deiconify()
        root.update()
        self._give_back_focus(prev_front)
        self._pending: dict[str, bool] = {}  # clicked, not yet confirmed by show()
        self._draw_padlock()
        self._refresh()
        root.mainloop()
        # Drop every Tk object here, on the Tk thread: if the main thread's shutdown
        # frees them instead, Tcl aborts ("async handler deleted by the wrong thread").
        self._root = self._padlock = self._status = None
        self._switches = {}
        del root, frame, head, row, sw
        import gc

        gc.collect()

    @staticmethod
    def _no_activate(root) -> int | None:
        """Set WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW; returns the window handle."""
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetAncestor(root.winfo_id(), 2)  # GA_ROOT
            GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = -20, 0x08000000, 0x00000080
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
            print(f"[panel] window {hwnd:#x} ex-style {style:#010x}: no-activate "
                  f"{bool(style & WS_EX_NOACTIVATE)}, topmost {bool(style & 0x8)}", flush=True)
            return hwnd
        except (AttributeError, OSError):
            return None  # not Windows

    @staticmethod
    def _foreground() -> int | None:
        try:
            import ctypes

            return ctypes.windll.user32.GetForegroundWindow() or None
        except (AttributeError, OSError):
            return None

    def _give_back_focus(self, prev: int | None) -> None:
        """Showing a new window makes it the foreground one on Windows; hand the
        foreground back so starting the panel doesn't pull the game out of focus."""
        if prev and self._hwnd and prev != self._hwnd:
            import ctypes

            if ctypes.windll.user32.GetForegroundWindow() != prev:
                ctypes.windll.user32.SetForegroundWindow(prev)

    def _keep_on_top(self) -> None:
        if self._hwnd:
            import ctypes

            HWND_TOPMOST = -1
            SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_NOOWNERZORDER = 0x1, 0x2, 0x10, 0x200
            ctypes.windll.user32.SetWindowPos(self._hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                              SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)

    def _click(self, key: str) -> None:
        with self._lock:
            now = self._pending.get(key, self._shown[key])
        self._pending[key] = not now
        self.actions.put((key, not now))
        self._draw_switch(key, not now)

    def _refresh(self) -> None:
        if self._closing.is_set():
            self._root.destroy()
            return
        with self._lock:
            shown = dict(self._shown)
        for key in self._switches:
            if key in self._pending and self._pending[key] == shown[key]:
                del self._pending[key]  # the main loop caught up
            self._draw_switch(key, self._pending.get(key, shown[key]))
        self._status.configure(text=shown["status"], fg="#ff6b6b" if shown["alert"] else DIM)
        self._ticks = getattr(self, "_ticks", 0) + 1
        if self._ticks % 7 == 0:  # about once a second
            self._keep_on_top()
        self._root.after(150, self._refresh)

    def _draw_switch(self, key: str, on: bool) -> None:
        c = self._switches[key]
        c.delete("all")
        r = SW_H / 2
        color = ON if on else OFF
        c.create_oval(0, 0, SW_H, SW_H, fill=color, outline=color)
        c.create_oval(SW_W - SW_H, 0, SW_W, SW_H, fill=color, outline=color)
        c.create_rectangle(r, 0, SW_W - r, SW_H, fill=color, outline=color)
        x = SW_W - SW_H + 3 if on else 3
        c.create_oval(x, 3, x + SW_H - 6, SW_H - 3, fill="#ffffff", outline="#ffffff")

    def _draw_padlock(self) -> None:
        c = self._padlock
        c.delete("all")
        color = FG if self._locked else DIM
        c.create_rectangle(2, 8, 14, 17, fill=color, outline=color)  # body
        if self._locked:
            c.create_arc(4, 1, 12, 13, start=0, extent=180, style="arc", outline=color, width=2)
            c.create_line(4, 7, 4, 9, fill=color, width=2)
            c.create_line(12, 7, 12, 9, fill=color, width=2)
        else:  # shackle open, swung up to the right
            c.create_arc(7, 0, 15, 10, start=0, extent=180, style="arc", outline=color, width=2)
            c.create_line(8, 5, 8, 7, fill=color, width=2)

    def _toggle_lock(self) -> None:
        self._locked = not self._locked
        self._draw_padlock()
        self._save()

    def _drag_start(self, e) -> None:
        self._drag_from = (e.x_root - self._root.winfo_x(), e.y_root - self._root.winfo_y())

    def _drag(self, e) -> None:
        if not self._locked:
            dx, dy = self._drag_from
            self._root.geometry(f"+{e.x_root - dx}+{e.y_root - dy}")

    def _save(self) -> None:
        try:
            self._file.write_text(json.dumps({"x": self._root.winfo_x(), "y": self._root.winfo_y(),
                                              "locked": self._locked}), encoding="utf-8")
        except OSError:
            pass
