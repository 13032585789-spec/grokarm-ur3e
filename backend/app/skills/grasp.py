"""Pick a paper cup with the printed passive semicircle gripper (config/semicircle_gripper.step).

The ring hangs below the flange axis (robot.yaml: gripper). Sequence: travel above every cup, come down BEHIND the
target cup, slide the ring around its narrow base, lift straight up: the cup's taper wedges in the ring and is
carried. Every segment is checked by the motion guard (links, gripper capsules, table, self, cups as boxes); the
gate re-checks it again from the actual joints before sending, as for every other motion.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np

from ..robot.kinematics import IKError
from .cartesian import FUORI_LIMITI, Plan
from .motion_guard import GuardRejected, MotionGuard
from .registry import MotionStep, SkillError


def _cup_diameter(gp: dict[str, Any], z: float) -> float:
    h = float(gp.get("cup_height_m", 0.08))
    db, dt = float(gp.get("cup_bottom_diameter_m", 0.048)), float(gp.get("cup_top_diameter_m", 0.072))
    return db + (dt - db) * max(0.0, min(1.0, z / h))


def _flange_ik(guard: MotionGuard, R: np.ndarray, f: np.ndarray, qnear: Sequence[float],
               first: bool = False) -> np.ndarray | None:
    kin = guard.kin
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = f + R @ kin.tcp
    if first:   # all 8 analytic branches: keep the safe one closest to the start (elbow up, arm above the table)
        from ..robot.ur_ik import ik_all
        best = None
        for qs in ik_all(kin, M, qnear):
            qs = np.asarray(qs, dtype=float)
            if guard.config_ok(qs):
                d = float(np.max(np.abs(qs - np.asarray(qnear, float))))
                if best is None or d < best[0]:
                    best = (d, qs)
        return None if best is None else best[1]
    try:
        return kin.ik(M, qnear)
    except IKError:
        pass
    T0 = kin.fk(qnear)
    qc = np.asarray(qnear, dtype=float)
    try:   # far target: small pose steps keep the solver on its branch
        for k in range(1, 21):
            t = k / 20
            Mk = np.eye(4)
            w = _rotvec(M[:3, :3] @ T0[:3, :3].T)
            Mk[:3, :3] = _rot(w * t) @ T0[:3, :3]
            Mk[:3, 3] = T0[:3, 3] + (M[:3, 3] - T0[:3, 3]) * t
            qc = kin.ik(Mk, qc, iters=200)
        return qc
    except IKError:
        return None


def _rotvec(R: np.ndarray) -> np.ndarray:
    from ..robot.kinematics import rotvec
    return rotvec(R)


def _rot(w: np.ndarray) -> np.ndarray:
    th = float(np.linalg.norm(w))
    if th < 1e-12:
        return np.eye(3)
    k = w / th
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(th) * K + (1 - math.cos(th)) * K @ K


def _with_offset(gp: dict[str, Any], xy: tuple[float, float]) -> tuple[float, float]:
    """grasp.xy_offset_m: a measured pointing error of the camera position (robot base frame, metres)."""
    dx, dy = (list(gp.get("xy_offset_m") or [0.0, 0.0]) + [0.0, 0.0])[:2]
    return float(xy[0]) + float(dx), float(xy[1]) + float(dy)


def plan_grasp(guard: MotionGuard, settings: Any, q: Sequence[float], xy: tuple[float, float], *,
               height_m: float | None = None, others: Sequence[tuple[float, float]] = ()) -> Plan:
    r = settings.robot
    g, gp = dict(r.get("gripper") or {}), dict(r.get("grasp") or {})
    xy = _with_offset(gp, xy)
    rel = r.get("relative") or {}
    if not g.get("enabled"):
        raise SkillError(FUORI_LIMITI, "Nessuna pinza configurata (robot.yaml: gripper.enabled).")
    q = np.asarray(q, dtype=float)
    guard.learn_beam(q)
    e = guard.beam_axis
    if e is None:
        raise SkillError(FUORI_LIMITI, "anello_sconosciuto")
    reach = math.hypot(float(xy[0]), float(xy[1]))
    if not float(rel.get("reach_min_m", 0.12)) <= reach <= float(rel.get("reach_max_m", 0.5)):
        raise SkillError(FUORI_LIMITI, f"Il bicchiere è fuori portata ({reach * 1000:.0f} mm dalla base).")
    tz = guard.table_z
    H = float(gp.get("cup_height_m", 0.08) if height_m is None else height_m)
    hh = float(g.get("ring_height_m", 0.010)) / 2
    ri = float(g.get("ring_inner_radius_m", 0.0265))
    # Ring bottom 1 mm above the strictest table margin the guard will apply (capsules or meshes). Seating it
    # exactly on the margin made every seat pose fail by rounding (pinza_tavolo_mesh = -0.0).
    mesh_cfg = ((r.get("guard") or {}).get("mesh") or {})
    floor = float(g.get("table_clearance_m", 0.003))
    if guard.mesh is not None:
        floor = max(floor, float(mesh_cfg.get("table_margin_m", 0.003)))
    # The ring is seated as HIGH as the cup still fits (grasp.seat_bottom_max_m, ring bottom above the table), never
    # lower than 1 mm above the guard's table margin. A small error in the table height then costs a looser grip,
    # not a protective stop against the table.
    margin = float(gp.get("entry_margin_m", 0.0005))
    lo = floor + 0.001
    hi = max(lo, float(gp.get("seat_bottom_max_m", 0.012)))
    bottom = None
    for k in range(41):
        b = hi - (hi - lo) * k / 40
        if _cup_diameter(gp, b + 2 * hh) + 2 * margin <= 2 * ri:
            bottom = b
            break
    if bottom is None:
        d = _cup_diameter(gp, lo + 2 * hh)
        raise SkillError(FUORI_LIMITI, f"anello_troppo_stretto:{d * 1000:.0f}:{2 * ri * 1000:.0f}")
    zc = tz + bottom + hh
    # Seated, the flange axis is ring_offset above the ring: the wrist / flange plate pass right over the rim.
    roof = bottom + hh + float(g.get("ring_offset_m", 0.1115)) - float(gp.get("wrist_radius_m", 0.035)) - 0.005
    if H > roof:
        raise SkillError(FUORI_LIMITI, f"bicchiere_troppo_alto:{H * 1000:.0f}:{roof * 1000:.0f}")
    d_entry = _cup_diameter(gp, bottom + 2 * hh)
    # Start low (near the table, or a pose recorded touching it)? Go straight up first, nothing else moves.
    pre = _lift_first(guard, gp, q, tz + H + float(gp.get("above_clear_m", 0.03)))
    if pre is not None:
        q = pre
    base_yaw = math.atan2(float(xy[1]), float(xy[0]))
    reasons: list[str] = []
    saved = list(guard.obstacles)
    try:
        for dyaw in (0, 15, -15, 30, -30, 45, -45, 60, -60, 75, -75, 90, -90):
            yaw = base_yaw + math.radians(dyaw)
            got = _try_heading(guard, g, gp, q, xy, e, np.array([math.cos(yaw), math.sin(yaw), 0.0]), tz, H, zc,
                               others, saved, reasons)
            if got is not None:
                got.info["diametro_ingresso_mm"] = round(d_entry * 1000, 1)
                got.info["anello_fondo_mm"] = round(bottom * 1000, 1)
                if pre is not None:
                    got.timeout_s += 15
                    got.motion.insert(0, MotionStep("movel", None, tuple(round(float(x), 6) for x in pre), 0.03, 0.2))
                    got.info["prima_su"] = True
                return got
    finally:
        guard.obstacles = saved
    why = max(set(reasons), key=reasons.count) if reasons else "ik"
    raise SkillError(FUORI_LIMITI, f"Nessun percorso sicuro per prendere il bicchiere ({why}).")


def _lift_first(guard: MotionGuard, gp: dict[str, Any], q: np.ndarray, z_clear: float) -> np.ndarray | None:
    """Joints after a straight vertical lift that brings the lowest gripper point to z_clear, or None when the
    gripper is already that high (or the lift itself is not possible: then the normal plan decides)."""
    L = guard._links(q)
    names = [n for n in ("ring_l", "ring_r", "beam") if n in L] or ["tool"]
    low = min(min(float(L[n][0][2]), float(L[n][1][2])) - float(L[n][2]) for n in names)
    if low >= z_clear - 0.005:
        return None
    T = guard.kin.fk(q)
    R = np.array(T[:3, :3])
    f = T[:3, 3] - R @ guard.kin.tcp + np.array([0.0, 0.0, z_clear - low])
    q_up = _flange_ik(guard, R, f, q)
    if q_up is None or guard.check_movel(q, q_up) is not None:
        return None
    return np.asarray(q_up, float)


def _try_heading(guard, g, gp, q, xy, e, hz, tz, H, zc, others, saved, reasons) -> Plan | None:
    off, axial = float(g.get("ring_offset_m", 0.1115)), float(g.get("ring_axial_m", 0.012))
    ro = float(g.get("ring_outer_radius_m", 0.0335))
    down = np.array([0.0, 0.0, -1.0])
    f_z = np.array([0.0, 0.0, 1.0])
    R = np.column_stack((down, hz, np.cross(hz, down))) @ np.column_stack((e, f_z, np.cross(f_z, e))).T
    to_flange = lambda c: c - hz * axial - down * off  # noqa: E731
    cup = np.array([float(xy[0]), float(xy[1]), zc])
    rtop = float(gp.get("cup_top_diameter_m", 0.072)) / 2
    back = rtop + ro + float(gp.get("approach_gap_m", 0.015))
    ring_pre = cup - hz * back
    ring_high = ring_pre.copy()
    ring_high[2] = tz + H + float(gp.get("above_clear_m", 0.03)) + 0.01
    ring_lift = cup + np.array([0.0, 0.0, float(gp.get("lift_m", 0.08))])
    from ..robot.ur_ik import ik_all
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = to_flange(ring_high) + R @ guard.kin.tcp
    branches = sorted((np.asarray(b, float) for b in ik_all(guard.kin, M, q)),
                      key=lambda b: float(np.max(np.abs(b - q))))
    q_high = q_pre = q_seat = q_lift = None
    blame: list[str] = []
    worst = lambda x: min(guard.margins(x).items(), key=lambda kv: kv[1])[0]  # noqa: E731
    for qh in branches:   # keep the branch that is also safe down at the cup (wrist above, arm above the table)
        if not guard.config_ok(qh):
            blame.append(f"alto:{worst(qh)}")
            continue
        qp = _flange_ik(guard, R, to_flange(ring_pre), qh)
        qs = None if qp is None else _flange_ik(guard, R, to_flange(cup), qp)
        ql = None if qs is None else _flange_ik(guard, R, to_flange(ring_lift), qs)
        if ql is None:
            blame.append("ik_discesa")
            continue
        bad = [(n, x) for n, x in (("prima", qp), ("sul_bicchiere", qs), ("sollevato", ql)) if not guard.config_ok(x)]
        if bad:
            blame.append(f"{bad[0][0]}:{worst(bad[0][1])}")
            continue
        q_high, q_pre, q_seat, q_lift = qh, qp, qs, ql
        break
    if q_lift is None:
        real = [b for b in blame if not b.endswith("limite_giunto")] or blame   # joint-limit branches are just unusable IK solutions
        top = sorted(set(real), key=real.count, reverse=True)[:3]
        reasons.append("nessuna_postura_sicura:" + (",".join(f"{b}x{real.count(b)}" for b in top) if top else "ik_polso"))
        return None
    box = lambda x, y, name: {"name": name, "min": [x - rtop, y - rtop, tz - 0.01],  # noqa: E731
                              "max": [x + rtop, y + rtop, tz + H]}
    as_obs = lambda bs: [(b["name"], np.array(b["min"], float), np.array(b["max"], float)) for b in bs]  # noqa: E731
    target = [box(float(xy[0]), float(xy[1]), "bicchiere")]
    rest = [box(float(a), float(b), f"bicchiere{i}") for i, (a, b) in enumerate(others)]
    guard.obstacles = saved + as_obs(target + rest)
    vias: list[np.ndarray] = []
    why = guard.check_movel(q_high, q_pre)
    if why is None and guard.check_movej(q, q_high) is not None:
        try:   # blocked direct travel: safe via points (lazy PRM in the guard) around arm, table and every cup
            vias = [np.asarray(v, float) for v in guard.plan(q, q_high)][:-1]
        except GuardRejected as err:
            why = err.code
    if why is None:
        guard.obstacles = saved + as_obs(rest)
        why = guard.check_movel(q_pre, q_seat) or guard.check_movel(q_seat, q_lift)
    guard.obstacles = saved
    if why is not None:
        reasons.append(why)
        return None
    m = guard_speeds = dict(guard_speeds_of(guard))
    slide = float(gp.get("slide_speed", 0.02))
    up = float(gp.get("lift_speed", 0.03))
    rnd = lambda v: tuple(round(float(x), 6) for x in v)  # noqa: E731
    motion = [MotionStep("movej", None, rnd(v), m["joint_speed"], m["joint_accel"]) for v in vias]
    motion += [MotionStep("movej", None, rnd(q_high), m["joint_speed"], m["joint_accel"]),
              MotionStep("movel", None, rnd(q_pre), 0.05, 0.2),
              MotionStep("movel", None, rnd(q_seat), slide, 0.2),
              MotionStep("wait", seconds=0.3),
              MotionStep("movel", None, rnd(q_lift), up, 0.2)]
    travel = float(np.max(np.abs(q_high - q))) / max(m["joint_speed"], 1e-3)
    dur = travel + (ring_high[2] - zc) / 0.05 + back / slide + float(gp.get("lift_m", 0.08)) / up + 2
    plan = Plan(motion, timeout_s=dur * 2 + 15,
                info={"xy_mm": [round(float(xy[0]) * 1000, 1), round(float(xy[1]) * 1000, 1)],
                      "anello_mm": round((zc - tz) * 1000, 1),
                      "sollevamento_mm": round(float(gp.get("lift_m", 0.08)) * 1000, 1),
                      "direzione_deg": round(math.degrees(math.atan2(float(hz[1]), float(hz[0])))),
                      "asse_trave": [int(v) for v in e]})
    plan.place = {"q_lift": rnd(q_lift), "q_seat": rnd(q_seat), "q_pre": rnd(q_pre), "q_high": rnd(q_high)}  # type: ignore[attr-defined]
    return plan


def guard_speeds_of(guard: MotionGuard) -> dict[str, float]:
    return {"joint_speed": float(guard.v), "joint_accel": 0.3}


def plan_place(q: Sequence[float], held: dict[str, Any], settings: Any) -> Plan:
    if float(np.max(np.abs(np.asarray(q, float) - np.asarray(held["q_lift"], float)))) > 0.05:
        raise SkillError(FUORI_LIMITI, "Il braccio non è più dove ha sollevato il bicchiere: posalo a mano.")
    slow = float((settings.robot.get("grasp") or {}).get("slide_speed", 0.02))
    motion = [MotionStep("movel", None, tuple(held["q_seat"]), slow, 0.2),
              MotionStep("wait", seconds=0.3),
              MotionStep("movel", None, tuple(held["q_pre"]), slow, 0.2),
              MotionStep("movel", None, tuple(held["q_high"]), 0.05, 0.2)]
    return Plan(motion, timeout_s=90, info={})


def plan_hover(guard: MotionGuard, settings: Any, q: Sequence[float], xy: tuple[float, float], *,
               height_m: float | None = None) -> Plan:
    """'Point at the cup' with the gripper on: the ring held level straight above the cup, beam down (the same
    posture the grasp uses), a few cm over the rim. The tool-down pointing pose turned the beam sideways and its
    wrist turn from the gripper posture dipped the flange ('La traiettoria scenderebbe verso il tavolo')."""
    r = settings.robot
    g, gp = dict(r.get("gripper") or {}), dict(r.get("grasp") or {})
    xy = _with_offset(gp, xy)
    q = np.asarray(q, dtype=float)
    guard.learn_beam(q)
    e = guard.beam_axis
    if not g.get("enabled") or e is None:
        raise SkillError(FUORI_LIMITI, "anello_sconosciuto")
    H = float(gp.get("cup_height_m", 0.08) if height_m is None else height_m)
    off, axial = float(g.get("ring_offset_m", 0.1115)), float(g.get("ring_axial_m", 0.012))
    ring = np.array([float(xy[0]), float(xy[1]), guard.table_z + H + float(gp.get("above_clear_m", 0.03)) + 0.01])
    down, f_z = np.array([0.0, 0.0, -1.0]), np.array([0.0, 0.0, 1.0])
    from ..robot.ur_ik import ik_all
    base_yaw = math.atan2(float(xy[1]), float(xy[0]))
    reasons: list[str] = []
    m = guard_speeds_of(guard)
    for dyaw in (0, 15, -15, 30, -30, 45, -45, 60, -60, 90, -90, 120, -120, 180):
        yaw = base_yaw + math.radians(dyaw)
        hz = np.array([math.cos(yaw), math.sin(yaw), 0.0])
        R = np.column_stack((down, hz, np.cross(hz, down))) @ np.column_stack((e, f_z, np.cross(f_z, e))).T
        M = np.eye(4)
        M[:3, :3] = R
        M[:3, 3] = ring - hz * axial - down * off + R @ guard.kin.tcp
        for qh in sorted((np.asarray(b, float) for b in ik_all(guard.kin, M, q)),
                         key=lambda b: float(np.max(np.abs(b - q)))):
            if not guard.config_ok(qh):
                reasons.append("postura")
                continue
            vias: list[np.ndarray] = []
            if guard.check_movej(q, qh) is not None:
                try:
                    vias = [np.asarray(v, float) for v in guard.plan(q, qh)][:-1]
                except GuardRejected as err:
                    reasons.append(err.code)
                    continue
            rnd = lambda v: tuple(round(float(x), 6) for x in v)  # noqa: E731
            motion = [MotionStep("movej", None, rnd(v), m["joint_speed"], m["joint_accel"]) for v in vias + [qh]]
            travel = float(np.max(np.abs(qh - q))) / max(m["joint_speed"], 1e-3)
            return Plan(motion, timeout_s=travel * 3 + 20,
                        info={"xy_mm": [round(float(xy[0]) * 1000, 1), round(float(xy[1]) * 1000, 1)],
                              "anello_mm": round((ring[2] - guard.table_z) * 1000, 1), "percorso": "pinza"})
    why = max(set(reasons), key=reasons.count) if reasons else "ik"
    raise SkillError(FUORI_LIMITI, f"Nessun percorso sicuro sopra il bicchiere ({why}).")
