import asyncio
import inspect
from pathlib import Path

import pytest

from backend.mock_adapter import MockUR3eAdapter
from backend.session import Session
from backend.skill_registry import SkillRegistry

ROOT = Path(__file__).resolve().parent.parent


def pytest_pyfunc_call(pyfuncitem):
    """Run async tests without an extra plugin."""
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        args = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
        asyncio.run(pyfuncitem.obj(**args))
        return True
    return None


@pytest.fixture
def registry():
    return SkillRegistry.load(ROOT / "config/skills.yaml")


@pytest.fixture
def adapter(registry):
    mock = MockUR3eAdapter(registry, time_scale=0.02)
    mock.connected = True
    return mock


@pytest.fixture
def session(registry, adapter):
    s = Session(registry, adapter, confirm_wait_s=0.02)
    s.spoken = []

    async def say(text):
        s.spoken.append(text)

    s.say = say
    return s
