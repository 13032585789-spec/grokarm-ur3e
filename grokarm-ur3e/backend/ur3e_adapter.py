"""URSim and real UR3e through ur_rtde.

Check every behaviour here on URSim first. stopJ is a software stop, not a
safety function: the physical e-stop and staff supervision stay in charge.
"""
from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .robot_adapter import ExecutionResult, RobotAdapter, RobotStatus, SkillRefused
from .skill_registry import Limits, PoseBook

POLL_S = 0.008
MOVING_RAD_S = 0.01


def _distance(a: list[float], b: list[float]) -> float:
    return max(abs(x - y) for x, y in zip(a, b))


class UR3eAdapter(RobotAdapter):
    def __init__(self, host: str, poses: PoseBook, limits: Limits, rtde_control=None, rtde_receive=None):
        self.host = host
        self.poses = poses
        self.limits = limits
        self._control_mod = rtde_control
        self._receive_mod = rtde_receive
        self._c = None
        self._r = None
        self._lock = threading.Lock()  # one caller at a time on the control interface
        self._stop = threading.Event()
        self._moving = False
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ur-motion")
        self._task: asyncio.Task | None = None

    async def connect(self) -> None:
        await asyncio.to_thread(self._connect)

    def _connect(self) -> None:
        if self._control_mod is None:
            import rtde_control  # type: ignore
            import rtde_receive  # type: ignore

            self._control_mod, self._receive_mod = rtde_control, rtde_receive
        self._r = self._receive_mod.RTDEReceiveInterface(self.host)
        self._c = self._control_mod.RTDEControlInterface(self.host)

    async def close(self) -> None:
        await self.stop()
        if self._c is not None:
            await asyncio.to_thread(self._c.stopScript)
        self._pool.shutdown(wait=False)

    def status(self) -> RobotStatus:
        if self._r is None or self._c is None:
            return RobotStatus(detail="not connected")
        try:
            connected = bool(self._r.isConnected() and self._c.isConnected())
            protective = bool(self._r.isProtectiveStopped())
            emergency = bool(self._r.isEmergencyStopped())
            program = bool(self._c.isProgramRunning())
        except Exception as exc:  # the library raises on a lost connection
            return RobotStatus(detail=f"status failed: {exc}")
        ready = connected and program and not protective and not emergency and not self._moving
        return RobotStatus(connected, ready, self._moving, protective, emergency, self.poses.target)

    async def start_skill(self, skill_id: str) -> None:
        waypoints = self.poses.waypoints.get(skill_id)
        if not waypoints:
            raise SkillRefused(f"no approved waypoints for {skill_id}")
        status = await asyncio.to_thread(self.status)
        if not status.ready:
            raise SkillRefused(f"robot not ready: {status}")
        current = await asyncio.to_thread(self._r.getActualQ)
        tolerance = self.limits.start_pose_tolerance_rad
        if not any(_distance(current, q) <= tolerance for q in self.poses.known_poses.values()):
            raise SkillRefused("arm is not at a known pose")
        self._stop.clear()
        self._moving = True
        loop = asyncio.get_running_loop()
        self._task = asyncio.ensure_future(loop.run_in_executor(self._pool, self._run, waypoints))

    def _run(self, waypoints: list[list[float]]) -> ExecutionResult:
        started = None
        deadline = time.monotonic() + self.limits.skill_timeout_s
        try:
            for target in waypoints:
                if self._stop.is_set():
                    break
                with self._lock:
                    if self._stop.is_set():
                        break
                    accepted = self._c.moveJ(target, self.limits.speed_rad_s, self.limits.accel_rad_s2, True)
                if accepted is False:
                    return ExecutionResult("failed", "controller rejected the move", started)
                while True:
                    if self._r.isProtectiveStopped() or self._r.isEmergencyStopped():
                        return ExecutionResult("failed", "protective or emergency stop", started, time.time())
                    if not self._r.isConnected():
                        return ExecutionResult("failed", "connection lost", started)
                    speed = max(abs(v) for v in self._r.getActualQd())
                    if started is None and speed > MOVING_RAD_S:
                        started = time.time()
                    if self._stop.is_set():
                        return self._wait_until_still(started)
                    if _distance(self._r.getActualQ(), target) <= self.limits.joint_tolerance_rad and speed < MOVING_RAD_S:
                        break
                    if time.monotonic() > deadline:
                        self._send_stop()
                        self._wait_until_still(started)
                        return ExecutionResult("failed", "skill timed out", started, time.time())
                    time.sleep(POLL_S)
            if self._stop.is_set():
                return self._wait_until_still(started)
            return ExecutionResult("completed", "", started, time.time())
        except Exception as exc:
            return ExecutionResult("failed", f"robot error: {exc}", started)
        finally:
            self._moving = False

    def _wait_until_still(self, started: float | None) -> ExecutionResult:
        end = time.monotonic() + 3.0
        while time.monotonic() < end:
            if max(abs(v) for v in self._r.getActualQd()) < MOVING_RAD_S:
                return ExecutionResult("stopped", "stop issued, speed near zero", started, time.time())
            time.sleep(POLL_S)
        return ExecutionResult("failed", "arm did not settle after stop", started, time.time())

    def _send_stop(self) -> None:
        if self._c is not None:
            with self._lock:
                self._c.stopJ(self.limits.stop_decel_rad_s2)

    async def wait_done(self) -> ExecutionResult:
        if self._task is None:
            return ExecutionResult("failed", "no motion was started")
        return await self._task

    async def stop(self) -> None:
        self._stop.set()
        if self._moving:
            await asyncio.to_thread(self._send_stop)

