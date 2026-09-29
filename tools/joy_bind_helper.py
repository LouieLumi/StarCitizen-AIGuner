"""Wiggle one joystick axis (or tap one button) so a game's key-binding screen can detect it.

    python tools/joy_bind_helper.py --axis x          # after a 5 s countdown, swing X for 3 s
    python tools/joy_bind_helper.py --axis y --delay 8
    python tools/joy_bind_helper.py --button 1        # press button 1 briefly

Start it, switch to the game, click the binding slot, and let the countdown run out.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))

from pico_link import JOY_AXES, PicoError, PicoLink  # noqa: E402

AXES = ["x", "y", "z", "rx", "ry", "rz", "slider"]
assert len(AXES) == JOY_AXES


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    what = ap.add_mutually_exclusive_group(required=True)
    what.add_argument("--axis", choices=AXES)
    what.add_argument("--button", type=int, choices=range(1, 33), metavar="1-32")
    ap.add_argument("--delay", type=float, default=5, help="countdown before moving (s)")
    ap.add_argument("--seconds", type=float, default=3, help="how long to swing the axis (s)")
    ap.add_argument("--amplitude", type=float, default=0.8, help="axis swing, 0..1")
    args = ap.parse_args()

    try:
        with PicoLink() as link:
            for remaining in range(int(args.delay), 0, -1):
                print(f"{remaining} ...", flush=True)
                link.joystick()  # keep the link alive, stick centred
                time.sleep(1)

            t_end = time.perf_counter() + (args.seconds if args.axis else 0.3)
            while time.perf_counter() < t_end:
                if args.axis:
                    axes = [0.0] * JOY_AXES
                    axes[AXES.index(args.axis)] = args.amplitude * math.sin(2 * math.pi * time.perf_counter())
                    link.joystick(axes)
                else:
                    link.joystick(buttons=1 << (args.button - 1))
                time.sleep(0.01)
            link.joystick()
            print("done (centred)")
    except PicoError as e:
        print(f"FAIL: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
