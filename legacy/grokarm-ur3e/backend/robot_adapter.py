"""Contract shared by the mock arm, URSim and the real UR3e."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass


class SkillRefused(Exception):
    """The adapter refused to start. The arm has not moved."""


@dataclass
class RobotStatus:
    connected: bool = False
    ready: bool = False
    moving: bool = False
    protective_stop: bool = False
    emergency_stop: bool = False
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExecutionResult:
    outcome: str  # completed | stopped | failed
    detail: str = ""
    motion_start_ts: float | None = None
    motion_stopped_ts: float | None = None


class RobotAdapter(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    def status(self) -> RobotStatus: ...

    @abstractmethod
    async def start_skill(self, skill_id: str) -> None:
        """Issue the motion and return without waiting for it to finish."""

    @abstractmethod
    async def wait_done(self) -> ExecutionResult:
        """Wait for the motion to end. The result must come from robot state."""

    @abstractmethod
    async def stop(self) -> None:
        """Issue a controlled stop. Safe to call at any time, more than once."""
