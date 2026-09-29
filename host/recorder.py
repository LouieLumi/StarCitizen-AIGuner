"""Background video recorder for captured ROI frames (input for offline replay).

Writes <stem>.mkv (lossless FFV1, so HUD colours survive for HSV tuning) or
<stem>.avi (MJPG, cheaper), plus <stem>.csv with each frame's present time so
replay can reproduce the real frame timing. Encoding runs on its own thread;
if it falls behind, frames are dropped and counted rather than stalling capture.
"""

from __future__ import annotations

import csv
import queue
import threading
from pathlib import Path

import cv2
import numpy as np

CODECS = {"ffv1": ("FFV1", ".mkv"), "mjpg": ("MJPG", ".avi")}


class VideoRecorder:
    def __init__(
        self,
        stem: Path,
        size: tuple[int, int],
        fps: float = 60,
        codec: str = "ffv1",
        max_queue: int = 120,
        quality: int = 95,
    ):
        fourcc, ext = CODECS[codec]
        self.video_path = stem.with_suffix(ext)
        self.csv_path = stem.with_suffix(".csv")
        self._writer = cv2.VideoWriter(str(self.video_path), cv2.VideoWriter_fourcc(*fourcc), fps, size)
        if not self._writer.isOpened():
            raise RuntimeError(f"cannot open video writer for {self.video_path}")
        if codec == "mjpg":
            self._writer.set(cv2.VIDEOWRITER_PROP_QUALITY, quality)
        self._csv_file = open(self.csv_path, "w", newline="", encoding="utf-8")
        self._csv = csv.writer(self._csv_file)
        self._csv.writerow(["frame", "present_time"])
        self._queue: queue.Queue = queue.Queue(max_queue)
        self.written = 0
        self.dropped = 0
        self._thread = threading.Thread(target=self._run, name="recorder", daemon=True)
        self._thread.start()

    def write(self, image: np.ndarray, present_time: float) -> None:
        try:
            self._queue.put_nowait((image, present_time))
        except queue.Full:
            self.dropped += 1

    def _run(self) -> None:
        while (item := self._queue.get()) is not None:
            image, present_time = item
            self._writer.write(image)
            self._csv.writerow([self.written, f"{present_time:.6f}"])
            self.written += 1

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join()
        self._writer.release()
        self._csv_file.close()
