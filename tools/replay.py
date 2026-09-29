"""Offline replay: run the vision pipeline (detector + Kalman tracker) on recorded
video. Never sends HID.

    python tools/replay.py D:\\...\\session_20260925_235339          # all segments, in parallel
    python tools/replay.py seg001.avi --video                        # also write an annotated video
    python tools/replay.py seg001.avi --show                         # watch it (desktop session)

Full-screen recordings are cropped to the configured ROI. Each video segment is
processed by its own worker (tracks don't carry across segment boundaries).
Writes <input>/analysis/replay_<time>.csv (one row per frame) and prints detection
and tracking statistics.
"""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))

from config import DEFAULT_PATH, load_config  # noqa: E402
from detector import HudDetector  # noqa: E402
from overlay import describe, draw_detection, draw_track  # noqa: E402
from tracker import PipTracker  # noqa: E402
from weapon_range import RangeFilter  # noqa: E402

VIDEO_SCALE = 0.5
TRACK_JOIN_FRAMES = 7  # detections this close in time (and <= 60 px apart) form one track
HEADER = ["segment", "frame", "t", "aim_x", "aim_y", "aim_conf", "pip_x", "pip_y", "pip_conf",
          "pip_green", "pip_r", "err_x", "err_y", "det_ms", "trk_x", "trk_y", "trk_vx", "trk_vy", "trk_conf", "trk_since",
          "ring", "ring_r", "range_evidence", "in_range"]


@dataclass
class SegmentResult:
    name: str
    rows: list[list] = field(default_factory=list)
    det_ms: list[float] = field(default_factory=list)
    jumps: list[float] = field(default_factory=list)
    runs: list[int] = field(default_factory=list)
    pips: list[tuple[int, float, float]] = field(default_factory=list)  # (frame, x, y)
    aim: int = 0
    pip_full: int = 0
    green: int = 0
    trk_frames: int = 0
    acquired: int = 0
    lost: int = 0
    gated: int = 0
    restarts: int = 0
    ring: int = 0  # frames with the range ring
    in_range: int = 0  # frames the filtered state says in range
    evidence_flips: int = 0  # changes of the per-frame evidence
    range_flips: int = 0  # changes of the filtered state
    pip_vs_ring: dict = field(default_factory=lambda: {k: 0 for k in ("G+ring", "G-ring", "W+ring", "W-ring")})


def segments(path: Path) -> list[Path]:
    if path.is_dir():
        vids = sorted(p for p in path.iterdir() if p.suffix in (".avi", ".mkv", ".mp4"))
        if not vids:
            raise SystemExit(f"no videos in {path}")
        return vids
    return [path]


def frame_times(video: Path) -> list[float] | None:
    """Present times from the recorder's CSV, if there is one."""
    side = video.with_suffix(".csv")
    if not side.exists():
        return None
    with open(side, encoding="utf-8") as f:
        return [float(row["present_time"]) for row in csv.DictReader(f)]


