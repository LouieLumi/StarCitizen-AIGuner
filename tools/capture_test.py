"""Milestone 3 test: capture the ROI and report capture FPS, processing FPS and frame latency.

    python tools/capture_test.py                             # preview window, q / Esc quits
    python tools/capture_test.py --seconds 10 --no-window    # headless: nothing takes focus from the game
    python tools/capture_test.py --snapshot                  # also save one ROI frame to recording.dir
    python tools/capture_test.py --pattern --seconds 10      # animate a window inside the ROI (no game needed)
    python tools/capture_test.py --record --seconds 60       # record the ROI to recording.dir for replay

capture fps     new frames delivered per second (capped by the game and monitor refresh)
processing fps  how fast per-frame processing could run (BGR->HSV as a stand-in for the detector)
latency         frame age when processing finishes: screen present -> result ready
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))

from capture import CaptureError, ScreenCapture  # noqa: E402
from config import DEFAULT_PATH, load_config  # noqa: E402
from recorder import CODECS, VideoRecorder  # noqa: E402

WINDOW = "AI Gunner - capture test"
PATTERN_WINDOW = "AI Gunner - test pattern"
PREVIEW_WIDTH = 640
PATTERN_SIZE = (400, 300)


def draw_pattern(n: int) -> None:
    """Moving bar + counter, so every screen refresh produces a new frame inside the ROI."""
    w, h = PATTERN_SIZE
    img = np.zeros((h, w, 3), np.uint8)
    x = (n * 8) % w
    cv2.rectangle(img, (x, 0), (x + 20, h), (0, 200, 0), -1)
    cv2.putText(img, str(n), (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
    cv2.imshow(PATTERN_WINDOW, img)


def p95(values: list[float]) -> float:
    return sorted(values)[int(0.95 * (len(values) - 1))]


def open_preview(roi_region: tuple[int, int, int, int], scale: float, roi_h: int) -> None:
    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
    cv2.moveWindow(WINDOW, 0, 0)
    left, top, _, _ = roi_region
    if left < PREVIEW_WIDTH and top < int(roi_h * scale) + 40:
        print("warning: preview window overlaps the ROI and will capture itself")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(DEFAULT_PATH))
    ap.add_argument("--seconds", type=float, default=0, help="stop after N seconds (default: run until q/Esc)")
    ap.add_argument("--no-window", action="store_true", help="no preview window")
    ap.add_argument("--snapshot", action="store_true", help="save one ROI frame to recording.dir")
    ap.add_argument("--pattern", action="store_true", help="animate a test window inside the ROI")
    ap.add_argument("--record", action="store_true", help="record the ROI to recording.dir (video + frame times)")
    ap.add_argument("--codec", choices=sorted(CODECS), help="override recording.codec (ffv1 = lossless, mjpg = cheaper)")
    args = ap.parse_args()
    if args.no_window and not args.seconds:
        ap.error("--no-window needs --seconds")

    cfg = load_config(args.config)
    r = cfg.roi
    print(
        f"screen {cfg.screen.width}x{cfg.screen.height}  roi x={r.x} y={r.y} {r.width}x{r.height}  "
        f"target_fps={cfg.capture.target_fps}"
    )

    scale = PREVIEW_WIDTH / r.width
    if not args.no_window:
        open_preview(r.region, scale, r.height)
    if args.pattern:
        cv2.namedWindow(PATTERN_WINDOW, cv2.WINDOW_AUTOSIZE)
        cv2.moveWindow(PATTERN_WINDOW, r.x + (r.width - PATTERN_SIZE[0]) // 2, r.y + (r.height - PATTERN_SIZE[1]) // 2)
    pattern_n = 0

    all_fps: list[float] = []
    all_proc: list[float] = []
    all_age: list[float] = []
    snapshot_pending = args.snapshot
    status = "waiting for frames"
    out_dir = cfg.recording.path
    if args.record or args.snapshot:
        out_dir.mkdir(parents=True, exist_ok=True)
    recorder = None
    if args.record:
        stem = out_dir / f"capture_{datetime.now():%Y%m%d_%H%M%S}"
        recorder = VideoRecorder(stem, (r.width, r.height), fps=60, codec=args.codec or cfg.recording.codec)
        print(f"recording to {recorder.video_path}")

    try:
        with ScreenCapture(cfg) as cap:
            t_start = win_start = time.perf_counter()
            frames, idle = 0, 0
            proc: list[float] = []
            age: list[float] = []

            while not (args.seconds and time.perf_counter() - t_start >= args.seconds):
                if args.pattern:
                    draw_pattern(pattern_n)
                    pattern_n += 1
                frame = cap.read(timeout=0.1)
                if frame is None:
                    idle += 1
                else:
                    t0 = time.perf_counter()
                    cv2.cvtColor(frame.image, cv2.COLOR_BGR2HSV)
                    t1 = time.perf_counter()
                    frames += 1
                    proc.append((t1 - t0) * 1000)
                    age.append(frame.age_ms(t1))
                    if recorder:
                        recorder.write(frame.image, frame.present_time)

                    if snapshot_pending and t1 - t_start > 1.0:
                        out = out_dir / f"capture_{datetime.now():%Y%m%d_%H%M%S}.png"
                        cv2.imwrite(str(out), frame.image)
                        print(f"snapshot saved: {out}")
                        snapshot_pending = False

                    if not args.no_window:
                        view = cv2.resize(frame.image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                        cv2.putText(view, status, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)
                        cv2.imshow(WINDOW, view)

                if (not args.no_window or args.pattern) and (cv2.waitKey(1) & 0xFF) in (ord("q"), 27):
                    break

                now = time.perf_counter()
                if now - win_start >= 1.0:
                    fps = frames / (now - win_start)
                    if proc:
                        mean_proc = statistics.fmean(proc)
                        status = (
                            f"capture {fps:5.1f} fps | processing {1000 / mean_proc:6.0f} fps ({mean_proc:.2f} ms) | "
                            f"latency avg {statistics.fmean(age):5.1f} p95 {p95(age):5.1f} max {max(age):5.1f} ms"
                        )
                    else:
                        status = "capture   0.0 fps | screen not changing"
                    if idle:
                        status += f" | idle {idle}x100ms"
                    print(status, flush=True)
                    all_fps.append(fps)
                    all_proc += proc
                    all_age += age
                    win_start, frames, idle, proc, age = now, 0, 0, [], []
    except CaptureError as e:
        print(f"FAIL: {e}")
        return 1
    finally:
        cv2.destroyAllWindows()
        if recorder:
            recorder.close()
            print(f"recorded {recorder.written} frames, dropped {recorder.dropped} -> {recorder.video_path}")

    if not all_age:
        print("summary: no frames captured - is anything changing on screen?")
        return 1
    fps_med = statistics.median(all_fps)
    print(
        f"summary: capture fps median {fps_med:.1f} min {min(all_fps):.1f} | "
        f"processing {statistics.fmean(all_proc):.2f} ms/frame | "
        f"latency median {statistics.median(all_age):.1f} p95 {p95(all_age):.1f} max {max(all_age):.1f} ms"
    )
    verdict = "PASS (>=60)" if fps_med >= 59 else "ACCEPTABLE (>=30)" if fps_med >= 30 else "BELOW TARGET (<30)"
    print(f"M3 capture rate: {verdict}  (only meaningful while the game is rendering)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
