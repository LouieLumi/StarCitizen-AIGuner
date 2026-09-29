"""Replay live session logs through the tracker with other settings.

Each logged frame's pip detection and the turn we sent are fed to PipTracker (with
OwnMotion, as main.py does), so tracker settings can be compared on real target
motion without playing. The turns are the logged ones - how a different tracker
would have steered isn't simulated - so this measures how well a tracker keeps
hold of the pip, not the aim error.

    python tools/track_replay.py logs/session_A.csv logs/session_B.csv
    python tools/track_replay.py logs/session_*.csv --grid     # try a range of settings

Columns: held = frames with a visible pip that the tracker has a track for;
accepted = visible pips taken as measurements; dropped = tracks lost while the pip
was still in view (gated for lost_after_ms); jumps = accepted measurements more
than 40 px from the prediction (risk of following a wrong detection).
"""

from __future__ import annotations

import argparse
import csv
import itertools
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))

from config import DEFAULT_PATH, load_config  # noqa: E402
from detector import Detection  # noqa: E402
from own_motion import OwnMotion  # noqa: E402
from tracker import PipTracker  # noqa: E402

JUMP_PX = 40
MAX_FRAME_GAP_S = 0.2  # a longer gap (program restart, pause) starts over


def _f(v) -> float | None:
    return float(v) if v not in ("", None) else None


def load(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return [
            {"t": _f(r["timestamp"]), "pip": (_f(r["target_x"]), _f(r["target_y"])) if r["target_x"] else None,
             "aim": (_f(r["aim_x"]), _f(r["aim_y"])), "sent": (int(_f(r["pid_x"]) or 0), int(_f(r["pid_y"]) or 0))}
            for r in csv.DictReader(fh)
        ]


def replay(sessions: list[list[dict]], cfg) -> dict:
    c = cfg.control
    n = {"seen": 0, "held": 0, "accepted": 0, "dropped": 0, "jumps": 0, "restarts": 0}
    for rows in sessions:
        tr = PipTracker(cfg.tracker)
        own = OwnMotion(c.view_delay_frames, c.view_smoothing, c.px_per_count)
        t_prev, recent_pip = None, 0
        for r in rows:
            t = r["t"]
            if t_prev is not None and t - t_prev > MAX_FRAME_GAP_S:
                tr.reset()
                own.reset()
            t_prev = t
            had = tr.active
            pred = tr.predict(t)
            if had and not tr.active and recent_pip >= 3:
                n["dropped"] += 1  # timed out although the pip kept showing
            sx, sy = own.next_frame()
            tr.shift(-sx, -sy)
            if pred is not None:
                pred = (pred[0] - sx, pred[1] - sy)
            pip = r["pip"]
            restarts = tr.restarts
            track = tr.update(Detection(r["aim"], 1.0, pip, 1.0 if pip else 0.0, False, 20.0), t)
            n["restarts"] += tr.restarts - restarts
            if pip is not None:
                n["seen"] += 1
                recent_pip = recent_pip + 1
                if track is not None:
                    n["held"] += 1
                    if track.since_update == 0:
                        n["accepted"] += 1
                        if pred is not None and np.hypot(pip[0] - pred[0], pip[1] - pred[1]) > JUMP_PX:
                            n["jumps"] += 1
            else:
                recent_pip = 0
            own.sent(r["sent"])
    return n


def fmt(n: dict) -> str:
    s = max(1, n["seen"])
    return (f"held {100 * n['held'] / s:5.1f}% | accepted {100 * n['accepted'] / s:5.1f}% | "
            f"dropped {n['dropped']:4d} | restarts {n['restarts']:4d} | jumps {n['jumps']:4d}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--config", default=str(DEFAULT_PATH))
    ap.add_argument("--grid", action="store_true", help="try a range of tracker settings")
    args = ap.parse_args()
    cfg = load_config(args.config)
    sessions = [load(p) for p in args.csv]
    print(f"{sum(len(s) for s in sessions)} frames from {len(sessions)} session(s)")
    t = cfg.tracker
    print(f"config  (accel {t.accel_sigma:.0f}, gate {t.gate}, lost {t.lost_after_ms} ms, sigma {t.meas_sigma_px}): "
          + fmt(replay(sessions, cfg)))
    if args.grid:
        for accel, gate, lost, sigma in itertools.product((1000, 2000, 3500, 6000), (13.8, 25.0), (200, 300), (2.0, 3.0)):
            tc = t.model_copy(update={"accel_sigma": accel, "gate": gate, "lost_after_ms": lost, "meas_sigma_px": sigma})
            n = replay(sessions, cfg.model_copy(update={"tracker": tc}))
            print(f"accel {accel:5d} gate {gate:4.1f} lost {lost} sigma {sigma:.0f}: " + fmt(n), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
