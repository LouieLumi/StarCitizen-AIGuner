"""Pip tracker tests on synthetic motion. Run: python tests/test_tracker.py"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))

from config import TrackerConfig  # noqa: E402
from detector import Detection  # noqa: E402
from tracker import PipTracker  # noqa: E402

DT = 1 / 30
AIM = (600.0, 450.0)


def det(pos, conf=1.0) -> Detection:
    return Detection(AIM, 1.0, None if pos is None else (float(pos[0]), float(pos[1])), conf if pos is not None else 0.0, False, 20.0)


def run(tracker: PipTracker, t: float, pos, conf=1.0):
    tracker.predict(t)
    return tracker.update(det(pos, conf), t)


def test_constant_velocity() -> None:
    rng = np.random.default_rng(0)
    trk = PipTracker(TrackerConfig(accel_sigma=300))  # live setting: own motion is compensated
    v = np.array([120.0, -60.0])  # px/s
    for k in range(60):
        t = k * DT
        truth = np.array([500.0, 400.0]) + v * t
        st = run(trk, t, truth + rng.normal(0, 1.5, 2))
    assert st is not None
    assert abs(st.vx - v[0]) < 15 and abs(st.vy - v[1]) < 15, (st.vx, st.vy)
    assert np.hypot(st.x - truth[0], st.y - truth[1]) < 3
    assert st.confidence > 0.9


def test_short_gap_and_loss() -> None:
    trk = PipTracker(TrackerConfig(lost_after_ms=200))
    v = np.array([90.0, 0.0])
    k = 0
    for k in range(30):
        run(trk, k * DT, (500 + v[0] * k * DT, 400))
    # three missed frames (100 ms): coasting, still near the truth
    for k in range(30, 33):
        st = run(trk, k * DT, None)
    assert st is not None
    assert abs(st.x - (500 + v[0] * k * DT)) < 4, st.x
    # 100 ms more without a measurement: lost
    for k in range(33, 37):
        st = run(trk, k * DT, None)
    assert st is None and not trk.active


def test_outlier_gated() -> None:
    trk = PipTracker(TrackerConfig())
    for k in range(20):
        run(trk, k * DT, (500, 400))
    st = run(trk, 20 * DT, (700, 250))  # stray detection far away
    assert st is not None and abs(st.x - 500) < 2 and abs(st.y - 400) < 2
    assert trk.gated == 1


def test_fast_move_restarts() -> None:
    trk = PipTracker(TrackerConfig(acquire_frames=3))
    for k in range(20):
        run(trk, k * DT, (500, 400))
    run(trk, 20 * DT, (700, 250))  # far complete pips: ignored until confirmed
    run(trk, 21 * DT, (706, 252))
    st = run(trk, 22 * DT, (710, 253))  # third agreeing one: the pip really is over there
    assert st is not None and abs(st.x - 710) < 1 and abs(st.y - 253) < 1
    assert trk.restarts == 1


def test_no_restart_far_from_crosshair() -> None:
    trk = PipTracker(TrackerConfig(acquire_frames=3, acquire_radius_px=250))
    for k in range(20):
        run(trk, k * DT, (560, 440))
    for k in range(20, 24):  # 480 px from the crosshair: never restarts there
        st = run(trk, k * DT, (120, 690))
    assert trk.restarts == 0
    assert st is None or np.hypot(st.x - 120, st.y - 690) > 100


def test_acquire_needs_confirmation() -> None:
    trk = PipTracker(TrackerConfig(acquire_frames=3))
    assert run(trk, 0.0, (500, 400), conf=0.75) is None  # three chevrons never start a track
    assert run(trk, 1 * DT, (500, 400)) is None
    assert run(trk, 2 * DT, (503, 401)) is None
    assert run(trk, 3 * DT, (506, 402)) is not None  # third agreeing complete pip
    assert run(trk, 4 * DT, (508, 402), conf=0.75) is not None  # three chevrons may continue a track


def test_no_acquire_far_or_jumping() -> None:
    trk = PipTracker(TrackerConfig(acquire_frames=3, acquire_radius_px=250))
    for k in range(5):  # 400 px from the crosshair at (600, 450)
        assert run(trk, k * DT, (1000, 450)) is None
    trk = PipTracker(TrackerConfig(acquire_frames=3))
    for k, pos in enumerate([(500, 400), (560, 430), (500, 400), (560, 430)]):  # never agrees
        assert run(trk, k * DT, pos) is None


def test_acquire_fast_pip_with_velocity() -> None:
    trk = PipTracker(TrackerConfig(acquire_frames=3))
    track = None
    for k in range(3):  # 900 px/s: 30 px a frame, more than acquire_agree_px between frames
        track = run(trk, k * DT, (450 + 30 * k, 400))
    assert track is not None and abs(track.vx - 900) < 60, track
    trk = PipTracker(TrackerConfig(acquire_frames=3))
    for k, x in enumerate((450, 480, 540, 570)):  # speeds up and jumps: not consistent
        assert run(trk, k * DT, (x, 400)) is None


def test_shift() -> None:
    trk = PipTracker(TrackerConfig())
    for k in range(10):
        run(trk, k * DT, (500, 400))
    trk.shift(-30, 12)
    pos = trk.predict(10 * DT)
    assert abs(pos[0] - 470) < 1 and abs(pos[1] - 412) < 1


if __name__ == "__main__":
    test_constant_velocity()
    test_short_gap_and_loss()
    test_outlier_gated()
    test_fast_move_restarts()
    test_no_restart_far_from_crosshair()
    test_acquire_needs_confirmation()
    test_no_acquire_far_or_jumping()
    test_acquire_fast_pip_with_velocity()
    test_shift()
    print("tracker tests: all passed")
