"""GrokArm server: one process, one port, one arm."""
from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from .event_log import EventLog
from .mock_adapter import MockUR3eAdapter
from .robot_adapter import RobotAdapter
from .session import Session
from .skill_registry import ConfigError, PoseBook, SkillRegistry
from .ur3e_adapter import UR3eAdapter
from .voice_gateway import GrokLink, OfflineLink

ROOT = Path(__file__).resolve().parent.parent
REAL_MOTION_PHRASE = "STAFF_APPROVED"
XAI_URL = "wss://api.x.ai/v1/realtime?model={model}"


@dataclass
class Settings:
    robot_mode: str = "mock"
    robot_host: str = ""
    voice_mode: str = "grok"
    api_key: str = ""
    model: str = "grok-voice-3.0"
    voice: str = "eve"
    reasoning: str = "none"
    stop_on_any_speech: bool = True
    poses_file: str = ""
    allow_real_motion: str = ""
    confirm_wait_s: float = 1.5

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(ROOT / ".env")
        env = os.getenv
        return cls(
            robot_mode=env("ROBOT_MODE", "mock"),
            robot_host=env("ROBOT_HOST", ""),
            voice_mode=env("VOICE_MODE", "grok"),
            api_key=env("XAI_API_KEY", ""),
            model=env("XAI_VOICE_MODEL", "grok-voice-3.0"),
            voice=env("XAI_VOICE", "eve"),
            reasoning=env("XAI_REASONING", "none"),
            stop_on_any_speech=env("STOP_ON_ANY_SPEECH", "true").lower() == "true",
            poses_file=env("POSES_FILE", ""),
            allow_real_motion=env("ALLOW_REAL_MOTION", ""),
            confirm_wait_s=float(env("CONFIRM_WAIT_S", "1.5")),
        )


def build_adapter(settings: Settings, registry: SkillRegistry) -> RobotAdapter:
    if settings.robot_mode == "mock":
        return MockUR3eAdapter(registry)
    if settings.robot_mode == "ursim":
        poses = PoseBook.load(settings.poses_file or ROOT / "config/poses.ursim.yaml", registry.ids(), "ursim")
        return UR3eAdapter(settings.robot_host or "127.0.0.1", poses, registry.limits)
    if settings.robot_mode == "real":
        if settings.allow_real_motion != REAL_MOTION_PHRASE:
            raise ConfigError(f"real mode needs ALLOW_REAL_MOTION={REAL_MOTION_PHRASE}, set only with staff present")
        if not settings.robot_host:
            raise ConfigError("real mode needs ROBOT_HOST")
        poses = PoseBook.load(settings.poses_file or ROOT / "config/poses.local.yaml", registry.ids(), "real")
        return UR3eAdapter(settings.robot_host, poses, registry.limits)
    raise ConfigError(f"unknown ROBOT_MODE {settings.robot_mode}")


def create_app(settings: Settings | None = None, adapter: RobotAdapter | None = None, connect_grok=None) -> Starlette:
    settings = settings or Settings.from_env()
    registry = SkillRegistry.load(ROOT / "config/skills.yaml")
    robot = adapter or build_adapter(settings, registry)
    session = Session(registry, robot, EventLog(ROOT / "runs"), settings.stop_on_any_speech, settings.confirm_wait_s)

    async def default_connect():
        import websockets

        return await websockets.connect(
            XAI_URL.format(model=settings.model),
            additional_headers={"Authorization": f"Bearer {settings.api_key}"},
            max_size=None,
        )

    connect = connect_grok or default_connect

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        await robot.connect()
        yield
        await robot.close()

    async def index(_request):
        return FileResponse(ROOT / "frontend/index.html")

    async def status(_request):
        return JSONResponse({
            "state": session.fsm.state.value,
            "robot": robot.status().to_dict(),
            "robot_mode": settings.robot_mode,
            "voice_mode": settings.voice_mode,
            "skills": [{"id": s.skill_id, "label": s.label_it} for s in registry.all()],
            "metrics": session.metrics,
        })

    async def stop(_request):
        return JSONResponse(await session.request_stop("http"))

    async def ws_endpoint(ws: WebSocket):
        await ws.accept()

        async def ui(message: dict):
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await ws.send_text(json.dumps(message, ensure_ascii=False))

        session.emit = ui
        offline = settings.voice_mode == "offline" or (not settings.api_key and connect_grok is None)
        link = OfflineLink(session, ui) if offline else GrokLink(
            session, ui, connect, settings.voice, settings.reasoning
        )
        try:
            await link.start()
        except Exception as exc:
            await ui({"type": "error", "message": f"Could not reach Grok: {exc}"})
            await ws.close()
            return
        await ui({"type": "hello", "voice": "offline" if offline else "grok"})
        await session.publish()
        try:
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes"):
                    await link.send_audio(message["bytes"])
                elif message.get("text"):
                    data = json.loads(message["text"])
                    if data.get("type") == "stop":
                        await session.request_stop("ui_button")
                    elif data.get("type") == "text":
                        await link.send_text(str(data.get("text", "")))
        except WebSocketDisconnect:
            pass
        finally:
            await session.link_lost("browser")
            await link.close()

    return Starlette(
        routes=[
            Route("/", index),
            Route("/api/status", status),
            Route("/api/stop", stop, methods=["POST"]),
            WebSocketRoute("/ws", ws_endpoint),
        ],
        lifespan=lifespan,
    )
