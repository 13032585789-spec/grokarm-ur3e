"""Is the four-tape table plane turned the right way? Moves NOTHING.

Reads the robot's joints, works out where the flange and the gripper ring really are (robot base XY), and draws
that point on one camera frame once for every way the four taped corners could be named:
  R0 = plane.json as saved (green), R90 / R180 / R270 = the names turned one corner further (other colours).
The right one lands ON the gripper in the picture. Then write it:

    .venv\\Scripts\\python.exe scripts\\check_plane.py              look: data\\check_plane.jpg
    .venv\\Scripts\\python.exe scripts\\check_plane.py --write 180  turn plane.json by 180 (backup plane.json.bak)
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.config import load_settings  # noqa: E402
from app.vision.plane import eye  # noqa: E402

RING = ("后右", "后左", "前左", "前右")   # the four taught corners, going round the table
COL = {0: (0, 220, 0), 90: (255, 120, 0), 180: (0, 0, 255), 270: (255, 0, 255)}


def turned(pairs: dict, deg: int) -> dict:
    """Same tape pixels, robot XY handed to the tape `deg` further round."""
    k = deg // 90
    names = [n for n in RING if n in pairs]
    out = {}
    for i, n in enumerate(names):
        out[n] = {"px": pairs[n]["px"], "xy_m": pairs[names[(i + k) % len(names)]]["xy_m"]}
    return out


def to_px(pairs: dict, xy) -> tuple[float, float]:
    src = np.float32([pairs[n]["xy_m"] for n in RING])
    dst = np.float32([pairs[n]["px"] for n in RING])
    H = cv2.getPerspectiveTransform(src, dst)
    p = cv2.perspectiveTransform(np.float32([[xy]]), H)[0, 0]
    return float(p[0]), float(p[1])


def main() -> None:
    path = ROOT / "data" / "plane.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    if "--write" in sys.argv:
        deg = int(sys.argv[sys.argv.index("--write") + 1]) % 360
        if deg == 0:
            print("0 = 不改。")
            return
        shutil.copy(path, path.with_suffix(".json.bak"))
        body["pairs"] = turned(body["pairs"], deg)
        body["note"] = body.get("note", "") + f" Turned {deg} deg by scripts/check_plane.py."
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ plane.json 已旋转 {deg}°（旧的在 plane.json.bak）。重启服务生效。")
        return

    s = load_settings("real", env_file=ROOT / ".env")
    from beam_axis import read_q
    from app.robot.kinematics import Kinematics
    q = read_q(s.robot_host, int(s.robot["connections"]["ports"]["rtde"]))
    T = Kinematics("UR3e", (0.0, 0.0, 0.0)).fk(q)
    flange = T[:3, 3]
    g = s.robot.get("gripper") or {}
    pts = {"flange": flange[:2]}
    e = g.get("offset_axis_flange")
    if e:
        R = T[:3, :3]
        ring = flange + R[:, 2] * float(g.get("ring_axial_m", 0.012)) + R @ np.array(e, float) * float(g.get("ring_offset_m", 0.1115))
        pts["ring"] = ring[:2]
    print("关节角:", " ".join(f"{v:.3f}" for v in q))
    for k, v in pts.items():
        print(f"{k}: x={v[0] * 1000:.0f} mm  y={v[1] * 1000:.0f} mm")

    from app.vision.camera import CameraHub
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
        raise SystemExit("❌ 没有相机画面")
    view = eye(frame.image).copy()
    for deg in (0, 90, 180, 270):
        pairs = turned(body["pairs"], deg)
        for k, v in pts.items():
            x, y = to_px(pairs, tuple(v))
            r = 22 if k == "ring" else 14
            cv2.circle(view, (int(x), int(y)), r, COL[deg], -1 if k == "ring" else 4)
            cv2.putText(view, f"R{deg}{'' if k == 'ring' else ' flange'}", (int(x) + 26, int(y) + 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.1, COL[deg], 3)
            print(f"R{deg:<3} {k:6s} -> 画面像素 ({x:.0f}, {y:.0f})")
    out = ROOT / "data" / "check_plane.jpg"
    cv2.imwrite(str(out), view)
    print(f"\n图片: {out}\n实心圆 = 夹爪的环，空心圆 = 法兰。哪种颜色落在真实夹爪上，就是对的：")
    print("  R0 绿 = 现在的 plane.json；R90 蓝；R180 红；R270 紫。")
    print("  不是 R0 的话运行: .venv\\Scripts\\python.exe scripts\\check_plane.py --write <90|180|270>")


if __name__ == "__main__":
    main()
