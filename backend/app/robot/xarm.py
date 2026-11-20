"""UFactory xArm 5 adapter, over the official xArm Python SDK (pip install xarm-python-sdk).

Same contract as the UR adapter: the planner and the motion guard decide every joint target with our own
kinematics, the arm receives plain joint vectors, and arrival is checked on the measured joints.

* movej  -> set_servo_angle (joint move, radians)
* movel  -> the straight line is cut into short steps solved with our IK and sent as joint moves.
            The controller's own linear move (set_position) is not used: on an xArm 5 it only accepts a tool
            pointing straight down (roll 180, pitch 0), and the gripper works with the flange level.
* wait   -> sleep
* STOP   -> set_state(4): the controller stops and drops queued commands.

The controller's errors are never cleared automatically: a collision or a fault must be looked at by a person
(UFactory Studio, or the "clear error" button the app shows), then the arm is re-enabled here.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Sequence

import numpy as np

from ..config import Settings
from ..skills.registry import MotionStep
from .base import (COMPLETED, FAILED, NOT_STARTED, STOPPED, UNKNOWN, RobotError, RobotStatus, StopAck, _Listeners,
                   result)
from .kinematics import IKError, Kinematics

STATE_MOVING, STATE_SLEEPING, STATE_PAUSED, STATE_STOPPED = 1, 2, 3, 4


def movel_steps(kin: Kinematics, qa: Sequence[float], qb: Sequence[float], step_m: float = 0.005) -> list[np.ndarray]:
    """Joint waypoints (ending with qb) along the straight flange line from FK(qa) to FK(qb), same IK branch."""
    a, b = np.asarray(qa, float), np.asarray(qb, float)
    Ta, Tb = kin.frames(a)[-1], kin.frames(b)[-1]
    dist = float(np.linalg.norm(Tb[:3, 3] - Ta[:3, 3]))
    n = max(1, int(math.ceil(dist / step_m)))
    out: list[np.ndarray] = []
    q = a
    flange = Kinematics(kin.model)   # waypoints are flange poses: no TCP
    for i in range(1, n):
        t = i / n
        T = Tb.copy()
        T[:3, 3] = Ta[:3, 3] + (Tb[:3, 3] - Ta[:3, 3]) * t   # orientation: the planner keeps it constant on a movel
        try:
            q = flange.ik(T, q, iters=120)
        except IKError:
            q = a + (b - a) * t                               # cannot happen on a guard-checked line; stay safe
        out.append(np.asarray(q, float))
    out.append(b)
    return out


class XArmAdapter:
    name = "real"

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.host = settings.robot_host
        if not self.host:
            raise RobotError("xArm IP not configured (robot_xarm5.yaml connections.real.host)")
        m = settings.robot["motion"]
        self.tol = float(m["joint_tolerance_rad"])
        self.n = 5
        self.kin = Kinematics("xArm5")
        self.xc = dict(settings.robot.get("xarm") or {})
        self.arm: Any = None
        self.listeners = _Listeners()
        self.progress_cb = None
        self._executing = False
        self._poll: threading.Thread | None = None
        self._alive = False

    # ------------------------------------------------------------ protocol ---
    def connect(self) -> None:
        try:
            from xarm.wrapper import XArmAPI
        except ImportError as e:
            raise RobotError("xArm SDK missing: .venv\\Scripts\\python.exe -m pip install xarm-python-sdk") from e
        if self.arm is not None and self.arm.connected:
            return
        try:
            self.arm = XArmAPI(self.host, is_radian=True)
            if not self.arm.connected:
                self.arm.connect()
        except Exception as e:  # noqa: BLE001
            self.arm = None
            raise RobotError(f"xArm {self.host} not reachable: {e}") from e
        if not self.arm.connected:
            self.arm = None
            raise RobotError(f"xArm {self.host} not reachable")
        # Connecting never enables the motors: read-only tools (beam_axis, record_pose) must not change the arm's
        # state. The first confirmed motion enables it (execute -> _arm_ready).
        self._alive = True
        self._poll = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll.start()

    def _arm_ready(self) -> None:
        """Enable the motors, position mode, ready state. Never clears a controller error."""
        g = self.s.robot.get("gripper") or {}
        if g.get("enabled") and g.get("mass_kg") is not None:
            try:   # payload in kg, centre of gravity in mm (flange frame)
                self.arm.set_tcp_load(float(g["mass_kg"]), [float(v) * 1000 for v in (g.get("cog_m") or [0, 0, 0])])
            except Exception:  # noqa: BLE001
                pass
        self.arm.motion_enable(enable=True)
        self.arm.set_mode(0)
        self.arm.set_state(0)
        time.sleep(0.1)

    def disconnect(self) -> None:
        self._alive = False
        if self.arm is not None:
            try:
                self.arm.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self.arm = None

    def _poll_loop(self) -> None:
        while self._alive:
            q = self.current_joints()
            if q:
                self.listeners.emit(q)
            time.sleep(0.05)

    def current_joints(self) -> list[float] | None:
        if self.arm is None or not self.arm.connected:
            return None
        try:
            return [float(v) for v in list(self.arm.angles)[: self.n]]
        except Exception:  # noqa: BLE001
            return None

    def status(self) -> RobotStatus:
        a = self.arm
        if a is None or not a.connected:
            return RobotStatus(connected=False, moving=False, detail=f"xArm {self.host} non connesso")
        err, warn, st = int(a.error_code or 0), int(a.warn_code or 0), int(a.state or 0)
        if err:
            safety, mode = "FAULT", "ERROR"
        else:
            safety = "NORMAL"
            mode = "RUNNING" if st in (STATE_MOVING, STATE_SLEEPING) or (st == STATE_STOPPED and not self._executing) \
                else "PAUSED" if st == STATE_PAUSED else "RUNNING"
        detail = f"xArm state {st}, mode {a.mode}, error {err}, warn {warn}"
        return RobotStatus(connected=True, moving=st == STATE_MOVING, robot_mode=mode, safety=safety,
                           program="PLAYING" if st == STATE_MOVING else "STOPPED", remote_control=True,
                           joints=self.current_joints(), detail=detail)

    def stop(self) -> StopAck:
        t0 = time.time()
        ok = False
        if self.arm is not None and self.arm.connected:
            try:
                ok = self.arm.set_state(4) == 0
            except Exception:  # noqa: BLE001
                ok = False
        t1 = time.time()
        halted = None
        end = time.time() + 2.0
        while time.time() < end and self.arm is not None:
            if int(self.arm.state or 0) != STATE_MOVING:
                halted = time.time()
                break
            time.sleep(0.01)
        return StopAck(requested_at=t0, acknowledged_at=t1, acknowledged=ok, motion_stopped_at=halted,
                       detail="xArm set_state(4)")

    # ------------------------------------------------------------ execute ---
    def execute(self, skill, params, motion: Sequence[MotionStep], cancel: threading.Event, timeout_s: float):
        t0 = time.time()
        total = sum(1 for m in motion if m.move != "wait")

        def state() -> dict[str, Any]:
            st = self.status()
            return {"joints": st.joints, "moving": st.moving, "safety": st.safety, "detail": st.detail}

        st = self.status()
        if not st.connected:
            return result(skill, params, t0, NOT_STARTED, state(), error="xArm non connesso", total=total)
        if st.safety == "FAULT":
            return result(skill, params, t0, NOT_STARTED, state(),
                          error=f"xArm in errore (codice {self.arm.error_code}): controllalo e azzera l'errore",
                          total=total)
        if cancel.is_set():
            return result(skill, params, t0, STOPPED, state(), error="fermato prima del movimento", total=total)
        try:
            if int(self.arm.state or 0) in (STATE_PAUSED, STATE_STOPPED) or int(self.arm.mode or 0) != 0:
                self._arm_ready()
        except Exception as e:  # noqa: BLE001
            return result(skill, params, t0, NOT_STARTED, state(), error=f"xArm non pronto: {e}", total=total)

        deadline = time.monotonic() + timeout_s
        done = 0
        q_prev = np.asarray(self.current_joints() or [0.0] * self.n, float)
        self._executing = True
        try:
            for step in motion:
                if step.move == "wait":
                    end = time.monotonic() + float(step.seconds or 0)
                    while time.monotonic() < end:
                        if cancel.is_set():
                            self.stop()
                            return result(skill, params, t0, STOPPED, state(), error="fermato", done=done, total=total)
                        time.sleep(0.02)
                    continue
                target = np.asarray(step.joints, float)
                if step.move == "movel":
                    speed = self._lin_to_joint_speed(q_prev, target, float(step.speed))
                    points = movel_steps(self.kin, q_prev, target, float(self.xc.get("movel_step_m", 0.005)))
                    blend = self.xc.get("movel_blend_radius")
                else:
                    speed, points, blend = float(step.speed), [target], None
                acc = float(step.accel or 0.3)
                for i, p in enumerate(points):
                    last = i == len(points) - 1
                    code = self.arm.set_servo_angle(angle=[float(v) for v in p], speed=speed, mvacc=acc, is_radian=True,
                                                    wait=False, radius=None if last else blend)
                    if code != 0:
                        self.stop()
                        return result(skill, params, t0, FAILED if done else NOT_STARTED, state(),
                                      error=f"xArm ha rifiutato il comando (codice {code})", done=done, total=total)
                    out = self._wait_arrival(p, cancel, deadline, final=last or blend is None)
                    if out is not None:
                        return result(skill, params, t0, out[0], state(), error=out[1], done=done, total=total)
                q_prev = target
                done += 1
                if self.progress_cb:
                    self.progress_cb(done, total, step.pose)
            return result(skill, params, t0, COMPLETED, state(), done=done, total=total)
        finally:
            self._executing = False

    def _lin_to_joint_speed(self, qa: np.ndarray, qb: np.ndarray, v_lin: float) -> float:
        """Joint speed (rad/s) that moves the flange at about v_lin (m/s) on this segment."""
        d = float(np.linalg.norm(self.kin.frames(qb)[-1][:3, 3] - self.kin.frames(qa)[-1][:3, 3]))
        dq = float(np.max(np.abs(qb - qa)))
        if d < 1e-6 or dq < 1e-6:
            return 0.2
        return max(0.02, min(1.0, dq * v_lin / d))

    def _wait_arrival(self, target: np.ndarray, cancel: threading.Event, deadline: float,
                      final: bool) -> tuple[str, str] | None:
        """None when the arm reached ``target`` (or, for a blended point, when it is close enough to go on)."""
        tol = self.tol if final else max(self.tol, 0.05)
        seen_motion = False
        t_sent = time.monotonic()
        while True:
            if cancel.is_set():
                self.stop()
                return STOPPED, "fermato"
            a = self.arm
            if a is None or not a.connected:
                return UNKNOWN, "connessione xArm persa durante il movimento"
            if int(a.error_code or 0):
                return FAILED, f"xArm in errore durante il movimento (codice {a.error_code})"
            q = self.current_joints()
            st = int(a.state or 0)
            seen_motion = seen_motion or st == STATE_MOVING
            if q is not None and float(np.max(np.abs(np.asarray(q) - target))) <= tol and (not final or st != STATE_MOVING):
                return None
            if st in (STATE_STOPPED, STATE_PAUSED) and time.monotonic() - t_sent > 0.5:
                return STOPPED, "xArm fermato (pulsante, pausa o arresto)"
            if final and seen_motion and st == STATE_SLEEPING and time.monotonic() - t_sent > 0.3:
                return FAILED, "xArm si è fermato lontano dal target"
            if time.monotonic() > deadline:
                self.stop()
                return UNKNOWN, "timeout del movimento"
            time.sleep(0.01)
