"""Links the browser, the session and Grok.

Grok is reached from this server, so the key stays off the browser and every
tool call passes through Session.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Awaitable, Callable

from .confirmation_fsm import State
from .keyword_baseline import parse
from .session import Session
from .speech_rules import classify_confirmation, has_stop_word
from .tools import dispatch, session_update

UiSend = Callable[[dict], Awaitable[None]]
MIC_SILENCE_LIMIT_S = 2.0


class GrokLink:
    def __init__(self, session: Session, ui: UiSend, connect: Callable[[], Awaitable], voice: str, reasoning: str):
        self.session = session
        self.ui = ui
        self.connect = connect
        self.voice = voice
        self.reasoning = reasoning
        self.ws = None
        self._reader: asyncio.Task | None = None
        self._watchdog: asyncio.Task | None = None
        self._tool_tasks: set[asyncio.Task] = set()
        self._want_response = False
        self._response_active = False
        self._seen_items: set[str] = set()
        self._last_audio = 0.0
        self._mic_used = False
        self._closing = False

    async def start(self) -> None:
        self.ws = await self.connect()
        await self.ws.send(json.dumps(session_update(self.session.registry, self.voice, self.reasoning)))
        self.session.say = self.say
        self._reader = asyncio.create_task(self._read())
        self._watchdog = asyncio.create_task(self._watch_mic())

    async def close(self) -> None:
        self._closing = True
        for task in (self._reader, self._watchdog):
            if task:
                task.cancel()
        if self.ws:
            await self.ws.close()

    async def send_audio(self, pcm: bytes) -> None:
        self._last_audio = time.monotonic()
        self._mic_used = True
        await self.ws.send(json.dumps({
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm).decode("ascii"),
        }))

    async def send_text(self, text: str) -> None:
        await self.session.on_final_transcript(text)
        await self.ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]},
        }))
        await self.ws.send(json.dumps({"type": "response.create"}))

    async def say(self, text: str) -> None:
        """Speak a fixed line. Used for results, so the model cannot invent one."""
        await self.ui({"type": "transcript", "role": "assistant", "text": text, "final": True})
        await self.ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "force_message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            },
        }))

    async def _watch_mic(self) -> None:
        """If the mic stream dies during motion, the voice stop is gone too."""
        while True:
            await asyncio.sleep(0.25)
            silent = time.monotonic() - self._last_audio > MIC_SILENCE_LIMIT_S
            if self._mic_used and silent and self.session.fsm.state is State.EXECUTING:
                await self.session.link_lost("mic_stream")

    async def _read(self) -> None:
        try:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    continue
                await self._handle(json.loads(raw))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.ui({"type": "error", "message": f"voice link error: {exc}"})
        if not self._closing:
            await self.session.link_lost("grok")
            await self.ui({"type": "error", "message": "Grok connection closed"})

    async def _handle(self, event: dict) -> None:
        kind = event.get("type", "")
        if kind == "input_audio_buffer.speech_started":
            await self.ui({"type": "audio_clear"})
            await self.session.on_speech_started()
            if self.session.fsm.state is State.STOPPING and self._response_active:
                await self.ws.send(json.dumps({"type": "response.cancel"}))
        elif kind == "input_audio_buffer.speech_stopped":
            await self.session.on_speech_stopped()
        elif kind == "conversation.item.input_audio_transcription.updated":
            text = event.get("transcript", "")
            await self.ui({"type": "transcript", "role": "user", "text": text, "final": False})
            await self.session.on_partial_transcript(text)
        elif kind == "conversation.item.input_audio_transcription.completed":
            await self._final_user(event.get("item_id"), event.get("transcript", ""))
        elif kind == "conversation.item.added":
            item = event.get("item") or {}
            if item.get("role") == "user":
                for part in item.get("content") or []:
                    if part.get("type") == "input_audio" and part.get("transcript"):
                        await self._final_user(item.get("id"), part["transcript"])
        elif kind == "response.created":
            self._response_active = True
        elif kind in ("response.output_audio.delta", "response.audio.delta"):
            await self.ui({"type": "audio", "delta": event.get("delta", "")})
        elif kind == "response.output_audio_transcript.delta":
            await self.ui({"type": "transcript", "role": "assistant", "text": event.get("delta", ""), "final": False})
        elif kind == "response.function_call_arguments.done":
            task = asyncio.create_task(self._run_tool(event))
            self._tool_tasks.add(task)
            task.add_done_callback(self._tool_tasks.discard)
        elif kind == "response.done":
            self._response_active = False
            await self.ui({"type": "assistant_done"})
            await self._flush_response()
        elif kind == "error":
            await self.ui({"type": "error", "message": json.dumps(event)[:300]})

    async def _final_user(self, item_id, text: str) -> None:
        if not text or item_id in self._seen_items:
            return
        self._seen_items.add(item_id)
        await self.ui({"type": "transcript", "role": "user", "text": text, "final": True})
        await self.session.on_final_transcript(text)

    async def _run_tool(self, event: dict) -> None:
        output, speak = await dispatch(self.session, event.get("name", ""), event.get("arguments", ""))
        await self.ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": event.get("call_id"),
                "output": json.dumps(output, ensure_ascii=False),
            },
        }))
        self._want_response = self._want_response or speak
        await self._flush_response()

    async def _flush_response(self) -> None:
        # One response.create, after every tool result and the current response.
        if self._want_response and not self._response_active and not self._tool_tasks - {asyncio.current_task()}:
            self._want_response = False
            await self.ws.send(json.dumps({"type": "response.create"}))


class OfflineLink:
    """Typed commands with keyword rules, so the UI works without a key."""

    def __init__(self, session: Session, ui: UiSend):
        self.session = session
        self.ui = ui

    async def start(self) -> None:
        self.session.say = self.say

    async def close(self) -> None:
        pass

    async def send_audio(self, pcm: bytes) -> None:
        pass

    async def say(self, text: str) -> None:
        await self.ui({"type": "transcript", "role": "assistant", "text": text, "final": True})

    async def send_text(self, text: str) -> None:
        await self.ui({"type": "transcript", "role": "user", "text": text, "final": True})
        session = self.session
        await session.on_final_transcript(text)
        if has_stop_word(text):
            return
        if session.fsm.state is State.PROPOSED:
            answer = classify_confirmation(text)
            proposal_id = session.fsm.proposal.proposal_id
            if answer == "yes":
                result = await session.tool_confirm(proposal_id)
                if not result.get("ok"):
                    await self.say(f"Rifiutato: {result.get('code')}.")
            elif answer == "no":
                await session.tool_cancel()
                await self.say("Va bene, annullato.")
            else:
                await self.say("Rispondi sì o no.")
            return
        skill_id = parse(text)
        if skill_id == "none":
            await session.tool_refuse("not_a_skill", text)
            await self.say("Non ho capito. In modalità offline conosco solo parole chiave.")
            return
        result = await session.tool_propose(skill_id, text)
        await self.say(result.get("ask_user") or f"Rifiutato: {result.get('code')}.")
