"""Load and validate config/config.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "config" / "config.yaml"


class _Section(BaseModel):
    # Reject unknown keys so a typo in config.yaml fails loudly.
    model_config = ConfigDict(extra="forbid")


class ScreenConfig(_Section):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class CaptureConfig(_Section):
    device_idx: int = Field(0, ge=0)
    output_idx: int = Field(0, ge=0)
    target_fps: int = Field(120, ge=1, le=240)


class RoiConfig(_Section):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)

    @property
    def region(self) -> tuple[int, int, int, int]:
        """(left, top, right, bottom) in screen pixels."""
        return (self.x, self.y, self.x + self.width, self.y + self.height)


Hsv = tuple[int, int, int]


class AimConfig(_Section):
    # Fallback crosshair centre (ROI px), used while the crosshair bars are not visible.
    center_x: float
    center_y: float


class CrosshairConfig(_Section):
    white_lower: Hsv = (0, 0, 220)
    white_upper: Hsv = (180, 60, 255)


class PipConfig(_Section):
    # Lead pip = four inward chevrons; white out of range, green in range.
    bright_v_min: int = Field(190, ge=0, le=255)  # chevron shape mask: bright pixels...
    saturated_min: int = Field(120, ge=1, le=255)  # ...that are unsaturated,
    keep_hue: tuple[int, int] = (20, 90)  # or saturated with a hue in this band
    green_lower: Hsv = (50, 90, 150)  # pip is green when most chevron pixels are in here
    green_upper: Hsv = (80, 255, 255)
    min_area: int = Field(4, ge=1)  # per blob, px (a split chevron arm can be this small)
    max_area: int = Field(90, ge=1)
    min_radius: float = Field(10, gt=0)  # chevron distance from the pip centre, px
    max_radius: float = Field(45, gt=0)


class RangeConfig(_Section):
    # Weapon range ring: thin green circle around the crosshair while the locked
    # target is within weapon range (with a green pip). Measured on 174 stills:
    # share of the circle found green 0.83-0.92 with a green pip, <= 0.01 without.
    ring_lower: Hsv = (55, 110, 120)
    ring_upper: Hsv = (70, 255, 255)
    ring_radius: tuple[int, int] = (110, 210)  # px from the crosshair centre
    ring_skip_deg: int = Field(20, ge=0, le=60)  # left/right sectors skipped (ammo counters' green underlines)
    ring_min_share: float = Field(0.4, gt=0, le=1)  # of the circle, to count as present
    # Time filter (spec: never on a single green frame): in range only after this
    # long and this many frames in a row with green evidence.
    min_ms: float = Field(80, ge=0)
    min_frames: int = Field(3, ge=1)
    release_frames: int = Field(2, ge=1)  # frames against in a row to drop out of range


class FireConfig(_Section):
    # Auto fire (M7), only while the weapons switch is on (panel / --auto-fire). Opens fire once the
    # tracked target is in weapon range; see host/fire_control.py.
    stop_after_unlocked_s: float = Field(1.0, ge=0)  # cease fire once the target is gone this long
    max_burst_s: float = Field(0, ge=0)  # 0 = continuous; else longest trigger hold...
    release_s: float = Field(0.3, ge=0)  # ...then released this long
    button: int = Field(1, ge=1, le=7)  # HID mouse button bits: 1 = left


class TrackerConfig(_Section):
    meas_sigma_px: float = Field(2.0, gt=0)  # pip position noise, four chevrons (x2 for three)
    accel_sigma: float = Field(3000, gt=0)  # px/s^2 the pip may accelerate on screen
    init_speed_px_s: float = Field(400, gt=0)  # velocity uncertainty of a new track
    gate: float = Field(13.8, gt=0)  # innovation gate, chi-square 2 dof (13.8 = 99.9%)
    lost_after_ms: float = Field(200, gt=0)  # no accepted measurement for this long = lost
    acquire_frames: int = Field(3, ge=1)  # consecutive complete pips needed to start a track
    acquire_max_step_px: float = Field(60, gt=0)  # ...the second within this of the first...
    acquire_agree_px: float = Field(20, gt=0)  # ...later ones within this of where the previous two put them
    acquire_radius_px: float = Field(250, gt=0)  # ...and within this of the crosshair


class FinderConfig(_Section):
    # Locked-target search (target_finder.py), full-screen px.
    scale: float = Field(0.5, gt=0, le=1)  # work on a subsampled frame (speed)
    every: int = Field(3, ge=1)  # run on every n-th frame while searching; reuse the hint between
    red_lower1: Hsv = (0, 150, 150)
    red_upper1: Hsv = (8, 255, 255)
    red_lower2: Hsv = (172, 150, 150)
    red_upper2: Hsv = (180, 255, 255)
    arrow_radius: tuple[int, int] = (230, 300)  # off-screen arrow ring around the crosshair
    label_to_target_px: float = 110  # target sits this far above the label's first line
    exclude: list[tuple[int, int, int, int]] = []  # x0, y0, x1, y1: red chat names, HUD widgets
    slew_counts: int = Field(20, ge=1)  # max mouse counts per frame turning to an on-screen target
    arrow_counts: int = Field(60, ge=1)  # mouse counts per frame following the off-screen arrow
    slew_kp: float = Field(0.3, gt=0)  # counts per px towards an on-screen target
    label_hold_px: float = Field(200, ge=0)  # label this close: hold still (its target estimate is coarse)
    slew_timeout_s: float = Field(10, gt=0)  # give up turning after this long without a pip
    label_hold_s: float = Field(0.7, ge=0)  # hold still near a label this long for its pip...
    label_close_px: float = Field(50, ge=0)  # ...then close in to this (far targets have no pip)
    # Lock a target ourselves: with no locked target in sight (no label, no arrow) for
    # lock_after_s, tap the game's lock key (HID usage; 0x17 = T; 0 = never), at most
    # every lock_every_s. Never while a target is locked, so it doesn't switch targets.
    lock_key: int = Field(0x17, ge=0, le=255)
    lock_after_s: float = Field(2.0, ge=0)
    lock_every_s: float = Field(3.0, gt=0)
    lock_hold_s: float = Field(0.06, gt=0, le=0.09)  # key down this long (< the 100 ms watchdog)


class ControlConfig(_Section):
    # PD on the aim error (px) -> mouse counts per control tick (one tick per frame).
    px_per_count: float = Field(0.7, gt=0)  # view shift per mouse count (measured 0.67-0.72)
    coast_hold_ms: float = Field(50, ge=0)  # no fresh pip for longer than this: hold still
    kp_x: float = 0.45
    kd_x: float = 0.0
    kp_y: float = 0.45
    kd_y: float = 0.0
    kff: float = Field(0.8, ge=0)  # share of the pip's own velocity fed forward
    ff_min_speed: float = Field(30, ge=0)  # px/s; slower counts as standing still (estimate noise)
    # How the view follows our turns (tools/turret_ident.py; see host/own_motion.py):
    # nothing visible before view_delay_frames (1 = the next captured frame), then
    # each frame closes the remaining gap by a share of 1 - view_smoothing.
    view_delay_frames: int = Field(2, ge=1, le=10)
    view_smoothing: float = Field(0.0, ge=0, le=0.95)
    # Count commanded-but-not-yet-visible turn as done (Smith predictor), so the
    # controller doesn't keep turning while the turret catches up.
    smith_predictor: bool = True
    # Aim where the pip will be when our turn shows up (its velocity times the
    # turret's mean delay), not where it is now.
    lead_target: bool = True
    lead_scale: float = Field(1.0, ge=0, le=1.5)  # share of the turret's mean delay to aim ahead by
    deadzone_x: float = Field(5, ge=0)
    deadzone_y: float = Field(5, ge=0)
    max_mouse_dx: int = Field(30, ge=1)
    max_mouse_dy: int = Field(30, ge=1)
    # (min |error| px, gain multiplier), largest distance first
    gain_schedule: list[tuple[float, float]] = [(300, 1.0), (100, 1.0), (0, 0.8)]

    @model_validator(mode="after")
    def _schedule_sorted(self) -> ControlConfig:
        dists = [d for d, _ in self.gain_schedule]
        if dists != sorted(dists, reverse=True):
            raise ValueError("gain_schedule must be ordered from the largest distance down")
        return self


class RecordingConfig(_Section):
    dir: str = "recordings"  # absolute, or relative to the project root
    codec: Literal["ffv1", "mjpg"] = "ffv1"

    @property
    def path(self) -> Path:
        p = Path(self.dir)
        return p if p.is_absolute() else ROOT / p


class GameConfig(_Section):
    exe: str = "StarCitizen.exe"  # output (mouse, fire, keys) only while this has the focus


class Config(_Section):
    screen: ScreenConfig
    capture: CaptureConfig = CaptureConfig()
    roi: RoiConfig
    aim: AimConfig
    crosshair: CrosshairConfig = CrosshairConfig()
    pip: PipConfig = PipConfig()
    range: RangeConfig = RangeConfig()
    fire: FireConfig = FireConfig()
    tracker: TrackerConfig = TrackerConfig()
    finder: FinderConfig = FinderConfig()
    control: ControlConfig = ControlConfig()
    recording: RecordingConfig = RecordingConfig()
    game: GameConfig = GameConfig()

    @model_validator(mode="after")
    def _roi_inside_screen(self) -> Config:
        _, _, right, bottom = self.roi.region
        if right > self.screen.width or bottom > self.screen.height:
            raise ValueError(
                f"roi {self.roi.region} extends past the {self.screen.width}x{self.screen.height} screen"
            )
        if not (0 <= self.aim.center_x < self.roi.width and 0 <= self.aim.center_y < self.roi.height):
            raise ValueError(f"aim centre ({self.aim.center_x}, {self.aim.center_y}) is outside the roi")
        return self


def load_config(path: Path | str = DEFAULT_PATH) -> Config:
    with open(path, encoding="utf-8") as f:
        return Config.model_validate(yaml.safe_load(f))
