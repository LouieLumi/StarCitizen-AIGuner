"""Per-session logging: one CSV row per frame, plus a screenshot on key events."""

from __future__ import annotations

import csv
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from config import ROOT

COLUMNS = [
    "timestamp", "fps", "target_x", "target_y", "predicted_x", "predicted_y", "aim_x", "aim_y",
    "error_x", "error_y", "pid_x", "pid_y", "tracking_confidence", "green", "fire", "state", "latency",
    "search",  # label / arrow / blocked while turning towards the locked target
    "search_x", "search_y",  # label: estimated target position; arrow: crosshair + 300 px along it
    "dither_x", "dither_y",  # random counts added to pid_x/y (--dither, turret identification)
    "ring",  # share of the weapon range ring found green
    "range_conf", "in_range",  # weapon range evidence this frame / held long enough (READY)
    "lock_key",  # 1 = tapped the game's lock key (T) this frame
]
EVENT_MIN_INTERVAL_S = 1.0  # at most one screenshot per event type per second


class SessionLogger:
    def __init__(self, screenshot_dir: Path):
        stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
        self.csv_path = ROOT / "logs" / f"session_{stamp}.csv"
        self.shot_dir = screenshot_dir / f"events_{stamp}"
        self._file = open(self.csv_path, "w", newline="", encoding="utf-8")
        self._csv = csv.DictWriter(self._file, COLUMNS)
        self._csv.writeheader()
        self._last_shot: dict[str, float] = {}

    def row(self, **values) -> None:
        self._csv.writerow({k: _fmt(v) for k, v in values.items()})

    def event(self, name: str, image: np.ndarray | None) -> None:
        now = time.monotonic()
        if image is None or now - self._last_shot.get(name, -1e9) < EVENT_MIN_INTERVAL_S:
            return
        self._last_shot[name] = now
        self.shot_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{datetime.now():%H%M%S_%f}"[:-3] + f"_{name}.png"
        cv2.imwrite(str(self.shot_dir / filename), image)

    def close(self) -> None:
        self._file.close()


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)
