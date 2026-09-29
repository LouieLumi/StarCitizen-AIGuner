"""Run the locked-target finder on full-screen stills and draw what it found.

    python tools/finder_debug.py D:\\...\\session_x\\still_*.png --sheet out.jpg
    python tools/finder_debug.py still.png --out annotated.png

Yellow cross = crosshair, grey ring = arrow search ring, grey boxes = excluded
zones, magenta = where the finder says the target is (label: point, arrow: direction).
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))

from config import DEFAULT_PATH, load_config  # noqa: E402
from detector import HudDetector  # noqa: E402
from target_finder import TargetFinder  # noqa: E402

MAGENTA = (255, 0, 255)


def annotate(img: np.ndarray, aim, hint, cfg) -> np.ndarray:
    out = img.copy()
    for x0, y0, x1, y1 in cfg.finder.exclude:
        cv2.rectangle(out, (x0, y0), (x1, y1), (90, 90, 90), 2)
    a = (int(aim[0]), int(aim[1]))
    for r in cfg.finder.arrow_radius:
        cv2.circle(out, a, r, (120, 120, 120), 1, cv2.LINE_AA)
    cv2.drawMarker(out, a, (0, 255, 255), cv2.MARKER_CROSS, 40, 3)
    if hint is not None:
        if hint.point is not None:
            p = (int(hint.point[0]), int(hint.point[1]))
            cv2.circle(out, p, 40, MAGENTA, 4)
            cv2.line(out, a, p, MAGENTA, 3, cv2.LINE_AA)
        else:
            tip = (int(aim[0] + 400 * hint.direction[0]), int(aim[1] + 400 * hint.direction[1]))
            cv2.arrowedLine(out, a, tip, MAGENTA, 5, cv2.LINE_AA, tipLength=0.15)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+", help="full-screen images (globs allowed)")
    ap.add_argument("--config", default=str(DEFAULT_PATH))
    ap.add_argument("--out", help="annotated image path for a single input")
    ap.add_argument("--sheet", help="write a contact sheet of all inputs")
    args = ap.parse_args()

    cfg = load_config(args.config)
    r = cfg.roi
    paths = sorted(p for pattern in args.images for p in glob.glob(pattern))
    finder = TargetFinder(cfg.finder)
    tiles = []
    counts = {"label": 0, "arrow": 0, "none": 0}
    for i, path in enumerate(paths):
        img = cv2.imread(path)
        det = HudDetector(cfg).detect(img[r.y:r.y + r.height, r.x:r.x + r.width])
        aim = (det.aim[0] + r.x, det.aim[1] + r.y)
        hint = finder.find(img, aim)
        counts[hint.kind if hint else "none"] += 1
        what = "-" if hint is None else (
            f"label at ({hint.point[0]:.0f},{hint.point[1]:.0f}) {hint.distance:.0f}px" if hint.point
            else f"arrow dir ({hint.direction[0]:+.2f},{hint.direction[1]:+.2f})")
        print(f"#{i:03d} {Path(path).name}: aim conf {det.aim_conf:.2f} | {what}")
        out = annotate(img, aim, hint, cfg)
        if args.out and len(paths) == 1:
            cv2.imwrite(args.out, out)
        if args.sheet:
            t = cv2.resize(out, (512, 288), interpolation=cv2.INTER_AREA)
            cv2.rectangle(t, (0, 0), (60, 20), (0, 0, 0), -1)
            cv2.putText(t, f"#{i:03d}", (3, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            tiles.append(t)
    print(counts)
    if args.sheet and tiles:
        while len(tiles) % 5:
            tiles.append(np.zeros_like(tiles[0]))
        rows = [np.hstack(tiles[k:k + 5]) for k in range(0, len(tiles), 5)]
        for s in range(0, len(rows), 6):
            cv2.imwrite(args.sheet.replace(".jpg", f"_{s // 6:02d}.jpg"), np.vstack(rows[s:s + 6]), [cv2.IMWRITE_JPEG_QUALITY, 85])
    return 0


if __name__ == "__main__":
    sys.exit(main())
