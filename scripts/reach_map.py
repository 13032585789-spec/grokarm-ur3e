"""Where on the table can the ring pick up a cup? Offline, moves NOTHING, needs no robot or camera.

For every cell of a grid over the table it asks: is there ANY ring heading and IK branch for which the arm is safe
(table, arm against itself, gripper against the arm) at the four poses of a grasp: high, behind the cup, around the
cup, lifted. That is the real blind zone of the arm + gripper + table, independent of where the arm starts. Cells that
fail say WHICH check refused (the name the guard uses: autocollisione_mesh, pinza_forearm, braccio_tavolo_mesh ...).

    .venv\\Scripts\\python.exe scripts\\reach_map.py                 grid 2 cm, table -0.30..0.30 m, cup 55 mm
    .venv\\Scripts\\python.exe scripts\\reach_map.py --step 0.01 --half 0.35
    .venv\\Scripts\\python.exe scripts\\reach_map.py --mode sim      sim settings instead of real

Output: data\\reach_map.png (green = can grasp, red = blind), data\\reach_map.csv (x, y, ok, best heading, reason).
Robot base is the black circle at (0, 0); +x is up in the picture, +y is left, like the robot frame.
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import load_settings  # noqa: E402
from app.robot.ur_ik import ik_all  # noqa: E402
from app.skills.motion_guard import guard_from_settings  # noqa: E402


def cell(guard, settings, xy, headings):
    """(ok, heading_deg, reason) for a cup standing at xy."""
    r = settings.robot
    g, gp = dict(r.get("gripper") or {}), dict(r.get("grasp") or {})
    off, axial = float(g.get("ring_offset_m", 0.1115)), float(g.get("ring_axial_m", 0.012))
    ro = float(g.get("ring_outer_radius_m", 0.0335))
    hh = float(g.get("ring_height_m", 0.010)) / 2
    H = float(gp.get("cup_height_m", 0.08))
    tz = guard.table_z
    bottom = float(gp.get("seat_bottom_max_m", 0.012))
    zc = tz + bottom + hh
    rtop = float(gp.get("cup_top_diameter_m", 0.072)) / 2
    back = rtop + ro + float(gp.get("approach_gap_m", 0.015))
    e = guard.beam_axis
    down, fz = np.array([0.0, 0.0, -1.0]), np.array([0.0, 0.0, 1.0])
    base_yaw = math.atan2(xy[1], xy[0])
    why: Counter = Counter()
    for dyaw in headings:
        hz = np.array([math.cos(base_yaw + math.radians(dyaw)), math.sin(base_yaw + math.radians(dyaw)), 0.0])
        R = np.column_stack((down, hz, np.cross(hz, down))) @ np.column_stack((e, fz, np.cross(fz, e))).T
        to_flange = lambda c, hz=hz: c - hz * axial - down * off  # noqa: E731
        cup = np.array([xy[0], xy[1], zc])
        pts = {"alto": cup - hz * back + np.array([0, 0, tz + H + float(gp.get("above_clear_m", 0.03)) + 0.01 - zc]),
               "prima": cup - hz * back, "sul_bicchiere": cup, "sollevato": cup + np.array([0, 0, float(gp.get("lift_m", 0.08))])}
        # IK branches of the first pose; the rest follow the same branch (a straight slide does not change it).
        M = np.eye(4)
        M[:3, :3] = R
        M[:3, 3] = to_flange(pts["alto"]) + R @ guard.kin.tcp
        branches = [np.asarray(b, float) for b in ik_all(guard.kin, M, np.zeros(6))]
        if not branches:
            why["fuori_portata_ik"] += 1
            continue
        for qh in branches:
            qs = {"alto": qh}
            bad = None
            for name in ("prima", "sul_bicchiere", "sollevato"):
                M2 = np.eye(4)
                M2[:3, :3] = R
                M2[:3, 3] = to_flange(pts[name]) + R @ guard.kin.tcp
                try:
                    qn = guard.kin.ik(M2, qs[list(qs)[-1]])
                except Exception:   # noqa: BLE001
                    bad = "ik_" + name
                    break
                qs[name] = np.asarray(qn, float)
            if bad:
                why[bad] += 1
                continue
            for name, qq in qs.items():
                m = {k: v for k, v in guard.margins(qq).items() if k != "limite_giunto"}
                k, v = min(m.items(), key=lambda kv: kv[1])
                if v < 0:
                    bad = f"{name}:{k}"
                    break
                if float(guard.margins(qq)["limite_giunto"]) < 0:
                    bad = f"{name}:limite_giunto"
                    break
            if bad is None:
                return True, dyaw, ""
            why[bad] += 1
    real = [(k, n) for k, n in why.items() if not k.endswith("limite_giunto")] or list(why.items())
    return False, None, max(real, key=lambda kn: kn[1])[0] if real else "?"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=float, default=0.02)
    ap.add_argument("--half", type=float, default=0.30, help="grid covers -half..+half in x and y (m)")
    ap.add_argument("--mode", default="real")
    ap.add_argument("--start", default=None,
                    help="named pose (home, attesa ...) or 6 joint angles 'q1,q2,..,q6' in rad: also PLAN the whole grasp "
                         "from there (slow, ~4 s per cell, use --step 0.05). Yellow = the pose is fine but no safe path.")
    a = ap.parse_args()
    s = load_settings(a.mode, env_file=ROOT / ".env")
    guard = guard_from_settings(s)
    gp = s.robot.get("gripper") or {}
    if guard.beam_axis is None and gp.get("offset_axis_flange"):
        guard.beam_axis = np.array(gp["offset_axis_flange"], float)
        if guard.mesh is not None:
            guard.mesh.set_beam_axis(guard.beam_axis)
    if guard.beam_axis is None:
        raise SystemExit("gripper.offset_axis_flange is null: run scripts/beam_axis.py first")
    reach_min = float((s.robot.get("relative") or {}).get("reach_min_m", 0.12))
    reach_max = float((s.robot.get("relative") or {}).get("reach_max_m", 0.5))
    q0 = None
    if a.start:
        if "," in a.start:
            q0 = np.array([float(v) for v in a.start.split(",")])
        else:
            q0 = np.array((s.poses or {})[a.start]["joints"], float)
        from app.skills.grasp import plan_grasp
    headings = (0, 15, -15, 30, -30, 45, -45, 60, -60, 75, -75, 90, -90, 120, -120, 150, -150, 180)
    xs = np.arange(-a.half, a.half + 1e-9, a.step)
    px = 600 / (2 * a.half)
    img = np.full((620, 620, 3), 255, np.uint8)
    rows, reasons = [], Counter()
    for x in xs:
        for y in xs:
            r = math.hypot(x, y)
            if not reach_min <= r <= reach_max:
                ok, hd, why = False, None, "fuori_portata"
            else:
                ok, hd, why = cell(guard, s, (float(x), float(y)), headings)
                if ok and q0 is not None:
                    try:
                        plan_grasp(guard_from_settings(s), s, q0, (float(x), float(y)))
                    except Exception as err:   # noqa: BLE001
                        ok, why = False, "percorso:" + str(err).split("(")[-1].rstrip(").")[:40]
            reasons[why or "ok"] += 1
            rows.append((round(float(x), 3), round(float(y), 3), int(ok), hd if hd is not None else "", why))
            col = (80, 190, 80) if ok else ((190, 190, 190) if why == "fuori_portata" else
                                            ((0, 200, 230) if why.startswith("percorso:") else (70, 70, 220)))
            cx, cy = int(310 - y * px), int(310 - x * px)
            cv2.rectangle(img, (cx - int(a.step * px / 2) + 1, cy - int(a.step * px / 2) + 1),
                          (cx + int(a.step * px / 2) - 1, cy + int(a.step * px / 2) - 1), col, -1)
    cv2.circle(img, (310, 310), 10, (0, 0, 0), -1)
    for rr in (reach_min, reach_max):
        cv2.circle(img, (310, 310), int(rr * px), (120, 120, 120), 1)
    cv2.putText(img, "up = +x, left = +y.  green = can grasp, yellow = no safe path from --start, red = blind, grey = out of reach", (6, 14), 0, 0.42, (0, 0, 0), 1)
    out = ROOT / "data"
    out.mkdir(exist_ok=True)
    cv2.imwrite(str(out / "reach_map.png"), img)
    with open(out / "reach_map.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["x_m", "y_m", "ok", "heading_deg", "reason"])
        w.writerows(rows)
    n_ok = sum(r[2] for r in rows)
    print(f"cells {len(rows)}  can grasp {n_ok} ({100 * n_ok / len(rows):.0f}%)")
    for k, n in reasons.most_common(8):
        print(f"  {n:5d}  {k or 'ok'}")
    print(f"picture: {out / 'reach_map.png'}\ntable:   {out / 'reach_map.csv'}")


if __name__ == "__main__":
    main()
