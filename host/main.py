"""AI Gunner main loop: capture -> HUD detector -> Kalman tracker -> controller -> Pico.

Once fire control is on it:
- locks a target itself (taps T) when none is locked;
- turns towards the locked target - its red label on screen or the red
  off-screen arrow - while ARMED/SEARCHING, until the pip is close;
- TRACKS the pip: only with a live pip track AND a visible crosshair (so never in
  menus or out of the turret);
- with weapons on, fires once the target is in range (host/fire_control.py).
Output only while the game has the focus.

Controlled from the floating panel (host/control_panel.py): fire control and
weapons switches. Creating logs/stop_main triggers an emergency stop and exits.

    python host/main.py --enable --auto-fire   # both switches on (start_gunner.bat)
    python host/main.py                        # both off: switch on in the panel
    python host/main.py --dry-run              # full pipeline, never touches the mouse
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from capture import ScreenCapture  # noqa: E402
from config import DEFAULT_PATH, ROOT, load_config  # noqa: E402
from control_panel import ControlPanel  # noqa: E402
from fire_control import FireControl  # noqa: E402
from game_window import GameWindow  # noqa: E402
from controller import PDController  # noqa: E402
from detector import HudDetector  # noqa: E402
from logger import SessionLogger  # noqa: E402
from overlay import describe, draw_detection, draw_track  # noqa: E402
from own_motion import OwnMotion  # noqa: E402
from pico_link import PicoLink  # noqa: E402
from search import Search  # noqa: E402
from state_machine import GunnerStateMachine, State  # noqa: E402
from target_finder import TargetFinder  # noqa: E402
from tracker import PipTracker  # noqa: E402
from weapon_range import RangeFilter  # noqa: E402

STOP_FILE = ROOT / "logs" / "stop_main"
# Screenshot on request (e.g. over SSH) without opening anything on the desktop:
# create logs\snap_main, get logs\snap_main.jpg (full screen, half size).
SNAP_REQUEST = ROOT / "logs" / "snap_main"
SNAP_FILE = ROOT / "logs" / "snap_main.jpg"
NO_TARGET_SHOT_AFTER_S = 5.0  # armed, crosshair seen, but no locked target found this long:
NO_TARGET_SHOT_EVERY_S = 10.0  # save the full screen (half size) to see why
AIM_STALE_S = 0.3  # crosshair must have been seen this recently to move
STATUS_EVERY_S = 1.0
STATE_ZH = {State.DISABLED: "已关闭", State.ARMED: "待命", State.SEARCHING: "搜索目标", State.TRACKING: "跟踪中",
            State.READY: "射程内", State.FIRING: "射程内", State.TARGET_LOST: "目标丢失", State.EMERGENCY_STOP: "急停"}

EVENT_NAMES = {State.TRACKING: "TARGET_ACQUIRED", State.TARGET_LOST: "TARGET_LOST", State.EMERGENCY_STOP: "EMERGENCY_STOP",
               State.READY: "IN_RANGE"}


def _search_point(hint, det, r) -> dict:
    """Where the finder's hint points, screen px (for the log)."""
    if hint is None:
        return {}
    if hint.point is not None:
        return {"search_x": hint.point[0], "search_y": hint.point[1]}
    ax, ay = det.aim[0] + r.x, det.aim[1] + r.y
    return {"search_x": ax + 300 * hint.direction[0], "search_y": ay + 300 * hint.direction[1]}


