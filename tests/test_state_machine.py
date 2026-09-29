"""State machine tests. Run: python tests/test_state_machine.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))

from state_machine import GunnerStateMachine, State  # noqa: E402


def test_disabled_ignores_targets() -> None:
    sm = GunnerStateMachine()
    assert sm.update(0.0, tracking=True, fire_ready=True) == State.DISABLED
    assert not sm.may_move and not sm.may_fire


def test_track_lose_search() -> None:
    sm = GunnerStateMachine()
    sm.enable(0.0)
    assert sm.state == State.ARMED and not sm.may_move and sm.may_search
    assert sm.update(0.1, tracking=True) == State.TRACKING and sm.may_move and not sm.may_search
    assert sm.update(0.2, tracking=False) == State.TARGET_LOST and not sm.may_move and not sm.may_search
    assert sm.update(0.5, tracking=False) == State.TARGET_LOST
    assert sm.update(0.8, tracking=False) == State.SEARCHING and sm.may_search
    assert sm.update(0.9, tracking=True) == State.TRACKING


def test_fire_needs_auto_fire_and_conditions() -> None:
    sm = GunnerStateMachine()
    sm.enable(0.0)
    sm.update(0.1, tracking=True)
    assert sm.update(0.2, tracking=True, fire_ready=True) == State.READY
    assert sm.update(0.3, tracking=True, fire_ready=True) == State.READY and not sm.may_fire  # auto fire off
    sm.toggle_auto_fire()
    assert sm.update(0.4, tracking=True, fire_ready=True) == State.FIRING and sm.may_fire
    assert sm.update(0.5, tracking=True, fire_ready=False) == State.TRACKING and not sm.may_fire
    sm.update(0.6, tracking=True, fire_ready=True)
    sm.update(0.7, tracking=True, fire_ready=True)
    assert sm.state == State.FIRING
    assert sm.update(0.8, tracking=False, fire_ready=True) == State.TARGET_LOST and not sm.may_fire


def test_emergency_is_latched() -> None:
    sm = GunnerStateMachine()
    sm.enable(0.0)
    sm.toggle_auto_fire()
    sm.update(0.1, tracking=True)
    sm.emergency(0.2)
    assert sm.state == State.EMERGENCY_STOP and not sm.may_move and not sm.may_search and not sm.auto_fire
    sm.enable(0.3)  # enable alone does not leave the emergency stop
    assert sm.update(0.4, tracking=True) == State.EMERGENCY_STOP
    sm.disable(0.5)
    sm.enable(0.6)
    assert sm.state == State.ARMED


def test_transitions_logged() -> None:
    sm = GunnerStateMachine()
    sm.enable(1.0)
    sm.update(1.1, tracking=True)
    assert [(a.value, b.value) for _, a, b in sm.drain_transitions()] == [("DISABLED", "ARMED"), ("ARMED", "TRACKING")]
    assert sm.drain_transitions() == []


def test_set_auto_fire_only_while_enabled() -> None:
    sm = GunnerStateMachine()
    sm.set_auto_fire(True)
    assert not sm.auto_fire  # disabled: stays off
    sm.enable(0.0)
    sm.set_auto_fire(True)
    assert sm.auto_fire
    sm.emergency(0.1)
    assert not sm.auto_fire
    sm.set_auto_fire(True)
    assert not sm.auto_fire  # emergency stop: stays off


if __name__ == "__main__":
    test_disabled_ignores_targets()
    test_track_lose_search()
    test_fire_needs_auto_fire_and_conditions()
    test_emergency_is_latched()
    test_transitions_logged()
    test_set_auto_fire_only_while_enabled()
    print("state machine tests: all passed")
