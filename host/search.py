"""Turn the turret towards the locked target the finder points at, until its pip is
close enough for the tracker to take over.

- On-screen target (label): proportional to the distance, so it slows down as the
  target nears the crosshair; within label_hold_px it holds still for the tracker
  to pick up the pip - for label_hold_s at most: a far target has no pip at all,
  so after that it keeps closing in on the label's estimate (to label_close_px).
- Off-screen target (arrow): constant rate (arrow_counts per frame) along the arrow.
- On-screen speed is capped at slew_counts per frame, keeping the direction.
- Gives up after slew_timeout_s of turning without progress (e.g. the target is
  outside the turret's arc; the target coming on screen restarts the clock) and
  tries again after RETRY_AFTER_S (the target may have come round into reach),
  or as soon as the finder has lost the target for a second (e.g. re-locked).
"""

from __future__ import annotations

from config import FinderConfig
from target_finder import TargetHint

RETRY_AFTER_NO_HINT_S = 1.0
RETRY_AFTER_S = 3.0  # blocked this long: try again even though the hint is still there


class Search:
    def __init__(self, cfg: FinderConfig):
        self._cfg = cfg
        self._since: float | None = None  # start of the current turn
        self._kind: str | None = None  # hint kind the current turn started with
        self._no_hint_since: float | None = None
        self._blocked_at = 0.0
        self._hold_since: float | None = None  # label close, waiting for the pip
        self.blocked = False  # timed out; waiting a while (or for the hint to go away)

    def reset(self) -> None:
        self._since = self._no_hint_since = self._hold_since = None
        self.blocked = False

    def step(self, hint: TargetHint | None, aim: tuple[float, float], t: float) -> tuple[int, int]:
        """Mouse counts for this frame (screen px geometry, like the finder)."""
        c = self._cfg
        if hint is None:
            if self._no_hint_since is None:
                self._no_hint_since = t
            if t - self._no_hint_since >= RETRY_AFTER_NO_HINT_S:
                self.blocked = False
            self._since = None
            return 0, 0
        self._no_hint_since = None
        if self.blocked:
            if t - self._blocked_at < RETRY_AFTER_S:
                return 0, 0
            self.blocked, self._since = False, None
        if self._since is None or hint.kind != self._kind:
            # a new turn - or the target just came on screen, which is progress
            self._since, self._kind = t, hint.kind
        if t - self._since > c.slew_timeout_s:
            self.blocked, self._blocked_at = True, t
            return 0, 0

        if hint.point is not None:
            if hint.distance is not None and hint.distance <= c.label_hold_px:
                # The pip should be within the tracker's reach; the label only estimates
                # where the target is (+-50 px), so hold still and let the tracker confirm
                # it. A far target shows no pip, though: then keep closing in slowly.
                self._hold_since = t if self._hold_since is None else self._hold_since
                if t - self._hold_since < c.label_hold_s or hint.distance <= c.label_close_px:
                    return 0, 0
            else:
                self._hold_since = None
            ux, uy = c.slew_kp * (hint.point[0] - aim[0]), c.slew_kp * (hint.point[1] - aim[1])
            cap = c.slew_counts
        else:  # off screen: turn fast, precision doesn't matter yet
            ux, uy = c.arrow_counts * hint.direction[0], c.arrow_counts * hint.direction[1]
            cap = c.arrow_counts
        biggest = max(abs(ux), abs(uy))
        if biggest > cap:
            ux, uy = ux * cap / biggest, uy * cap / biggest
        return int(round(ux)), int(round(uy))
