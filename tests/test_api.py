"""FastAPI endpoints (spec §11, §14 API). Simulated robot, no xAI."""

import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.robot.sim import SimAdapter


@pytest.fixture
def client(settings):
    app = create_app(settings, SimAdapter(settings.poses["home"]["joints"], time_scale=20))
    with TestClient(app) as c:
        yield c


def wait_gate(c, state, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if c.get("/api/status").json()["gate"] == state:
            return True
        time.sleep(0.02)
    return False


def test_status(client):
    s = client.get("/api/status").json()
    assert s["gate"] == "IDLE" and s["config"]["mode"] == "sim" and "xai" not in str(s["config"]).lower()
    assert set(s["catalogue"]) == {"vai_a_posa", "indica", "solleva_vassoio", "appoggia_vassoio", "spingi",
                                    "porta_in_ispezione", "smista"}


def test_stop_without_voice_connection(client):
    r = client.post("/api/stop", json={"source": "button"}).json()
    assert r["ok"] and client.get("/api/status").json()["gate"] == "STOPPED"
    r = client.post("/api/stop", json={"source": "space"}).json()   # repeated STOP is harmless
    assert r["ok"]


def test_reset_requires_deliberate_operator_flag(client):
    client.post("/api/stop", json={"source": "button"})
    assert client.post("/api/reset", json={}).status_code == 422
    assert client.post("/api/reset", json={"operator_confirmed": False}).status_code == 400
    r = client.post("/api/reset", json={"operator_confirmed": True})
    assert r.status_code == 200 and r.json()["ok"]
    assert client.get("/api/status").json()["gate"] == "IDLE"


def test_text_command_flow_and_label(client):
    r = client.post("/api/text-command", json={"text": "Potresti indicarmi la zona centrale?"}).json()
    assert r["mode"] == "TEXT MODE — NOT VOICE" and r["gate"] == "PENDING_CONFIRMATION"
    r = client.post("/api/text-command", json={"text": "sì"}).json()
    assert r["result"]["ok"]
    assert wait_gate(client, "IDLE")
    assert client.get("/api/status").json()["last_result"]["success"]


def test_duplicate_requests_ignored(client):
    body = {"text": "indica la zona destra", "request_id": "req-1"}
    a = client.post("/api/text-command", json=body).json()
    b = client.post("/api/text-command", json=body).json()
    assert b.get("duplicate") and a["result"]["action_id"] == b["result"]["action_id"]
    hist = client.get("/api/status").json()["history"]
    assert sum(1 for h in hist if h["kind"] == "proposta") == 1


def test_request_validation(client):
    assert client.post("/api/text-command", json={"text": ""}).status_code == 422
    assert client.post("/api/text-command", json={"text": "x" * 301}).status_code == 422
    assert client.post("/api/stop", json={"source": "grok"}).status_code == 422


def test_events_websocket_and_disconnect(client):
    with client.websocket_connect("/ws/events") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["gate"] == "IDLE"
        client.post("/api/stop", json={"source": "button"})
        types = set()
        for _ in range(20):
            ev = ws.receive_json()
            types.add(ev["type"])
            if "stop_ack" in types:
                break
        assert {"stop", "stop_ack"} <= types
    # client gone: server still healthy, and a new subscriber works
    assert client.get("/api/status").status_code == 200
    with client.websocket_connect("/ws/events") as ws:
        assert ws.receive_json()["gate"] == "STOPPED"


def test_voice_websocket_without_key(settings):
    settings.xai_api_key = None
    app = create_app(settings, SimAdapter(settings.poses["home"]["joints"]))
    with TestClient(app) as c, c.websocket_connect("/ws/voice") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error" and "TEXT MODE" in msg["message"]


def test_backend_restart_never_executes_old_pending(settings):
    sim = SimAdapter(settings.poses["home"]["joints"], time_scale=20)
    with TestClient(create_app(settings, sim)) as c:
        c.post("/api/text-command", json={"text": "indica la zona sinistra"})
        assert c.get("/api/status").json()["gate"] == "PENDING_CONFIRMATION"
    q_before = list(sim._q)
    with TestClient(create_app(settings, sim)) as c:          # "restart"
        s = c.get("/api/status").json()
        assert s["gate"] == "IDLE" and s["pending"] is None
        r = c.post("/api/text-command", json={"text": "sì"}).json()
        assert not (r["result"] or {}).get("ok")
    assert list(sim._q) == q_before   # the robot never moved


def test_language_switch(client):
    assert client.post("/api/language", json={"lang": "zh"}).json()["lang"] == "zh"
    assert client.get("/api/status").json()["config"]["lang"] == "zh"
    assert client.post("/api/language", json={"lang": "xx"}).status_code == 400


def test_inspection_over_http_with_browser_camera(client):
    import cv2
    import numpy as np
    app_settings = client.app.state.settings
    app_settings.robot["inspection"]["settle_s"] = 0.05
    from app.vision.inspector import MockInspector
    client.app.state.gate.inspector = MockInspector("FAIL", delay_s=0.05)
    frame = cv2.imencode(".jpg", np.full((60, 80, 3), 128, np.uint8))[1].tobytes()
    assert client.post("/api/camera/frame", content=b"not an image").status_code == 400
    assert client.post("/api/camera/frame", content=frame).json()["ok"]
    assert client.get("/api/camera/frame.jpg").status_code == 200
    r = client.post("/api/inspection/start", json={"rule": "Reject items with scratches"}).json()
    assert r["ok"] and r["skill"] == "porta_in_ispezione"
    r = client.post("/api/text-command", json={"text": "sì, procedi"}).json()
    assert r["result"]["ok"], r
    end = time.time() + 5
    st = {}
    while time.time() < end:
        client.post("/api/camera/frame", content=frame)
        st = client.get("/api/status").json()
        if st["pending"] and st["pending"]["skill"] == "smista":
            break
        time.sleep(0.05)
    assert st["pending"]["skill"] == "smista" and st["inspection"]["last"]["source"] == "mock"
    assert client.get("/api/inspection/last.jpg").status_code == 200
    r = client.post("/api/text-command", json={"text": "yes"}).json()
    assert r["result"]["ok"] and wait_gate(client, "IDLE")
    assert client.post("/api/world/part-ready").json()["ok"]
