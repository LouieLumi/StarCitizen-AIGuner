"""Pico link test: drive the HID mouse / joystick through the CDC serial port.

This moves the real mouse cursor (or deflects the joystick) on this PC, so it
asks before starting.

    python tools/pico_test.py              # link check + mouse move tests
    python tools/pico_test.py --click      # also test left button down/up
    python tools/pico_test.py --joystick   # joystick axes/buttons, read back through Windows
    python tools/pico_test.py --yes        # skip the confirmation prompt
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))

from pico_link import KEY_F24, USB_PID, USB_VID, PicoError, PicoLink  # noqa: E402

RATE_HZ = 100

# Report the cursor in physical pixels even when display scaling is not 100%.
try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2
except (AttributeError, OSError):
    pass


def cursor_pos() -> tuple[int, int] | None:
    """Cursor position, or None when not available (non-Windows, or a
    non-interactive session such as SSH)."""
    try:
        from ctypes import wintypes

        pt = wintypes.POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return pt.x, pt.y
    except (AttributeError, OSError):
        pass
    return None


def delta(a, b) -> str:
    if a is None or b is None:
        return "cursor n/a (watch the screen)"
    return f"cursor moved ({b[0] - a[0]:+d}, {b[1] - a[1]:+d})"


def stream(link: PicoLink, dx: int, dy: int, count: int, buttons: int = 0) -> None:
    """Send `count` moves at RATE_HZ, the way the control loop will."""
    period = 1.0 / RATE_HZ
    next_t = time.perf_counter()
    for _ in range(count):
        link.move(dx, dy, buttons)
        next_t += period
        time.sleep(max(0.0, next_t - time.perf_counter()))


def confirm(prompt: str) -> bool:
    try:
        return input(f"{prompt} [y/N] ").strip().lower() == "y"
    except EOFError:
        return False


def test_link(link: PicoLink) -> None:
    print(f"[link] port={link.port}")
    print(f"[link] {link.version()}")
    rtts = sorted(link.ping() for _ in range(20))
    print(f"[link] PING rtt median={rtts[10]:.2f} ms max={rtts[-1]:.2f} ms")


def test_move(link: PicoLink) -> None:
    p0 = cursor_pos()
    link.move(10, 0)
    time.sleep(0.05)
    print(f"[move] M,10,0,0 -> {delta(p0, cursor_pos())}")

    # 20 x 10 counts per leg. Measured pixels only equal counts when
    # "Enhance pointer precision" is off.
    for name, dx, dy in (("right", 10, 0), ("down", 0, 10), ("left", -10, 0), ("up", 0, -10)):
        p0 = cursor_pos()
        stream(link, dx, dy, 20)
        time.sleep(0.05)
        print(f"[move] {name:5s} 200 counts -> {delta(p0, cursor_pos())}")


def test_stop(link: PicoLink) -> None:
    # Queue far more motion than can be sent in 1 ms, then STOP: the rest must be dropped.
    p0 = cursor_pos()
    link.move(2000, 0)
    link.stop()
    time.sleep(0.1)
    print(f"[stop] M,2000,0,0 then STOP -> OK, {delta(p0, cursor_pos())} (expect far less than 2000)")


def test_timeout(link: PicoLink) -> None:
    before = link.stats()["timeouts"]
    link.move(0, 0)
    time.sleep(0.25)
    after = link.stats()["timeouts"]
    ok = after == before + 1
    print(f"[timeout] host silent 250 ms -> firmware timeouts {before} -> {after} {'OK' if ok else 'FAIL'}")
    if not ok:
        raise PicoError("host timeout did not fire")


class _JoyInfoEx(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "dwSize", "dwFlags", "dwXpos", "dwYpos", "dwZpos", "dwRpos", "dwUpos", "dwVpos",
        "dwButtons", "dwButtonNumber", "dwPOV", "dwReserved1", "dwReserved2")]


class _JoyCaps(ctypes.Structure):
    # JOYCAPSW; joyGetDevCapsW rejects any other size.
    _fields_ = [("wMid", ctypes.c_uint16), ("wPid", ctypes.c_uint16), ("szPname", ctypes.c_wchar * 32)]
    _fields_ += [(name, ctypes.c_uint32) for name in (
        "wXmin", "wXmax", "wYmin", "wYmax", "wZmin", "wZmax", "wNumButtons", "wPeriodMin", "wPeriodMax",
        "wRmin", "wRmax", "wUmin", "wUmax", "wVmin", "wVmax", "wCaps", "wMaxAxes", "wNumAxes", "wMaxButtons")]
    _fields_ += [("szRegKey", ctypes.c_wchar * 32), ("szOEMVxD", ctypes.c_wchar * 260)]


def find_winmm_joystick() -> int | None:
    """WinMM joystick id of the AI Crew Controller (matched by VID/PID)."""
    winmm = ctypes.windll.winmm
    for jid in range(16):
        caps = _JoyCaps()
        if winmm.joyGetDevCapsW(jid, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
            if (caps.wMid, caps.wPid) == (USB_VID, USB_PID):
                return jid
    return None


def read_joystick(jid: int) -> tuple[float, float, int]:
    """(x, y, buttons) as Windows sees them; axes scaled back to -1..1."""
    info = _JoyInfoEx(dwSize=ctypes.sizeof(_JoyInfoEx), dwFlags=0xFF)  # JOY_RETURNALL
    if ctypes.windll.winmm.joyGetPosEx(jid, ctypes.byref(info)) != 0:
        raise PicoError("joyGetPosEx failed")
    return (info.dwXpos / 32767.5 - 1, info.dwYpos / 32767.5 - 1, info.dwButtons)


def test_joystick(link: PicoLink) -> None:
    jid = find_winmm_joystick()
    if jid is None:
        raise PicoError("Windows does not list the AI Crew Controller as a game controller")
    print(f"[joy] WinMM joystick id {jid}")
    # Buttons 31/32 only: low-numbered buttons are often bound to fire in games.
    for x, y, b in ((0.5, -0.5, 1 << 30), (-1.0, 1.0, 1 << 31), (0.0, 0.0, 0)):
        stream_joy = time.perf_counter() + 0.15
        while time.perf_counter() < stream_joy:  # refresh like the control loop does
            link.joystick((x, y), b)
            time.sleep(0.01)
        rx, ry, rb = read_joystick(jid)
        ok = abs(rx - x) < 0.01 and abs(ry - y) < 0.01 and rb == b
        print(f"[joy] sent x={x:+.2f} y={y:+.2f} buttons={b:#010x} -> read x={rx:+.3f} y={ry:+.3f} "
              f"buttons={rb:#010x} {'OK' if ok else 'FAIL'}")
        if not ok:
            raise PicoError("joystick readback mismatch")

    # Host goes silent while the stick is deflected: the firmware must centre it.
    link.joystick((0.8, 0.8), 1 << 30)
    time.sleep(0.25)
    rx, ry, rb = read_joystick(jid)
    ok = abs(rx) < 0.01 and abs(ry) < 0.01 and rb == 0
    print(f"[joy] deflected then silent 250 ms -> read x={rx:+.3f} y={ry:+.3f} buttons={rb:#010x} "
          f"{'OK (centred)' if ok else 'FAIL'}")
    if not ok:
        raise PicoError("joystick not centred by host timeout")


def test_click(link: PicoLink) -> None:
    # Button state is a level that must be refreshed; hold for ~100 ms then release.
    stream(link, 0, 0, 10, buttons=1)
    link.move(0, 0, 0)
    print("[click] left down 100 ms, up")


def test_keyboard(link: PicoLink) -> None:
    """Tap F24 (bound to nothing, games included) and watch Windows see it go down and up."""
    get = ctypes.windll.user32.GetAsyncKeyState
    VK_F24 = 0x87
    get(VK_F24)  # clear the "pressed since last call" bit
    link.key(KEY_F24)
    down = False
    t_end = time.perf_counter() + 0.08
    while time.perf_counter() < t_end:
        down = down or bool(get(VK_F24) & 0x8000)
        time.sleep(0.005)
    link.key(0)
    time.sleep(0.05)
    up = not (get(VK_F24) & 0x8000)
    if not (down and up):
        raise PicoError(f"keyboard: F24 seen down={down}, released={up}")
    print("[keyboard] F24 down seen by Windows, then released")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="COM port (default: auto-detect by VID:PID)")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--click", action="store_true", help="also test left mouse down/up")
    ap.add_argument("--joystick", action="store_true", help="test the joystick instead of the mouse")
    ap.add_argument("--keyboard", action="store_true", help="only test the keyboard (taps F24, which nothing uses)")
    ap.add_argument("--delay", type=float, default=0, help="seconds to wait before moving (time to click into the game)")
    args = ap.parse_args()

    try:
        with PicoLink(args.port) as link:
            test_link(link)
            if args.keyboard:
                test_keyboard(link)
                print(f"[stats] {link.stats()}")
                print("PASS")
                return 0

            what = "deflect the joystick" if args.joystick else "move the mouse cursor"
            if not args.yes and not confirm(f"Next steps {what} on this PC. Continue?"):
                print("aborted")
                return 1
            for remaining in range(int(args.delay), 0, -1):
                print(f"moving in {remaining} s - switch to the game now", flush=True)
                time.sleep(1)
            if args.joystick:
                test_joystick(link)
            else:
                test_move(link)
                test_stop(link)
                test_timeout(link)

            if args.click:
                if args.yes or confirm("Left-click test clicks whatever is under the cursor. Continue?"):
                    test_click(link)

            print(f"[stats] {link.stats()}")
    except PicoError as e:
        print(f"FAIL: {e}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
