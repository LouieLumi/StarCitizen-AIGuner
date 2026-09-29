"""Record a whole play session for offline HUD analysis and replay.

Records the full screen (or just the ROI) as 5-minute video segments, each with
a CSV of frame present times, plus a lossless PNG still every few seconds for
exact colour sampling. Runs until the stop file appears, the time limit is
reached, or the disk gets low. Encoding runs on its own thread and drops
frames rather than slowing capture (drops are reported).

    python tools/record_session.py                    # full screen, MJPG, until stopped
    python tools/record_session.py --roi --codec ffv1 # ROI only, lossless
    type nul > logs\\stop_record                       # stop cleanly (from any shell)
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))

from capture import CaptureError, ScreenCapture  # noqa: E402
from config import DEFAULT_PATH, ROOT, RoiConfig, load_config  # noqa: E402
from recorder import CODECS, VideoRecorder  # noqa: E402

STOP_FILE = ROOT / "logs" / "stop_record"
REPORT_EVERY_S = 10


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(DEFAULT_PATH))
    ap.add_argument("--roi", action="store_true", help="record only the configured ROI (default: full screen)")
    ap.add_argument("--codec", choices=sorted(CODECS), default="mjpg")
    ap.add_argument("--quality", type=int, default=95, help="MJPG quality 1-100")
    ap.add_argument("--segment", type=float, default=300, help="seconds per video file")
    ap.add_argument("--still-every", type=float, default=5, help="seconds between lossless PNG stills (0 = off)")
    ap.add_argument("--max-minutes", type=float, default=180)
    ap.add_argument("--min-free-gb", type=float, default=20)
    args = ap.parse_args()

    cfg = load_config(args.config)
    if not args.roi:
        full = RoiConfig(x=0, y=0, width=cfg.screen.width, height=cfg.screen.height)
        cfg = cfg.model_copy(update={"roi": full})
    r = cfg.roi
    session = cfg.recording.path / f"session_{datetime.now():%Y%m%d_%H%M%S}"
    session.mkdir(parents=True)
    STOP_FILE.unlink(missing_ok=True)
    print(f"recording {r.width}x{r.height} at ({r.x},{r.y}) codec={args.codec} -> {session}")
    print(f"stop: create {STOP_FILE}", flush=True)

    recorder: VideoRecorder | None = None
    segment = 0
    written = dropped = stills = 0
    reason = "?"

    def close_segment() -> None:
        nonlocal recorder, written, dropped
        if recorder:
            recorder.close()
            written += recorder.written
            dropped += recorder.dropped
            print(f"segment {segment:03d} closed: {recorder.written} frames, {recorder.dropped} dropped", flush=True)
            recorder = None

    try:
        with ScreenCapture(cfg) as cap:
            t_start = seg_start = last_still = time.perf_counter()
            next_report = t_start + REPORT_EVERY_S
            win_frames = 0
            while True:
                now = time.perf_counter()
                if STOP_FILE.exists():
                    reason = "stop file"
                    break
                if now - t_start > args.max_minutes * 60:
                    reason = "time limit"
                    break
                if recorder is None or now - seg_start >= args.segment:
                    close_segment()
                    free_gb = shutil.disk_usage(session).free / 1e9
                    if free_gb < args.min_free_gb:
                        reason = f"disk low ({free_gb:.1f} GB free)"
                        break
                    segment += 1
                    recorder = VideoRecorder(
                        session / f"seg{segment:03d}", (r.width, r.height), fps=30, codec=args.codec,
                        max_queue=30, quality=args.quality,
                    )
                    seg_start = now

                frame = cap.read(timeout=0.2)
                if frame is not None:
                    recorder.write(frame.image, frame.present_time)
                    win_frames += 1
                    if args.still_every and now - last_still >= args.still_every:
                        name = f"still_{datetime.now():%H%M%S_%f}"[:-3] + ".png"
                        cv2.imwrite(str(session / name), frame.image, [cv2.IMWRITE_PNG_COMPRESSION, 1])
                        stills += 1
                        last_still = now

                if now >= next_report:
                    elapsed = now - t_start
                    size_gb = sum(f.stat().st_size for f in session.iterdir()) / 1e9
                    print(
                        f"{elapsed / 60:5.1f} min | {win_frames / REPORT_EVERY_S:4.1f} fps | "
                        f"dropped so far {dropped + recorder.dropped} | stills {stills} | {size_gb:.2f} GB",
                        flush=True,
                    )
                    win_frames = 0
                    next_report = now + REPORT_EVERY_S
    except CaptureError as e:
        print(f"FAIL: {e}")
        return 1
    finally:
        close_segment()
        STOP_FILE.unlink(missing_ok=True)

    print(f"stopped ({reason}): {segment} segments, {written} frames, {dropped} dropped, {stills} stills -> {session}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
