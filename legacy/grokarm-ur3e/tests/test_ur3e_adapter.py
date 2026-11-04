"""Adapter logic against a fake controller. This does not prove URSim or arm behaviour."""
import asyncio
from pathlib import Path

import pytest

from backend.robot_adapter import SkillRefused
from backend.skill_registry import ConfigError, PoseBook
from backend.ur3e_adapter import UR3eAdapter

ROOT = Path(__file__).resolve().parent.parent
SAFE = [0.0, -1.57, 1.57, -1.57, -1.57, 0.0]


class FakeArm:
    def __init__(self):
        self.q = list(SAFE)
        self.target = None
        self.speed = 0.0
        self.protective = False
        self.stops = 0
        self.moves = []
        self.frozen = False

    def tick(self):
        if self.target is None or self.frozen:
            self.speed = 0.0
            return
        step = 0.02
        done = True
        for i, goal in enumerate(self.target):
            delta = goal - self.q[i]
            if abs(delta) > step:
                self.q[i] += step if delta > 0 else -step
                done = False
            else:
                self.q[i] = goal
        self.speed = 0.0 if done else 0.5
        if done:
            self.target = None


class FakeControl:
    def __init__(self, arm):
        self.arm = arm

    def isConnected(self): return True
    def isProgramRunning(self): return True
    def stopScript(self): pass

    def moveJ(self, q, speed, acc, asynchronous):
        assert asynchronous is True
        self.arm.moves.append((q, speed, acc))
        self.arm.target = list(q)
        return True

    def stopJ(self, decel):
        self.arm.stops += 1
        self.arm.target = None
        self.arm.speed = 0.0


class FakeReceive:
    def __init__(self, arm):
        self.arm = arm

    def isConnected(self): return True
    def isProtectiveStopped(self): return self.arm.protective
    def isEmergencyStopped(self): return False
    def getActualQ(self): return list(self.arm.q)

    def getActualQd(self):
        self.arm.tick()
        return [self.arm.speed] * 6


class Modules:
    def __init__(self, arm):
        self.RTDEControlInterface = lambda host: FakeControl(arm)
        self.RTDEReceiveInterface = lambda host: FakeReceive(arm)


@pytest.fixture
def arm():
    return FakeArm()


@pytest.fixture
def ur(arm, registry):
    poses = PoseBook.load(ROOT / "config/poses.ursim.yaml", registry.ids(), "ursim")
    mods = Modules(arm)
    return UR3eAdapter("127.0.0.1", poses, registry.limits, mods, mods)


async def test_completes_from_robot_state(ur, arm):
    await ur.connect()
    await ur.start_skill("point_left")
    result = await asyncio.wait_for(ur.wait_done(), 5)
    assert result.outcome == "completed"
    assert result.motion_start_ts is not None
    assert arm.moves[0][1:] == (0.25, 0.5)


async def test_stop_halts_and_waits_for_still(ur, arm):
    await ur.connect()
    await ur.start_skill("point_left")
    await asyncio.sleep(0.03)
    await ur.stop()
    result = await asyncio.wait_for(ur.wait_done(), 5)
    assert result.outcome == "stopped"
    assert arm.stops == 1
    assert arm.q[0] < 0.5


async def test_protective_stop_is_failure(ur, arm):
    await ur.connect()
    await ur.start_skill("point_left")
    arm.protective = True
    result = await asyncio.wait_for(ur.wait_done(), 5)
    assert result.outcome == "failed"
    with pytest.raises(SkillRefused):
        await ur.start_skill("point_right")


async def test_refuses_from_unknown_pose(ur, arm):
    await ur.connect()
    arm.q[0] = 0.3
    with pytest.raises(SkillRefused):
        await ur.start_skill("point_left")
    assert arm.moves == []


def test_real_mode_refuses_simulator_poses(registry):
    with pytest.raises(ConfigError):
        PoseBook.load(ROOT / "config/poses.ursim.yaml", registry.ids(), "real")


def test_real_mode_refuses_unapproved_template(registry):
    with pytest.raises(ConfigError):
        PoseBook.load(ROOT / "config/poses.example.yaml", registry.ids(), "real")
