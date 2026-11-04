"""HTTP and WebSocket routes in offline mode, with the mock arm."""
import time

from starlette.testclient import TestClient

from backend.main import ConfigError, Settings, build_adapter, create_app
from backend.mock_adapter import MockUR3eAdapter

import pytest


def receive_until(ws, predicate, limit=40):
    for _ in range(limit):
        message = ws.receive_json()
        if predicate(message):
            return message
    raise AssertionError("message not seen")


@pytest.fixture
def client(registry, tmp_path):
    settings = Settings(voice_mode="offline")
    app = create_app(settings, adapter=MockUR3eAdapter(registry, time_scale=0.05))
    with TestClient(app) as test_client:
        yield test_client


def test_page_and_status(client):
    assert "GrokArm" in client.get("/").text
    body = client.get("/api/status").json()
    assert body["state"] == "IDLE" and len(body["skills"]) == 3


def test_typed_command_runs_after_yes(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "text", "text": "Indica a sinistra"})
        receive_until(ws, lambda m: m.get("type") == "state" and m["state"] == "PROPOSED")
        time.sleep(0.01)
        ws.send_json({"type": "text", "text": "sì"})
        receive_until(ws, lambda m: m.get("type") == "state" and m["state"] == "EXECUTING")
        done = receive_until(ws, lambda m: m.get("type") == "transcript" and str(m.get("text", "")).startswith("Fatto"))
        assert "sinistra" in done["text"]


def test_ui_stop_halts(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "text", "text": "Indica a destra"})
        receive_until(ws, lambda m: m.get("type") == "state" and m["state"] == "PROPOSED")
        time.sleep(0.01)
        ws.send_json({"type": "text", "text": "ok"})
        receive_until(ws, lambda m: m.get("type") == "state" and m["state"] == "EXECUTING")
        assert client.post("/api/stop").json()["status"] == "stopping"
        receive_until(ws, lambda m: str(m.get("text", "")).startswith("Mi sono fermato"))


def test_real_mode_is_locked(registry):
    with pytest.raises(ConfigError):
        build_adapter(Settings(robot_mode="real", robot_host="10.0.0.1"), registry)
    with pytest.raises(ConfigError):
        build_adapter(Settings(robot_mode="real", allow_real_motion="STAFF_APPROVED"), registry)
