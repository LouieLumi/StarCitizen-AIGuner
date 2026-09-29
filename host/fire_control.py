"""Auto fire (M7): when to hold the trigger. Rules as the user asked for them:

- only while the weapons switch is on (panel or --auto-fire) and fire control is
  on; switching either off releases at once;
- open fire once the tracked target is in weapon range - green, held >= 80 ms
  (host/weapon_range.py) - no aiming condition;
- then keep firing, whatever the aim or range does, until the target has not
  been locked (no tracked or detected pip) for fire.stop_after_unlocked_s;
  locking it again in time keeps the stream going.

fire.max_burst_s > 0 would add a forced pause (fire.release_s) after that long;
0 = continuous.
"""

from __future__ import annotations

from config import FireConfig


class FireControl:
    def __init__(self, cfg: FireConfig):
        self._cfg = cfg
        self.firing = False
        self._last_locked = -1e9
        self._burst_start: float | None = None
        self._rest_until = 0.0

    def trigger(self, t: float, armed: bool, in_range: bool, locked: bool) -> bool:
        """Hold the trigger this frame?

        armed: auto fire on and the gunner enabled (not DISABLED / EMERGENCY_STOP).
        in_range: tracked target in weapon range (the state machine's READY / FIRING).
        locked: the target is still there (tracked, or its pip seen this frame)."""
        c = self._cfg
        if not armed:
            self.firing, self._burst_start = False, None
            return False
        if locked:
            self._last_locked = t
        if not self.firing:
            if in_range:
                self.firing, self._last_locked = True, t
        elif t - self._last_locked > c.stop_after_unlocked_s:
            self.firing, self._burst_start = False, None
        if not self.firing:
            return False
        if t < self._rest_until:
            return False
        if self._burst_start is None:
            self._burst_start = t
        if c.max_burst_s > 0 and t - self._burst_start >= c.max_burst_s:
            self._burst_start = None
            self._rest_until = t + c.release_s
            return False
        return True
