"""Simulated arm for work outside hardware slots."""
from __future__ import annotations

import asyncio
import time

from .robot_adapter import ExecutionResult, RobotAdapter, RobotStatus, SkillRefused
from .skill_registry import SkillRegistry


class MockUR3eAdapter(RobotAdapter):
    def __init__(self, registry: SkillRegistry, time_scale: float = 1.0, decel_s: float = 0.15):
        self.registry = registry
        self.time_scale = time_scale
        self.decel_s = decel_s
        self.connected = False
        self.protective_stop = False
        self.fail_next: str | None = None  # test hook: "protective_stop" or "disconnect"
        self.started: list[str] = []
        self._moving = False
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        await self.stop()
        self.connected = False

    def status(self) -> RobotStatus:
        return RobotStatus(
            connected=self.connected,
            ready=self.connected and not self.protective_stop and not self._moving,
            moving=self._moving,
            protective_stop=self.protective_stop,
            detail="mock",
        )

    async def start_skill(self, skill_id: str) -> None:
        skill = self.registry.get(skill_id)
        if skill is None:
            raise SkillRefused(f"unknown skill {skill_id}")
        if not self.status().ready:
            raise SkillRefused("robot not ready")
        self.started.append(skill_id)
        self._stop.clear()
        self._moving = True
        self._task = asyncio.create_task(self._move(skill.mock_duration_s * self.time_scale))

    async def _move(self, duration: float) -> ExecutionResult:
        start = time.time()
        fault = self.fail_next
        self.fail_next = None
        limit = duration / 2 if fault else duration
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=limit)
            await asyncio.sleep(self.decel_s * self.time_scale)
            return ExecutionResult("stopped", "stop issued", start, time.time())
        except asyncio.TimeoutError:
            pass
        finally:
            self._moving = False
        if fault == "protective_stop":
            self.protective_stop = True
            return ExecutionResult("failed", "protective stop", start, time.time())
        if fault == "disconnect":
            self.connected = False
            return ExecutionResult("failed", "connection lost", start, time.time())
        return ExecutionResult("completed", "", start, time.time())

    async def wait_done(self) -> ExecutionResult:
        if self._task is None:
            return ExecutionResult("failed", "no motion was started")
        return await self._task

    async def stop(self) -> None:
        self._stop.set()
