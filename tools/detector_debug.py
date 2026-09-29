"""Run the HUD detector on still images and show Original / HSV / pip mask / green mask.

    python tools/detector_debug.py still.png [more.png ...]            # window, any key = next
    python tools/detector_debug.py still.png --out logs/debug_{}.png   # save instead ({} = image name)

Full-screen images are cropped to the configured ROI; ROI-sized images are used as is.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))

from config import DEFAULT_PATH, load_config  # noqa: E402
from detector import HudDetector  # noqa: E402
from overlay import describe, draw_detection  # noqa: E402


def to_roi(img: np.ndarray, cfg) -> np.ndarray:
    h, w = img.shape[:2]
    if (w, h) == (cfg.screen.width, cfg.screen.height):
        r = cfg.roi
        return img[r.y:r.y + r.height, r.x:r.x + r.width]
    if (w, h) == (cfg.roi.width, cfg.roi.height):
        return img
    raise ValueError(f"image is {w}x{h}: neither the screen nor the ROI size")


def panels(roi: np.ndarray, det, detector: HudDetector) -> np.ndarray:
    annotated = draw_detection(roi.copy(), det, describe(det))
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    pip_mask = detector.masks["pip_shape"]
    tiles = [annotated, hsv, cv2.cvtColor(pip_mask, cv2.COLOR_GRAY2BGR), cv2.cvtColor(detector.masks["pip_green"], cv2.COLOR_GRAY2BGR)]
    for t, name in zip(tiles, ("original", "HSV", "pip shape mask", "green mask")):
        cv2.putText(t, name, (8, t.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
    return np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:])])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+")
    ap.add_argument("--config", default=str(DEFAULT_PATH))
    ap.add_argument("--out", help="save panels to this path pattern ({} = image stem) instead of showing")
    args = ap.parse_args()

    cfg = load_config(args.config)
    detector = HudDetector(cfg)
    for path in args.images:
        img = cv2.imread(path)
        if img is None:
            print(f"{path}: cannot read")
            continue
        det = detector.detect(to_roi(img, cfg))
        print(f"{Path(path).name}: " + " | ".join(describe(det)))
        grid = panels(to_roi(img, cfg), det, detector)
        if args.out:
            cv2.imwrite(args.out.format(Path(path).stem), grid)
        else:
            cv2.imshow("detector debug", cv2.resize(grid, None, fx=0.6, fy=0.6))
            if cv2.waitKey(0) & 0xFF in (ord("q"), 27):
                break
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
