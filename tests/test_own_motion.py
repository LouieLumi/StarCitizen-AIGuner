"""Own-motion model tests. Run: python tests/test_own_motion.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))

from own_motion import OwnMotion  # noqa: E402


def close(a, b, tol=1e-9) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_pure_delay() -> None:
    m = OwnMotion(delay=3, smoothing=0.0, px_per_count=0.5)
    m.sent((10, -4))
    assert close(m.in_flight, (5.0, -2.0))
    assert close(m.next_frame(), (0, 0)) and close(m.next_frame(), (0, 0))
    assert close(m.next_frame(), (5.0, -2.0))  # shows in the third frame
    assert close(m.in_flight, (0, 0)) and close(m.next_frame(), (0, 0))
    assert abs(m.mean_delay_frames - 3.0) < 1e-9


def test_smoothing_spreads_and_completes() -> None:
    m = OwnMotion(delay=1, smoothing=0.5, px_per_count=1.0)
    m.sent((8, 0))
    shown = [m.next_frame()[0] for _ in range(4)]
    assert close(shown, (4.0, 2.0, 1.0, 0.5))  # half of what's left each frame
    total = sum(shown) + sum(m.next_frame()[0] for _ in range(100))
    assert abs(total - 8.0) < 1e-9  # nothing lost
    assert abs(OwnMotion(1, 0.5, 1.0).mean_delay_frames - 2.0) < 1e-6


def test_turns_add_up() -> None:
    m = OwnMotion(delay=2, smoothing=0.0, px_per_count=1.0)
    m.sent((3, 0))
    m.next_frame()
    m.sent((4, 0))
    assert close(m.in_flight, (7.0, 0.0))
    assert close(m.next_frame(), (3.0, 0.0)) and close(m.next_frame(), (4.0, 0.0))


if __name__ == "__main__":
    test_pure_delay()
    test_smoothing_spreads_and_completes()
    test_turns_add_up()
    print("own motion tests: all passed")
