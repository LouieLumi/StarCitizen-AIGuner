"""Weapon range time filter tests. Run: python tests/test_weapon_range.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))

from config import RangeConfig  # noqa: E402
from detector import Detection  # noqa: E402
from weapon_range import RangeFilter  # noqa: E402

DT = 1 / 30
CFG = RangeConfig(min_ms=80, min_frames=3, ring_min_share=0.4)


def det(ring: float, pip: str | None = "green", aim_conf: float = 1.0) -> Detection:
    """pip: 'green', 'white' or None (not seen this frame)."""
    return Detection((600, 458), aim_conf, None if pip is None else (620, 450), 1.0 if pip else 0.0,
                     pip == "green", 20.0, ring, 150.0 if ring >= 0.4 else None)


def test_needs_time_and_frames() -> None:
    f = RangeFilter(CFG)
    states = [f.update(det(0.86), k * DT) for k in range(5)]
    assert all(s.evidence for s in states)
    # 3 frames = 67 ms: not yet; 4 frames = 100 ms >= 80 ms: in range
    assert [s.in_range for s in states] == [False, False, False, True, True]


def test_entry_is_strict() -> None:
    f = RangeFilter(CFG)
    f.update(det(0.86), 0.0)
    f.update(det(0.86), DT)
    assert not f.update(det(0.86, pip="white"), 2 * DT).in_range  # one frame against while building up...
    states = [f.update(det(0.86), (3 + k) * DT) for k in range(4)]
    assert [s.in_range for s in states] == [False, False, False, True]  # ...counts from scratch


def test_release_needs_two_frames_against() -> None:
    f = RangeFilter(CFG)
    for k in range(5):
        f.update(det(0.86), k * DT)
    s = f.update(det(0.86, pip="white"), 5 * DT)
    assert s.in_range and not s.evidence  # a stray frame is held through
    assert f.update(det(0.86), 6 * DT).in_range
    f.update(det(0.1), 7 * DT)
    assert not f.update(det(0.1), 8 * DT).in_range  # two in a row: out
    assert not f.update(det(0.86), 9 * DT).in_range  # and entry is strict again


def test_crosshair_lost_drops_at_once() -> None:
    f = RangeFilter(CFG)
    for k in range(5):
        f.update(det(0.86), k * DT)
    assert not f.update(det(0.86, aim_conf=0.0), 5 * DT).in_range


def test_ring_alone_counts_while_pip_unseen() -> None:
    f = RangeFilter(CFG)
    for k in range(5):
        s = f.update(det(0.86, pip=None if k % 2 else "green"), k * DT)
    assert s.in_range
    g = RangeFilter(CFG)
    for k in range(5):
        s = g.update(det(0.0, pip="green"), k * DT)  # green pip but no ring: not trusted
    assert not s.evidence and not s.in_range


if __name__ == "__main__":
    test_needs_time_and_frames()
    test_entry_is_strict()
    test_release_needs_two_frames_against()
    test_crosshair_lost_drops_at_once()
    test_ring_alone_counts_while_pip_unseen()
    print("weapon range tests: all passed")
