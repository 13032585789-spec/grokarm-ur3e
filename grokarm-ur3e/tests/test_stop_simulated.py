import pytest

from backend.confirmation_fsm import State
from backend.session import Session


async def moving(session):
    await session.adapter.connect()
    pid = (await session.tool_propose("point_left"))["proposal_id"]
    import asyncio
    await asyncio.sleep(0.001)
    await session.on_final_transcript("sì")
    assert (await session.tool_confirm(pid))["ok"]
    await asyncio.sleep(0.005)
    assert session.fsm.state is State.EXECUTING


@pytest.mark.parametrize("trigger", [
    lambda s: s.on_speech_started(),
    lambda s: s.on_partial_transcript("fer ma fermati"),
    lambda s: s.on_final_transcript("basta"),
    lambda s: s.request_stop("ui_button"),
    lambda s: s.tool_stop(),
    lambda s: s.link_lost("grok"),
])
async def test_every_stop_path_halts(session, adapter, trigger):
    await moving(session)
    await trigger(session)
    await session.wait_idle()
    assert session.fsm.state is State.IDLE
    assert session.spoken == ["Mi sono fermato. Il movimento è stato interrotto."]
    assert "last_stop_to_still_ms" in session.metrics


async def test_speech_can_be_set_not_to_stop(registry, adapter):
    session = Session(registry, adapter, stop_on_any_speech=False)
    await moving(session)
    await session.on_speech_started()
    assert session.fsm.state is State.EXECUTING
    await session.on_partial_transcript("fermati")
    assert session.fsm.state is State.STOPPING
    await session.wait_idle()


async def test_stop_is_idempotent(session):
    await moving(session)
    await session.request_stop("a")
    await session.request_stop("b")
    await session.wait_idle()
    assert len(session.spoken) == 1


async def test_stop_cancels_a_pending_proposal(session, adapter):
    await adapter.connect()
    await session.tool_propose("point_left")
    await session.on_final_transcript("fermati")
    assert session.fsm.state is State.IDLE
    assert adapter.started == []
