"""Side-by-side preview: dancer video (left) and the xArm 5 stick model playing the trajectory (right), with audio.

    python scripts/dance/preview.py src.mp4 kp_clean.json traj.json preview.mp4
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.robot.kinematics import Kinematics  # noqa: E402

W, H = 540, 916


def camera(eye, target, f=900.0):
    eye, target = np.asarray(eye, float), np.asarray(target, float)
    z = target - eye
    z /= np.linalg.norm(z)
    x = np.cross(z, [0, 0, 1.0])
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    R = np.stack([x, y, z])

    def proj(p):
        c = R @ (np.asarray(p, float) - eye)
        return int(W / 2 + f * c[0] / c[2]), int(H * 0.62 + f * c[1] / c[2])
    return proj


def draw_robot(img, kin, q, proj, trail):
    F = kin.frames(q)
    P = [F[i][:3, 3] for i in range(len(F))]
    tip = F[-1][:3, 3] + F[-1][:3, 2] * 0.06
    # table grid
    for k in np.linspace(-0.4, 0.6, 6):
        cv2.line(img, proj([k, -0.5, 0]), proj([k, 0.5, 0]), (70, 70, 70), 1)
    for k in np.linspace(-0.5, 0.5, 6):
        cv2.line(img, proj([-0.4, k, 0]), proj([0.6, k, 0]), (70, 70, 70), 1)
    cv2.circle(img, proj([0, 0, 0]), 26, (120, 120, 120), -1)
    for i in range(len(trail) - 1):
        a = int(255 * (i + 1) / len(trail))
        cv2.line(img, proj(trail[i]), proj(trail[i + 1]), (a // 3, a // 2, a), 2)
    chain = [np.zeros(3), P[1], P[2], P[3], P[4], P[5], tip]
    widths = [16, 12, 11, 9, 8, 6]
    for (a, b), w in zip(zip(chain[:-1], chain[1:]), widths):
        cv2.line(img, proj(a), proj(b), (235, 235, 235), w, cv2.LINE_AA)
    for p in chain[1:-1]:
        cv2.circle(img, proj(p), 7, (90, 160, 255), -1, cv2.LINE_AA)
    xr = F[-1][:3, 3] + F[-1][:3, 0] * 0.05                      # roll marker
    cv2.line(img, proj(F[-1][:3, 3]), proj(xr), (80, 200, 120), 4, cv2.LINE_AA)
    cv2.circle(img, proj(tip), 9, (60, 90, 255), -1, cv2.LINE_AA)


def main() -> None:
    src, kpf, trf, out = sys.argv[1:5]
    kp = json.load(open(kpf))["kp"]
    tr = json.load(open(trf))
    Q = np.array(tr["q"])
    rate = tr["rate"]
    kin = Kinematics("xArm5")
    proj = camera([1.05, -1.05, 0.72], [0.18, 0.0, 0.26])
    cap = cv2.VideoCapture(src)
    fps = cap.get(5)
    tmp = str(Path(out).with_suffix(".noaudio.mp4"))
    vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W * 2, H))
    E = [("lsh", "rsh"), ("lsh", "lelb"), ("lelb", "lwri"), ("rsh", "relb"), ("relb", "rwri")]
    K = {k: np.asarray(v) for k, v in kp.items()}
    trail: list = []
    t = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        left = cv2.resize(f, (W, int(f.shape[0] * W / f.shape[1])))[:H]
        left = cv2.copyMakeBorder(left, 0, H - left.shape[0], 0, 0, cv2.BORDER_CONSTANT)
        sx = W / f.shape[1]
        for a, b in E:
            if t < len(K[a]):
                cv2.line(left, tuple((K[a][t] * sx).astype(int)), tuple((K[b][t] * sx).astype(int)), (0, 255, 0), 3)
        i = min(int(t / fps * rate), len(Q) - 1)
        F = kin.frames(Q[i])
        trail = (trail + [F[-1][:3, 3] + F[-1][:3, 2] * 0.06])[-20:]
        right = np.full((H, W, 3), 28, np.uint8)
        draw_robot(right, kin, Q[i], proj, trail)
        cv2.putText(right, f"xArm 5  t={t / fps:5.1f}s", (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (220, 220, 220), 2)
        vw.write(np.hstack([left, right]))
        t += 1
    vw.release()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmp, "-i", src, "-map", "0:v", "-map", "1:a?", "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", out], check=True)
    Path(tmp).unlink()
    print("wrote", out)


if __name__ == "__main__":
    main()
