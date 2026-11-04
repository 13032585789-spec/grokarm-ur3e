"""Gateway against a scripted fake of the Grok event stream."""
import asyncio
import json

from backend.confirmation_fsm import State
from backend.voice_gateway import GrokLink


class FakeGrok:
    def __init__(self):
        self.sent = []
        self.queue = asyncio.Queue()

    async def send(self, data):
        self.sent.append(json.loads(data))

    async def close(self):
        await self.queue.put(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.queue.get()
        if item is None:
            raise StopAsyncIteration
        return json.dumps(item)

    async def feed(self, **event):
        await self.queue.put(event)
        await asyncio.sleep(0.01)

    def of_type(self, kind):
        return [m for m in self.sent if m["type"] == kind]


async def start(session):
    grok = FakeGrok()
    ui = []

    async def send_ui(message):
        ui.append(message)

    async def connect():
        return grok

    session.emit = send_ui
    link = GrokLink(session, send_ui, connect, "eve", "none")
    await link.start()
    return link, grok, ui


async def tool(grok, name, args, call_id="c1"):
    await grok.feed(type="response.created")
    await grok.feed(type="response.function_call_arguments.done", name=name, call_id=call_id, arguments=json.dumps(args))
    await grok.feed(type="response.done")


async def test_session_update_has_only_enabled_skills(session):
    _, grok, _ = await start(session)
    update = grok.sent[0]["session"]
    enum = update["tools"][0]["parameters"]["properties"]["skill_id"]["enum"]
    assert enum == ["go_to_safe_pose", "point_left", "point_right"]
    assert update["audio"]["input"]["transcription"]["language_hint"] == "it"


async def test_full_turn_voice_flow(session, adapter):
    _, grok, ui = await start(session)
    await tool(grok, "propose_robot_skill", {"skill_id": "point_left"})
    output = json.loads(grok.of_type("conversation.item.create")[0]["item"]["output"])
    assert output["ok"]
    assert len(grok.of_type("response.create")) == 1

    await grok.feed(type="input_audio_buffer.speech_started")
    await grok.feed(type="input_audio_buffer.speech_stopped")
    await grok.feed(type="conversation.item.input_audio_transcription.completed", item_id="u1", transcript="sì")
    await tool(grok, "confirm_and_execute", {"proposal_id": output["proposal_id"]}, "c2")
    assert adapter.started == ["point_left"]
    assert len(grok.of_type("response.create")) == 1  # silent while moving
    await session.wait_idle()
    last = grok.of_type("conversation.item.create")[-1]["item"]
    assert last["type"] == "force_message"
    assert last["content"][0]["text"].startswith("Fatto")


async def test_model_cannot_confirm_alone(session, adapter):
    _, grok, _ = await start(session)
    await tool(grok, "propose_robot_skill", {"skill_id": "point_left"})
    pid = json.loads(grok.of_type("conversation.item.create")[0]["item"]["output"])["proposal_id"]
    await tool(grok, "confirm_and_execute", {"proposal_id": pid}, "c2")
    await asyncio.sleep(0.05)
    assert adapter.started == []


async def test_partial_transcript_stops_arm(session, adapter):
    _, grok, _ = await start(session)
    session.stop_on_any_speech = False
    await tool(grok, "propose_robot_skill", {"skill_id": "point_left"})
    pid = json.loads(grok.of_type("conversation.item.create")[0]["item"]["output"])["proposal_id"]
    await grok.feed(type="input_audio_buffer.speech_started")
    await grok.feed(type="conversation.item.input_audio_transcription.completed", item_id="u1", transcript="sì")
    await tool(grok, "confirm_and_execute", {"proposal_id": pid}, "c2")
    await grok.feed(type="input_audio_buffer.speech_started")
    assert session.fsm.state is State.EXECUTING
    await grok.feed(type="conversation.item.input_audio_transcription.updated", transcript="fermati")
    assert session.fsm.state in (State.STOPPING, State.IDLE)
    await session.wait_idle()
    assert session.metrics["last_stop_to_still_ms"] >= 0


async def test_lost_grok_link_stops_arm(session, adapter):
    _, grok, ui = await start(session)
    await tool(grok, "propose_robot_skill", {"skill_id": "point_left"})
    pid = json.loads(grok.of_type("conversation.item.create")[0]["item"]["output"])["proposal_id"]
    await grok.feed(type="input_audio_buffer.speech_started")
    await grok.feed(type="conversation.item.input_audio_transcription.completed", item_id="u1", transcript="sì")
    await tool(grok, "confirm_and_execute", {"proposal_id": pid}, "c2")
    await grok.queue.put(None)
    await asyncio.sleep(0.02)
    await session.wait_idle()
    assert session.fsm.state is State.IDLE
    assert any(m.get("type") == "error" for m in ui)


async def test_bad_tool_arguments_do_not_move(session, adapter):
    _, grok, _ = await start(session)
    await grok.feed(type="response.function_call_arguments.done", name="confirm_and_execute", call_id="c", arguments="{oops")
    await grok.feed(type="response.done")
    assert adapter.started == []


async def test_transcript_counted_once(session):
    _, grok, ui = await start(session)
    await grok.feed(type="conversation.item.input_audio_transcription.completed", item_id="u1", transcript="ciao")
    await grok.feed(type="conversation.item.added", item={"id": "u1", "role": "user", "content": [{"type": "input_audio", "transcript": "ciao"}]})
    assert len([m for m in ui if m.get("type") == "transcript" and m.get("final")]) == 1
