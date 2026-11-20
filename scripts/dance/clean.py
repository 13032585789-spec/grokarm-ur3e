"""Clean raw keypoints: drop low-confidence and jumping points, fill gaps by interpolation, smooth.

    python scripts/dance/clean.py kp_raw.json kp_clean.json
"""
import json
import sys

import numpy as np
from scipy.signal import savgol_filter

JOINTS = {"nose": 0, "lsh": 5, "rsh": 6, "lelb": 7, "relb": 8, "lwri": 9, "rwri": 10, "lhip": 11, "rhip": 12}


def main() -> None:
    d = json.load(open(sys.argv[1]))
    K = np.array(d["frames"], float)
    T = len(K)
    sw = float(np.median(np.linalg.norm(K[:, 5, :2] - K[:, 6, :2], axis=1)))
    idx = np.arange(T)
    out = {}
    for name, i in JOINTS.items():
        P, s = K[:, i, :2].copy(), K[:, i, 2]
        good = s >= 0.3
        med = np.array([np.median(P[max(0, t - 3):t + 4][good[max(0, t - 3):t + 4]], axis=0)
                        if good[max(0, t - 3):t + 4].any() else P[t] for t in range(T)])
        good &= np.linalg.norm(P - med, axis=1) < 0.7 * sw
        if good.sum() < 2:
            good[:] = True
        for k in range(2):
            P[:, k] = np.interp(idx, idx[good], P[good, k])
        out[name] = savgol_filter(P, 9, 2, axis=0).tolist()
        print(f"{name:5s} kept {100 * good.mean():3.0f}%")
    json.dump({"fps": d["fps"], "w": d["w"], "h": d["h"], "kp": out}, open(sys.argv[2], "w"))


if __name__ == "__main__":
    main()
