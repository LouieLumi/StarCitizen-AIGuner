"""Gunner state machine. Pure logic: the main loop feeds events and the current
track, and asks whether the turret may move / fire.

    DISABLED --enable--> ARMED --track--> TRACKING --fire conditions--> READY --> FIRING
    track lost (from TRACKING/READY/FIRING) --> TARGET_LOST --hold--> SEARCHING
    any --emergency--> EMERGENCY_STOP, latched: only 'disable' leaves it (to DISABLED)

Tracking motion is allowed only while TRACKING/READY/FIRING; turning towards the
locked target (search) only while ARMED/SEARCHING. READY = tracked target in
weapon range; FIRING = READY with auto fire on. The trigger (fire_control.py)
opens only from READY/FIRING with auto fire on and may stay held while the target
is briefly lost; DISABLED / EMERGENCY_STOP (auto fire off) release it at once.
"""

from __future__ import annotations

from enum import Enum


class State(Enum):
    DISABLED = "DISABLED"
    ARMED = "ARMED"
    SEARCHING = "SEARCHING"
    TRACKING = "TRACKING"
    READY = "READY"
    FIRING = "FIRING"
    TARGET_LOST = "TARGET_LOST"
    EMERGENCY_STOP = "EMERGENCY_STOP"


ENGAGED = (State.TRACKING, State.READY, State.FIRING)
TARGET_LOST_HOLD_S = 0.5  # stay in TARGET_LOST this long before SEARCHING


class GunnerStateMachine:
    def __init__(self) -> None:
        self.state = State.DISABLED
        self.auto_fire = False
        self._lost_at = 0.0
        self.transitions: list[tuple[float, State, State]] = []  # (t, from, to) since last drain

    # ---------------------------------------------------------------- events

    def enable(self, t: float) -> None:
        if self.state == State.DISABLED:
            self._go(State.ARMED, t)

    def disable(self, t: float) -> None:
        self.auto_fire = False
        if self.state != State.DISABLED:
            self._go(State.DISABLED, t)

    def emergency(self, t: float) -> None:
        self.auto_fire = False
        if self.state != State.EMERGENCY_STOP:
            self._go(State.EMERGENCY_STOP, t)

    def toggle_auto_fire(self) -> None:
        if self.state not in (State.DISABLED, State.EMERGENCY_STOP):
            self.auto_fire = not self.auto_fire

    def set_auto_fire(self, on: bool) -> None:
        """Only while enabled; disable / emergency always switch it off."""
        if self.state not in (State.DISABLED, State.EMERGENCY_STOP):
            self.auto_fire = on

    # ---------------------------------------------------------------- per frame

    def update(self, t: float, tracking: bool, fire_ready: bool = False) -> State:
        """tracking: a confident, live track exists. fire_ready: the tracked target is in
        weapon range (the trigger itself is host/fire_control.py's)."""
        s = self.state
        if s in (State.DISABLED, State.EMERGENCY_STOP):
            return s
        if s in ENGAGED and not tracking:
            self._lost_at = t
            self._go(State.TARGET_LOST, t)
        elif s in (State.ARMED, State.SEARCHING, State.TARGET_LOST) and tracking:
            self._go(State.TRACKING, t)
        elif s == State.TARGET_LOST and t - self._lost_at >= TARGET_LOST_HOLD_S:
            self._go(State.SEARCHING, t)
        elif s == State.TRACKING and fire_ready:
            self._go(State.READY, t)
        elif s == State.READY:
            if not fire_ready:
                self._go(State.TRACKING, t)
            elif self.auto_fire:
                self._go(State.FIRING, t)
        elif s == State.FIRING and (not fire_ready or not self.auto_fire):
            self._go(State.READY if fire_ready else State.TRACKING, t)
        return self.state

    @property
    def may_move(self) -> bool:
        return self.state in ENGAGED

    @property
    def may_search(self) -> bool:
        return self.state in (State.ARMED, State.SEARCHING)

    @property
    def may_fire(self) -> bool:
        return self.state == State.FIRING and self.auto_fire

    def drain_transitions(self) -> list[tuple[float, State, State]]:
        out, self.transitions = self.transitions, []
        return out

    def _go(self, new: State, t: float) -> None:
        self.transitions.append((t, self.state, new))
        self.state = new
