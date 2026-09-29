"""Search (turn towards the locked target) tests. Run: python tests/test_search.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))

from config import FinderConfig  # noqa: E402
from search import Search  # noqa: E402
from target_finder import TargetHint  # noqa: E402

AIM = (1280.0, 728.0)
DT = 1 / 30


def label(x: float, y: float) -> TargetHint:
    d = ((x - AIM[0]) ** 2 + (y - AIM[1]) ** 2) ** 0.5
    return TargetHint("label", ((x - AIM[0]) / d, (y - AIM[1]) / d), (x, y), d)


def arrow(dx: float, dy: float) -> TargetHint:
    return TargetHint("arrow", (dx, dy), None, None)


def test_label_proportional_and_capped() -> None:
    s = Search(FinderConfig(slew_kp=0.3, slew_counts=20, label_hold_px=0))
    assert s.step(label(1280 + 40, 728 - 20), AIM, 0.0) == (12, -6)  # 0.3 counts/px
    ux, uy = s.step(label(1280 + 800, 728 + 400), AIM, DT)  # far: capped, direction kept
    assert (ux, uy) == (20, 10)


def test_label_close_holds_still() -> None:
    s = Search(FinderConfig(slew_kp=0.3, slew_counts=20, label_hold_px=200, label_hold_s=0.7))
    assert s.step(label(1280 + 150, 728 - 50), AIM, 0.0) == (0, 0)
    assert s.step(label(1280 + 400, 728), AIM, DT) == (20, 0)


def test_label_close_but_no_pip_closes_in() -> None:
    s = Search(FinderConfig(slew_kp=0.3, slew_counts=20, label_hold_px=200, label_hold_s=0.7, label_close_px=50))
    t = 0.0
    while t < 0.65:  # waiting for the tracker to pick up the pip
        assert s.step(label(1280 + 150, 728), AIM, t) == (0, 0)
        t += DT
    assert s.step(label(1280 + 150, 728), AIM, 0.75) == (20, 0)  # no pip: close in (capped)
    assert s.step(label(1280 + 60, 728), AIM, 0.8) == (18, 0)  # proportional
    assert s.step(label(1280 + 40, 728), AIM, 0.85) == (0, 0)  # close enough


def test_arrow_constant_rate() -> None:
    s = Search(FinderConfig(arrow_counts=20))
    assert s.step(arrow(-1.0, 0.0), AIM, 0.0) == (-20, 0)
    assert s.step(arrow(0.6, -0.8), AIM, DT) == (12, -16)


def test_timeout_then_retry_after_hint_gone() -> None:
    s = Search(FinderConfig(arrow_counts=20, slew_timeout_s=2))
    t = 0.0
    while t < 2.0:
        assert s.step(arrow(1, 0), AIM, t) == (20, 0)
        t += DT
    assert s.step(arrow(1, 0), AIM, t + DT) == (0, 0) and s.blocked  # gave up
    assert s.step(arrow(1, 0), AIM, t + 1.0) == (0, 0)  # still resting while the arrow stays
    s.step(None, AIM, t + 1.1)  # arrow gone (target re-locked, ...)
    s.step(None, AIM, t + 2.2)
    assert not s.blocked
    assert s.step(arrow(1, 0), AIM, t + 2.3) == (20, 0)


def test_retry_while_hint_stays() -> None:
    s = Search(FinderConfig(arrow_counts=20, slew_timeout_s=2))
    t = 0.0
    while not s.blocked:
        s.step(arrow(1, 0), AIM, t)
        t += DT
    assert s.step(arrow(1, 0), AIM, t + 2.0) == (0, 0)  # resting
    assert s.step(arrow(1, 0), AIM, t + 3.1) == (20, 0) and not s.blocked  # tries again


def test_target_coming_on_screen_restarts_clock() -> None:
    s = Search(FinderConfig(arrow_counts=20, slew_timeout_s=2))
    t = 0.0
    while t < 1.9:  # most of the time budget spent following the arrow
        s.step(arrow(-1, 0), AIM, t)
        t += DT
    for _ in range(30):  # target now on screen: a fresh 2 s to reach it
        assert s.step(label(900, 700), AIM, t) != (0, 0)
        t += DT
    assert not s.blocked


if __name__ == "__main__":
    test_label_proportional_and_capped()
    test_label_close_holds_still()
    test_label_close_but_no_pip_closes_in()
    test_arrow_constant_rate()
    test_timeout_then_retry_after_hint_gone()
    test_retry_while_hint_stays()
    test_target_coming_on_screen_restarts_clock()
    print("search tests: all passed")
