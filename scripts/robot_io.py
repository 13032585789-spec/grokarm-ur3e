"""Read the arm's current joints for the helper scripts, on a UR (RTDE) or an xArm 5 (SDK). Never moves it."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def poses_path() -> Path:
    """config/poses.yaml, or the poses_file named by the arm's config (ROBOT_CONFIG in .env)."""
    import yaml
    from dotenv import load_dotenv

    from app.config import CONFIG_DIR
    load_dotenv(ROOT / ".env")
    robot = yaml.safe_load((CONFIG_DIR / (os.getenv("ROBOT_CONFIG") or "robot.yaml")).read_text(encoding="utf-8"))
    return CONFIG_DIR / str(robot.get("poses_file") or "poses.yaml")


def is_xarm(settings) -> bool:
    return str((settings.robot.get("robot") or {}).get("model", "")).replace(" ", "").lower().startswith("xarm")


def read_joints(settings) -> tuple[list[float], bool]:
    """(joints in rad, moving?) from the real arm."""
    if is_xarm(settings):
        from app.robot.xarm import STATE_MOVING, XArmAdapter
        ad = XArmAdapter(settings)
        ad.connect()
        try:
            time.sleep(0.3)
            q = ad.current_joints()
            if q is None:
                raise SystemExit("xArm: nessun dato giunti")
            return q, int(ad.arm.state or 0) == STATE_MOVING
        finally:
            ad.disconnect()
    from app.robot.ur import RTDEReader
    r = RTDEReader(settings.robot_host, int(settings.robot["connections"]["ports"]["rtde"]))
    r.connect(3.0)
    end = time.monotonic() + 3.0
    while not r.fresh() and time.monotonic() < end:
        time.sleep(0.02)
    if not r.fresh():
        raise SystemExit("Nessun dato RTDE dal robot: è acceso e collegato?")
    d = r.latest
    r.close()
    return [float(v) for v in d["actual_q"]], any(abs(v) > 0.005 for v in d.get("actual_qd") or [])
