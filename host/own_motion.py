"""Our own turns as the captured frames will show them.

The turret doesn't jump to a new direction: nothing is visible for a few frames,
then the view closes in on the commanded direction (measured with
tools/turret_ident.py). Share of a turn visible L frames after sending it:

    s(L) = 0                                  L < delay
    s(L) = 1 - smoothing ** (L - delay + 1)   L >= delay

Used for three things:
- the tracker is told about each frame's part of our turns as it shows up, so
  the pip's velocity is the target's alone;
- in_flight is what we have commanded but can't see yet; the controller counts
  it as done (Smith predictor), or it keeps turning until the view catches up
  and swings past;
- mean_delay_frames is how far ahead the controller aims at a moving pip.
"""

from __future__ import annotations

import numpy as np

HORIZON = 60  # frames; whatever is still missing by then counts as shown


class OwnMotion:
    def __init__(self, delay: int, smoothing: float, px_per_count: float):
        L = np.arange(1, HORIZON + 1)
        s = np.where(L >= delay, 1 - smoothing ** np.maximum(L - delay + 1, 1), 0.0)
        s[-1] = 1.0
        self._h = np.diff(np.r_[0.0, s]) * px_per_count  # px per count shown in frame L
        self._pending = np.zeros((HORIZON, 2))  # [0] = shown in the next frame

    def reset(self) -> None:
        self._pending[:] = 0

    def sent(self, counts: tuple[int, int]) -> None:
        """This frame's command went out."""
        if counts[0] or counts[1]:
            self._pending += self._h[:, None] * np.array(counts, float)

    def next_frame(self) -> tuple[float, float]:
        """View motion (px, direction of the turn) that shows in the next frame."""
        v = self._pending[0].copy()
        self._pending = np.roll(self._pending, -1, axis=0)
        self._pending[-1] = 0
        return float(v[0]), float(v[1])

    @property
    def mean_delay_frames(self) -> float:
        """Average frames from sending a turn to seeing it: how far ahead to aim at
        a moving pip so that our turn lands where it will be."""
        L = np.arange(1, HORIZON + 1)
        return float(L @ self._h / self._h.sum())

    @property
    def in_flight(self) -> tuple[float, float]:
        """Turn commanded but not visible yet (px)."""
        t = self._pending.sum(axis=0)
        return float(t[0]), float(t[1])
