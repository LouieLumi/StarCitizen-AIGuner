"""Controller test on a simulated turret. No game, no HID.

Plant (FPS-mode turret): 1 mouse count turns the view by --gain px; nothing
shows for --latency - 1 frames, then each frame closes a share of 1 - --smoothing
of the remaining gap (like control.view_delay_frames / view_smoothing, measured
with tools/turret_ident.py; by default the plant is what the config says). The
measured pip position has --noise px of jitter. The loop is main.py's: the real
PipTracker (acquisition, gate, own-motion shift) feeds the controller position
and velocity, OwnMotion models our turns, the Smith predictor counts turns in
flight. Scenarios: target jumps 200 px, sinusoid, steady crossing, fast crossing.

    python tools/controller_test.py                          # plant = config
    python tools/controller_test.py --latency 3 --smoothing 0.8   # plant differs from the model
    python tools/controller_test.py --kp 0.6 --kff 0 --no-smith
    python tools/controller_test.py --sweep                  # stability vs Kp
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import deque
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))

from config import DEFAULT_PATH, load_config  # noqa: E402
from controller import PDController  # noqa: E402
from detector import Detection  # noqa: E402
from own_motion import OwnMotion  # noqa: E402
from tracker import PipTracker  # noqa: E402

FPS = 30
SECONDS = 8
AIM = (600.0, 458.0)


def scenarios() -> dict:
    return {
        "step 200px": lambda t: 200.0 if t >= 0.5 else 0.0,
        "sine 150px 0.3Hz": lambda t: 150 * math.sin(2 * math.pi * 0.3 * t),
        "cross 60px/s": lambda t: 60.0 * t,
        "cross 300px/s": lambda t: 300.0 * t,
    }


def simulate(cfg, target, gain: float, latency: int, smoothing: float, noise: float, seed: int = 0):
    rng = np.random.default_rng(seed)
    c = cfg.control
    ctl, tracker = PDController(c), PipTracker(cfg.tracker)
    own = OwnMotion(c.view_delay_frames, c.view_smoothing, c.px_per_count)
    commanded = view = 0.0  # where we told the turret to point / where it points (px)
    pipeline = deque([0] * (latency - 1))  # counts sent but not acting yet
    errs, outs = [], []
    dt = 1 / FPS
    for k in range(SECONDS * FPS):
        t = k * dt
        e = target(t) - view
        tracker.predict(t)
        tracker.shift(-own.next_frame()[0], 0.0)
        pip = (AIM[0] + e + rng.normal(0, noise), AIM[1] + rng.normal(0, noise))
        track = tracker.update(Detection(AIM, 1.0, pip, 1.0, False, 20.0), t)
        counts = 0
        if track is not None:
            ex = track.x - AIM[0] - (own.in_flight[0] if c.smith_predictor else 0.0)
            if c.lead_target and abs(track.vx) >= c.ff_min_speed:
                ex += track.vx * own.mean_delay_frames * dt * c.lead_scale
            counts, _ = ctl.step((ex, track.y - AIM[1]), dt, (track.vx, track.vy))
        own.sent((counts, 0))
        pipeline.append(counts)
        commanded += gain * pipeline.popleft()
        view += (1 - smoothing) * (commanded - view)
        errs.append(e)
        outs.append(counts)
    return np.array(errs), np.array(outs)


def metrics(name: str, errs: np.ndarray, outs: np.ndarray) -> str:
    settled = errs[len(errs) // 2:]
    rms = float(np.sqrt(np.mean(settled**2)))
    sign_changes = int(np.sum(np.diff(np.sign(outs[outs != 0])) != 0))
    if name.startswith("step"):
        after = errs[int(0.5 * FPS):]
        overshoot = max(0.0, float(-after.min()))  # error went past zero
        within = np.nonzero(np.abs(after) < 20)[0]
        t20 = f"{within[0] / FPS:.2f}s" if within.size else "never"
        return f"{name:18s} to <20px {t20:>6s} | overshoot {overshoot:5.1f}px | settled rms {rms:5.1f}px | output reversals {sign_changes}"
    return f"{name:18s} settled rms {rms:5.1f}px | max |e| {float(np.abs(settled).max()):6.1f}px | output reversals {sign_changes}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(DEFAULT_PATH))
    ap.add_argument("--gain", type=float, help="plant px per mouse count (default: config)")
    ap.add_argument("--latency", type=int, help="plant: first frame a command shows in, 1 = next (default: config)")
    ap.add_argument("--smoothing", type=float, help="plant: share of the gap left each frame (default: config)")
    ap.add_argument("--noise", type=float, default=1.5, help="measurement noise, px")
    ap.add_argument("--kp", type=float, help="override kp_x")
    ap.add_argument("--kd", type=float, help="override kd_x")
    ap.add_argument("--kff", type=float, help="override the velocity feed-forward gain")
    ap.add_argument("--ff-min", type=float, help="override ff_min_speed (px/s)")
    ap.add_argument("--assume-delay", type=int, help="override view_delay_frames (the controller's model)")
    ap.add_argument("--assume-smoothing", type=float, help="override view_smoothing (the controller's model)")
    ap.add_argument("--no-smith", action="store_true", help="don't count turns in flight")
    ap.add_argument("--no-lead", action="store_true", help="aim at the pip, not where it will be")
    ap.add_argument("--sweep", action="store_true", help="step response for a range of Kp")
    args = ap.parse_args()

    cfg = load_config(args.config)
    over = {k: v for k, v in {
        "kp_x": args.kp, "kd_x": args.kd, "kff": args.kff, "ff_min_speed": args.ff_min,
        "view_delay_frames": args.assume_delay, "view_smoothing": args.assume_smoothing,
    }.items() if v is not None}
    if args.no_smith:
        over["smith_predictor"] = False
    if args.no_lead:
        over["lead_target"] = False
    cfg = cfg.model_copy(update={"control": cfg.control.model_copy(update=over)})
    c = cfg.control
    gain = c.px_per_count if args.gain is None else args.gain
    latency = c.view_delay_frames if args.latency is None else args.latency
    smoothing = c.view_smoothing if args.smoothing is None else args.smoothing
    if latency < 1:
        ap.error("--latency is at least 1 (the next frame)")

    print(f"plant: {gain} px/count, shows from frame {latency}, smoothing {smoothing} @ {FPS} fps, noise {args.noise} px")
    print(f"model: delay {c.view_delay_frames} smoothing {c.view_smoothing} smith {c.smith_predictor} lead {c.lead_target}")
    if args.sweep:
        for kp in (0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.3):
            ck = cfg.model_copy(update={"control": c.model_copy(update={"kp_x": kp})})
            errs, outs = simulate(ck, scenarios()["step 200px"], gain, latency, smoothing, args.noise)
            print(f"kp {kp:4.2f}: " + metrics("step 200px", errs, outs))
        return 0

    print(f"controller: kp {c.kp_x} kd {c.kd_x} kff {c.kff} ff_min {c.ff_min_speed} deadzone {c.deadzone_x} "
          f"clamp {c.max_mouse_dx} schedule {c.gain_schedule}")
    for name, target in scenarios().items():
        errs, outs = simulate(cfg, target, gain, latency, smoothing, args.noise)
        print(metrics(name, errs, outs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