def run_segment(seg: Path, config: str, video_path: Path | None, show: bool, max_frames: int) -> SegmentResult:
    cfg = load_config(config)
    r = cfg.roi
    detector = HudDetector(cfg)
    tracker = PipTracker(cfg.tracker)
    weapon_range = RangeFilter(cfg.range)
    res = SegmentResult(seg.name)
    prev_ev = prev_in = False
    times = frame_times(seg)
    cap = cv2.VideoCapture(str(seg))
    writer = None
    prev_pip = None
    run = 0
    was_active = False
    idx = 0
    t_start = time.perf_counter()
    while not max_frames or idx < max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        h, w = frame.shape[:2]
        roi = frame[r.y:r.y + r.height, r.x:r.x + r.width] if (w, h) == (cfg.screen.width, cfg.screen.height) else frame
        t = times[idx] if times and idx < len(times) else idx / 30

        t0 = time.perf_counter()
        predicted = tracker.predict(t)
        det = detector.detect(roi, pip_hint=predicted)
        ms = (time.perf_counter() - t0) * 1000
        track = tracker.update(det, t)
        res.det_ms.append(ms)
        wr = weapon_range.update(det, t)
        ring_on = det.ring_radius is not None
        res.ring += ring_on
        res.in_range += wr.in_range
        res.evidence_flips += wr.evidence != prev_ev
        res.range_flips += wr.in_range != prev_in
        prev_ev, prev_in = wr.evidence, wr.in_range
        if det.pip is not None:
            res.pip_vs_ring[("G" if det.pip_green else "W") + ("+ring" if ring_on else "-ring")] += 1

        res.acquired += track is not None and not was_active
        res.lost += was_active and track is None
        was_active = track is not None
        res.trk_frames += was_active
        res.aim += det.aim_conf > 0
        if det.pip is not None:
            res.pip_full += det.pip_conf == 1.0
            res.green += det.pip_green
            if prev_pip is not None:
                res.jumps.append(float(np.hypot(det.pip[0] - prev_pip[0], det.pip[1] - prev_pip[1])))
            res.pips.append((idx, det.pip[0], det.pip[1]))
            run += 1
        elif run:
            res.runs.append(run)
            run = 0
        prev_pip = det.pip

        err = det.error
        res.rows.append([
            seg.name, idx, f"{t:.4f}", f"{det.aim[0]:.1f}", f"{det.aim[1]:.1f}", f"{det.aim_conf:.2f}",
            *(("", "", "0", "", "") if det.pip is None else
              (f"{det.pip[0]:.1f}", f"{det.pip[1]:.1f}", f"{det.pip_conf:.2f}", int(det.pip_green), f"{det.pip_radius:.1f}")),
            *(("", "") if err is None else (f"{err[0]:.1f}", f"{err[1]:.1f}")),
            f"{ms:.2f}",
            *(("",) * 6 if track is None else (f"{track.x:.1f}", f"{track.y:.1f}", f"{track.vx:.0f}", f"{track.vy:.0f}",
                                               f"{track.confidence:.2f}", f"{track.since_update * 1000:.0f}")),
            f"{det.ring:.2f}", "" if det.ring_radius is None else f"{det.ring_radius:.0f}", int(wr.evidence), int(wr.in_range),
        ])

        if video_path or show:
            view = draw_track(draw_detection(roi.copy(), det, [f"{seg.name} #{idx}"] + describe(det)), track)
            view = cv2.resize(view, None, fx=VIDEO_SCALE, fy=VIDEO_SCALE, interpolation=cv2.INTER_AREA)
            if video_path:
                if writer is None:
                    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"MJPG"), 30, view.shape[1::-1])
                writer.write(view)
            if show:
                cv2.imshow("replay", view)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
        idx += 1
        if idx % 2000 == 0:
            recent = sorted(res.det_ms[-2000:])
            print(f"{seg.name}: {idx} frames, {time.perf_counter() - t_start:.0f} s | detect ms median "
                  f"{recent[len(recent) // 2]:.1f} p95 {recent[int(0.95 * (len(recent) - 1))]:.1f}", flush=True)
    if run:
        res.runs.append(run)
    cap.release()
    if writer:
        writer.release()
    res.gated, res.restarts = tracker.gated, tracker.restarts
    return res


