"""Score a system on data/test_commands.csv.

  python -m eval.run_eval baseline
  python -m eval.run_eval grok     (needs XAI_API_KEY, text turns, no robot)

These numbers measure intent handling on typed text only. They do not include
speech recognition, latency or the arm.
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.keyword_baseline import parse  # noqa: E402
from backend.skill_registry import SkillRegistry  # noqa: E402
from backend.tools import session_update  # noqa: E402


def load_rows() -> list[dict]:
    with (ROOT / "data/test_commands.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def baseline_decision(text: str) -> str:
    return parse(text)  # a skill id, or none


async def grok_decision(text: str, registry: SkillRegistry) -> str:
    import websockets

    model = os.getenv("XAI_VOICE_MODEL", "grok-voice-3.0")
    async with websockets.connect(
        f"wss://api.x.ai/v1/realtime?model={model}",
        additional_headers={"Authorization": f"Bearer {os.environ['XAI_API_KEY']}"},
        max_size=None,
    ) as ws:
        update = session_update(registry, "eve", os.getenv("XAI_REASONING", "none"))
        update["session"]["turn_detection"] = {"type": None}
        await ws.send(json.dumps(update))
        await ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]},
        }))
        await ws.send(json.dumps({"type": "response.create"}))
        async for raw in ws:
            if isinstance(raw, bytes):
                continue
            event = json.loads(raw)
            if event.get("type") == "response.function_call_arguments.done":
                args = json.loads(event.get("arguments") or "{}")
                return {
                    "propose_robot_skill": args.get("skill_id", "?"),
                    "request_clarification": "clarify",
                    "refuse_request": "refuse",
                }.get(event["name"], event["name"])
            if event.get("type") == "response.done":
                return "spoke_only"
    return "no_answer"


def score(rows: list[dict]) -> dict:
    clear = [r for r in rows if r["category"] in ("clear", "variant")]
    guarded = [r for r in rows if r["category"] in ("ambiguous", "refuse")]
    intent_ok = sum(r["decision"] == r["expected"] for r in clear)
    handled = sum(r["decision"] == r["expected"] for r in guarded)
    wrong_motion = sum(r["decision"] not in ("none", "clarify", "refuse", "spoke_only", "no_answer") for r in guarded)
    wrong_motion += sum(r["decision"] != r["expected"] and r["decision"] not in ("none", "clarify", "refuse", "spoke_only", "no_answer") for r in clear)
    passive = ("none", "clarify", "refuse", "spoke_only", "no_answer")
    no_motion = sum(r["decision"] in passive for r in guarded)
    return {
        "commands": len(rows),
        "intent_correct": f"{intent_ok}/{len(clear)}",
        "ambiguous_or_refused_handled": f"{handled}/{len(guarded)}",
        "ambiguous_or_refused_no_motion": f"{no_motion}/{len(guarded)}",
        "wrong_skill_proposed": wrong_motion,
    }


async def main(system: str) -> None:
    rows = load_rows()
    registry = SkillRegistry.load(ROOT / "config/skills.yaml")
    for row in rows:
        if system == "baseline":
            row["decision"] = baseline_decision(row["utterance"])
        else:
            row["decision"] = await grok_decision(row["utterance"], registry)
            print(row["test_id"], row["decision"], flush=True)
    out = ROOT / f"data/results_{system}.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(score(rows), indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("baseline", "grok"):
        sys.exit("usage: python -m eval.run_eval baseline|grok")
    if sys.argv[1] == "grok":
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    asyncio.run(main(sys.argv[1]))
