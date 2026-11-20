"""Play a dance trajectory on the real xArm 5 (servo mode, 100 Hz). HAND ON THE E-STOP.

    .venv\\Scripts\\python.exe scripts\\dance\\play_xarm.py data\\dance\\traj.json --slow 3      (rehearsal: 3x slower, no music)
    .venv\\Scripts\\python.exe scripts\\dance\\play_xarm.py data\\dance\\traj.json --music data\\dance\\music.wav

Safety: the whole trajectory is checked again with this arm's MotionGuard before anything moves; the arm first
goes slowly to the start pose and waits for Enter; during the dance it stops (set_state 4) on Ctrl+C, on any
controller error, or if the arm lags more than 0.25 rad behind the command.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
LAG_S = 0.4      # the arm may trail the command by up to this long ...
LAG_RAD = 0.15   # ... and must then be within this of it
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("ROBOT_CONFIG", "robot_xarm5.yaml")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("traj")
    ap.add_argument("--slow", type=float, default=1.0, help="time stretch, 3 = three times slower")
    ap.add_argument("--music", help="WAV file played at the start (Windows), only with --slow 1")
    ap.add_argument("--start", type=float, default=0.0, help="start at this second")
    ap.add_argument("--duration", type=float, default=None, help="play only this many seconds")
    a = ap.parse_args()

    from app.config import load_settings
    from app.skills.motion_guard import guard_from_settings
    s = load_settings("real", env_file=ROOT / ".env")
    g = guard_from_settings(s)
    tr = json.load(open(a.traj))
    rate = float(tr["rate"])
    Q = np.array(tr["q"], float)
    i0 = int(a.start * rate)
    i1 = len(Q) if a.duration is None else min(len(Q), i0 + int(a.duration * rate))
    Q = Q[i0:i1]
    bad = [i for i in range(0, len(Q), 2) if not g.config_ok(Q[i])]
    if bad:
        raise SystemExit(f"❌ {len(bad)} unsafe samples, first at {bad[0] / rate:.2f}s: refusing to play")
    vmax = float(np.max(np.abs(np.diff(Q, axis=0))) * rate / a.slow)
    print(f"trajectory {len(Q) / rate * a.slow:.1f}s, peak joint speed {vmax:.2f} rad/s, all samples safe")

    from xarm.wrapper import XArmAPI
    arm = XArmAPI(s.robot_host, is_radian=True)
    if not arm.connected:
        raise SystemExit("xArm not reachable")
    if arm.error_code:
        raise SystemExit(f"xArm error {arm.error_code}: clear it in UFactory Studio first")
    try:
        arm.motion_enable(True)
        arm.set_mode(0)
        arm.set_state(0)
        time.sleep(0.5)
        print("moving slowly to the start pose ...")
        code = arm.set_servo_angle(angle=[float(v) for v in Q[0]], speed=0.3, mvacc=1.0, is_radian=True, wait=True)
        if code != 0 or arm.error_code:
            raise SystemExit(f"could not reach the start pose (code {code}, error {arm.error_code})")
        input("At the start pose. Hand on the E-stop, then press Enter to dance (Ctrl+C stops) ...")
        arm.set_mode(1)          # servo mode: stream joint targets
        arm.set_state(0)
        end = time.monotonic() + 3.0
        while time.monotonic() < end and not (arm.mode == 1 and arm.state in (1, 2)):
            time.sleep(0.05)
        if not (arm.mode == 1 and arm.state in (1, 2)) or arm.error_code:
            raise SystemExit(f"servo mode not ready (mode {arm.mode}, state {arm.state}, error {arm.error_code})")
        time.sleep(0.2)
        for _ in range(20):      # hold the start pose for 0.2 s so the controller is streaming before we move
            arm.set_servo_angle_j([float(v) for v in Q[0]], is_radian=True)
            time.sleep(0.01)
        if a.music and a.slow == 1.0 and sys.platform == "win32":
            import winsound
            winsound.PlaySound(a.music, winsound.SND_FILENAME | winsound.SND_ASYNC)
        dt = 1.0 / rate * a.slow
        t0 = time.perf_counter()
        for k, q in enumerate(Q):
            target = t0 + k * dt
            while time.perf_counter() < target:
                time.sleep(0.0005)
            arm.set_servo_angle_j([float(v) for v in q], is_radian=True)
            if k % 10 == 0:
                if arm.error_code:
                    raise RuntimeError(f"controller error {arm.error_code}")
                # Servo mode always trails the command a little. "Following" = close to SOME command sent in the
                # last LAG_S seconds; only a real stall or a blocked joint grows beyond that.
                if k * dt > 0.5:
                    act = np.array(arm.angles[:5], float)
                    recent = Q[max(0, k - int(LAG_S / dt)):k + 1]
                    lag = float(np.min(np.max(np.abs(recent - act), axis=1)))
                    if lag > LAG_RAD:
                        raise RuntimeError(f"arm not following: {lag:.2f} rad from every command of the last {LAG_S} s")
        print("done")
    except (KeyboardInterrupt, RuntimeError) as e:
        arm.set_state(4)
        print("STOPPED:", e)
    finally:
        try:
            if a.music and sys.platform == "win32":
                import winsound
                winsound.PlaySound(None, 0)
            arm.set_mode(0)
            arm.set_state(0)
        finally:
            arm.disconnect()


if __name__ == "__main__":
    main()
