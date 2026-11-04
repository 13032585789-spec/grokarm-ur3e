"""One proposal, one confirmation, one motion.

The confirmation gate checks the user's own transcribed words. A tool call from
the model cannot approve a motion by itself.
"""
from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass

from .speech_rules import classify_confirmation


class State(str, enum.Enum):
    IDLE = "IDLE"
    PROPOSED = "PROPOSED"
    EXECUTING = "EXECUTING"
    STOPPING = "STOPPING"


class Rejected(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Proposal:
    proposal_id: str
    skill_id: str
    user_intent: str
    created_at: float
    expires_at: float


class ConfirmationFSM:
    def __init__(self, ttl_s: float = 30.0):
        self.ttl_s = ttl_s
        self.state = State.IDLE
        self.proposal: Proposal | None = None
        self._utterance: tuple[float, str] | None = None

    def note_user_utterance(self, text: str, ts: float) -> None:
        self._utterance = (ts, text)

    def utterance_since_proposal(self) -> str | None:
        if self.proposal and self._utterance and self._utterance[0] > self.proposal.created_at:
            return self._utterance[1]
        return None

    def expire(self, now: float) -> bool:
        if self.state is State.PROPOSED and self.proposal and now > self.proposal.expires_at:
            self.cancel()
            return True
        return False

    def propose(self, skill_id: str, user_intent: str, now: float) -> Proposal:
        self.expire(now)
        if self.state is not State.IDLE:
            raise Rejected("busy", f"cannot propose in state {self.state.value}")
        self.proposal = Proposal(uuid.uuid4().hex[:8], skill_id, user_intent, now, now + self.ttl_s)
        self.state = State.PROPOSED
        return self.proposal

    def confirm(self, proposal_id: str, now: float) -> Proposal:
        if self.expire(now):
            raise Rejected("expired", "proposal expired")
        if self.state is not State.PROPOSED or self.proposal is None:
            raise Rejected("no_proposal", "nothing to confirm")
        if proposal_id != self.proposal.proposal_id:
            raise Rejected("wrong_proposal", "proposal id does not match")
        words = self.utterance_since_proposal()
        if words is None:
            raise Rejected("no_user_speech", "the user has not answered yet")
        verdict = classify_confirmation(words)
        if verdict == "no":
            self.cancel()
            raise Rejected("user_declined", "the user declined")
        if verdict != "yes":
            raise Rejected("not_a_confirmation", "the answer was not a clear yes")
        proposal = self.proposal
        self.proposal = None  # consumed: this confirmation cannot be reused
        self.state = State.EXECUTING
        return proposal

    def cancel(self) -> None:
        if self.state is State.PROPOSED:
            self.proposal = None
            self.state = State.IDLE

    def begin_stop(self) -> bool:
        if self.state is State.EXECUTING:
            self.state = State.STOPPING
            return True
        return False

    def finish(self) -> None:
        self.proposal = None
        self.state = State.IDLE
