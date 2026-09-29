# Star Citizen turret HUD (Polaris turret, FPS mouse mode)

Measured on lossless 2560x1440 captures from session `session_20260925_235339`
(14.5 min of NPC combat, 174 PNG stills). Screen coordinates below; the ROI
(680,270 1200x900) starts at screen (680,270).

## Elements

| Element | Look | Meaning / use |
|---|---|---|
| Crosshair | 4 thick white bars (8-14 x 48-70 px) around a small centre dot, inside a thin grey-blue circle + hexagon | Aim point. Centre ~(1276-1281, 710-729); drifts tens of px, bars spread 100-145 px from centre. Measured every frame. |
| Lead pip | 4 small inward chevrons `v < > ^` in a diamond, 16-35 px from its centre | Where the game says to aim. **White** = target out of weapon range, **green** = in range. Control error = pip - crosshair. |
| Weapon range ring | Thin green circle, radius ~130-190 px, around the crosshair (cut into 4 arcs by the bars) | Target within weapon range (present at 0.6-1.7 km, absent at 3.6 km). |
| Target marker | Red: outward diamond at long range, 4 corner brackets around the ship up close; red name + `distance [closing speed]` text below | Locked hostile target. |
| Gun direction | Small dot with 4 diagonal ticks (blue or dark brown) | Where the guns actually point (lags the crosshair). Not used yet; candidate for fire gating. |
| Crosshair: arc variant | Bars replaced by two tall arcs `( )` (~24 x 120 px, ~95 px left/right of centre; thin bright core with coloured fringes) and a small grey `+` | Shown with no target locked, and with a locked target that is far away (seen at 4.8-5.4 km). Still the turret HUD: detected by brightness + shape, aim_conf 0.5, so search and the auto lock key (T) work. |
| Crosshair: X variant | Bars rotated 45 deg (white or orange) | Ignore (confirmed by user). Detector keeps the last crosshair centre. |

Ammo counters (e.g. `61 / 61`) sit left and right of the crosshair with small
**green underlines** - must not be mistaken for the range ring or a green pip.

## Colours (OpenCV HSV, H 0-180)

| Element | H | S | V |
|---|---|---|---|
| Crosshair bars | any | 4-22 | 249-255 |
| Range ring | 62-65 | 143-190 | 146-222 |
| Green pip chevrons | 58-65 | 132-194 | 199-253 |
| White pip chevrons (core) | any | ~20 | 255 |

The HUD has a chromatic-aberration effect: white elements have cyan (H 83-88)
and blue fringes, and white chevrons have small (3-4 px) green fringes. Hence
the narrow green hue range, and pip colour is decided from the whole chevron
(green share >= 60%), not from any green pixel.

## Finding the pip

Chevrons are 8-12 px across and 5-7 px deep; the diamond radius (chevron to
centre) varies 16-35 px. How the detector finds them, and why:

- **Shape mask = brightness, not a colour key.** A white chevron is a 1 px white
  core with red/green/cyan fringes; only all of it together is V-shaped. Saturated
  pixels outside hue 20-90 are dropped so red target brackets and blue gun ticks
  touching a chevron don't merge into it. Green pixels are added back because
  green chevrons can be dimmer than the brightness cut in compressed video.
- **Blobs only propose, windows decide.** In real frames a chevron is often split
  at its tip or touching a neighbour, so a connected blob is not a chevron. Blob
  centroids propose top/bottom (or left/right) pairs; each chevron is then judged
  from all mask pixels in a 17x11 window at its expected position.
- **V test:** pixels spread wide across the open half and bunch in the tip half
  (std of the cross coordinate), tip pointing at the pip centre. Dashes, dots and
  most text strokes fail.
- **Three chevrons** (one hidden behind a crosshair bar, a laser, ...) are only
  accepted within 60 px of the tracked pip; four are needed to acquire a new one.

## Weapon range

Two signals, which agree on every one of the 174 stills: the **range ring** is
there exactly when the **pip is green**. The ring is also visible while the pip
is hidden (e.g. behind the target marker), so it is the main signal:

- Unrolled to polar coordinates around the crosshair (1 deg x 1 px), the share of
  angles that are ring-green at the best radius (110-210 px, +-2 px) is
  0.83-0.92 with the ring and <= 0.01 without; nothing in between except a
  partly covered ring (0.59). Threshold 0.4.
- The left/right +-20 deg sectors are skipped: the ammo counters there have
  green underlines. The crosshair bars cut the ring, which costs a few percent.
- Radius seen: 120-172 px (not constant).
- A white pip overrides the ring (out of range). In range needs the evidence for
  >= 80 ms and >= 3 frames in a row (`range` in config.yaml, host/weapon_range.py).

## Weapon-group text

`0 - 舰炮（所有）` sits under the crosshair at x -90..+78, y +124..+152 from the
crosshair centre (independent of bar spread). Its full-width brackets and strokes
pass as pip chevrons, so the detector blanks that zone.
