"""PD controller: aim error (px) -> mouse counts per control tick.

Turret in FPS mouse mode: mouse +x turns right (the scene and the pip move left),
mouse +y turns down (they move up), so a pip right of / below the crosshair needs
positive counts on that axis.

    u = gain(|e|) * (Kp * e + Kd * de/dt) + Kff * v * dt / px_per_count
    (dead zone on the PD part, clamp, fractional carry)

v is the pip's own screen velocity from the tracker (our turning already taken
out): the feed-forward turns with the target instead of trailing it, which a
PD alone does on anything that moves.

The gain schedule is the spec's dynamic gain: full gain far from the target,
less close in so it doesn't swing left-right-left.
"""

from __future__ import annotations

from config import ControlConfig


class _Axis:
    def __init__(self, kp: float, kd: float, deadzone: float, limit: int, kff: float, px_per_count: float,
                 ff_min_speed: float):
        self.kp, self.kd, self.deadzone, self.limit = kp, kd, deadzone, limit
        self.kff, self.px_per_count, self.ff_min_speed = kff, px_per_count, ff_min_speed
        self.prev: float | None = None
        self.carry = 0.0  # fractional counts not sent yet

    def reset(self) -> None:
        self.prev = None
        self.carry = 0.0

    def step(self, e: float, dt: float, gain: float, v: float = 0.0) -> int:
        de = 0.0 if self.prev is None or dt <= 0 else (e - self.prev) / dt
        self.prev = e
        # below ff_min_speed the velocity is mostly estimation noise: don't turn it into jitter
        ff = 0.0 if abs(v) < self.ff_min_speed else self.kff * v * dt / self.px_per_count
        pd = 0.0 if abs(e) < self.deadzone else gain * (self.kp * e + self.kd * de)
        if pd == 0.0 and abs(ff) < 0.5:
            self.carry = 0.0
            return 0
        u = pd + ff + self.carry
        u = max(-self.limit, min(self.limit, u))
        counts = int(u)  # toward zero; the remainder is kept for the next tick
        self.carry = u - counts
        return counts


class PDController:
    def __init__(self, cfg: ControlConfig):
        self._cfg = cfg
        self._x = _Axis(cfg.kp_x, cfg.kd_x, cfg.deadzone_x, cfg.max_mouse_dx, cfg.kff, cfg.px_per_count, cfg.ff_min_speed)
        self._y = _Axis(cfg.kp_y, cfg.kd_y, cfg.deadzone_y, cfg.max_mouse_dy, cfg.kff, cfg.px_per_count, cfg.ff_min_speed)

    def reset(self) -> None:
        self._x.reset()
        self._y.reset()

    def gain(self, distance: float) -> float:
        for min_px, g in self._cfg.gain_schedule:
            if distance >= min_px:
                return g
        return 0.0

    def step(
        self, error: tuple[float, float] | None, dt: float, velocity: tuple[float, float] = (0.0, 0.0)
    ) -> tuple[int, int]:
        """Mouse counts for this tick. velocity: the pip's own screen velocity (px/s).
        No error (no target) -> no motion and the derivative memory is cleared."""
        if error is None:
            self.reset()
            return 0, 0
        ex, ey = error
        g = self.gain((ex * ex + ey * ey) ** 0.5)
        return self._x.step(ex, dt, g, velocity[0]), self._y.step(ey, dt, g, velocity[1])
