"""Auto fire decision tests. Run: python tests/test_fire_control.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))

from config import FireConfig  # noqa: E402
from fire_control import FireControl  # noqa: E402
from state_machine import GunnerStateMachine, State  # noqa: E402

DT = 1 / 30
CFG = FireConfig(stop_after_unlocked_s=1.0)


def test_opens_fire_on_green_only_when_armed() -> None:
    f = FireControl(CFG)
    assert not f.trigger(0.0, armed=False, in_range=True, locked=True)  # auto fire off: never
    assert not f.trigger(DT, armed=True, in_range=False, locked=True)  # locked but not green yet
    assert f.trigger(2 * DT, armed=True, in_range=True, locked=True)  # green: open fire


def test_keeps_firing_until_unlocked_for_a_while() -> None:
    f = FireControl(CFG)
    f.trigger(0.0, True, True, True)
    assert f.trigger(0.5, True, in_range=False, locked=True)  # target turned white: keep firing
    assert f.trigger(1.0, True, False, locked=True)  # last frame with the target
    assert f.trigger(1.5, True, False, locked=False)  # lock lost...
    assert f.trigger(1.9, True, False, locked=False)  # ...for 0.9 s: still firing
    assert f.trigger(2.0, True, False, locked=True)  # locked again in time: stream goes on
    assert f.trigger(2.9, True, False, locked=False)
    assert not f.trigger(3.1, True, False, locked=False)  # gone 1.1 s: cease fire
    assert not f.trigger(3.2, True, False, locked=True)  # locked but not green: stays ceased
    assert f.trigger(3.3, True, True, True)  # green again: open fire


def test_end_or_auto_fire_off_releases_at_once() -> None:
    f = FireControl(CFG)
    assert f.trigger(0.0, True, True, True)
    assert not f.trigger(DT, armed=False, in_range=True, locked=True)
    assert not f.trigger(2 * DT, armed=True, in_range=False, locked=True)  # re-armed: waits for green again


def test_continuous_or_burst_limited() -> None:
    f = FireControl(CFG)  # max_burst_s 0: continuous
    assert all(f.trigger(k * DT, True, True, True) for k in range(300))  # 10 s without a pause
    f = FireControl(CFG.model_copy(update={"max_burst_s": 2.0, "release_s": 0.3}))
    held = [f.trigger(k * DT, True, True, True) for k in range(75)]
    first_release = held.index(False)
    assert abs(first_release * DT - 2.0) < DT
    back = held.index(True, first_release)
    assert abs((back - first_release) * DT - 0.3) < 2 * DT


def test_with_state_machine() -> None:
    sm, f = GunnerStateMachine(), FireControl(CFG)
    armed = lambda: sm.auto_fire and sm.state not in (State.DISABLED, State.EMERGENCY_STOP)  # noqa: E731
    ready = lambda: sm.state in (State.READY, State.FIRING)  # noqa: E731
    sm.enable(0.0)
    sm.toggle_auto_fire()
    sm.update(0.1, tracking=True)
    assert not f.trigger(0.1, armed(), ready(), True)  # tracking, not in range
    sm.update(0.2, tracking=True, fire_ready=True)
    sm.update(0.23, tracking=True, fire_ready=True)
    assert sm.state == State.FIRING and f.trigger(0.23, armed(), ready(), True)
    sm.update(0.3, tracking=False)  # track lost: TARGET_LOST, trigger still held
    assert sm.state == State.TARGET_LOST and f.trigger(0.3, armed(), ready(), False)
    sm.emergency(0.4)  # stop file
    assert not f.trigger(0.4, armed(), ready(), True)


if __name__ == "__main__":
    test_opens_fire_on_green_only_when_armed()
    test_keeps_firing_until_unlocked_for_a_while()
    test_end_or_auto_fire_off_releases_at_once()
    test_continuous_or_burst_limited()
    test_with_state_machine()
    print("fire control tests: all passed")