def _disable_console_quick_edit() -> None:
    """Started from a console window (start_gunner.bat): with QuickEdit on, a click
    into the window starts a text selection and Windows blocks the program at its
    next print until the selection ends - aiming, fire and the panel all freeze."""
    if sys.platform != "win32":
        return
    import ctypes

    k32 = ctypes.windll.kernel32
    handle = k32.GetStdHandle(-10)  # STD_INPUT_HANDLE
    mode = ctypes.c_uint32()
    if k32.GetConsoleMode(handle, ctypes.byref(mode)):
        ENABLE_QUICK_EDIT_MODE, ENABLE_EXTENDED_FLAGS = 0x0040, 0x0080
        k32.SetConsoleMode(handle, (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(DEFAULT_PATH))
    ap.add_argument("--dry-run", action="store_true", help="never send anything to the Pico")
    ap.add_argument("--enable", action="store_true", help="start with fire control on")
    ap.add_argument("--auto-fire", action="store_true", help="start with weapons (auto fire) on")
    ap.add_argument("--seconds", type=float, default=0, help="exit after N seconds")
    ap.add_argument("--no-panel", action="store_true", help="no floating control panel")
    ap.add_argument("--dither", type=int, default=0, metavar="COUNTS",
                    help="while tracking, add random -N/0/+N counts per frame and axis (for "
                         "tools/turret_ident.py: measures how the turret follows our turns)")
    args = ap.parse_args()
    _disable_console_quick_edit()

    cfg = load_config(args.config)
    STOP_FILE.unlink(missing_ok=True)
    link = None if args.dry_run else PicoLink()
    panel = None if args.no_panel else ControlPanel(ROOT / "logs" / "panel.json")
    game = GameWindow(cfg.game.exe)
    detector = HudDetector(cfg)
    tracker = PipTracker(cfg.tracker)
    weapon_range = RangeFilter(cfg.range)
    fire = FireControl(cfg.fire)
    controller = PDController(cfg.control)
    finder = TargetFinder(cfg.finder)
    search = Search(cfg.finder)
    r = cfg.roi
    sm = GunnerStateMachine()
    log = SessionLogger(cfg.recording.path)
    print(f"AI Gunner | {'DRY RUN (no mouse output)' if args.dry_run else 'Pico ' + link.port} | "
          f"{'no panel' if panel is None else 'control panel'}")
    print(f"log: {log.csv_path}", flush=True)

    t0 = time.perf_counter()
    # Weapons switch: remembered while fire control is off, applied whenever it is on.
    # Fire control switch: the state machine (on = enabled, off = disabled).
    want_fire = args.auto_fire
    if args.enable:
        sm.enable(t0)
    sm.set_auto_fire(want_fire)
    if want_fire:
        print("auto fire ON (--auto-fire)", flush=True)
    game_front = True
    last_aim_seen = -1e9
    hint, search_frame = None, 0
    since_hint = (0.0, 0.0)  # own view motion since the finder last looked
    no_target_since: float | None = None
    last_lock_press = -1e9
    lock_key_up_at: float | None = None  # lock key is down until then
    lock_pressed = False
    prev_buttons = 0
    last_no_target_shot = -1e9
    t_prev = None
    # Our turns as the frames will show them: the tracker learns about each part
    # when it shows up; the controller counts the rest as already done.
    own = OwnMotion(cfg.control.view_delay_frames, cfg.control.view_smoothing, cfg.control.px_per_count)
    rng = np.random.default_rng()
    fps = 0.0
    next_status = t0 + STATUS_EVERY_S
    reason = "?"
    frame = None
    try:
        with ScreenCapture(cfg, full_screen=True) as cap:
            while True:
                now = time.perf_counter()
                lock_pressed = False
                while panel and not panel.actions.empty():
                    switch, on = panel.actions.get()
                    if switch == "fire_control" and on:
                        if sm.state == State.EMERGENCY_STOP:
                            sm.disable(now)  # the switch clears an emergency stop
                        sm.enable(now)
                    elif switch == "fire_control":
                        sm.disable(now)
                    elif switch == "weapons":
                        want_fire = on
                    sm.set_auto_fire(want_fire)
                    print(f"[panel] {switch} {'on' if on else 'off'} -> {sm.state.value} | "
                          f"auto fire {'ON' if sm.auto_fire else 'off'}", flush=True)

                # Only while the game has the focus do moves, fire and keys go out.
                front = game.in_front()
                if front != game_front:
                    game_front = front
                    print(f"[focus] game {'in front: output on' if front else 'not in front: output paused'}", flush=True)
                    if link and not front:
                        link.stop()
                out = link if game_front else None
                if STOP_FILE.exists():
                    sm.emergency(now)
                    reason = "stop file"
                if args.seconds and now - t0 >= args.seconds:
                    reason = "time limit"

                frame = cap.read(timeout=0.1)
                if frame is None:
                    # No new frame (game paused/minimised): nothing to steer by.
                    tracker.predict(time.perf_counter())
                    sm.update(time.perf_counter(), tracking=False)
                    det = track = hint = wr = None
                    counts = search_counts = (0, 0)
                    search.reset()
                    weapon_range.reset()
                else:
                    t = frame.present_time
                    roi_img = frame.image[r.y:r.y + r.height, r.x:r.x + r.width]
                    predicted = tracker.predict(t)
                    sx, sy = own.next_frame()
                    since_hint = (since_hint[0] + sx, since_hint[1] + sy)
                    if predicted is not None and (sx or sy):
                        # Our own turn moves the view: tell the tracker, so its velocity is
                        # the target's alone (else it chases its own motion while coasting).
                        tracker.shift(-sx, -sy)
                        predicted = (predicted[0] - sx, predicted[1] - sy)
                    det = detector.detect(roi_img, pip_hint=predicted)
                    track = tracker.update(det, t)
                    if det.aim_conf > 0:
                        last_aim_seen = t
                    tracking = track is not None and t - last_aim_seen <= AIM_STALE_S
                    wr = weapon_range.update(det, t)
                    # READY = tracked and in weapon range (green, held >= 80 ms); FIRING = READY
                    # with auto fire on. The trigger (host/fire_control.py) opens fire from there
                    # and keeps firing until the target has been gone for a while.
                    sm.update(t, tracking, fire_ready=tracking and wr.in_range)

                    counts = (0, 0)
                    if sm.may_move and track.since_update * 1000 <= cfg.control.coast_hold_ms:
                        err = (track.x - det.aim[0], track.y - det.aim[1])
                        if cfg.control.lead_target and max(abs(track.vx), abs(track.vy)) >= cfg.control.ff_min_speed:
                            ahead = own.mean_delay_frames * (1 / fps if fps else 1 / 30) * cfg.control.lead_scale
                            err = (err[0] + track.vx * ahead, err[1] + track.vy * ahead)
                        if cfg.control.smith_predictor:
                            fx, fy = own.in_flight
                            err = (err[0] - fx, err[1] - fy)
                        counts = controller.step(err, 0.0 if t_prev is None else t - t_prev, (track.vx, track.vy))
                    elif not sm.may_move:
                        controller.reset()
                    # Coasting (pip briefly hidden): hold still, don't chase the prediction.

                    # No pip yet: turn towards the locked target (screen coordinates).
                    search_counts = (0, 0)
                    if sm.may_search and track is None and t - last_aim_seen <= AIM_STALE_S:
                        aim_screen = (det.aim[0] + r.x, det.aim[1] + r.y)
                        if search_frame % cfg.finder.every == 0:  # the finder is slow; turning changes slowly
                            hint = finder.find(frame.image, aim_screen)
                            since_hint = (0.0, 0.0)
                        search_frame += 1
                        # Where the target will be relative to the crosshair once the turns
                        # already made (shown since the hint, or still in flight) are done.
                        fx, fy = own.in_flight
                        aim_eff = (aim_screen[0] + since_hint[0] + fx, aim_screen[1] + since_hint[1] + fy)
                        search_counts = search.step(hint, aim_eff, t)
                        if hint is None:
                            no_target_since = t if no_target_since is None else no_target_since
                            # Nothing locked in sight for a while: lock something ourselves (T).
                            f = cfg.finder
                            if (out and f.lock_key and t - no_target_since >= f.lock_after_s
                                    and t - last_lock_press >= f.lock_every_s):
                                out.key(f.lock_key)
                                lock_key_up_at = time.perf_counter() + f.lock_hold_s
                                last_lock_press, lock_pressed = t, True
                                print(f"[lock] pressed lock key (no locked target for {t - no_target_since:.1f} s)", flush=True)
                            if t - no_target_since >= NO_TARGET_SHOT_AFTER_S and t - last_no_target_shot >= NO_TARGET_SHOT_EVERY_S:
                                last_no_target_shot = t
                                log.event("NO_TARGET", cv2.resize(frame.image, None, fx=0.5, fy=0.5))
                        else:
                            no_target_since = None
                    else:
                        search.reset()
                        hint, search_frame = None, 0
                        no_target_since = None
                    if SNAP_REQUEST.exists():
                        SNAP_REQUEST.unlink(missing_ok=True)
                        cv2.imwrite(str(SNAP_FILE), cv2.resize(frame.image, None, fx=0.5, fy=0.5),
                                    [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if t_prev is not None and t > t_prev:
                        fps = 0.9 * fps + 0.1 / (t - t_prev) if fps else 1 / (t - t_prev)
                    t_prev = t

                # Trigger: opens fire in READY / FIRING with auto fire on, then holds until the
                # target has not been locked for fire.stop_after_unlocked_s; fire control or
                # weapons off (or the game losing the focus) release at once.
                armed = sm.auto_fire and sm.state not in (State.DISABLED, State.EMERGENCY_STOP) and game_front
                locked = frame is not None and det is not None and (track is not None or det.pip is not None)
                buttons = cfg.fire.button if fire.trigger(
                    time.perf_counter(), armed, sm.state in (State.READY, State.FIRING), locked) else 0

                # Output: moves only while engaged; STOP once whenever we leave that (unless
                # the trigger is still held, which is refreshed below).
                for t_tr, old, new in sm.drain_transitions():
                    print(f"[state] {old.value} -> {new.value}", flush=True)
                    acquired_again = new == State.TRACKING and old in (State.READY, State.FIRING)
                    shot = None
                    if frame is not None and det is not None:
                        shot = draw_track(draw_detection(roi_img.copy(), det, describe(det)), track)
                    if new in EVENT_NAMES and not acquired_again:
                        log.event(EVENT_NAMES[new], shot)
                    if link and not sm.may_move and not buttons:
                        link.stop()
                if bool(buttons) != bool(prev_buttons):
                    print(f"[fire] {'OPEN' if buttons else 'CEASE'}", flush=True)
                    if frame is not None and det is not None:
                        log.event("FIRE_START" if buttons else "FIRE_STOP",
                                  draw_track(draw_detection(roi_img.copy(), det, describe(det)), track))
                planned = dither = (0, 0)
                sent = False
                if sm.may_move:
                    if args.dither:
                        # independent of the target, so its effect on the pip can be told apart
                        dither = tuple(int(v) for v in rng.choice((-args.dither, 0, args.dither), 2, p=(0.25, 0.5, 0.25)))
                    planned = (counts[0] + dither[0], counts[1] + dither[1])
                    if out:
                        out.move(planned[0], planned[1], buttons)
                        sent = True
                elif sm.may_search and (search_counts != (0, 0) or buttons):
                    planned = search_counts
                    if out:
                        out.move(planned[0], planned[1], buttons)
                        sent = True
                if link and not sent and (buttons or prev_buttons):
                    link.move(0, 0, buttons)  # hold the trigger while the target is briefly lost / release it
                prev_buttons = buttons
                if lock_key_up_at is not None and time.perf_counter() >= lock_key_up_at:
                    if link:
                        link.key(0)
                    lock_key_up_at = None
                if frame is not None:  # dry run / game not in front: the view doesn't move
                    own.sent(planned if sent else (0, 0))
                if panel:
                    status = STATE_ZH[sm.state]
                    if buttons and out:
                        status += " · 开火中"
                    if not game_front:
                        status += " · 游戏不在前台，暂停输出"
                    if args.dry_run:
                        status += " · 试运行"
                    panel.show(sm.state not in (State.DISABLED, State.EMERGENCY_STOP), want_fire, status,
                               alert=not game_front or sm.state == State.EMERGENCY_STOP)

                if det is not None:
                    err = det.error if track is None else (track.x - det.aim[0], track.y - det.aim[1])
                    log.row(
                        timestamp=frame.present_time, fps=fps,
                        target_x=det.pip[0] if det.pip else None, target_y=det.pip[1] if det.pip else None,
                        predicted_x=track.x if track else None, predicted_y=track.y if track else None,
                        aim_x=det.aim[0], aim_y=det.aim[1],
                        error_x=err[0] if err else None, error_y=err[1] if err else None,
                        pid_x=planned[0], pid_y=planned[1], dither_x=dither[0], dither_y=dither[1],
                        tracking_confidence=track.confidence if track else 0.0,
                        green=bool(track and track.green), fire=bool(buttons and out), state=sm.state.value,
                        lock_key=lock_pressed,
                        ring=det.ring, range_conf=wr.confidence if wr else 0.0,
                        in_range=bool(wr and wr.in_range),
                        latency=frame.age_ms(),
                        search="blocked" if search.blocked else (hint.kind if hint else ""),
                        **_search_point(hint, det, r),
                    )
                if now >= next_status:
                    e = "-" if det is None or track is None else f"({track.x - det.aim[0]:+.0f},{track.y - det.aim[1]:+.0f})"
                    if sm.may_search:
                        what = "blocked (timeout)" if search.blocked else (
                            "-" if hint is None else f"{hint.kind} {'%.0fpx' % hint.distance if hint.distance else ''}"
                            f" dir ({hint.direction[0]:+.2f},{hint.direction[1]:+.2f})")
                        print(f"{sm.state.value:14s} fps {fps:4.1f} | search {what} | mouse {search_counts} | "
                              f"latency {frame.age_ms() if frame else 0:4.0f} ms", flush=True)
                    else:
                        rs = "-" if wr is None else ("IN RANGE" if wr.in_range else "green" if wr.evidence else "out")
                        print(f"{sm.state.value:14s} fps {fps:4.1f} | error {e:>11s} | mouse {counts} | "
                              f"range {rs:8s} | fire {'HOLD' if buttons and out else '-':4s} | "
                              f"latency {frame.age_ms() if frame else 0:4.0f} ms", flush=True)
                    next_status = now + STATUS_EVERY_S
                if reason != "?":
                    break
    except KeyboardInterrupt:
        reason = "ctrl-c"
    finally:
        if link:
            link.close()  # sends STOP
        if panel:
            panel.close()
        log.close()
        STOP_FILE.unlink(missing_ok=True)
    print(f"exit ({reason}), log {log.csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
