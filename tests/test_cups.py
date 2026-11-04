"""Coloured cups -> zone -> `indica` proposal (still confirmed by the operator)."""

import cv2
import numpy as np

from app.safety.gate import GateState
from app.vision.camera import CameraHub
from app.vision.cups import colour_of, find_cups
from app.vision.inspector import MockInspector

from .conftest import say, wait_state

ZONES = ["sinistra", "centro", "destra"]


def table(*cups: tuple[str, int]) -> np.ndarray:
    """cups: (colour, x centre) on a grey table, 960x540."""
    img = np.full((540, 960, 3), (95, 100, 105), np.uint8)
    bgr = {"red": (30, 30, 210), "blue": (200, 90, 20), "green": (50, 170, 40), "yellow": (30, 210, 230)}
    for colour, x in cups:
        cv2.ellipse(img, (x, 300), (45, 30), 0, 0, 360, bgr[colour], -1)
        cv2.rectangle(img, (x - 40, 300), (x + 40, 380), bgr[colour], -1)
    return img


def jpeg(img):
    return cv2.imencode(".jpg", img)[1].tobytes()


def test_find_cups_zones_and_colours():
    cups = find_cups(table(("red", 150), ("blue", 480), ("yellow", 800)), ZONES, {})
    assert [(c.colour, c.zone) for c in cups] == [("red", "sinistra"), ("blue", "centro"), ("yellow", "destra")]
    assert find_cups(np.full((540, 960, 3), 100, np.uint8), ZONES, {}) == []


def test_mirrored_camera_and_roi():
    cfg = {"image_zone_order": ["destra", "centro", "sinistra"]}
    assert find_cups(table(("red", 150)), ZONES, cfg)[0].zone == "destra"
    assert find_cups(table(("red", 150)), ZONES, {"roi": [0.5, 0.0, 1.0, 1.0]}) == []


def test_colour_words():
    assert colour_of("indica il bicchiere rosso") == "red"
    assert colour_of("指一下蓝色的纸杯") == "blue"
    assert colour_of("zeig auf den grünen Becher") == "green"
    assert colour_of("red or blue?") is None and colour_of("the cup") is None


async def _gate_with(gate, img):
    cam = CameraHub(gate.s)
    gate.attach_vision(cam, MockInspector())
    cam.push(jpeg(img))
    return cam


async def test_point_at_cup_proposes_indica_and_needs_yes(gate):
    await _gate_with(gate, table(("red", 150), ("blue", 480)))
    gate.s.lang = "zh"
    r = gate.point_at_cup("blue")
    assert r["ok"] and r["skill"] == "indica" and r["parametri"] == {"posizione": "centro"}
    assert r["frase_conferma"].startswith("我看到蓝色的纸杯在中间区域")
    assert gate.state == GateState.PENDING_CONFIRMATION
    gate.mark_question_asked(r["action_id"])
    await say(gate, "是的")
    assert (await gate.confirm(r["action_id"]))["ok"]
    assert await wait_state(gate, "IDLE") and gate.world.known_pose == "centro_sopra"


async def test_point_at_cup_missing_ambiguous_no_camera(gate):
    r = gate.point_at_cup("red")
    assert r["esito"] == "telecamera_non_disponibile"
    await _gate_with(gate, table(("green", 150), ("green", 800), ("red", 480)))
    r = gate.point_at_cup("blue")
    assert r["esito"] == "oggetto_non_trovato" and "red (centro)" in r["visti"]
    r = gate.point_at_cup("green")
    assert r["esito"] == "richiesta_ambigua" and r["opzioni_valide"] == ["sinistra", "destra"]
    assert gate.point_at_cup("pink")["esito"] == "richiesta_ambigua"
    assert gate.pending is None


async def test_text_mode_cup(gate):
    from app.conversation.text_mode import TextConversation
    await _gate_with(gate, table(("yellow", 800)))
    out = await TextConversation(gate).handle("point at the yellow cup")
    assert out["result"]["parametri"] == {"posizione": "destra"} and gate.pending.question_asked_at is not None
