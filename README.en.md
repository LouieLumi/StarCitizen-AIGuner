# StarCitizen AIGuner

[中文](README.md) · [Architecture](docs/architecture.md) · [Firmware](docs/firmware.md)

An experimental external vision controller for the Star Citizen turret HUD. It captures the Windows desktop, detects the crosshair and lead pip, tracks the pip, and sends USB HID input through a Raspberry Pi Pico 2 W.

The host uses OpenCV, Kalman filtering and PD control. No model weights, cloud API, game-memory reads or process injection are required.

**Source available for noncommercial use only**, under [PolyForm Noncommercial 1.0.0](LICENSE). Noncommercial use, modification and redistribution are permitted subject to the license. Commercial use is not granted by this license. This is not a permissive open-source license.

![Offline tracking examples](docs/assets/track_strip.png)

## Scope

Live capture and control require Windows 10/11, Python 3.12 and an interactive desktop session. Hardware output requires the Pico firmware. `--dry-run` works without a Pico and sends no HID input. Offline tests and analysis can run on Windows, macOS and Linux.

The default configuration is calibrated for a 2560×1440 Polaris turret HUD in FPS mouse mode. Different HUDs, resolutions, sensitivities and turrets need recalibration. The author has validated and used the complete system on the original setup. Other configurations still need calibration.

## Windows setup

```powershell
git clone https://github.com/LouieLumi/StarCitizen-AIGuner.git
cd StarCitizen-AIGuner
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
```

Build and flash the Pico following [the firmware guide](docs/firmware.md), or skip hardware for a dry run. Edit `config/config.yaml` for your monitor, screen dimensions, ROI and HUD geometry. Coordinates do not scale automatically. `aim` is ROI-relative; `finder` exclusion rectangles use full-screen coordinates.

Run from the project root, in the logged-in Windows desktop session:

```powershell
# Detection and state machine only; no HID output
.venv\Scripts\python.exe host\main.py --dry-run --enable --seconds 30
# Both control switches initially off; use the floating panel
.venv\Scripts\python.exe host\main.py
# Start with tracking, automatic target locking and auto fire enabled
.venv\Scripts\python.exe host\main.py --enable --auto-fire
```

`start_gunner.bat` starts with tracking and auto fire **enabled**. Disable fire control before opening game chat: the controller may otherwise type its automatic T lock key into chat. Use FPS mouse mode; stopping relative mouse motion does not center a virtual joystick.

Turn off the panel switches to stop control, or exit with Ctrl+C. A second terminal can request shutdown with `New-Item logs\stop_main -ItemType File -Force`. Firmware releases outputs after 100 ms without commands. Game focus loss pauses active input.

Recordings and event screenshots default to `recordings/`; frame logs go to `logs/`. Both are ignored by Git. For local settings, copy the config to `config/config.local.yaml` and pass `--config config/config.local.yaml`.

## Development and documentation

See [CONTRIBUTING.md](CONTRIBUTING.md) for offline setup, [usage](docs/usage.md) for tools and calibration, and [HUD notes](docs/hud.md) for detection details. Windows/Linux CI exercises offline logic only, not live capture, USB hardware or a complete firmware build.

Copyright 2026 LouieLumi. See [LICENSE](LICENSE) and [NOTICE](NOTICE). This project is not affiliated with or endorsed by Cloud Imperium Games or Roberts Space Industries. Game imagery and trademarks remain the property of their respective owners and are not relicensed with the code.
