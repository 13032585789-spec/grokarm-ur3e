"""Dancer keypoints with Google MediaPipe Pose (more accurate on hand gestures than MoveNet). Run on a PC with internet:

    .venv\\Scripts\\python.exe -m pip install mediapipe
    .venv\\Scripts\\python.exe scripts\\dance\\extract_mediapipe.py data\\dance\\src.mp4 data\\dance\\kp_raw.json

Downloads the pose model once (≈30 MB) into scripts/dance/models/. Output has the same format as the MoveNet
extractor (17 COCO joints, x/y in pixels + confidence), so clean.py / retarget.py work unchanged.
"""
import json
import sys
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp

URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task"
MP_TO_COCO = [0, 2, 5, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]


def main() -> None:
    src, out = sys.argv[1], sys.argv[2]
    model = Path(__file__).with_name("models") / "pose_landmarker_heavy.task"
    if not model.exists():
        model.parent.mkdir(exist_ok=True)
        print("downloading the pose model ...")
        urllib.request.urlretrieve(URL, model)
    opts = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),
        running_mode=mp.tasks.vision.RunningMode.VIDEO, num_poses=1,
        min_pose_detection_confidence=0.3, min_tracking_confidence=0.3)
    cap = cv2.VideoCapture(src)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames, t = [], 0
    with mp.tasks.vision.PoseLandmarker.create_from_options(opts) as det:
        while True:
            ok, f = cap.read()
            if not ok:
                break
            h, w = f.shape[:2]
            img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(f, cv2.COLOR_BGR2RGB))
            r = det.detect_for_video(img, int(t * 1000 / fps))
            if r.pose_landmarks:
                L = r.pose_landmarks[0]
                frames.append([[L[i].x * w, L[i].y * h, float(L[i].visibility)] for i in MP_TO_COCO])
            else:
                frames.append([[0.0, 0.0, 0.0]] * 17)
            t += 1
            if t % 100 == 0:
                print(f"{t} frames")
    json.dump({"fps": fps, "w": w, "h": h, "frames": frames, "model": "mediapipe_pose_heavy"}, open(out, "w"))
    print(f"done: {t} frames -> {out}")


if __name__ == "__main__":
    main()