def report_tracks(results: list[SegmentResult], min_len: int = 15) -> None:
    """What a tracker would see from detections alone: detections joined into tracks
    across short gaps and jumps of up to 60 px."""
    tracks: list[list[tuple[int, float, float]]] = []
    for res in results:
        seg_tracks: list[list[tuple[int, float, float]]] = []
        for row, x, y in res.pips:
            if seg_tracks:
                prow, px, py = seg_tracks[-1][-1]
                if row - prow <= TRACK_JOIN_FRAMES and np.hypot(x - px, y - py) <= 60:
                    seg_tracks[-1].append((row, x, y))
                    continue
            seg_tracks.append([(row, x, y)])
        tracks += seg_tracks
    long_ = [t for t in tracks if t[-1][0] - t[0][0] + 1 >= min_len]
    if not long_:
        print("tracks: none >= 0.5 s")
        return
    span = sum(t[-1][0] - t[0][0] + 1 for t in long_)
    hits = sum(len(t) for t in long_)
    gaps = [b[0] - a[0] - 1 for t in long_ for a, b in zip(t, t[1:]) if b[0] - a[0] > 1]
    hist = {"1": sum(g == 1 for g in gaps), "2-3": sum(2 <= g <= 3 for g in gaps), "4-6": sum(g >= 4 for g in gaps)}
    lengths = sorted(t[-1][0] - t[0][0] + 1 for t in long_)
    print(f"tracks >= {min_len} frames: {len(long_)} (median {statistics.median(lengths):.0f}, max {lengths[-1]} frames) | "
          f"{span} frames spanned, pip found in {100 * hits / span:.1f}% | gaps (frames missed): {hist} | "
          f"short fragments outside tracks: {len(tracks) - len(long_)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="video file or session directory")
    ap.add_argument("--config", default=str(DEFAULT_PATH))
    ap.add_argument("--video", action="store_true", help="write annotated half-size ROI videos")
    ap.add_argument("--show", action="store_true", help="display while running (q quits; runs serially)")
    ap.add_argument("--max-frames", type=int, default=0, help="per segment")
    ap.add_argument("--jobs", type=int, default=0, help="parallel workers (default: one per segment, max cpus/2)")
    args = ap.parse_args()

    src = Path(args.input)
    segs = segments(src)
    out_dir = (src if src.is_dir() else src.parent) / "analysis"
    out_dir.mkdir(exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
    jobs = 1 if args.show else (args.jobs or max(1, min(len(segs), (os.cpu_count() or 2) // 2)))

    t0 = time.perf_counter()
    work = [(s, args.config, out_dir / f"replay_{stamp}_{s.stem}.avi" if args.video else None, args.show, args.max_frames)
            for s in segs]
    if jobs == 1:
        results = [run_segment(*w) for w in work]
    else:
        with ProcessPoolExecutor(jobs) as pool:
            results = list(pool.map(run_segment, *zip(*work)))
    cv2.destroyAllWindows()

    csv_path = out_dir / f"replay_{stamp}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        out = csv.writer(f)
        out.writerow(HEADER)
        for res in results:
            out.writerows(res.rows)

    rows = sum(len(r.rows) for r in results)
    if not rows:
        print("no frames read")
        return 1
    total = lambda attr: sum(getattr(r, attr) for r in results)  # noqa: E731
    pct = lambda n: f"{n} ({100 * n / rows:.1f}%)"  # noqa: E731
    det_ms = sorted(ms for r in results for ms in r.det_ms)
    runs = [x for r in results for x in r.runs]
    jumps = sorted(j for r in results for j in r.jumps)
    n_pip = sum(len(r.pips) for r in results)
    print(f"{len(segs)} segment(s), {jobs} worker(s), {time.perf_counter() - t0:.0f} s")
    print(f"frames {rows} | crosshair found {pct(total('aim'))} | pip {pct(n_pip)} "
          f"(all 4 chevrons {total('pip_full')}) | green pip {pct(total('green'))}")
    print(f"detect ms: median {statistics.median(det_ms):.2f} p95 {det_ms[int(0.95 * (len(det_ms) - 1))]:.2f} max {det_ms[-1]:.2f}")
    if runs:
        print(f"pip runs: {len(runs)} | length median {statistics.median(runs):.0f} frames, max {max(runs)} | "
              f"single-frame runs {sum(1 for x in runs if x == 1)}")
    if jumps:
        print(f"pip frame-to-frame jump px: median {statistics.median(jumps):.1f} p95 {jumps[int(0.95 * (len(jumps) - 1))]:.1f} "
              f"max {jumps[-1]:.1f} | jumps > 60 px: {sum(1 for x in jumps if x > 60)}")
    report_tracks(results)
    pvr = {k: sum(r.pip_vs_ring[k] for r in results) for k in results[0].pip_vs_ring}
    minutes = rows / 30 / 60
    print(f"weapon range: ring {pct(total('ring'))} | in range (filtered) {pct(total('in_range'))} | "
          f"changes per minute: per-frame evidence {total('evidence_flips') / minutes:.1f}, "
          f"filtered {total('range_flips') / minutes:.1f}")
    print("  pip colour vs ring (frames with a pip): " + ", ".join(f"{k} {v}" for k, v in pvr.items()))
    print(f"kalman: track active {pct(total('trk_frames'))} | acquired {total('acquired')} | lost {total('lost')} | "
          f"measurements gated out {total('gated')} | restarts on fast moves {total('restarts')}")
    print(f"csv: {csv_path}")
    if args.video:
        print(f"videos: {out_dir / f'replay_{stamp}_*.avi'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
