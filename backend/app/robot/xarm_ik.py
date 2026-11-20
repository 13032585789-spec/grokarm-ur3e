"""Inverse kinematics of a 5-joint xArm 5.

The arm is planar after the base joint: joints 2, 3 and 4 are parallel horizontal axes and no link has a lateral
offset, so the flange origin and the tool axis always lie in the vertical plane through the base axis. Joint 5 only
spins the tool about its own axis. Consequences the planner has to live with:

* a target tool axis that is not in that vertical plane is unreachable (``ik_all`` returns nothing),
* the sideways heading of a horizontal tool is fixed by where the target is (radial, toward or away from the base).

Up to 4 branches: base facing the target or turned 180 deg (arm reaching backwards over its shoulder) x elbow up/down.
Every candidate is checked on the forward kinematics, so a wrong branch is dropped, never returned.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from .kinematics import Kinematics, rotvec

TWO_PI = 2 * math.pi


def _wrap(a: float) -> float:
    return (a + math.pi) % TWO_PI - math.pi


def _ang(v) -> float:
    return math.atan2(float(v[1]), float(v[0]))


def _plane(kin: Kinematics, q: Sequence[float]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    """Joint 2, 3, 4 positions and flange position in the arm plane (u, w) at q1 = 0, plus the tool-axis angle."""
    F = kin.frames([0.0, *q[1:4], 0.0])
    pl = lambda T: np.array([T[0, 3], T[2, 3]])  # noqa: E731
    z = F[5][:3, 2]
    return pl(F[1]), pl(F[2]), pl(F[3]), pl(F[5]), math.atan2(float(z[2]), float(z[0]))


def _calib(kin: Kinematics) -> dict:
    c = getattr(kin, "_xarm_plane", None)
    if c is not None:
        return c
    def angles(q):
        j2, j3, j4, fl, tau = _plane(kin, q)
        return _ang(j3 - j2), _ang(j4 - j3), tau, fl - j4
    a0 = angles([0, 0, 0, 0, 0])
    e = 1e-3
    s = []
    for i in (1, 2, 3):
        dq = [0.0] * 5
        dq[i] = e
        ai = angles(dq)
        s.append([round(_wrap(ai[k] - a0[k]) / e) for k in range(3)])
    v = a0[3]
    c = {"j2": _plane(kin, [0] * 5)[0], "a0": a0[:3], "s": s, "L": float(np.linalg.norm(v)),
         "delta": _wrap(_ang(v) - a0[2]), "a2": float(np.linalg.norm(_plane(kin, [0] * 5)[1] - _plane(kin, [0] * 5)[0])),
         "a3": float(np.linalg.norm(_plane(kin, [0] * 5)[2] - _plane(kin, [0] * 5)[1]))}
    kin._xarm_plane = c  # type: ignore[attr-defined]
    return c


def ik_all(kin: Kinematics, target_tip: np.ndarray, q_ref: Sequence[float] | None = None,
           tol: float = 1e-4) -> list[np.ndarray]:
    q_ref = np.zeros(5) if q_ref is None else np.asarray(q_ref, dtype=float)
    tcp = np.eye(4)
    tcp[:3, 3] = kin.tcp
    T = target_tip @ np.linalg.inv(tcp)           # flange pose
    R, p = T[:3, :3], T[:3, 3]
    zt = R[:, 2]
    r = math.hypot(float(p[0]), float(p[1]))
    phi = math.atan2(float(p[1]), float(p[0])) if r > 1e-6 else math.atan2(float(zt[1]), float(zt[0]))
    if abs(float(zt[0]) * math.sin(phi) - float(zt[1]) * math.cos(phi)) > 0.02:   # tool axis leaves the arm plane
        return []
    c = _calib(kin)
    (s2, _, _), (_, s3, _), (_, _, s4) = c["s"][0], c["s"][1], c["s"][2]
    a20, a30, t0 = c["a0"]
    out: list[np.ndarray] = []
    for q1 in (phi, _wrap(phi + math.pi)):
        ex, ey = math.cos(q1), math.sin(q1)
        goal = np.array([float(p[0]) * ex + float(p[1]) * ey, float(p[2])])
        tau = math.atan2(float(zt[2]), float(zt[0]) * ex + float(zt[1]) * ey)
        j4 = goal - c["L"] * np.array([math.cos(tau + c["delta"]), math.sin(tau + c["delta"])])
        d = j4 - c["j2"]
        D = float(np.linalg.norm(d))
        a2, a3 = c["a2"], c["a3"]
        cb = (D * D - a2 * a2 - a3 * a3) / (2 * a2 * a3)
        if abs(cb) > 1.0 + 1e-9:
            continue
        for elbow in (1.0, -1.0):
            b = elbow * math.acos(max(-1.0, min(1.0, cb)))
            al2 = _ang(d) - math.atan2(a3 * math.sin(b), a2 + a3 * math.cos(b))
            al3 = al2 + b
            q2 = _wrap((al2 - a20) * s2)
            q3 = _wrap((al3 - a30 - s3 * 0 - (al2 - a20)) * s3)
            q4 = _wrap((tau - t0 - (al3 - a30)) * s4)
            F0 = kin.frames([q1, q2, q3, q4, 0.0])[-1][:3, :3]
            rel = F0.T @ R
            q5 = math.atan2(float(rel[1, 0]), float(rel[0, 0]))
            cand = np.array([q1, q2, q3, q4, q5])
            Tc = kin.frames(cand)[-1]
            err = float(np.linalg.norm(Tc[:3, 3] - p)) + 0.05 * float(np.linalg.norm(rotvec(R @ Tc[:3, :3].T)))
            if err > tol:
                continue
            cand = _near(cand, q_ref)
            if not any(float(np.max(np.abs(cand - o))) < 1e-3 for o in out):
                out.append(cand)
    return out


def _near(q: np.ndarray, ref: np.ndarray) -> np.ndarray:
    out = q.copy()
    for i in range(len(q)):
        best = min((q[i] + k * TWO_PI for k in (-1, 0, 1)), key=lambda v: abs(v - ref[i]))
        out[i] = best
    return out

