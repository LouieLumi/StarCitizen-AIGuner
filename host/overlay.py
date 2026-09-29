"""Draw detector / tracker state onto a frame for debugging."""

from __future__ import annotations

import cv2
import numpy as np

from detector import Detection

YELLOW = (0, 255, 255)
GREEN = (0, 255, 0)
WHITE = (255, 255, 255)
MAGENTA = (255, 0, 255)
GREY = (128, 128, 128)


def _cross(img: np.ndarray, p: tuple[float, float], size: int, color, thickness: int = 1) -> None:
    x, y = int(round(p[0])), int(round(p[1]))
    cv2.line(img, (x - size, y), (x + size, y), color, thickness, cv2.LINE_AA)
    cv2.line(img, (x, y - size), (x, y + size), color, thickness, cv2.LINE_AA)


def draw_detection(img: np.ndarray, det: Detection, lines: list[str] | None = None) -> np.ndarray:
    """Annotate in place: crosshair centre (yellow cross, grey when using the
    fallback), weapon range ring (thin green circle, when found), pip (diamond,
    green/white by range state), aim->pip error vector, and optional text lines."""
    _cross(img, det.aim, 14, YELLOW if det.aim_conf > 0 else GREY, 2)
    if det.ring_radius is not None:
        cv2.circle(img, tuple(int(round(v)) for v in det.aim), int(round(det.ring_radius)) + 6, GREEN, 1, cv2.LINE_AA)
    if det.pip is not None:
        x, y = det.pip
        r = max(det.pip_radius, 6) + 6
        pts = np.array([(x, y - r), (x + r, y), (x, y + r), (x - r, y)], np.int32)
        cv2.polylines(img, [pts], True, GREEN if det.pip_green else WHITE, 2, cv2.LINE_AA)
        cv2.arrowedLine(
            img, tuple(int(round(v)) for v in det.aim), (int(round(x)), int(round(y))), MAGENTA, 1, cv2.LINE_AA, tipLength=0.1
        )
    y = 22
    for text in lines or []:
        cv2.putText(img, text, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, text, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, YELLOW, 1, cv2.LINE_AA)
        y += 22
    return img


def draw_track(img: np.ndarray, track) -> np.ndarray:
    """Tracker estimate: cyan cross, velocity arrow (0.1 s ahead)."""
    if track is not None:
        p = (track.x, track.y)
        _cross(img, p, 10, (255, 255, 0), 1)
        tip = (int(round(track.x + 0.1 * track.vx)), int(round(track.y + 0.1 * track.vy)))
        cv2.arrowedLine(img, (int(round(p[0])), int(round(p[1]))), tip, (255, 255, 0), 1, cv2.LINE_AA, tipLength=0.2)
    return img


def describe(det: Detection) -> list[str]:
    lines = [f"aim ({det.aim[0]:.0f},{det.aim[1]:.0f}) conf {det.aim_conf:.2f}"]
    if det.pip is None:
        lines.append("pip -")
    else:
        ex, ey = det.error
        lines.append(
            f"pip ({det.pip[0]:.0f},{det.pip[1]:.0f}) conf {det.pip_conf:.2f} r {det.pip_radius:.0f} "
            f"{'GREEN' if det.pip_green else 'white'}"
        )
        lines.append(f"error ({ex:+.0f},{ey:+.0f})")
    lines.append(f"range ring {det.ring:.2f}" + (f" r {det.ring_radius:.0f}" if det.ring_radius is not None else ""))
    return lines
