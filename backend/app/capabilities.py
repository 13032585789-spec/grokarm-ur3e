"""What this station can do right now. Read from live status, never invented by the model."""

from __future__ import annotations

from typing import Any

from .safety.gate import Gate


def describe(gate: Gate) -> dict[str, Any]:
    st = gate.status()
    robot = st.get("robot") or {}
    cam = st.get("camera") or {}
    frame_age = (cam.get("frame") or {}).get("age_s")
    fresh = frame_age is not None and frame_age <= float((gate.s.robot.get("cups") or {}).get("max_frame_age_s", 2.0))
    poses = {name: bool((pose or {}).get("verificata_reale")) for name, pose in gate.s.poses.items()}
    return {
        "connesso": bool(robot.get("connected")),
        "sicurezza": robot.get("safety"),
        "modo": gate.s.mode,
        "pinza": gate.s.gripper_on,
        "anello": bool((gate.s.robot.get("gripper") or {}).get("enabled")),
        "camera_fresca": fresh,
        "pose_registrate": sorted(name for name, ok in poses.items() if ok),
        "puo": ["指区域", "指杯子", "从一个区域指到另一个区域", "按厘米移动", "转关节", "去 home 或等待姿势"]
               + (["用半圆环托起杯子", "放回杯子"] if (gate.s.robot.get("gripper") or {}).get("enabled") else []),
    }


def answer(gate: Gate) -> str:
    info = describe(gate)
    lang = gate.s.lang or "it"
    link = "已连接" if info["connesso"] else "没连接"
    if lang == "zh":
        cam = "相机画面是新的" if info["camera_fresca"] else "现在没有新的相机画面"
        grip = ("装着半圆环夹爪，可以把杯子托起来再放回" if info["anello"]
                else "夹爪开关开着，但没有夹爪驱动，所以不会抓" if info["pinza"] else "没有夹爪，用手腕指")
        recorded = "、".join(info["pose_registrate"]) or "没有在这台手臂上录过的姿势"
        return (f"现在手臂{link}。{cam}。{grip}。这台机器录过的姿势：{recorded}。"
                "我可以指向一个区域或杯子，从一边指到另一边，按你说的厘米移动，转一个关节，或者去初始位置和等待位置。"
                "够不到，或者路不安全，就不会动。")
    if lang == "en":
        cam = "the camera frame is fresh" if info["camera_fresca"] else "there is no fresh camera frame"
        grip = ("the semicircle gripper is mounted: I can lift a cup and put it back" if info["anello"]
                else "the gripper switch is on, but no gripper driver is connected" if info["pinza"]
                else "there is no gripper; the wrist points")
        return (f"The arm is {'connected' if info['connesso'] else 'not connected'}. {cam}. {grip}. "
                "I can point at a zone or a cup, point from one zone to another, move by the centimetres you say, "
                "turn one joint, or go to home and the waiting pose. An unreachable or unsafe path does not move.")
    cam = "la telecamera ha un fotogramma recente" if info["camera_fresca"] else "non ho un fotogramma recente"
    grip = ("c'è la pinza a semicerchio: posso sollevare un bicchiere e rimetterlo giù" if info["anello"]
            else "l'interruttore pinza è acceso, ma non c'è un driver" if info["pinza"] else "non c'è una pinza: punto col polso")
    return (f"Il braccio è {'connesso' if info['connesso'] else 'non connesso'}. {cam}. {grip}. "
            "Posso indicare una zona o un bicchiere, indicare da una zona a un'altra, spostare di centimetri, "
            "ruotare un giunto, o andare a home e in attesa. Una traiettoria irraggiungibile o non sicura non parte.")
