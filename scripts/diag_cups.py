"""Why is a cup not found? Grabs ONE camera frame, runs the detector, saves an annotated picture. Moves nothing.

    .venv\\Scripts\\python.exe scripts\\diag_cups.py            (colour red by default)
    .venv\\Scripts\\python.exe scripts\\diag_cups.py blue

Needs the stereo service running (run_stereo.bat). Output: data\\diag_cups.jpg  (open it and look).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import load_settings  # noqa: E402
from app.vision.camera import CameraHub  # noqa: E402
from app.vision.plane import Plane, colour_mask, eye, footprint  # noqa: E402


def main() -> None:
    colour = sys.argv[1] if len(sys.argv) > 1 else "red"
    s = load_settings("real", env_file=ROOT / ".env")
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
        raise SystemExit("❌ 没有收到相机画面：run_stereo.bat 在运行吗？.env 里 CAMERA_SOURCE/CAMERA_URL 对吗？")
    view = eye(frame.image).copy()
    h, w = view.shape[:2]
    print(f"画面 {w}x{h}")
    plane = Plane.load(s.data_dir / "plane.json") if (s.data_dir / "plane.json").exists() else None
    if plane is None:
        print("⚠ 没有 data/plane.json（桌面标定）")
    else:
        print(f"标定分辨率 {tuple(plane.frame_size)}  相机动过: {plane.camera_moved(view)}")
        for (x, y) in plane._saved_tapes().values():
            cv2.circle(view, (int(x), int(y)), 18, (0, 255, 255), 3)
    m = colour_mask(view, colour)
    n = int(m.sum() // 255) if m is not None else 0
    print(f"{colour} 颜色像素: {n}  ({100.0 * n / (w * h):.2f}% 画面)")
    if m is not None:
        view[m > 0] = (0.5 * view[m > 0] + 0.5 * np.array([255, 0, 255])).astype(np.uint8)
    keep = plane._keep(view) if plane else None
    print(f"整个画面里 {colour} 底部: {footprint(eye(frame.image), colour)}")
    print(f"桌面内 {colour} 底部: {footprint(eye(frame.image), colour, keep) if keep else '（无标定）'}")
    if plane:
        found = plane.scan(frame.image)
        print(f"桌面内找到 {len(found)} 个杯子:")
        for c, (bx, by), bb, af in found:
            print(f"  {c:7s} 底部像素 ({bx:.0f},{by:.0f})  面积 {100 * af:.2f}%")
            x, y, bw, bh = bb
            cv2.rectangle(view, (x, y), (x + bw, y + bh), (0, 255, 0), 3)
            cv2.putText(view, c, (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 3)
        print("  结果:", plane.locate(frame.image, colour).get("messaggio") or "找到了")
    out = s.data_dir / "diag_cups.jpg"
    cv2.imwrite(str(out), view)
    print("图片已保存:", out, "(洋红=颜色掩码, 黄圈=已标定的胶带, 绿框=找到的杯子)")


if __name__ == "__main__":
    main()
