import asyncio

import pytest

from backend.confirmation_fsm import ConfirmationFSM, Rejected, State


async def propose(session, skill="point_left"):
    result = await session.tool_propose(skill, "test")
    assert result["ok"]
    await asyncio.sleep(0.001)
    return result["proposal_id"]


async def test_no_motion_without_user_words(session, adapter):
    pid = await propose(session)
    result = await session.tool_confirm(pid)
    assert result == {"ok": False, "code": "no_user_speech"}
    assert adapter.started == []
    assert session.fsm.state is State.PROPOSED


async def test_utterance_before_proposal_does_not_count(session, adapter):
    await session.on_final_transcript("sì vai")
    await asyncio.sleep(0.001)
    pid = await propose(session)
    assert not (await session.tool_confirm(pid))["ok"]
    assert adapter.started == []


async def test_late_transcript_of_the_request_does_not_count(session, adapter):
    await session.on_speech_started()
    await asyncio.sleep(0.001)
    pid = await propose(session)
    await session.on_final_transcript("ok vai a sinistra")  # the request, transcribed late
    assert not (await session.tool_confirm(pid))["ok"]
    assert adapter.started == []


async def test_yes_runs_once_and_reports_from_robot(session, adapter):
    pid = await propose(session)
    await session.on_final_transcript("sì")
    assert (await session.tool_confirm(pid))["ok"]
    assert not (await session.tool_confirm(pid))["ok"]  # one yes, one motion
    await session.wait_idle()
    assert adapter.started == ["point_left"]
    assert session.spoken == ["Fatto: ho indicato a sinistra."]
    assert session.fsm.state is State.IDLE


async def test_every_motion_needs_a_new_yes(session, adapter):
    pid = await propose(session)
    await session.on_final_transcript("sì")
    await session.tool_confirm(pid)
    await session.wait_idle()
    pid = await propose(session, "point_right")
    assert not (await session.tool_confirm(pid))["ok"]
    assert adapter.started == ["point_left"]


async def test_no_cancels(session, adapter):
    pid = await propose(session)
    await session.on_final_transcript("no grazie")
    assert (await session.tool_confirm(pid))["code"] == "user_declined"
    assert session.fsm.state is State.IDLE
    assert adapter.started == []


async def test_unclear_answer_keeps_waiting(session, adapter):
    pid = await propose(session)
    await session.on_final_transcript("forse")
    assert (await session.tool_confirm(pid))["code"] == "not_a_confirmation"
    assert session.fsm.state is State.PROPOSED


async def test_wrong_id_refused(session, adapter):
    await propose(session)
    await session.on_final_transcript("sì")
    assert (await session.tool_confirm("deadbeef"))["code"] == "wrong_proposal"
    assert adapter.started == []


async def test_unknown_and_disabled_skills_refused(session):
    for skill in ("draw_circle", "lift_tray"):
        result = await session.tool_propose(skill)
        assert result["code"] == "unknown_skill"
    assert session.fsm.state is State.IDLE


async def test_second_proposal_refused_while_one_is_open(session):
    await propose(session)
    assert (await session.tool_propose("point_right"))["code"] == "busy"


def test_proposal_expires():
    fsm = ConfirmationFSM(ttl_s=5)
    proposal = fsm.propose("point_left", "", 100.0)
    fsm.note_user_utterance("sì", 101.0)
    with pytest.raises(Rejected) as err:
        fsm.confirm(proposal.proposal_id, 200.0)
    assert err.value.code == "expired"
    assert fsm.state is State.IDLE


async def test_fault_is_reported_and_blocks_next_motion(session, adapter):
    adapter.fail_next = "protective_stop"
    pid = await propose(session)
    await session.on_final_transcript("sì")
    await session.tool_confirm(pid)
    await session.wait_idle()
    assert "Non ho completato" in session.spoken[0]
    assert (await session.tool_propose("point_right"))["code"] == "robot_not_ready"


async def test_disconnect_blocks_next_motion(session, adapter):
    adapter.fail_next = "disconnect"
    pid = await propose(session)
    await session.on_final_transcript("sì")
    await session.tool_confirm(pid)
    await session.wait_idle()
    assert (await session.tool_propose("point_right"))["code"] == "robot_not_ready"
