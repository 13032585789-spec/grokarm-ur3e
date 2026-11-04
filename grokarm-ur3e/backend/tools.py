"""Session prompt, tool schema and tool dispatch for Grok."""
from __future__ import annotations

import json

from .session import Session
from .skill_registry import SkillRegistry

REFUSAL_REASONS = ["out_of_reach", "not_a_skill", "free_trajectory", "unsafe"]


def instructions(registry: SkillRegistry) -> str:
    skills = "\n".join(f"- {s.skill_id}: {s.description}" for s in registry.all())
    return f"""You are the voice of a UR3e robot arm in a workshop. Speak Italian, in one short sentence.

Skills:
{skills}

Flow:
1. Understand the request, even when it is phrased indirectly.
2. Clear request for one skill: call propose_robot_skill, then say the ask_user text it returns.
3. Vague request (unclear object, place or direction, such as "spostalo lì"): call request_clarification, then ask one short question. Never guess.
4. Anything outside the skills, such as coordinates, distances, speeds or free movement: call refuse_request and say why. Do not offer to try.
5. After the user answers a proposal: on yes call confirm_and_execute with the proposal_id; on no call cancel_proposal.
6. When confirm_and_execute starts the motion, stay silent. The system announces the result. Never say a motion is finished by yourself.
7. If the user says stop, fermati or basta, call stop_robot at once.

A motion needs a new proposal and a new yes every time. For a sequence, do one skill at a time."""


def tool_schemas(registry: SkillRegistry) -> list[dict]:
    def tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
        return {
            "type": "function",
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        }

    return [
        tool(
            "propose_robot_skill",
            "Propose one allowed skill. Nothing moves until the user confirms.",
            {
                "skill_id": {"type": "string", "enum": registry.ids()},
                "user_intent": {"type": "string", "description": "What the user asked for"},
            },
            ["skill_id"],
        ),
        tool(
            "confirm_and_execute",
            "Run the proposal after the user said yes. The system checks the user's words too.",
            {"proposal_id": {"type": "string"}},
            ["proposal_id"],
        ),
        tool("cancel_proposal", "Drop the current proposal.", {}, []),
        tool("stop_robot", "Stop the arm now.", {}, []),
        tool(
            "request_clarification",
            "Record that the request is ambiguous before asking the user.",
            {"question": {"type": "string"}},
            ["question"],
        ),
        tool(
            "refuse_request",
            "Record a refusal for a request no skill can do.",
            {
                "reason": {"type": "string", "enum": REFUSAL_REASONS},
                "explanation": {"type": "string"},
            },
            ["reason"],
        ),
    ]


def session_update(registry: SkillRegistry, voice: str, reasoning: str) -> dict:
    return {
        "type": "session.update",
        "session": {
            "voice": voice,
            "instructions": instructions(registry),
            "tools": tool_schemas(registry),
            "turn_detection": {"type": "server_vad"},
            "reasoning": {"effort": reasoning},
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "transcription": {
                        "model": "grok-transcribe",
                        "language_hint": "it",
                        "keyterms": ["fermati", "stop", "basta", "vassoio", "braccio"],
                    },
                },
                "output": {"format": {"type": "audio/pcm", "rate": 24000}},
            },
        },
    }


async def dispatch(session: Session, name: str, raw_args: str) -> tuple[dict, bool]:
    """Run one tool. Returns the output and whether Grok should speak next."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "code": "bad_arguments"}, True
    if name == "propose_robot_skill":
        return await session.tool_propose(str(args.get("skill_id", "")), str(args.get("user_intent", ""))), True
    if name == "confirm_and_execute":
        result = await session.tool_confirm(str(args.get("proposal_id", "")))
        return result, not result.get("ok")  # silent while the arm moves
    if name == "cancel_proposal":
        return await session.tool_cancel(), True
    if name == "stop_robot":
        return await session.tool_stop(), False  # the system reports the outcome
    if name == "request_clarification":
        return await session.tool_clarify(str(args.get("question", ""))), True
    if name == "refuse_request":
        return await session.tool_refuse(str(args.get("reason", "")), str(args.get("explanation", ""))), True
    return {"ok": False, "code": "unknown_tool"}, True
