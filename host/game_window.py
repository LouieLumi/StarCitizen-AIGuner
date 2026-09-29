"""Is the game the foreground window?

Our mouse and keyboard reports go to whatever window has the focus. With the game
in the background (Alt-Tab, a browser on top) they would move and click the
desktop cursor instead of turning the turret, so main.py sends nothing then.
"""

from __future__ import annotations

import ctypes
import os
import sys

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class GameWindow:
    def __init__(self, exe: str):
        self._exe = exe.lower()
        self._names: dict[int, str] = {}  # pid -> exe name

    def in_front(self) -> bool:
        if sys.platform != "win32":
            return True
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        pid = ctypes.c_uint32()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        name = self._names.get(pid.value)
        if name is None:
            name = ""
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
            if handle:
                buf = ctypes.create_unicode_buffer(512)
                size = ctypes.c_uint32(len(buf))
                if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    name = os.path.basename(buf.value).lower()
                kernel32.CloseHandle(handle)
            if len(self._names) > 64:
                self._names.clear()
            self._names[pid.value] = name
        return name == self._exe
