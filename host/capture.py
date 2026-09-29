"""ROI screen capture via DXGI Desktop Duplication (dxcam).

Must run in the logged-on user's desktop session (not over SSH); see
tools/desktop_run.ps1.
"""

from __future__ import annotations

import ctypes
import time
from dataclasses import dataclass

import dxcam
import numpy as np

from config import Config

# Work in physical pixels (DXGI, cursor and window coordinates) regardless of display scaling.
ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2


class CaptureError(RuntimeError):
    pass


@dataclass
class Frame:
    image: np.ndarray  # BGR, the captured region (ROI, or full screen)
    present_time: float  # when the frame hit the screen (time.perf_counter() clock)
    read_time: float  # when read() returned it

    def age_ms(self, now: float | None = None) -> float:
        return ((now if now is not None else time.perf_counter()) - self.present_time) * 1000


class ScreenCapture:
    def __init__(self, cfg: Config, full_screen: bool = False):
        """full_screen: capture the whole output instead of the ROI (the caller then
        slices the ROI out of each frame)."""
        c = cfg.capture
        self._camera = dxcam.create(
            device_idx=c.device_idx, output_idx=c.output_idx, output_color="BGR", max_buffer_len=4
        )
        size = (self._camera.width, self._camera.height)
        if size != (cfg.screen.width, cfg.screen.height):
            self._camera.release()
            raise CaptureError(
                f"output {c.device_idx}/{c.output_idx} is {size[0]}x{size[1]}, "
                f"config.screen says {cfg.screen.width}x{cfg.screen.height}"
            )
        self._region = (0, 0, cfg.screen.width, cfg.screen.height) if full_screen else cfg.roi.region
        self._target_fps = c.target_fps
        self._last_ticks = None

    def start(self) -> None:
        self._camera.start(region=self._region, target_fps=self._target_fps)
        self._last_ticks = self._camera.latest_frame_ticks

    def read(self, timeout: float = 0.1) -> Frame | None:
        """Next new frame, or None if the screen has not changed within `timeout` s."""
        # latest_frame_ticks only changes when a new frame is captured, so poll it
        # rather than blocking in get_latest_frame(), which has no timeout.
        deadline = time.perf_counter() + timeout
        while self._camera.latest_frame_ticks == self._last_ticks:
            if time.perf_counter() >= deadline:
                return None
            time.sleep(0.0005)
        image, present = self._camera.get_latest_frame(with_timestamp=True)
        self._last_ticks = self._camera.latest_frame_ticks
        now = time.perf_counter()
        return Frame(image, present if present > 0 else now, now)

    def close(self) -> None:
        if self._camera.is_capturing:
            self._camera.stop()
        self._camera.release()

    def __enter__(self) -> ScreenCapture:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
