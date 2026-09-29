# StarCitizen AIGuner

[中文](README.md) · [Implementation](docs/architecture.md) · [Firmware](docs/firmware.md) · [Usage and debugging](docs/usage.md)

The program detects the turret HUD from screen captures, tracks the game's lead pip, and sends USB mouse and keyboard input through a Pico. It handles target search, aiming and automatic fire using computer vision and control algorithms, without reading game memory or injecting code into the game process.

My setup uses **Windows, Python 3.12 and a Pico 2 W**. The included configuration is calibrated for a **2560×1440 display and a Polaris turret in FPS mouse mode**. Other resolutions, turrets and sensitivity settings require corresponding adjustments.

## Disclaimer

**CIG does not allow this kind of automation. Using this project may result in a ban or other account penalties.**

Publishing the source is intended to share the implementation and does not imply authorization from CIG. Use is at your own discretion. Users assume responsibility for bans, account losses and other consequences arising from use of this project; the author accepts no responsibility for those consequences.

![Detection and tracking from recorded gameplay](docs/assets/track_strip.png)

## Implementation

The game HUD already provides a lead pip, so I use that as the aiming target. The program does not calculate ballistics or require model weights or a cloud API.

```text
Game screen → capture → HUD detection → tracking and control → USB serial → Pico HID → game input
```

**Detection.** DXCAM captures the screen. OpenCV identifies the crosshair, lead pip and range ring using HSV color ranges, connected components and shape features. When no pip is available, the controller turns toward a red target label or off-screen arrow. If no lock indication is visible for a configured period, it attempts to lock a target with T.

**Tracking.** A Kalman filter estimates the pip's position and velocity, rejects outliers and handles brief occlusions. New tracks require confirmation across consecutive frames; established tracks can accept partially occluded observations near the predicted position.

**Control.** A PD controller converts aiming error into mouse movement, with velocity feed-forward. Turret response includes delay and smoothing, so correcting only the current screen error can cause overshoot. I added own-motion compensation and a Smith predictor to account for screen motion caused by the turret and for commands that have not yet appeared in the captured frame.

**Input.** Python sends commands through pyserial. The Pico firmware uses C, the Pico SDK and TinyUSB to provide USB CDC serial, mouse/keyboard HID and a reserved seven-axis, 32-button joystick interface. The host program and game run on the same computer, with the Pico connected over USB.

**Range and firing.** Range detection combines the green pip and range ring, requiring at least 80 ms and three consecutive frames of evidence. With automatic fire enabled, firing begins when the conditions are met and continues until the target has been lost for one second by default. Tracking and weapons have separate switches.

### Technology

| Technology | Role |
|---|---|
| Python 3.12 | Host loop, recording, replay and debugging tools |
| DXCAM / DXGI | Windows screen capture and frame timestamps |
| OpenCV / NumPy | HUD processing, feature detection and numerical operations |
| Kalman filter | Lead-pip position and velocity estimation |
| PD control, feed-forward, Smith predictor | Turret tracking and delay compensation |
| Pydantic / YAML | Configuration loading and validation |
| pyserial | Host-to-Pico serial communication |
| C / Pico SDK / TinyUSB | Pico firmware and USB HID input |
| Windows API | Game focus detection and control panel |

See the [implementation notes](docs/architecture.md) and [HUD notes](docs/hud.md) for details.

## Installation and configuration

The live controller requires Windows, Python 3.12, Git, a Pico 2 W and a USB data cable.

### Host setup

Run in PowerShell:

```powershell
git clone https://github.com/LouieLumi/StarCitizen-AIGuner.git
cd StarCitizen-AIGuner
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Firmware

Build and flash the Pico following the [firmware instructions](docs/firmware.md). This requires the ARM toolchain, Pico SDK, CMake, Ninja and picotool.

After flashing, the device appears as `AI Crew Controller`. The host locates its serial port by VID/PID automatically.

### Configuration

Edit [`config/config.yaml`](config/config.yaml):

| Section | Setting |
|---|---|
| `screen` | Screen resolution; default 2560×1440 |
| `capture` | GPU and monitor used for capture |
| `roi` | HUD detection region; default origin `(680,270)`, size `1200×900` |
| `aim` | Fallback crosshair position relative to the ROI |
| `control` | Turret response model, gains and mouse limits |
| `recording.dir` | Video and event-screenshot directory; default `recordings/` |

Other resolutions also require changes to the finder exclusion areas, shape sizes and range-ring radius. These are pixel-based parameters and do not scale automatically.

Personal settings can be saved in `config/config.local.yaml` and selected with `--config config/config.local.yaml`. Git ignores this file.

## Usage

Enter the turret and select **FPS mouse mode**. The controller is calibrated for that mode; in virtual joystick mode, stopping mouse movement does not necessarily stop turret rotation.

Double-click **`start_gunner.bat`** to start with fire control and automatic fire enabled. The program searches for targets, turns toward them, tracks the pip and fires when range conditions are met.

The floating panel has two switches:

- **火控系统** (fire control): automatic locking, search and tracking. Turning it off stops all control.
- **武器系统** (weapons): automatic fire. Tracking can remain active while firing manually.

The panel can be dragged and locked in place. Input pauses when the game loses focus. Close the console or press Ctrl+C to exit.

Command-line equivalents, run from the project directory:

```powershell
# Start with both switches off; enable them through the panel
.venv\Scripts\python.exe host\main.py

# Enable tracking and automatic fire, as with the batch file
.venv\Scripts\python.exe host\main.py --enable --auto-fire

# Run detection and tracking without HID output; no Pico required
.venv\Scripts\python.exe host\main.py --dry-run --enable --seconds 30
```

Run in the logged-in Windows desktop session. For SSH, use `desktop_run.ps1` as described in the [usage guide](docs/usage.md).

Disable fire control before opening chat to prevent the automatic T lock key from being entered into the chat box. Turning off fire control or weapons stops firing. The lost-target firing delay is set by `fire.stop_after_unlocked_s`, with a default of one second. The Pico releases buttons, stops mouse movement and centers the joystick after 100 ms without new commands.

## Source and debugging

`host/` contains the Python controller, `firmware/` the Pico firmware, `config/` the settings, and `tools/` the recording, replay, detection and calibration utilities. Offline tests are in `tests/`.

After changing turrets or sensitivity, use `tools/turret_ident.py` to measure response delay, smoothing and gain. Offline replay requires no Pico and allows detection settings to be compared against the same recording.

Logs, recordings and personal settings are excluded from Git. Lossless recording can consume several GB per minute. Tool commands are documented in the [usage guide](docs/usage.md); development setup and offline tests are in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

This project uses [PolyForm Noncommercial 1.0.0](LICENSE), permitting noncommercial use, modification and redistribution under its terms. **Commercial use is not granted.** Preserve the license and [copyright notice](NOTICE) when redistributing.

This is my personal project and has no official affiliation with CIG or RSI. Star Citizen imagery and trademarks belong to their respective owners.
