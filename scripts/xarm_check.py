"""xArm 5 first contact: reads everything, MOVES NOTHING.

    .venv\\Scripts\\python.exe scripts\\xarm_check.py

Prints connection, state/error codes, joints, and compares the controller's own flange position with our
kinematics (the number that tells whether the planner's model matches this arm).
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import load_settings  # noqa: E402
from app.robot.kinematics import Kinematics  # noqa: E402


def main() -> None:
    s = load_settings("real", env_file=ROOT / ".env")
    model = str((s.robot.get("robot") or {}).get("model"))
    print("配置:", model, " IP:", s.robot_host)
    if not model.lower().startswith("xarm"):
        raise SystemExit("❌ .env 里没有 ROBOT_CONFIG=robot_xarm5.yaml")
    try:
        from xarm.wrapper import XArmAPI
    except ImportError:
        raise SystemExit("❌ 没装 SDK: .venv\\Scripts\\python.exe -m pip install xarm-python-sdk")
    arm = XArmAPI(s.robot_host, is_radian=True)
    time.sleep(0.5)
    if not arm.connected:
        raise SystemExit(f"❌ 连不上 {s.robot_host}")
    try:
        print("连接: ✅   固件:", getattr(arm, "version", "?"), "  轴数:", getattr(arm, "axis", "?"))
        print(f"状态 state={arm.state} (1运动 2就绪 3暂停 4停止)  mode={arm.mode}  error={arm.error_code}  warn={arm.warn_code}")
        q = [float(v) for v in list(arm.angles)[:5]]
        print("关节 (rad):", " ".join(f"{v:.4f}" for v in q))
        print("关节 (deg):", " ".join(f"{math.degrees(v):.1f}" for v in q))
        pos = list(arm.position)          # x y z mm, roll pitch yaw rad (is_radian)
        tcp = list(getattr(arm, "tcp_offset", [0] * 6) or [0] * 6)
        print("控制器 TCP 位姿:", " ".join(f"{v:.1f}" for v in pos[:3]), "mm  ",
              " ".join(f"{math.degrees(v):.1f}" for v in pos[3:6]), "deg")
        print("控制器 TCP 偏移:", tcp[:3], "mm   负载:", getattr(arm, "tcp_load", "?"))
        T = Kinematics("xArm5").frames(q)[-1]
        ours = T[:3, 3] * 1000
        # controller TCP = flange + its TCP offset (flange frame); compare flange to flange
        flange_ctrl = np.array(pos[:3]) - T[:3, :3] @ np.array(tcp[:3], float)
        d = float(np.linalg.norm(flange_ctrl - ours))
        print("我们算的法兰:", " ".join(f"{v:.1f}" for v in ours), "mm")
        print(f"差: {d:.1f} mm  ->", "✅ 运动学一致" if d < 2 else "❌ 不一致：先别让它自动动，把这段输出发给我")
    finally:
        arm.disconnect()


if __name__ == "__main__":
    main()
