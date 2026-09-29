"""Kalman tracker for the lead pip, state [x, y, vx, vy] in screen/ROI px.

- Constant-velocity model; dt comes from real frame times.
- A pip is acquired only after acquire_frames consecutive four-chevron detections
  that move consistently (second within acquire_max_step_px of the first, each
  later one within acquire_agree_px of where the previous two put it - so fast
  pips qualify but jumping ones don't) and lie within acquire_radius_px of the
  crosshair (bright ship hulls can pass for a pip in single frames). The new
  track starts with the velocity of the last two. Measurements far outside
  the prediction (innovation gate) are treated as misses, so a stray detection
  can't drag the track away.
- Without measurements the track coasts on its prediction, but is dropped after
  lost_after_ms: never predict indefinitely.
- shift() applies known view motion (our own mouse input turning the turret), so
  the filter doesn't mistake camera rotation for target motion.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from config import TrackerConfig
from detector import Detection

HIT_SMOOTHING = 0.3  # EMA weight of the latest hit/miss in the confidence score


@dataclass
class TrackState:
    x: float
    y: float
    vx: float
    vy: float
    confidence: float  # 0..1, recent share of frames with an accepted measurement
    since_update: float  # s since the last accepted measurement
    green: bool  # last accepted measurement was a green (in range) pip


class PipTracker:
    def __init__(self, cfg: TrackerConfig):
        self._cfg = cfg
        self._x: np.ndarray | None = None  # state
        self._P: np.ndarray | None = None  # covariance
        self._t = 0.0  # time of the state
        self._t_update = 0.0
        self._conf = 0.0
        self._green = False
        self._candidate: list[tuple[float, np.ndarray]] = []  # (t, pos): consecutive full pips before (re)acquisition
        self.gated = 0  # measurements rejected by the gate (for stats)
        self.restarts = 0

    @property
    def active(self) -> bool:
        return self._x is not None

    def reset(self) -> None:
        self._x = self._P = None
        self._conf = 0.0
        self._candidate.clear()

    def predict(self, t: float) -> tuple[float, float] | None:
        """Advance to time t; returns the predicted pip position, or None when there is
        no track (or it just timed out)."""
        if self._x is None:
            return None
        if (t - self._t_update) * 1000 > self._cfg.lost_after_ms:
            self.reset()
            return None
        dt = max(0.0, t - self._t)
        F = np.eye(4)
        F[0, 2] = F[1, 3] = dt
        q = self._cfg.accel_sigma**2
        # white-noise acceleration
        Q = q * np.array([
            [dt**4 / 4, 0, dt**3 / 2, 0],
            [0, dt**4 / 4, 0, dt**3 / 2],
            [dt**3 / 2, 0, dt**2, 0],
            [0, dt**3 / 2, 0, dt**2],
        ])
        self._x = F @ self._x
        self._P = F @ self._P @ F.T + Q
        self._t = t
        return float(self._x[0]), float(self._x[1])

    def shift(self, dx: float, dy: float) -> None:
        """The view moved by (dx, dy) px for reasons we know about (our own input)."""
        if self._x is not None:
            self._x[0] += dx
            self._x[1] += dy
        for _, z in self._candidate:
            z += (dx, dy)

    def update(self, det: Detection, t: float) -> TrackState | None:
        """Feed this frame's detection (call predict(t) first). Returns the track, or
        None if there is none."""
        hit = False
        if det.pip is not None:
            z = np.array(det.pip)
            sigma = self._cfg.meas_sigma_px * (1.0 if det.pip_conf >= 1.0 else 2.0)
            R = np.eye(2) * sigma**2
            if self._x is None:
                v = self._confirm(z, det, t)
                if v is not None:
                    self._start(z, sigma, t, det.pip_green, v)
                    self._conf = HIT_SMOOTHING
                    return self.state(t)
                return None
            else:
                H = np.array([[1.0, 0, 0, 0], [0, 1.0, 0, 0]])
                y = z - H @ self._x
                S = H @ self._P @ H.T + R
                d2 = float(y @ np.linalg.solve(S, y))
                if d2 <= self._cfg.gate:
                    K = self._P @ H.T @ np.linalg.inv(S)
                    self._x = self._x + K @ y
                    self._P = (np.eye(4) - K @ H) @ self._P
                    self._t_update = t
                    self._green = det.pip_green
                    self._candidate.clear()
                    hit = True
                else:
                    self.gated += 1
                    # A stray pip is ignored, but if complete pips keep turning up somewhere
                    # else - confirmed exactly like a new acquisition - the pip really moved
                    # faster than the model allows (or the target changed): restart there.
                    v = self._confirm(z, det, t)
                    if v is not None:
                        self._start(z, sigma, t, det.pip_green, v)
                        self.restarts += 1
                        hit = True
        if self._x is None:
            self._candidate.clear()  # no detection this frame: confirmation restarts
            return None
        self._conf = (1 - HIT_SMOOTHING) * self._conf + HIT_SMOOTHING * hit
        return self.state(t)

    def _confirm(self, z: np.ndarray, det: Detection, t: float) -> np.ndarray | None:
        """Count consecutive complete pips near the crosshair that move consistently;
        once there are acquire_frames of them, returns their velocity (else None)."""
        c = self._cfg
        near_aim = np.hypot(z[0] - det.aim[0], z[1] - det.aim[1]) <= c.acquire_radius_px
        if det.pip_conf < 1.0 or not near_aim:
            self._candidate.clear()
            return None
        cand = self._candidate
        if len(cand) == 1:
            ok = np.hypot(*(z - cand[-1][1])) <= c.acquire_max_step_px
        elif len(cand) >= 2:
            (t0, z0), (t1, z1) = cand[-2], cand[-1]
            expected = z1 + (z1 - z0) * ((t - t1) / (t1 - t0) if t1 > t0 else 1.0)
            ok = np.hypot(*(z - expected)) <= c.acquire_agree_px
        else:
            ok = True
        if not ok:
            cand.clear()
        cand.append((t, z.copy()))
        if len(cand) >= c.acquire_frames:
            if len(cand) >= 2 and cand[-1][0] > cand[-2][0]:
                v = (cand[-1][1] - cand[-2][1]) / (cand[-1][0] - cand[-2][0])
            else:
                v = np.zeros(2)
            cand.clear()
            return v
        return None

    def _start(self, z: np.ndarray, sigma: float, t: float, green: bool, v: np.ndarray | None = None) -> None:
        vx, vy = (0.0, 0.0) if v is None else (float(v[0]), float(v[1]))
        self._x = np.array([z[0], z[1], vx, vy])
        self._P = np.diag([sigma**2, sigma**2, self._cfg.init_speed_px_s**2, self._cfg.init_speed_px_s**2])
        self._t = self._t_update = t
        self._green = green
        self._candidate.clear()

    def state(self, t: float) -> TrackState | None:
        if self._x is None:
            return None
        x, y, vx, vy = (float(v) for v in self._x)
        return TrackState(x, y, vx, vy, self._conf, t - self._t_update, self._green)
