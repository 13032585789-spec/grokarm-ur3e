"""Why does 'take the red cup' say no safe path? Plans the grasp from the robot's CURRENT pose and prints the reason.
Never moves the robot. Needs the camera service and the robot on.

    .venv\\Scripts\\python.exe scripts\\diag_grasp.py            (red)
    .venv\\Scripts\\python.exe scripts\\diag_grasp.py blue
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.config import load_settings  # noqa: E402
from app.skills.grasp import plan_grasp  # noqa: E402
from app.skills.motion_guard import guard_from_settings  # noqa: E402
from app.vision.camera import CameraHub  # noqa: E402
from app.vision.plane import Plane  # noqa: E402
from beam_axis import read_q  # noqa: E402


def main() -> None:
    colour = sys.argv[1] if len(sys.argv) > 1 else "red"
    s = load_settings("real", env_file=ROOT / ".env")
    q = read_q(s.robot_host, int(s.robot["connections"]["ports"]["rtde"]))
    print("关节角:", " ".join(f"{v:.3f}" for v in q))
    cam = CameraHub(s)
    cam.start()
    frame = None
    for _ in range(100):
        frame = cam.fresh(3.0)
        if frame is not None:
            break
        time.sleep(0.1)
    cam.stop()
    if frame is None:
        raise SystemExit("没有相机画面")
    plane = Plane.load(s.data_dir / "plane.json")
    loc = plane.locate(frame.image, colour)
    if not loc.get("ok"):
        raise SystemExit(f"找不到{colour}杯: {loc.get('messaggio')}")
    xy = tuple(loc["xy_m"])
    print(f"{colour}杯位置: x={xy[0] * 1000:.0f} mm  y={xy[1] * 1000:.0f} mm")
    for label, mesh_on in (("网格 关", False), ("网格 开", True), ("网格 关(再来一次)", False), ("网格 开(再来一次)", True)):
        g = guard_from_settings(s)
        if not mesh_on:
            g.mesh = None
        log: list[str] = []
        orig = g.config_ok

        def spy(qq, _o=orig, _g=g, _l=log):
            ok = _o(qq)
            k, v = min(_g.margins(qq).items(), key=lambda kv: kv[1])
            _l.append(f"{'ok ' if ok else 'NO '} {k}={v * 1000:.1f}mm")
            return ok
        g.config_ok = spy
        print(f"\n[{label}]")
        try:
            p = plan_grasp(g, s, q, xy)
            print("  ✅ 能规划")
        except Exception as e:  # noqa: BLE001
            print("  ❌", getattr(e, "message", None) or e)
        from collections import Counter
        for k, n in Counter(log).most_common(8):
            print(f"     {n:3d} x {k}")

if __name__ == "__main__":
    main()
