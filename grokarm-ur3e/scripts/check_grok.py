"""Check the key and the live event names. Prints events; moves nothing."""
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

import websockets  # noqa: E402

from backend.skill_registry import SkillRegistry  # noqa: E402
from backend.tools import session_update  # noqa: E402


async def main():
    registry = SkillRegistry.load(ROOT / "config/skills.yaml")
    model = os.getenv("XAI_VOICE_MODEL", "grok-voice-3.0")
    async with websockets.connect(
        f"wss://api.x.ai/v1/realtime?model={model}",
        additional_headers={"Authorization": f"Bearer {os.environ['XAI_API_KEY']}"},
        max_size=None,
    ) as ws:
        await ws.send(json.dumps(session_update(registry, os.getenv("XAI_VOICE", "eve"), "none")))
        await ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "Indica la posizione a sinistra"}]},
        }))
        await ws.send(json.dumps({"type": "response.create"}))
        async for raw in ws:
            if isinstance(raw, bytes):
                continue
            event = json.loads(raw)
            if "audio.delta" not in event["type"]:
                print(json.dumps(event, ensure_ascii=False)[:400])
            if event["type"] == "error":
                print("ERROR: fix this before going further")
            if event["type"] == "response.done":
                return


asyncio.run(main())
