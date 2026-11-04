"""Rehearsal camera: push a synthetic part image to VOCE (CAMERA_SOURCE=browser) twice a second.

    python scripts/fake_camera.py                 # clean part
    python scripts/fake_camera.py --scratch       # part with a scratch
    python scripts/fake_camera.py --url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import time

import cv2
import httpx
import numpy as np


def part_image(scratch: bool, t: float) -> np.ndarray:
    img = np.full((540, 960, 3), (58, 62, 66), np.uint8)
    cv2.rectangle(img, (0, 400), (960, 540), (40, 42, 45), -1)
    cx = 480 + int(4 * np.sin(t))
    cv2.circle(img, (cx, 270), 150, (175, 180, 186), -1)
    cv2.circle(img, (cx, 270), 150, (120, 125, 130), 4)
    cv2.circle(img, (cx, 270), 40, (70, 74, 78), -1)
    if scratch:
        cv2.line(img, (cx + 30, 170), (cx + 110, 250), (60, 60, 70), 3)
        cv2.line(img, (cx + 40, 168), (cx + 118, 244), (215, 215, 220), 1)
    cv2.putText(img, "rehearsal camera", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)
    return img


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--scratch", action="store_true")
    ap.add_argument("--fps", type=float, default=2.0)
    a = ap.parse_args()
    with httpx.Client(timeout=3) as c:
        while True:
            ok, buf = cv2.imencode(".jpg", part_image(a.scratch, time.time()))
            try:
                c.post(f"{a.url}/api/camera/frame", content=buf.tobytes(), headers={"Content-Type": "image/jpeg"})
            except httpx.HTTPError as e:
                print("push failed:", e)
            time.sleep(1 / a.fps)


if __name__ == "__main__":
    main()
