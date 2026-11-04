"""The safety core: every path to a motion or a stop goes through this class."""
from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Awaitable, Callable

from .confirmation_fsm import ConfirmationFSM, Rejected, State
from .event_log import EventLog
from .robot_adapter import ExecutionResult, RobotAdapter, SkillRefused
from .skill_registry import SkillRegistry
from .speech_rules import has_stop_word

Emit = Callable[[dict], Awaitable[None]]
Say = Callable[[str], Awaitable[None]]


async def _noop(_):
    return None


class Session:
    def __init__(
        self,
        registry: SkillRegistry,
        adapter: RobotAdapter,
        log: EventLog | None = None,
        stop_on_any_speech: bool = True,
        confirm_wait_s: float = 1.5,
        proposal_ttl_s: float = 30.0,
    ):
        self.registry = registry
        self.adapter = adapter
        self.log = log or EventLog(None)
        self.stop_on_any_speech = stop_on_any_speech
        self.confirm_wait_s = confirm_wait_s
        self.fsm = ConfirmationFSM(proposal_ttl_s)
        self.emit: Emit = _noop
        self.say: Say = _noop
        self.last_speech_end_ts: float | None = None
        self._speech_start_ts: float | None = None
        self.metrics: dict = {}
        self._new_utterance = asyncio.Event()
        self._exec_task: asyncio.Task | None = None
        self._stop_ts: float | None = None
        self._stop_source: str | None = None
        self._cur_skill: str | None = None
        self._confirm_speech_end: float | None = None

    # ----- state published to the UI -----
    async def publish(self) -> None:
        proposal = self.fsm.proposal
        await self.emit({
            "type": "state",
            "state": self.fsm.state.value,
            "skill": proposal.skill_id if proposal else self._cur_skill,
            "robot": self.adapter.status().to_dict(),
            "metrics": self.metrics,
        })

    async def _record(self, event: str, **fields) -> None:
        await self.emit({"type": "event", **self.log.write(event, **fields)})

    # ----- speech signals -----
    async def on_speech_started(self) -> None:
        self._speech_start_ts = time.time()
        if self.fsm.state is State.EXECUTING and self.stop_on_any_speech:
            await self.request_stop("speech_detected")

    async def on_speech_stopped(self) -> None:
        self.last_speech_end_ts = time.time()

    async def on_partial_transcript(self, text: str) -> None:
        if has_stop_word(text):
            await self.request_stop("partial_transcript", text)

    async def on_final_transcript(self, text: str) -> None:
        # Stamp with when speech began: a late transcript of the request itself
        # must not count as the answer to the proposal it produced.
        self.fsm.note_user_utterance(text, self._speech_start_ts or time.time())
        self._speech_start_ts = None
        self._new_utterance.set()
        await self._record("user_utterance", text=text)
        if has_stop_word(text):
            await self.request_stop("final_transcript", text)

    # ----- stop: never waits on the model -----
    async def request_stop(self, source: str, text: str = "") -> dict:
        now = time.time()
        if self.fsm.state is State.PROPOSED:
            self.fsm.cancel()
            await self._record("proposal_cancelled", source=source, text=text)
            await self.publish()
            return {"status": "cancelled"}
        if self.fsm.begin_stop():
            self._stop_ts = now
            self._stop_source = source
            await self.adapter.stop()
            await self._record("stop_issued", source=source, text=text)
            await self.publish()
            return {"status": "stopping"}
        if self.fsm.state is State.STOPPING:
            return {"status": "stopping"}
        # Idle: send a stop anyway, in case our state and the arm disagree.
        await self.adapter.stop()
        return {"status": "idle"}

    async def link_lost(self, reason: str) -> None:
        """No voice link means no voice stop, so motion must not continue."""
        await self._record("link_lost", reason=reason)
        await self.request_stop(f"link_lost:{reason}")

    # ----- tools called by Grok -----
    async def tool_propose(self, skill_id: str, user_intent: str = "") -> dict:
        skill = self.registry.get(skill_id)
        if skill is None:
            await self._record("proposal_rejected", skill_id=skill_id, code="unknown_skill")
            return {"ok": False, "code": "unknown_skill", "allowed": self.registry.ids()}
        status = self.adapter.status()
        if not status.ready:
            await self._record("proposal_rejected", skill_id=skill_id, code="robot_not_ready")
            return {"ok": False, "code": "robot_not_ready", "detail": status.detail}
        try:
            proposal = self.fsm.propose(skill_id, user_intent, time.time())
        except Rejected as exc:
            return {"ok": False, "code": exc.code}
        await self._record("proposed", skill_id=skill_id, user_intent=user_intent, proposal_id=proposal.proposal_id)
        await self.publish()
        return {
            "ok": True,
            "proposal_id": proposal.proposal_id,
            "ask_user": f"Vuoi che vada a {skill.label_it}? Rispondi sì o no.",
        }

    async def tool_confirm(self, proposal_id: str) -> dict:
        # The transcript can arrive just after the tool call, so give it a moment.
        if self.fsm.state is State.PROPOSED and self.fsm.utterance_since_proposal() is None:
            self._new_utterance.clear()
            try:
                await asyncio.wait_for(self._new_utterance.wait(), self.confirm_wait_s)
            except asyncio.TimeoutError:
                pass
        status = self.adapter.status()
        if not status.ready:
            self.fsm.cancel()
            await self.publish()
            await self._record("confirm_rejected", code="robot_not_ready")
            return {"ok": False, "code": "robot_not_ready", "detail": status.detail}
        try:
            proposal = self.fsm.confirm(proposal_id, time.time())
        except Rejected as exc:
            await self._record("confirm_rejected", code=exc.code)
            await self.publish()
            return {"ok": False, "code": exc.code}
        self._cur_skill = proposal.skill_id
        self._stop_ts = None
        self._stop_source = None
        self._confirm_speech_end = self.last_speech_end_ts
        await self._record("confirmed", skill_id=proposal.skill_id)
        await self.publish()
        self._exec_task = asyncio.create_task(self._execute(proposal.skill_id))
        return {"ok": True, "status": "started", "instruction": "Stay silent until the system reports the result."}

    async def tool_cancel(self) -> dict:
        self.fsm.cancel()
        await self._record("proposal_cancelled", source="model")
        await self.publish()
        return {"ok": True}

    async def tool_stop(self) -> dict:
        return await self.request_stop("model_tool")

    async def tool_refuse(self, reason: str, explanation: str = "") -> dict:
        await self._record("refused", reason=reason, explanation=explanation)
        return {"ok": True, "moved": False}

    async def tool_clarify(self, question: str) -> dict:
        await self._record("clarification", question=question)
        return {"ok": True, "moved": False}

    # ----- execution -----
    async def _execute(self, skill_id: str) -> None:
        skill = self.registry.get(skill_id)
        try:
            await self.adapter.start_skill(skill_id)
            if self.fsm.state is State.STOPPING:  # stop arrived during start
                await self.adapter.stop()
            result = await self.adapter.wait_done()
        except SkillRefused as exc:
            result = ExecutionResult("failed", f"refused: {exc}")
        except Exception as exc:
            await self.adapter.stop()
            result = ExecutionResult("failed", f"error: {exc}")
        self._update_metrics(result)
        await self._record(
            "finished", skill_id=skill_id, outcome=result.outcome, detail=result.detail,
            stop_source=self._stop_source, metrics=self.metrics,
        )
        self.fsm.finish()
        self._cur_skill = None
        await self.publish()
        with contextlib.suppress(Exception):  # the voice link may already be gone
            await self.say(self._report(skill.label_it, skill.done_it, result))

    def _update_metrics(self, result: ExecutionResult) -> None:
        if result.motion_start_ts and self._confirm_speech_end:
            self.metrics["last_speech_to_motion_ms"] = round((result.motion_start_ts - self._confirm_speech_end) * 1000)
        if result.motion_stopped_ts and self._stop_ts and result.outcome == "stopped":
            self.metrics["last_stop_to_still_ms"] = round((result.motion_stopped_ts - self._stop_ts) * 1000)

    @staticmethod
    def _report(label: str, done: str, result: ExecutionResult) -> str:
        if result.outcome == "completed":
            return f"Fatto: {done}."
        if result.outcome == "stopped":
            return "Mi sono fermato. Il movimento è stato interrotto."
        return f"Non ho completato l'azione: {label}. Controlla il robot."

    async def wait_idle(self) -> None:
        if self._exec_task:
            await self._exec_task
