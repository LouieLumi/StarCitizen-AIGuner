"""Serial link to the AI Crew Controller (Pico) using text protocol V1.

See firmware/protocol.h for the command set.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

import serial
from serial.tools import list_ports

USB_VID = 0xCAFE
USB_PID = 0x4143

JOY_AXES = 7
AXIS_MAX = 32767

# HID keyboard usages (USB HID Usage Tables, keyboard page)
KEY_T = 0x17
KEY_F24 = 0x73

# USB CDC ignores the baud rate, but pyserial needs one.
_BAUD = 115200


class PicoError(RuntimeError):
    pass


def find_port() -> str | None:
    """Return the COM port of the first AI Crew Controller found."""
    for p in list_ports.comports():
        if p.vid == USB_VID and p.pid == USB_PID:
            return p.device
    return None


class PicoLink:
    def __init__(self, port: str | None = None, timeout: float = 0.3):
        port = port or find_port()
        if port is None:
            raise PicoError(f"no device with VID:PID {USB_VID:04X}:{USB_PID:04X} found")
        self.port = port
        # DTR on (pyserial default) - the firmware releases everything when DTR drops.
        self._ser = serial.Serial(port, _BAUD, timeout=timeout, write_timeout=timeout)
        self._ser.reset_input_buffer()

    def _send(self, line: str) -> None:
        self._ser.write((line + "\n").encode("ascii"))

    def _query(self, line: str) -> str:
        self._ser.reset_input_buffer()
        self._send(line)
        reply = self._ser.readline().decode("ascii", "replace").strip()
        if not reply:
            raise PicoError(f"no reply to {line!r}")
        return reply

    def ping(self) -> float:
        """Round-trip time in milliseconds."""
        t0 = time.perf_counter()
        reply = self._query("PING")
        rtt = (time.perf_counter() - t0) * 1000
        if reply != "PONG":
            raise PicoError(f"unexpected PING reply {reply!r}")
        return rtt

    def version(self) -> str:
        return self._query("VER")

    def stats(self) -> dict[str, int]:
        reply = self._query("STAT")
        if not reply.startswith("STAT "):
            raise PicoError(f"unexpected STAT reply {reply!r}")
        return {k: int(v) for k, v in (kv.split("=") for kv in reply.split()[1:])}

    def move(self, dx: int, dy: int, buttons: int = 0) -> None:
        """Relative move plus button level. Must be refreshed within 100 ms
        or the firmware releases all outputs."""
        self._send(f"M,{int(dx)},{int(dy)},{int(buttons)}")

    def key(self, key: int = 0, modifiers: int = 0) -> None:
        """Keyboard state: one HID usage held down (0 = none) plus modifier bits
        (bit0 LCtrl .. bit7 RGui). Held until changed; released like everything
        else when the host goes quiet for 100 ms (firmware 0.3.0+)."""
        self._send(f"K,{int(modifiers) & 0xFF},{int(key) & 0xFF}")

    def joystick(self, axes: Sequence[float] = (), buttons: int = 0) -> None:
        """Absolute joystick state. axes are X, Y, Z, Rx, Ry, Rz, Slider in -1.0..1.0
        (missing ones centred); buttons is a bitmask (bit0 = button 1). Must be
        refreshed within 100 ms or the firmware centres everything."""
        if len(axes) > JOY_AXES:
            raise ValueError(f"at most {JOY_AXES} axes")
        raw = [round(max(-1.0, min(1.0, a)) * AXIS_MAX) for a in axes]
        raw += [0] * (JOY_AXES - len(raw))
        self._send("J," + ",".join(map(str, raw)) + f",{int(buttons) & 0xFFFFFFFF}")

    def stop(self) -> None:
        reply = self._query("STOP")
        if reply != "OK STOP":
            raise PicoError(f"unexpected STOP reply {reply!r}")

    def close(self) -> None:
        try:
            self.stop()
        except (PicoError, serial.SerialException):
            pass
        finally:
            self._ser.close()

    def __enter__(self) -> PicoLink:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
