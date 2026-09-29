"""Is the locked target within weapon range? Read from the HUD, filtered in time.

Per frame, the evidence is the green range ring around the crosshair, and - when
the pip is seen - a green pip (a white pip means out of range, whatever the ring
says). The spec forbids acting on a single green frame, so the target only counts
as in range after the evidence has held for range.min_ms and range.min_frames in
a row; any frame against it (no ring, white pip) starts that count over.
Once in range, it takes range.release_frames frames against in a row to drop
out: single frames with the thin chevrons or the ring washed out would otherwise
cut every run short. Losing the crosshair (HUD gone) drops out at once.
"""

from __future__ import annotations

from dataclasses import dataclass

from config import RangeConfig
from detector import Detection

FULL_RING = 0.85  # typical share of the ring found when it is there (0.83-0.92)


@dataclass
class RangeState:
    evidence: bool  # this frame says in range
    confidence: float  # 0..1 for this frame
    in_range: bool  # evidence held long enough
    held_s: float  # how long the evidence has held


class RangeFilter:
    def __init__(self, cfg: RangeConfig):
        self._cfg = cfg
        self._since: float | None = None
        self._frames = 0
        self._in_range = False
        self._against = 0  # frames against in a row while in range

    def reset(self) -> None:
        self._since, self._frames = None, 0
        self._in_range, self._against = False, 0

    def update(self, det: Detection, t: float) -> RangeState:
        c = self._cfg
        ring = min(1.0, det.ring / FULL_RING) if det.ring >= c.ring_min_share else 0.0
        if det.aim_conf == 0 or (det.pip is not None and not det.pip_green):
            ring = 0.0  # HUD not seen, or the pip itself says out of range
        confidence = ring if det.pip is None else ring * (1.0 if det.pip_conf >= 1.0 else 0.9)
        evidence = confidence > 0
        if not evidence:
            self._against += 1
            if self._in_range and det.aim_conf > 0 and self._against < c.release_frames:
                return RangeState(False, confidence, True, t - self._since)  # hold through a stray frame
            self.reset()
            return RangeState(False, confidence, False, 0.0)
        self._against = 0
        if self._since is None:
            self._since = t
        self._frames += 1
        held = t - self._since
        self._in_range = self._in_range or (self._frames >= c.min_frames and held * 1000 >= c.min_ms)
        return RangeState(True, confidence, self._in_range, held)
