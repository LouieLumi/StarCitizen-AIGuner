"""Where is the locked target (T) when its pip is not near the crosshair?

- On screen: the locked target carries a red two-line label (name, then
  "distance [closing speed]", centre-aligned) under its bracket box; the target
  sits roughly label_to_target_px above the first line.
- Off screen: a red arrow (triangle + small ring) on a ~230-300 px circle around
  the crosshair points towards it.

Red chat names and fixed red HUD widgets are blanked (finder.exclude zones).
Takes full-screen frames and answers in screen coordinates. The red mask is made
at full resolution (thin text strokes), then OR-pooled to finder.scale for the
rest - all at full 2560x1440 costs ~30 ms a frame. The main loop runs it on every
finder.every-th frame only.
Sizes below are full-resolution px. See docs/hud.md.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from config import FinderConfig

LINE_KERNEL = (9, 3)  # closing that merges characters into text lines
LINE_W = (30, 160)
LINE_H = (8, 26)
LINE_GAP = (15, 40)  # vertical distance between the two label lines' centres
LINE_ALIGN = 15  # max horizontal offset of their centres
ARROW_MIN_PX = 25
ARROW_CONCENTRATION = 0.7  # a 30 deg window must hold this share of the red pixels in the ring


@dataclass
class TargetHint:
    kind: str  # "label" (target on screen) or "arrow" (off screen)
    direction: tuple[float, float]  # unit vector from the crosshair towards the target
    point: tuple[float, float] | None  # target position (label only), screen px
    distance: float | None  # px from the crosshair (label only)


class TargetFinder:
    def __init__(self, cfg: FinderConfig):
        self._cfg = cfg
        s = self._s = cfg.scale
        self._kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, round(LINE_KERNEL[0] * s)), max(1, round(LINE_KERNEL[1] * s))))
        self._line_w = (LINE_W[0] * s, LINE_W[1] * s)
        self._line_h = (LINE_H[0] * s, LINE_H[1] * s)
        self._line_gap = (LINE_GAP[0] * s, LINE_GAP[1] * s)
        self._line_align = LINE_ALIGN * s
        self._arrow_r = (cfg.arrow_radius[0] * s, cfg.arrow_radius[1] * s)
        self._arrow_min = max(4, round(ARROW_MIN_PX * s * s))
        self.red: np.ndarray | None = None  # last red mask (subsampled), for debugging

    def find(self, bgr: np.ndarray, aim: tuple[float, float]) -> TargetHint | None:
        c, s = self._cfg, self._s
        red = self._red_mask(bgr)
        if s != 1:
            # Any red pixel in a block keeps the block: thin text strokes survive.
            red = cv2.resize(red, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            red = cv2.threshold(red, 0, 255, cv2.THRESH_BINARY)[1]
        for x0, y0, x1, y1 in c.exclude:
            red[round(y0 * s):round(y1 * s), round(x0 * s):round(x1 * s)] = 0
        self.red = red
        aim_s = (aim[0] * s, aim[1] * s)
        hint = self._label(red, aim_s) or self._arrow(red, aim_s)
        if hint is not None and hint.point is not None:
            hint.point = (hint.point[0] / s, hint.point[1] / s)
            hint.distance = hint.distance / s
        return hint

    def _red_mask(self, bgr: np.ndarray) -> np.ndarray:
        """Full-resolution red mask (~12 ms at 2560x1440; splitting HSV channels to
        use cheaper single-channel ops is slower)."""
        c = self._cfg
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        return cv2.inRange(hsv, c.red_lower1, c.red_upper1) | cv2.inRange(hsv, c.red_lower2, c.red_upper2)

    def _label(self, red: np.ndarray, aim: tuple[float, float]) -> TargetHint | None:
        lines = cv2.morphologyEx(red, cv2.MORPH_CLOSE, self._kernel)
        n, _, stats, cents = cv2.connectedComponentsWithStats(lines, connectivity=8)
        (w0, w1), (h0, h1) = self._line_w, self._line_h
        cand = [
            cents[k] for k in range(1, n)
            if w0 <= stats[k, cv2.CC_STAT_WIDTH] <= w1 and h0 <= stats[k, cv2.CC_STAT_HEIGHT] <= h1
        ]
        (g0, g1), align = self._line_gap, self._line_align
        best = None
        for a in cand:
            for b in cand:
                if g0 <= b[1] - a[1] <= g1 and abs(b[0] - a[0]) <= align:
                    point = (float(a[0]), float(a[1] - self._cfg.label_to_target_px * self._s))
                    dist = float(np.hypot(point[0] - aim[0], point[1] - aim[1]))
                    if best is None or dist < best[1]:
                        best = (point, dist)
        if best is None:
            return None
        point, dist = best
        if dist < 1:
            return TargetHint("label", (0.0, 0.0), point, dist)
        return TargetHint("label", ((point[0] - aim[0]) / dist, (point[1] - aim[1]) / dist), point, dist)

    def _arrow(self, red: np.ndarray, aim: tuple[float, float]) -> TargetHint | None:
        r0, r1 = self._arrow_r
        ax, ay, rr1 = int(round(aim[0])), int(round(aim[1])), int(round(r1))
        y0, x0 = max(0, ay - rr1), max(0, ax - rr1)
        patch = red[y0:ay + rr1 + 1, x0:ax + rr1 + 1]
        ys, xs = np.nonzero(patch)
        dx, dy = xs + x0 - aim[0], ys + y0 - aim[1]
        rr = np.hypot(dx, dy)
        ring = (rr >= r0) & (rr <= r1)
        if int(ring.sum()) < self._arrow_min:
            return None
        ang = np.degrees(np.arctan2(dy[ring], dx[ring])) % 360
        hist = np.bincount((ang // 10).astype(int) % 36, minlength=36)
        window = hist + np.roll(hist, 1) + np.roll(hist, -1)  # bins i-1, i, i+1
        peak = int(window.argmax())
        if window[peak] < ARROW_CONCENTRATION * ring.sum():
            return None  # red scattered around the ring: lasers, sparks - not the arrow
        centre = (peak + 0.5) * 10
        sel = np.abs((ang - centre + 180) % 360 - 180) <= 15
        vx, vy = float(dx[ring][sel].sum()), float(dy[ring][sel].sum())
        norm = float(np.hypot(vx, vy)) or 1.0
        return TargetHint("arrow", (vx / norm, vy / norm), None, None)
