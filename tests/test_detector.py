"""Detector tests on synthetic shapes. Run: python tests/test_detector.py"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))

from config import load_config  # noqa: E402
from detector import HudDetector, _is_chevron  # noqa: E402

# Tip direction for each diamond role: the chevron points at the pip centre.
TIP = {"top": (0, 1), "bottom": (0, -1), "left": (1, 0), "right": (-1, 0)}


def chevron(size: int, role: str, thickness: int = 1) -> np.ndarray:
    """Binary V of `size` px whose tip points in the role's direction."""
    img = np.zeros((size + 4, size + 4), np.uint8)
    c, s = (size + 3) / 2, size / 2
    tx, ty = TIP[role]
    tip = (c + tx * s * 0.5, c + ty * s * 0.5)
    # arms end on the side opposite the tip
    if tx == 0:
        ends = [(c - s, c - ty * s * 0.5), (c + s, c - ty * s * 0.5)]
    else:
        ends = [(c - tx * s * 0.5, c - s), (c - tx * s * 0.5, c + s)]
    for e in ends:
        cv2.line(img, tuple(int(round(v)) for v in e), tuple(int(round(v)) for v in tip), 255, thickness)
    ys, xs = np.nonzero(img)
    return img[ys.min():ys.max() + 1, xs.min():xs.max() + 1] > 0


def test_chevron_shapes() -> None:
    for size in (8, 10, 12):  # real chevrons are 8-12 px across
        for role in TIP:
            blob = chevron(size, role)
            assert _is_chevron(blob, role), f"{role} chevron size {size} rejected"
            opposite = {"top": "bottom", "bottom": "top", "left": "right", "right": "left"}[role]
            assert not _is_chevron(blob, opposite), f"{role} chevron size {size} accepted as {opposite}"
    dash_h = np.ones((2, 7), bool)
    dash_v = np.ones((7, 2), bool)
    square = np.ones((5, 5), bool)
    for role in TIP:
        for name, blob in (("h-dash", dash_h), ("v-dash", dash_v), ("square", square)):
            assert not _is_chevron(blob, role), f"{name} accepted as {role} chevron"


def synthetic_pip(detector_cfg, r: int, colour: tuple[int, int, int], drop: str | None = None) -> np.ndarray:
    """ROI-sized dark frame with a pip of radius r at (400, 300)."""
    img = np.full((detector_cfg.roi.height, detector_cfg.roi.width, 3), (40, 50, 45), np.uint8)
    cx, cy = 400, 300
    for role, (ox, oy) in {"top": (0, -r), "bottom": (0, r), "left": (-r, 0), "right": (r, 0)}.items():
        if role == drop:
            continue
        blob = chevron(10, role, thickness=2)
        h, w = blob.shape
        y0, x0 = cy + oy - h // 2, cx + ox - w // 2
        img[y0:y0 + h, x0:x0 + w][blob] = colour
    return img


def test_synthetic_pips() -> None:
    cfg = load_config()
    green, white = (60, 230, 60), (250, 250, 250)
    for r, colour, is_green in ((18, green, True), (33, white, False)):
        det = HudDetector(cfg).detect(synthetic_pip(cfg, r, colour))
        assert det.pip is not None and det.pip_conf == 1.0, f"r={r}: {det}"
        assert abs(det.pip[0] - 400) < 2 and abs(det.pip[1] - 300) < 2, det.pip
        assert det.pip_green == is_green

    # one chevron hidden: only accepted next to the tracked position
    img = synthetic_pip(cfg, 20, green, drop="right")
    assert HudDetector(cfg).detect(img).pip is None
    det = HudDetector(cfg).detect(img, pip_hint=(405, 298))
    assert det.pip is not None and det.pip_conf == 0.75
    assert HudDetector(cfg).detect(img, pip_hint=(600, 300)).pip is None


def hsv_bgr(h: int, s: int, v: int) -> tuple[int, int, int]:
    return tuple(int(c) for c in cv2.cvtColor(np.uint8([[[h, s, v]]]), cv2.COLOR_HSV2BGR)[0, 0])


def synthetic_hud(cfg, ring_radius: int | None, underlines: bool = False) -> np.ndarray:
    """Crosshair bars at the nominal aim point, optionally the green range ring and
    the ammo counters' green underlines (which must not count as a ring)."""
    img = np.full((cfg.roi.height, cfg.roi.width, 3), (40, 50, 45), np.uint8)
    cx, cy = int(cfg.aim.center_x), int(cfg.aim.center_y)
    ring_green = hsv_bgr(63, 170, 200)
    if ring_radius:
        cv2.circle(img, (cx, cy), ring_radius, ring_green, 2, cv2.LINE_AA)
    if underlines:
        for sx in (-1, 1):
            for dy in (-2, 26):
                cv2.line(img, (cx + sx * 170 - 8, cy + dy), (cx + sx * 170 + 8, cy + dy), ring_green, 2)
    for dx, dy, w, h in ((-120, 0, 60, 10), (120, 0, 60, 10), (0, -120, 10, 60), (0, 120, 10, 60)):
        cv2.rectangle(img, (cx + dx - w // 2, cy + dy - h // 2), (cx + dx + w // 2, cy + dy + h // 2), (255, 255, 255), -1)
    return img


def test_range_ring() -> None:
    cfg = load_config()
    for radius in (125, 150, 185):
        det = HudDetector(cfg).detect(synthetic_hud(cfg, radius))
        assert det.aim_conf == 1.0
        assert det.ring > 0.8 and abs(det.ring_radius - radius) <= 3, (radius, det.ring, det.ring_radius)
    det = HudDetector(cfg).detect(synthetic_hud(cfg, None, underlines=True))
    assert det.ring < 0.05 and det.ring_radius is None, det.ring
    det = HudDetector(cfg).detect(synthetic_hud(cfg, 150, underlines=True))
    assert det.ring > 0.8


def test_arc_crosshair_variant() -> None:
    """No target locked: the crosshair is two arcs "( )" - still the turret HUD."""
    cfg = load_config()
    img = np.full((cfg.roi.height, cfg.roi.width, 3), (40, 50, 45), np.uint8)
    cx, cy = int(cfg.aim.center_x), int(cfg.aim.center_y) - 5
    for sx, (a0, a1) in ((-1, (150, 210)), (1, (-30, 30))):
        cv2.ellipse(img, (cx, cy), (95, 120), 0, a0, a1, hsv_bgr(95, 190, 255), 5)  # ~18 x 120 px, fringed
    det = HudDetector(cfg).detect(img)
    assert det.aim_conf == 0.5, det.aim_conf
    assert abs(det.aim[0] - cx) < 4 and abs(det.aim[1] - cy) < 4, det.aim
    empty = np.full_like(img, (40, 50, 45))
    assert HudDetector(cfg).detect(empty).aim_conf == 0.0


if __name__ == "__main__":
    test_chevron_shapes()
    test_synthetic_pips()
    test_range_ring()
    test_arc_crosshair_variant()
    print("detector tests: all passed")
