"""Dance retargeting: cleaned 2D keypoints of a dancer -> xArm 5 joint trajectory (100 Hz). Moves nothing.

    python scripts/dance/retarget.py kp_clean.json traj.json [--amp 1.0] [--vmax 1.2]

Mapping (both hands, robust to one being missed):
  hands centre left/right  -> base yaw            hands height       -> flange height
  distance between hands   -> reach               tilt of the hands  -> tool roll (J5)
  hands high               -> tool tips up from pointing down to forward
Then: analytic IK on one continuous branch, joint speed / acceleration limiting, MotionGuard check on every frame.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
from scipy.signal import savgol_filter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("ROBOT_CONFIG", "robot_xarm5.yaml")

from app.robot.kinematics import Kinematics  # noqa: E402
from app.robot.xarm_ik import ik_all  # noqa: E402

RATE = 100.0
VMAX = np.array([1.2, 1.0, 1.2, 2.0, 2.5])     # rad/s per joint (xArm limit is 3.14)
AMAX = np.array([6.0, 5.0, 6.0, 10.0, 12.0])  # rad/s^2


def body_signals(kp: dict) -> dict[str, np.ndarray]:
    P = {k: np.asarray(v, float) for k, v in kp.items()}
    c = (P["lsh"] + P["rsh"]) / 2
    sw = float(np.median(np.linalg.norm(P["lsh"] - P["rsh"], axis=1)))
    H = (P["lwri"] + P["rwri"]) / 2
    d = P["rwri"] - P["lwri"]
    return {
        "u": (H[:, 0] - c[:, 0]) / sw,                    # image right +
        "v": (c[:, 1] - H[:, 1]) / sw,                    # up +, 0 = shoulder height
        "spread": np.linalg.norm(d, axis=1) / sw,
        "tilt": np.arctan2(-d[:, 1], -d[:, 0]),           # 0 = level
    }


def targets(sig: dict, amp: float, mirror: bool) -> np.ndarray:
    """Per frame: yaw, radius, height, tool pitch (from horizontal), roll."""
    s = -1.0 if mirror else 1.0
    yaw = np.clip(s * 0.9 * amp * sig["u"], -0.9, 0.9)
    z = np.clip(0.32 + 0.11 * amp * sig["v"], 0.20, 0.55)
    r = np.clip(0.30 + 0.05 * amp * (sig["spread"] - 1.0), 0.24, 0.44)
    hi = np.clip((sig["v"] + 0.5) / 1.7, 0.0, 1.0)
    pitch = np.radians(-90 + 60 * hi * amp)
    tilt = (sig["tilt"] + np.pi / 2) % np.pi - np.pi / 2
    roll = np.clip(amp * tilt, -1.2, 1.2)
    return np.stack([yaw, r, z, pitch, roll], 1)


def flange_pose(yaw, r, z, pitch, roll) -> np.ndarray:
    radial = np.array([math.cos(yaw), math.sin(yaw), 0.0])
    up = np.array([0.0, 0.0, 1.0])
    zt = math.cos(pitch) * radial + math.sin(pitch) * up           # tool axis, in the arm's plane
    xt = np.cross(np.cross(radial, up), zt)                         # perpendicular, in the plane
    xt /= np.linalg.norm(xt)
    yt = np.cross(zt, xt)
    c, s = math.cos(roll), math.sin(roll)
    R = np.column_stack((c * xt + s * yt, -s * xt + c * yt, zt))
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = r * radial + np.array([0, 0, z])
    return T


def solve(tg: np.ndarray, kin: Kinematics, q0: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> tuple[np.ndarray, int]:
    out, miss, q = [], 0, q0.copy()
    for row in tg:
        sols = [x for x in ik_all(kin, flange_pose(*row), q) if np.all(x >= lo) and np.all(x <= hi)]
        if not sols:
            miss += 1
            out.append(q.copy())
            continue
        q = min(sols, key=lambda x: float(np.sum(np.abs(x - q))))
        out.append(q.copy())
    return np.array(out), miss


def limit(Q: np.ndarray, dt: float) -> np.ndarray:
    """Forward-backward speed and acceleration limiting (keeps the timing, trims the peaks)."""
    def one_pass(Q):
        out = [Q[0].copy()]
        v = np.zeros(Q.shape[1])
        for t in range(1, len(Q)):
            want = (Q[t] - out[-1]) / dt
            dv = np.clip(want - v, -AMAX * dt, AMAX * dt)
            v = np.clip(v + dv, -VMAX, VMAX)
            out.append(out[-1] + v * dt)
        return np.array(out)
    a = one_pass(Q)
    b = one_pass(Q[::-1])[::-1]
    return (a + b) / 2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kp")
    ap.add_argument("out")
    ap.add_argument("--amp", type=float, default=1.0, help="movement size, 0.5 = half")
    ap.add_argument("--mirror", action="store_true", help="mirror left/right (audience behind the camera)")
    a = ap.parse_args()
    d = json.load(open(a.kp))
    fps = float(d["fps"])
    tg = targets(body_signals(d["kp"]), a.amp, a.mirror)
    t_src = np.arange(len(tg)) / fps
    t = np.arange(0, t_src[-1], 1 / RATE)
    tg = np.stack([np.interp(t, t_src, tg[:, k]) for k in range(tg.shape[1])], 1)
    tg = savgol_filter(tg, 21, 3, axis=0)

    from app.config import load_settings
    from app.skills.motion_guard import guard_from_settings
    s = load_settings("sim", env_file=None)
    s.robot.setdefault("gripper", {})["enabled"] = False          # bare flange (nothing mounted)
    g = guard_from_settings(s)
    kin = Kinematics("xArm5")
    q0 = np.array(s.poses["home"]["joints"], float)
    Q, miss = solve(tg, kin, q0, g.lo, g.hi)
    Q = limit(savgol_filter(Q, 15, 3, axis=0), 1 / RATE)
    bad = [i for i in range(0, len(Q), 5) if not g.config_ok(Q[i])]
    margins = [g.margins(Q[i]) for i in bad[:3]]
    vel = np.abs(np.diff(Q, axis=0)) * RATE
    json.dump({"rate": RATE, "fps_src": fps, "amp": a.amp, "q": np.round(Q, 5).tolist(),
               "targets": np.round(tg, 4).tolist()}, open(a.out, "w"))
    print(f"frames {len(Q)} ({len(Q) / RATE:.1f} s), IK misses {miss}, unsafe samples {len(bad)}")
    print("max joint speed (rad/s):", np.round(vel.max(0), 2), " limit", VMAX)
    print("joint range (deg): ", [f"{math.degrees(a):.0f}..{math.degrees(b):.0f}" for a, b in zip(Q.min(0), Q.max(0))])
    if bad:
        print("first unsafe:", {k: round(v, 3) for k, v in min(margins[0].items(), key=lambda kv: kv[1]) and margins[0].items() if v < 0})


if __name__ == "__main__":
    main()
