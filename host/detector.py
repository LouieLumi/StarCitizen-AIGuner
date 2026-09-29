"""Star Citizen turret HUD detector: crosshair centre and lead pip.

- Crosshair: four thick white bars around the aim point. Its centre drifts a
  few px and the bars spread in and out, so it is measured every frame. With no
  target locked the game shows a variant instead - two tall arcs "( )" left and
  right of the centre - which still says the turret HUD is up (aim_conf 0.5).
- Lead pip: four small inward chevrons (^ < > v) in a diamond. White when the
  target is out of weapon range, green when in range. The pip is where the
  game says to aim; the control error is pip - crosshair.
- Range ring: thin green circle around the crosshair while the target is in
  weapon range; reported as the share of the circle that is green.

All coordinates are pixels of the image passed to detect() (normally the ROI).
See docs/hud.md for the measurements behind the thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from config import Config

# Crosshair bar geometry at 2560x1440 (bars measured 8-14 x 48-70 px).
BAR_SHORT_SIDE = (6, 18)
BAR_LONG_SIDE = (35, 90)
BAR_MIN_AREA = 200
BAR_SEARCH_RADIUS = 260  # bars lie within this distance of the expected centre

# Arc variant ("( )", no target locked), measured: 24 x 120 px each, ~95 px left and
# right of the centre. Thin bright core with coloured fringes: found by brightness.
ARC_V_MIN = 200
ARC_HEIGHT = (90, 160)
ARC_WIDTH = (8, 40)
ARC_DX = (60, 135)  # |arc centre x - crosshair x|
ARC_DY_MAX = 25  # the two arcs' centres differ this little in height

CHEVRON_MAX_SIDE = 20  # motion blur can double a chevron
CHEVRON_MAX_ASPECT = 3.0
MAX_CANDIDATES = 400  # above this the frame is too cluttered to trust
HINT_RADIUS = 60  # a three-chevron pip must be this close to the tracked pip
# Weapon-group text, relative to the crosshair centre: x -90..+78, y +124..+152
# measured, plus a margin.
TEXT_ZONE = ((-100, 90), (114, 162))
PIP_GREEN_FRACTION = 0.6  # share of chevron pixels that must be green for a green pip


@dataclass
class Detection:
    aim: tuple[float, float]  # crosshair centre (fallback when aim_conf == 0)
    aim_conf: float  # 0..1, share of the four crosshair bars found
    pip: tuple[float, float] | None  # lead pip centre
    pip_conf: float  # 1.0 all four chevrons, 0.75 three, 0 none
    pip_green: bool  # target inside weapon range
    pip_radius: float
    ring: float = 0.0  # share of the weapon range ring found green (0..1)
    ring_radius: float | None = None  # px, when ring >= range.ring_min_share

    @property
    def error(self) -> tuple[float, float] | None:
        """pip - aim, i.e. how far the crosshair must move to sit on the pip."""
        if self.pip is None:
            return None
        return (self.pip[0] - self.aim[0], self.pip[1] - self.aim[1])


class HudDetector:
    def __init__(self, cfg: Config, offset: tuple[int, int] = (0, 0)):
        """offset: position of the ROI inside the image given to detect(), for
        running on full-screen frames instead of ROI crops."""
        self._cfg = cfg
        self._aim_fallback = (cfg.aim.center_x + offset[0], cfg.aim.center_y + offset[1])
        self._last_aim = self._aim_fallback
        self.masks: dict[str, np.ndarray] = {}  # last frame's masks, for debugging

    def detect(self, bgr: np.ndarray, pip_hint: tuple[float, float] | None = None) -> Detection:
        """pip_hint: where the pip is expected (last / predicted position). Lets a pip
        with one chevron hidden (e.g. behind a crosshair bar) keep being tracked."""
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        aim, aim_conf = self._find_crosshair(hsv)
        if aim_conf > 0:
            self._last_aim = aim
        else:
            aim = self._last_aim
        pip, pip_conf, pip_green, radius = self._find_pip(hsv, pip_hint, aim)
        ring, ring_radius = self._find_ring(hsv, aim) if aim_conf > 0 else (0.0, None)
        return Detection(aim, aim_conf, pip, pip_conf, pip_green, radius, ring, ring_radius)

    # ------------------------------------------------------------------ crosshair

    def _find_crosshair(self, hsv: np.ndarray) -> tuple[tuple[float, float], float]:
        c = self._cfg.crosshair
        mask = cv2.inRange(hsv, c.white_lower, c.white_upper)
        self.masks["crosshair"] = mask
        n, _, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)

        # Anchor on the nominal centre, not the last result, so one bad frame can't drag
        # the search away (the crosshair itself only drifts a few tens of px).
        ex, ey = self._aim_fallback
        horiz, vert = [], []  # bar centres
        for k in range(1, n):
            x, y, w, h, area = stats[k]
            short, long_ = min(w, h), max(w, h)
            if area < BAR_MIN_AREA or not (BAR_SHORT_SIDE[0] <= short <= BAR_SHORT_SIDE[1]):
                continue
            if not (BAR_LONG_SIDE[0] <= long_ <= BAR_LONG_SIDE[1]):
                continue
            cx, cy = cents[k]
            if (cx - ex) ** 2 + (cy - ey) ** 2 > BAR_SEARCH_RADIUS**2:
                continue
            (horiz if w > h else vert).append((cx, cy))

        # Left/right bars must be on opposite sides of the centre, top/bottom likewise;
        # keep the one nearest the expected centre on each side.
        left = min((b for b in horiz if b[0] < ex), key=lambda b: abs(b[1] - ey), default=None)
        right = min((b for b in horiz if b[0] >= ex), key=lambda b: abs(b[1] - ey), default=None)
        top = min((b for b in vert if b[1] < ey), key=lambda b: abs(b[0] - ex), default=None)
        bottom = min((b for b in vert if b[1] >= ey), key=lambda b: abs(b[0] - ex), default=None)
        found = [b for b in (left, right, top, bottom) if b is not None]
        if not found:
            return self._find_arcs(hsv)

        # x from the vertical bars and y from the horizontal ones: a bar cut short by
        # the weapon-group text still has the right cross-axis coordinate.
        xs = [b[0] for b in (top, bottom) if b]
        if not xs and left and right:
            xs = [(left[0] + right[0]) / 2]
        ys = [b[1] for b in (left, right) if b]
        if not ys and top and bottom:
            ys = [(top[1] + bottom[1]) / 2]
        if not xs or not ys:
            return self._find_arcs(hsv)
        return (float(np.mean(xs)), float(np.mean(ys))), len(found) / 4

    def _find_arcs(self, hsv: np.ndarray) -> tuple[tuple[float, float], float]:
        """The "( )" crosshair variant: two tall bright arcs, one each side of the
        nominal centre at about the same height. Confidence 0.5 when found."""
        ex, ey = self._aim_fallback
        r = BAR_SEARCH_RADIUS
        x0, y0 = max(0, int(ex - r)), max(0, int(ey - r))
        crop = hsv[y0:int(ey + r), x0:int(ex + r)]
        bright = cv2.inRange(crop, (0, 0, ARC_V_MIN), (180, 255, 255))
        n, _, stats, cents = cv2.connectedComponentsWithStats(bright, connectivity=8)
        left, right = [], []
        for k in range(1, n):
            w, h = stats[k, cv2.CC_STAT_WIDTH], stats[k, cv2.CC_STAT_HEIGHT]
            if not (ARC_HEIGHT[0] <= h <= ARC_HEIGHT[1] and ARC_WIDTH[0] <= w <= ARC_WIDTH[1]):
                continue
            cx, cy = cents[k][0] + x0, cents[k][1] + y0
            if abs(cy - ey) > ARC_HEIGHT[1] / 2:
                continue
            if ARC_DX[0] <= ex - cx <= ARC_DX[1]:
                left.append((cx, cy))
            elif ARC_DX[0] <= cx - ex <= ARC_DX[1]:
                right.append((cx, cy))
        pairs = [(a, b) for a in left for b in right if abs(a[1] - b[1]) <= ARC_DY_MAX]
        if not pairs:
            return self._last_aim, 0.0
        a, b = min(pairs, key=lambda ab: abs((ab[0][0] + ab[1][0]) / 2 - ex))
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), 0.5

    # ------------------------------------------------------------------ range ring

    def _find_ring(self, hsv: np.ndarray, aim: tuple[float, float]) -> tuple[float, float | None]:
        """Share of the circle around the crosshair that is ring-green, at the best
        radius. Unrolled to polar (rows = 1 deg, columns = 1 px of radius), a ring is
        a column that is green almost all the way down; the crosshair bars cut it
        in four, which costs a few percent."""
        c = self._cfg.range
        r1 = c.ring_radius[1] + 3
        ax, ay = int(round(aim[0])), int(round(aim[1]))
        x0, y0 = max(0, ax - r1), max(0, ay - r1)
        crop = hsv[y0:ay + r1, x0:ax + r1]
        green = cv2.inRange(crop, c.ring_lower, c.ring_upper)
        self.masks["ring"] = green
        polar = cv2.warpPolar(green, (r1, 360), (ax - x0, ay - y0), r1, cv2.WARP_POLAR_LINEAR) > 0
        deg = np.arange(360)
        side = np.minimum(np.abs(deg - 0), np.abs(deg - 360)) < c.ring_skip_deg
        side |= np.abs(deg - 180) < c.ring_skip_deg  # ammo counters left and right
        polar = polar[~side]
        near = polar.copy()  # +-2 px of radius: the ring is thin and not perfectly round
        for d in (1, 2):
            near[:, d:] |= polar[:, :-d]
            near[:, :-d] |= polar[:, d:]
        share = near[:, c.ring_radius[0]:c.ring_radius[1] + 1].mean(axis=0)
        best = int(np.argmax(share))
        found = float(share[best])
        return found, (float(c.ring_radius[0] + best) if found >= c.ring_min_share else None)

    # ------------------------------------------------------------------ lead pip

    def _find_pip(
        self, hsv: np.ndarray, hint: tuple[float, float] | None, aim: tuple[float, float]
    ) -> tuple[tuple[float, float] | None, float, bool, float]:
        p = self._cfg.pip
        # Chevron shapes come from brightness, not a colour key: a white chevron is a
        # 1 px core with chromatic fringes and is only V-shaped together with them.
        # Saturated pixels outside the yellow-green-cyan band are dropped, so red target
        # brackets and blue gun-direction ticks touching a chevron don't merge into it.
        mask = cv2.inRange(hsv, (0, 0, p.bright_v_min), (180, 255, 255))
        mask &= cv2.inRange(hsv, (0, 0, 0), (180, p.saturated_min - 1, 255)) | cv2.inRange(
            hsv, (p.keep_hue[0], 0, 0), (p.keep_hue[1], 255, 255)
        )
        green = cv2.inRange(hsv, p.green_lower, p.green_upper)
        mask |= green  # green chevrons can be dimmer than bright_v_min
        # The weapon-group text under the crosshair ("0 - 舰炮（所有）") has bracket and
        # stroke shapes that pass as chevrons; blank it (a pip right there is lost).
        ax, ay = int(round(aim[0])), int(round(aim[1]))
        (dx0, dx1), (dy0, dy1) = TEXT_ZONE
        mask[max(0, ay + dy0):max(0, ay + dy1), max(0, ax + dx0):max(0, ax + dx1)] = 0
        self.masks["pip_shape"] = mask
        self.masks["pip_green"] = green

        # Blob centroids only propose where a pip might be; each chevron is then judged
        # from all mask pixels in a window at its expected position, because in real
        # frames a chevron is often split at the tip or touching a neighbour.
        n, _, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
        keep = [
            k for k in range(1, n)
            if p.min_area <= stats[k, cv2.CC_STAT_AREA] <= p.max_area
            and max(stats[k, 2], stats[k, 3]) <= CHEVRON_MAX_SIDE
            and max(stats[k, 2], stats[k, 3]) <= CHEVRON_MAX_ASPECT * min(stats[k, 2], stats[k, 3])
        ]
        if len(keep) < 2 or len(keep) > MAX_CANDIDATES:
            return None, 0.0, False, 0.0

        cache: dict[tuple[int, int, str], tuple[float, float] | None] = {}

        def chevron_at(x: float, y: float, role: str) -> tuple[float, float] | None:
            key = (int(round(x)), int(round(y)), role)
            if key not in cache:
                cache[key] = _window_chevron(mask, key[0], key[1], role)
            return cache[key]

        best = _best_diamond(cents[keep], p.min_radius, p.max_radius, chevron_at, hint)
        if best is None:
            return None, 0.0, False, 0.0
        centre, radius, positions = best

        # Colour: share of green among the chevron pixels.
        n_total = n_green = 0
        for (x, y), role in positions:
            x0, y0, x1, y1 = _window(mask, int(round(x)), int(round(y)), role)
            n_total += int(np.count_nonzero(mask[y0:y1, x0:x1]))
            n_green += int(np.count_nonzero(green[y0:y1, x0:x1]))
        is_green = n_green >= PIP_GREEN_FRACTION * max(n_total, 1)
        conf = 1.0 if len(positions) == 4 else 0.75
        return centre, conf, is_green, radius


ROLE_OFFSETS = {"top": (0, -1), "bottom": (0, 1), "left": (-1, 0), "right": (1, 0)}


def _best_diamond(pts: np.ndarray, rmin: float, rmax: float, chevron_at, hint):
    """Find chevrons at (c +- r, c) and (c, c +- r), each pointing at c.
    Hypotheses come from top/bottom and left/right pairs of candidate points, so one
    chevron may be missing - but a three-chevron pip is only accepted near `hint` (the
    tracked pip), since three HUD text strokes can line up by chance.
    Returns (centre, radius, [((x, y), role), ...]) or None."""
    dx = pts[None, :, 0] - pts[:, None, 0]  # dx[i, j] = x_j - x_i
    dy = pts[None, :, 1] - pts[:, None, 1]
    best, best_key = None, None

    for axis in (1, 0):  # 1: i above j (vertical pair), 0: i left of j
        along, across = (dy, dx) if axis == 1 else (dx, dy)
        tol = np.maximum(3.0, 0.25 * along / 2)
        ii, jj = np.nonzero((along >= 2 * rmin) & (along <= 2 * rmax) & (np.abs(across) <= tol))
        pair_roles = ("top", "bottom") if axis == 1 else ("left", "right")
        for i, j in zip(ii, jj):
            # The pair itself first, at the blobs' own positions (cached per blob), so
            # most hypotheses are rejected after one or two cheap checks.
            first = chevron_at(pts[i][0], pts[i][1], pair_roles[0])
            if first is None:
                continue
            second = chevron_at(pts[j][0], pts[j][1], pair_roles[1])
            if second is None:
                continue
            r = along[i, j] / 2
            cx, cy = (pts[i] + pts[j]) / 2
            found = {pair_roles[0]: first, pair_roles[1]: second}
            for role, (ox, oy) in ROLE_OFFSETS.items():
                if role not in found:
                    pos = chevron_at(cx + ox * r, cy + oy * r, role)
                    if pos is not None:
                        found[role] = pos
            if len(found) < 3:
                continue
            if len(found) == 3 and (hint is None or np.hypot(cx - hint[0], cy - hint[1]) > HINT_RADIUS):
                continue
            # Refine from the chevrons' own positions: a complete opposite pair gives
            # the centre on its axis.
            xs = [(found["left"][0] + found["right"][0]) / 2] if "left" in found and "right" in found else []
            ys = [(found["top"][1] + found["bottom"][1]) / 2] if "top" in found and "bottom" in found else []
            rcx = xs[0] if xs else float(np.mean([found[k][0] for k in ("top", "bottom") if k in found]))
            rcy = ys[0] if ys else float(np.mean([found[k][1] for k in ("left", "right") if k in found]))
            err = sum(np.hypot(px - (rcx + ROLE_OFFSETS[k][0] * r), py - (rcy + ROLE_OFFSETS[k][1] * r)) for k, (px, py) in found.items())
            key = (len(found), -err / r)
            if best_key is None or key > best_key:
                best, best_key = ((rcx, rcy), float(r), [(pos, role) for role, pos in found.items()]), key
    return best


def _window(mask: np.ndarray, x: int, y: int, role: str) -> tuple[int, int, int, int]:
    """Window around an expected chevron position, clipped to the image: 17 x 11 px,
    long side across the chevron."""
    hw, hh = (8, 5) if role in ("top", "bottom") else (5, 8)
    h, w = mask.shape
    return max(0, x - hw), max(0, y - hh), min(w, x + hw + 1), min(h, y + hh + 1)


def _window_chevron(mask: np.ndarray, x: int, y: int, role: str) -> tuple[float, float] | None:
    """Centroid of the chevron in the window at (x, y), or None if the window's
    pixels don't form an inward-pointing V."""
    x0, y0, x1, y1 = _window(mask, x, y, role)
    win = mask[y0:y1, x0:x1] > 0
    ys, xs = np.nonzero(win)
    if xs.size < 5:
        return None
    blob = win[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    if not _is_chevron(blob, role):
        return None
    return (x0 + float(xs.mean()), y0 + float(ys.mean()))


def _is_chevron(blob: np.ndarray, role: str) -> bool:
    """True if the blob is a V whose tip points at the pip centre: its pixels spread
    wide across the open half and bunch together in the tip half. Uses every pixel
    rather than the end rows, so blur, ghosting and compression noise don't decide it;
    straight dashes, solid dots and most text strokes fail.
    role: which arm of the diamond the blob is (the top chevron points down, etc.)."""
    ys, xs = np.nonzero(blob)
    if xs.size < 5:
        return False
    vertical = role in ("top", "bottom")
    along, across = (ys, xs) if vertical else (xs, ys)
    half = (blob.shape[0] if vertical else blob.shape[1]) / 2
    # top chevron's tip is at the bottom (+y), left chevron's tip at the right (+x)
    tip = (along + 0.5 > half) if role in ("top", "left") else (along + 0.5 < half)
    if tip.sum() < 2 or (~tip).sum() < 2:
        return False
    spread_open, spread_tip = float(np.std(across[~tip])), float(np.std(across[tip]))
    return spread_open >= 1.0 and spread_open >= 1.2 * spread_tip + 0.3
