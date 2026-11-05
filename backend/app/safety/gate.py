"""Deterministic safety gate.

    IDLE ──propose──▶ PENDING_CONFIRMATION ──confirm (validated)──▶ EXECUTING ──result──▶ IDLE
      ▲                     │ cancel / expiry / voice loss                │ unknown/failed ─▶ FAULT
      └─────────────────────┘                                             │
    any state ──STOP──▶ STOPPED      STOPPED/FAULT ──operator reset (robot verified)──▶ IDLE

Grok (or the text-mode rules) may only *propose* and *ask* to confirm.
Authorisation is decided here from the operator's own transcript.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import threading
import time

import numpy as np
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from ..config import Settings
from ..monitoring.events import EventBus, History, Metrics, log_event
from ..robot.base import COMPLETED, FAILED, NOT_STARTED, STOPPED, UNKNOWN, ExecutionResult, RobotAdapter, RobotStatus
from ..skills.amounts import amounts_in_order, angle_deg, distance_cm, is_repeat, length_cm
from ..skills.cartesian import DIRECTIONS, JOINTS, Planner, canon_direction, canon_joint, canon_side
from ..skills.registry import Registry, SkillError, ValidatedAction
from ..skills.world import WorldModel, joints_close
from ..vision.inspector import FAIL, PASS, UNSURE, clean_rule
from ..vision.cups import ALL_COLOURS, CupFinder, colour_of
from ..vision.marker import MarkerFitError, detect, pairs_for_plane
from ..vision.table_calib import CalibrationError, TableCalibration
from ..vision.texts import t as tr
from ..vision.texts import word
from . import phrases

log = logging.getLogger("voce.gate")


class GateState(str, Enum):
    IDLE = "IDLE"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    EXECUTING = "EXECUTING"
    STOPPED = "STOPPED"
    FAULT = "FAULT"


@dataclass
class Utterance:
    id: int
    t: float                      # monotonic time the operator's turn was committed
    text: str | None = None       # transcript (may arrive slightly after the commit)
    source: str = "voice"         # voice | text
    used_for: str | None = None   # action id it confirmed (one-time)
    done: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass
class PendingAction:
    id: str
    action: ValidatedAction
    created: float
    source: str
    question_asked_at: float | None = None
    question_after_utt: int = 0          # utterance id current when the question was asked; the yes must be a later turn
    used: bool = False
    plan_id: str | None = None
    step_index: int = 0
    step_total: int = 1
    remaining: list[dict[str, Any]] = field(default_factory=list)   # raw later steps (re-validated each time)

    def public(self, ttl: float, now: float) -> dict[str, Any]:
        return {"id": self.id, **self.action.public(), "expires_in_s": max(0.0, round(ttl - (now - self.created), 1)),
                "ttl_s": ttl, "question_asked": self.question_asked_at is not None, "source": self.source,
                "plan_id": self.plan_id, "step": self.step_index + 1, "steps": self.step_total}


@dataclass
class InspectionState:
    rule: str = ""
    running: bool = False
    last: dict[str, Any] | None = None
    last_jpeg: bytes | None = None
    counts: dict[str, int] = field(default_factory=lambda: {PASS: 0, FAIL: 0, UNSURE: 0})

    def public(self) -> dict[str, Any]:
        return {"rule": self.rule, "running": self.running, "last": self.last, "counts": dict(self.counts),
                "has_image": self.last_jpeg is not None}


def _err(code: str, msg: str, **kw: Any) -> dict[str, Any]:
    return {"ok": False, "esito": code, "messaggio": msg, **kw}


class Gate:
    STATUS_POLL_S = 0.5

    def __init__(self, settings: Settings, registry: Registry, adapter: RobotAdapter, bus: EventBus,
                 metrics: Metrics | None = None, history: History | None = None,
                 *, clock: Callable[[], float] = time.monotonic) -> None:
        self.s = settings
        self.reg = registry
        self.robot = adapter
        self.bus = bus
        self.metrics = metrics or Metrics(path=None)
        self.history = history or History()
        self.clock = clock
        self.state = GateState.IDLE
        self.pending: PendingAction | None = None
        self.world = WorldModel.initial(settings.zones, settings.robot["workspace"].get("trays_assumed_at", []))
        self.robot_status: RobotStatus = RobotStatus(connected=False, moving=False, detail="non ancora interrogato")
        self.last_result: ExecutionResult | None = None
        self.last_stop: dict[str, Any] | None = None
        self.fault_reason: str | None = None
        self.stop_on_voice_loss = bool(settings.robot["safety"].get("stop_on_voice_loss", True))
        self._utt_ids = itertools.count(1)
        self._act_ids = itertools.count(1)
        self._plan_ids = itertools.count(1)
        self.utterance: Utterance | None = None
        self._exec_task: asyncio.Task | None = None
        self._cancel: threading.Event | None = None
        self._exec_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="robot-exec")
        self._io_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="robot-io")
        self._bg: list[asyncio.Task] = []
        self._report_cbs: list[Callable[[dict[str, Any]], Any]] = []
        self.camera: Any = None
        self.inspector: Any = None
        self.inspection = InspectionState()
        self._inspect_task: asyncio.Task | None = None
        self.planner = Planner(settings)
        self.table_cal = TableCalibration.load(settings.data_dir / "table_calibration.json")
        self._last_amount: dict[str, float] = {}
        self._calib_corners: list[dict[str, Any]] | None = None
        self._marker: dict[str, dict[str, Any] | None] = {"center": None, "axis": None}

    def attach_vision(self, camera: Any, inspector: Any) -> None:
        self.camera, self.inspector = camera, inspector
        self.cups = CupFinder(self.s.zones, dict(self.s.robot.get("cups") or {}),
                              (self.s.inspection or {}).get("labels"))

    def scan_cups(self) -> dict[str, Any]:
        """Read-only: which coloured cups the camera sees, and in which zone."""
        if self.camera is None:
            return _err("telecamera_non_disponibile", "Telecamera non disponibile.")
        frame = self.camera.fresh(float((self.s.robot.get("cups") or {}).get("max_frame_age_s", 2.0)))
        if frame is None:
            return _err("telecamera_non_disponibile", "Nessuna immagine recente dalla telecamera.")
        res = self.cups.scan(frame)
        layout, cups = self._cup_layout(res.get("cups") or [], frame)
        res = {**res, "cups": cups, "layout": layout}
        self.bus.publish("cups", **{k: v for k, v in res.items() if k != "cups"})
        return {"ok": True, **res}

    def cups_background(self, *, clear: bool = False) -> dict[str, Any]:
        """Photo of the empty table: enables detection of cups of any colour (white, grey, black)."""
        if self.camera is None:
            return _err("telecamera_non_disponibile", "Telecamera non disponibile.")
        if clear:
            self.cups.clear_background()
            return {"ok": True, "detector": self.cups.detector}
        frame = self.camera.fresh(float((self.s.robot.get("cups") or {}).get("max_frame_age_s", 2.0)))
        if frame is None:
            return _err("telecamera_non_disponibile", "Nessuna immagine recente dalla telecamera.")
        return {**self.cups.capture_background(frame), "detector": self.cups.detector}

    async def point_at_cup(self, colour: Any, *, source: str = "grok") -> dict[str, Any]:
        """Find the cup of that colour in the camera image and propose `indica` on its zone (needs confirmation)."""
        b = self._blocked()
        if b:
            return b
        c = str(colour or "").strip().lower()
        c = "grey" if c == "gray" else c
        c = c if c in ALL_COLOURS else colour_of(c)
        if c is None:
            return _err("richiesta_ambigua", "Di che colore è il bicchiere?", param="colore", opzioni_valide=ALL_COLOURS)
        scan = self.scan_cups()
        if not scan.get("ok"):
            return scan
        seen = scan["cups"]
        detector = scan.get("detector")
        if not any(x["colore"] == c for x in seen) and self.s.xai_api_key and \
                (self.s.robot.get("cups") or {}).get("grok_fallback", True):
            frame = self.camera.store.latest()
            try:
                seen = await self._io(self.cups.grok_lookup, frame, self.s.xai_api_key, self.s.xai_vision_model,
                                      self.s.xai_base_url, timeout=15)
                detector = "grok"
            except Exception as e:
                log_event(log, "grok cup lookup failed", error=str(e))
            b = self._blocked()
            if b:
                return b
        zones = list(dict.fromkeys(x["zona"] for x in seen if x["colore"] == c))
        if not zones:
            return _err("oggetto_non_trovato", f"Non vedo nessun bicchiere {c}.",
                        visti=[f"{x['colore']} ({x['zona']})" for x in seen])
        if len(zones) > 1:
            return _err("richiesta_ambigua", f"Vedo bicchieri {c} in più zone: quale?", param="posizione",
                        opzioni_valide=zones)
        res = self.propose("indica", {"posizione": zones[0]}, source=source)
        if res.get("ok") and self.pending is not None:
            lang = self.s.lang
            self.pending.action.conferma = tr("cup_question", lang, colour=word("colour", c, lang),
                                              zone=word("zone", zones[0], lang))
            res["frase_conferma"] = self.pending.action.conferma
            res["bicchiere"] = {"colore": c, "zona": zones[0], "rilevatore": detector}
            self.publish_state()
        return res

    # ===================================================== computed motions ===
    async def _operator_text(self) -> str:
        u = self.utterance
        if u is None or u.used_for:
            return ""
        if u.text is None:
            try:
                await asyncio.wait_for(u.done.wait(), 2.5)
            except asyncio.TimeoutError:
                return ""
        return u.text or ""

    async def _operator_amount(self, kind: str) -> float | None:
        """The number in the operator's latest (unused) turn: never a value chosen by the model."""
        text = await self._operator_text()
        if not text and (self.utterance is None or self.utterance.used_for):
            return None
        v = distance_cm(text) if kind == "cm" else angle_deg(text)
        if v is None and is_repeat(text):
            v = self._last_amount.get(kind)
        return v

    async def _joints_now(self) -> list[float] | dict[str, Any]:
        st = await self.refresh_robot()
        if not st.connected or not st.joints:
            return _err("robot_non_disponibile", "Posizione attuale del robot non disponibile.")
        if st.moving:
            return _err("robot_in_movimento", "Il robot si sta muovendo: attendi che sia fermo.")
        return list(st.joints)

    def _propose_computed(self, skill: str, params: dict[str, str], plan: Any, q: list[float], conferma: str,
                          risultato: str, source: str, **extra: Any) -> dict[str, Any]:
        act = ValidatedAction(skill=skill, params=params, motion=plan.motion, timeout_s=plan.timeout_s,
                              conferma=conferma, risultato=risultato, strumento="punta",
                              extra={"start_joints": [round(x, 5) for x in q], **plan.info, **extra})
        res = self._set_pending(act, source)
        res["dettagli"] = plan.info
        return res

    async def propose_move(self, direction: Any, *, source: str = "grok") -> dict[str, Any]:
        """'3 cm a sinistra': straight move of the tip; the distance comes from the operator's words."""
        b = self._blocked()
        if b:
            return b
        d = canon_direction(direction)
        if d is None:
            return _err("richiesta_ambigua", "In che direzione?", param="direzione", opzioni_valide=DIRECTIONS)
        lang = self.s.lang
        cm = await self._operator_amount("cm")
        if cm is None:
            return _err("richiesta_ambigua", tr("how_much_cm", lang, max=f"{self.planner.max_cm:g}"), param="quantita")
        q = await self._joints_now()
        if isinstance(q, dict):
            return q
        b = self._blocked()
        if b:
            return b
        try:
            plan = self.planner.translate(q, d, cm, self.table_cal if self.table_cal.points else None)
        except SkillError as e:
            self.bus.publish("proposal_rejected", skill="sposta", params={"direzione": d, "cm": cm}, result=e.to_dict())
            return e.to_dict()
        self._last_amount["cm"] = cm
        amt = f"{round(cm, 1):g}"
        return self._propose_computed("sposta", {"direzione": d, "cm": amt}, plan, q,
                                      tr("move_question", lang, amount=amt, dir=word("dir", d, lang)),
                                      f"Punta spostata di {amt} cm verso {d}.", source)

    async def propose_rotate(self, joint: Any, side: Any, *, source: str = "grok") -> dict[str, Any]:
        """'ruota la base di 30 gradi a sinistra': one joint, the angle comes from the operator's words."""
        b = self._blocked()
        if b:
            return b
        j = canon_joint(joint)
        if j is None:
            return _err("richiesta_ambigua", "Quale giunto?", param="giunto", opzioni_valide=JOINTS)
        sd = canon_side(side)
        if sd is None:
            return _err("richiesta_ambigua", "In che verso?", param="verso",
                        opzioni_valide=["piu", "meno"] + list(((self.s.robot.get("relative") or {})
                                                               .get("joint_sides") or {}).get(j) or {}))
        lang = self.s.lang
        said = await self._operator_text()
        # "肘关节向上十公分" names a joint but states a length: that moves the tip, it does not rotate 10 degrees.
        if said and length_cm(said) is not None:
            if sd in ("sinistra", "destra", "avanti", "indietro", "su", "giu"):
                return await self.propose_move(sd, source=source)
            return _err("richiesta_ambigua", tr("cm_not_degrees", lang))
        deg = await self._operator_amount("deg")
        if deg is None:
            return _err("richiesta_ambigua", tr("how_much_deg", lang, max=f"{self.planner.max_deg:g}"), param="quantita")
        q = await self._joints_now()
        if isinstance(q, dict):
            return q
        b = self._blocked()
        if b:
            return b
        try:
            plan = self.planner.rotate(q, j, sd, deg, self.table_cal if self.table_cal.points else None)
        except SkillError as e:
            self.bus.publish("proposal_rejected", skill="ruota", params={"giunto": j, "verso": sd}, result=e.to_dict())
            return e.to_dict()
        self._last_amount["deg"] = deg
        amt = f"{round(deg, 1):g}"
        return self._propose_computed("ruota", {"giunto": j, "verso": sd, "gradi": amt}, plan, q,
                                      tr("rotate_question", lang, joint=word("joint", j, lang), amount=amt,
                                         dir=word("dir", sd, lang)),
                                      f"Giunto {j} ruotato di {amt} gradi ({sd}).", source)

    async def propose_batch(self, steps: list[dict[str, Any]], *, source: str = "grok") -> dict[str, Any]:
        """Several tip moves and joint turns from one sentence. One yes runs them all, in order."""
        b = self._blocked()
        if b:
            return b
        if not steps or len(steps) > 5:
            return _err("sequenza_non_valida", "La sequenza deve avere da 2 a 5 passi.")
        parsed: list[tuple[str, str, str | None]] = []
        for st in steps:
            kind = str(st.get("kind") or st.get("tipo") or "")
            if kind in ("move", "sposta"):
                d = canon_direction(st.get("direzione") or st.get("direction"))
                if d is None:
                    return _err("richiesta_ambigua", "In che direzione?", param="direzione", opzioni_valide=DIRECTIONS)
                parsed.append(("move", d, None))
            elif kind in ("rotate", "ruota"):
                j = canon_joint(st.get("giunto") or st.get("joint"))
                sd = canon_side(st.get("verso") or st.get("side"))
                if j is None or sd is None:
                    return _err("richiesta_ambigua", "Quale giunto e in che verso?", param="giunto", opzioni_valide=JOINTS)
                parsed.append(("rotate", j, sd))
            else:
                return _err("sequenza_non_valida", "Ogni passo è uno spostamento della punta o la rotazione di un giunto.")
        said = await self._operator_text()
        amounts = amounts_in_order(said)
        lang = self.s.lang
        if len(amounts) != len(parsed) or any(
                (kind == "move" and unit != "cm") or (kind == "rotate" and unit != "deg")
                for (kind, _, _), (unit, _) in zip(parsed, amounts)):
            return _err("richiesta_ambigua", tr("batch_amounts", lang, n=len(parsed)), param="quantita")
        q = await self._joints_now()
        if isinstance(q, dict):
            return q
        b = self._blocked()
        if b:
            return b
        q0 = list(q)
        motion: list = []
        timeout = 0.0
        lines: list[str] = []
        cal = self.table_cal if self.table_cal.points else None
        try:
            for (kind, target, side), (_, amt) in zip(parsed, amounts):
                shown = f"{round(amt, 1):g}"
                if kind == "move":
                    plan = self.planner.translate(q, target, amt, cal)
                    lines.append(tr("step_move", lang, amount=shown, dir=word("dir", target, lang)))
                else:
                    plan = self.planner.rotate(q, target, side, amt, cal)
                    lines.append(tr("step_rotate", lang, joint=word("joint", target, lang), amount=shown,
                                    dir=word("dir", side or "", lang)))
                motion.extend(plan.motion)
                timeout += plan.timeout_s
                q = list(plan.motion[-1].joints)
        except SkillError as e:
            self.bus.publish("proposal_rejected", skill="sequenza", params={"passi": len(parsed)}, result=e.to_dict())
            return e.to_dict()
        phrase = tr("batch_question", lang, n=len(parsed), steps="；".join(f"{i + 1}. {s}" for i, s in enumerate(lines)))
        plan = type("Batch", (), {"motion": motion, "timeout_s": timeout, "info": {}})()
        return self._propose_computed("sequenza", {"passi": str(len(parsed))}, plan, q0, phrase,
                                      f"Sequenza di {len(parsed)} movimenti completata.", source)

    async def touch_cup(self, colour: Any, *, zone: Any = None, source: str = "grok") -> dict[str, Any]:
        """Find the cup in the calibrated camera image and propose: above it, slow descent to the rim, back up."""
        b = self._blocked()
        if b:
            return b
        c = str(colour or "").strip().lower()
        c = "grey" if c == "gray" else c
        c = c if c in ALL_COLOURS else colour_of(c)
        if c is None:
            return _err("richiesta_ambigua", "Di che colore è il bicchiere?", param="colore", opzioni_valide=ALL_COLOURS)
        if not self.table_cal.ready:
            return _err("non_calibrato", tr("marker_need", self.s.lang))
        scan = self.scan_cups()
        if not scan.get("ok"):
            return scan
        frame = self.camera.store.latest()
        if frame is not None and self.table_cal.frame_size and tuple(frame.size) != tuple(self.table_cal.frame_size):
            return _err("non_calibrato", "La risoluzione della telecamera è cambiata dalla calibrazione: ricalibra.")
        seen = [x for x in scan["cups"] if x["colore"] == c]
        z = self.reg.normalize("zona", zone) if zone else None
        if z:
            seen = [x for x in seen if x["zona"] == z]
        if not seen:
            hint = "" if scan.get("detector") == "background" else \
                " Per bicchieri bianchi, grigi o neri scatta prima la foto del tavolo vuoto."
            return _err("oggetto_non_trovato", f"Non vedo nessun bicchiere {c}.{hint}",
                        visti=[f"{x['colore']} ({x['zona']})" for x in scan["cups"]])
        if len(seen) > 1:
            where = "；".join(x.get("posto") or x["zona"] for x in seen)
            return _err("richiesta_ambigua", tr("cups_same_colour", self.s.lang, n=len(seen),
                                                colour=word("colour", c, self.s.lang), where=where),
                        param="posizione", opzioni_valide=sorted({x["zona"] for x in seen}))
        cup = seen[0]
        if (self.s.robot.get("touch") or {}).get("cup_point") == "bottom":
            x0, y0, w, h = cup["bbox"]
            u, v = x0 + w / 2, y0 + h
        else:
            u, v = cup["px"]
        xy = self.table_cal.to_xy(u, v)
        height = self._cup_height_m(frame, cup)
        q = await self._joints_now()
        if isinstance(q, dict):
            return q
        b = self._blocked()
        if b:
            return b
        try:
            plan = self.planner.touch(q, xy, self.table_cal, height_m=height)
        except SkillError as e:
            if str(e) == "fuori_dal_tavolo":
                return _err(e.code, tr("outside_table", self.s.lang))
            self.bus.publish("proposal_rejected", skill="tocca", params={"colore": c}, result=e.to_dict())
            return e.to_dict()
        lang = self.s.lang
        x_mm, y_mm = plan.info["xy_mm"]
        res = self._propose_computed("tocca", {"colore": c}, plan, q,
                                     tr("touch_question", lang, colour=word("colour", c, lang), x=f"{x_mm:.0f}",
                                        y=f"{y_mm:.0f}"),
                                     f"Bicchiere {c} toccato a X {x_mm:.0f} mm, Y {y_mm:.0f} mm.", source,
                                     px=[round(u), round(v)])
        if res.get("ok"):
            res["bicchiere"] = {"colore": c, "px": [round(u), round(v)], "xy_mm": [x_mm, y_mm],
                                "rilevatore": scan.get("detector")}
        return res

    # ======================================================== calibration ===
    async def calibration_add(self, u: Any, v: Any) -> dict[str, Any]:
        """Record one calibration point: pixel clicked by the operator + tip position measured on the robot NOW."""
        if self.state == GateState.EXECUTING:
            return _err("occupato", "Il braccio si sta muovendo.")
        if self.camera is None:
            return _err("telecamera_non_disponibile", "Telecamera non disponibile.")
        frame = self.camera.fresh(2.0)
        if frame is None:
            return _err("telecamera_non_disponibile", "Nessuna immagine recente dalla telecamera.")
        try:
            u, v = float(u), float(v)
        except (TypeError, ValueError):
            return _err("punto_non_valido", "Coordinate del punto non valide.")
        w, h = frame.size
        if not (0 <= u < w and 0 <= v < h):
            return _err("punto_non_valido", "Il punto è fuori dall'immagine.")
        q = await self._joints_now()
        if isinstance(q, dict):
            return q
        try:
            self.table_cal.add((u, v), (w, h), self.planner.kin.fk(q), q, self.s.mode)
        except CalibrationError as e:
            return _err("calibrazione_rifiutata", str(e))
        self.history.add(kind="calibrazione", points=len(self.table_cal.points))
        self.publish_state()
        return {"ok": True, **self.table_cal.public()}

    _CORNER_MSG = {"punta_non_verticale": "tip_not_vertical", "angolo_lontano": "corner_too_far",
                   "area_troppo_piccola": "area_too_small"}

    def _corner_error(self, err: SkillError) -> dict[str, Any]:
        key = self._CORNER_MSG.get(str(err))
        if key:
            return _err(err.code, tr(key, self.s.lang))
        return err.to_dict()

    async def calibration_corners(self) -> dict[str, Any]:
        """Rectangle centred on the tip now. Coordinates stay here; the UI only receives millimetre offsets."""
        if self.state == GateState.EXECUTING:
            return _err("occupato", "Il braccio si sta muovendo.")
        q = await self._joints_now()
        if isinstance(q, dict):
            return q
        try:
            corners = self.planner.table_corners(q)
        except SkillError as e:
            return self._corner_error(e)
        self._calib_corners = corners
        return {"ok": True, "corners": [{"i": c["i"], "name": c["name"], "dx_mm": c["dx_mm"], "dy_mm": c["dy_mm"],
                                         "label": word("corner_name", c["name"], self.s.lang)} for c in corners]}

    async def propose_calib_corner(self, index: Any, *, source: str = "ui") -> dict[str, Any]:
        b = self._blocked()
        if b:
            return b
        try:
            i = int(index)
        except (TypeError, ValueError):
            i = -1
        corners = self._calib_corners or []
        if not 0 <= i < len(corners):
            return _err("richiesta_ambigua", tr("corners_first", self.s.lang))
        q = await self._joints_now()
        if isinstance(q, dict):
            return q
        b = self._blocked()
        if b:
            return b
        c = corners[i]
        try:
            plan = self.planner.goto_table_point(q, c["xyz"], c["rot"])
        except SkillError as e:
            return self._corner_error(e)
        lang = self.s.lang
        info = plan.info
        phrase = tr("corner_question", lang, n=i + 1, name=word("corner_name", c["name"], lang),
                    dx=f"{info['dx_mm']:g}", dy=f"{info['dy_mm']:g}", lift=f"{info['lift_mm']:g}")
        res = self._propose_computed("angolo_calibrazione", {"angolo": str(i + 1)}, plan, q, phrase,
                                     f"Punta all'angolo {i + 1}. Clicca la punta nell'immagine.", source)
        if res.get("ok") and source == "ui":
            self.mark_question_asked(res["action_id"])
        return res

    async def confirm_from_button(self, action_id: str | None = None) -> dict[str, Any]:
        """The operator pressed the on-screen confirm. That sentence is their own, not the model's."""
        pa = self.pending
        if pa is None:
            return _err("nessuna_azione_in_attesa", tr("corners_first", self.s.lang))
        if action_id and action_id != pa.id:
            return _err("azione_diversa", "L'azione è cambiata: chiedi di nuovo lo spostamento.")
        if pa.question_asked_at is None:
            self.mark_question_asked(pa.id)
        self.note_transcript("是的", source="button")
        return await self.confirm(pa.id, source="button")

    async def go_calib_corner(self, index: Any) -> dict[str, Any]:
        """One tap on a corner: the operator asked for that move, so it is proposed and confirmed together."""
        proposed = await self.propose_calib_corner(index, source="ui")
        if not proposed.get("ok"):
            return proposed
        return await self.confirm_from_button(proposed["action_id"])

    def _cup_layout(self, cups: list[dict[str, Any]], frame: Any) -> tuple[str, list[dict[str, Any]]]:
        """Left-to-right and, once the table is calibrated, front-to-back. No coordinates leave this method."""
        lang = self.s.lang
        if not cups:
            return "", []
        cal = self.table_cal
        use_table = bool(cal.ready and cal.frame_size and tuple(frame.size) == tuple(cal.frame_size))
        rows = []
        for c in cups:
            if use_table:
                x, y = cal.to_xy(float(c["px"][0]), float(c["px"][1]))
            else:
                x, y = 0.0, float(c["px"][0])
            rows.append((c, x, y))
        by_left = sorted(rows, key=lambda row: row[2])
        by_front = sorted(rows, key=lambda row: row[1]) if use_table else []
        left_rank = {id(c): i + 1 for i, (c, _x, _y) in enumerate(by_left)}
        front_rank = {id(c): i + 1 for i, (c, _x, _y) in enumerate(by_front)}
        out = []
        for c, _x, _y in rows:
            if use_table:
                posto = tr("cup_place", lang, left=left_rank[id(c)], front=front_rank[id(c)], n=len(rows))
            else:
                posto = tr("cup_place_image", lang, left=left_rank[id(c)], n=len(rows))
            out.append({**c, "posto": posto})
        names = "、".join(word("colour", c["colore"], lang) for c, _x, _y in by_left)
        if use_table:
            front_names = "、".join(word("colour", c["colore"], lang) for c, _x, _y in by_front)
            layout = tr("cup_layout", lang, lr=names, fb=front_names)
        else:
            layout = tr("cup_layout_image", lang, lr=names)
        return layout, out

    def calibration_edit(self, action: str) -> dict[str, Any]:
        if action == "undo":
            self.table_cal.undo()
        elif action == "clear":
            self.table_cal.clear()
            self._marker = {"center": None, "axis": None}
        self.publish_state()
        return {"ok": True, **self.table_cal.public(), "marker": self.marker_status()}

    def _camera_matrix(self, size: tuple[int, int]) -> np.ndarray | None:
        raw = dict(self.s.robot.get("camera_intrinsics") or {})
        vals = [raw.get("fx"), raw.get("fy"), raw.get("cx"), raw.get("cy")]
        if any(v is None for v in vals):
            return None
        return np.array([[float(vals[0]), 0.0, float(vals[2])],
                         [0.0, float(vals[1]), float(vals[3])],
                         [0.0, 0.0, 1.0]], dtype=np.float64)

    def _cup_height_m(self, frame, cup: dict[str, Any]) -> float | None:
        """Rim height above the table. None keeps the fixed cup height: the lens is not measured yet."""
        if frame is None or not cup.get("bbox"):
            return None
        matrix = self._camera_matrix(frame.size)
        if matrix is None:
            return None
        from ..vision.height import HeightError, pose_from_marker, standing_xyz
        found = detect(frame.image)
        if found is None:
            return None
        x0, y0, w, h = cup["bbox"]
        try:
            rvec, tvec = pose_from_marker(found["corners"], self._marker_size_m(), matrix)
            _x, _y, height = standing_xyz((x0 + w / 2.0, y0 + h), (x0 + w / 2.0, y0), rvec, tvec, matrix)
        except HeightError:
            return None
        return height

    def _marker_size_m(self) -> float:
        return float((self.s.robot.get("marker") or {}).get("size_m", 0.05))

    def marker_status(self) -> dict[str, Any]:
        seen = False
        try:
            frame = self.camera.store.latest() if self.camera is not None else None
            if frame is not None:
                seen = detect(frame.image) is not None
        except Exception:
            log.exception("marker detect")
            seen = False
        return {"seen": seen, "center": self._marker.get("center") is not None,
                "axis": self._marker.get("axis") is not None,
                "size_mm": round(self._marker_size_m() * 1000)}

    async def marker_record(self, which: str) -> dict[str, Any]:
        """Store the tip on the marker centre or on the arrow, then fit the plane when both exist.

        Neither button moves the arm. The operator jogs the tip there on the pendant.
        """
        if which not in ("center", "axis"):
            return _err("punto_non_valido", "Punto del marcatore sconosciuto.")
        if self.state == GateState.EXECUTING:
            return _err("occupato", "Il braccio si sta muovendo.")
        q = await self._joints_now()
        if isinstance(q, dict):
            return q
        T = self.planner.kin.fk(q)
        R = T[:3, :3]
        tilt = float(np.degrees(np.arccos(np.clip(-R[2, 2], -1, 1))))
        if tilt > 20.0:
            return _err("calibrazione_rifiutata", tr("marker_tilt", self.s.lang))
        sample = {"xy": (float(T[0, 3]), float(T[1, 3])), "z": float(T[2, 3]),
                  "rot": R.tolist(), "joints": tuple(float(v) for v in q)}
        other_name = "axis" if which == "center" else "center"
        other = self._marker.get(other_name)
        if other is not None:
            if abs(sample["z"] - float(other["z"])) > 0.015:
                return _err("calibrazione_rifiutata", tr("marker_height", self.s.lang))
            from ..robot.kinematics import angle_between
            if float(np.degrees(angle_between(R, np.array(other["rot"])))) > 5.0:
                return _err("calibrazione_rifiutata", tr("marker_orient", self.s.lang))
        self._marker[which] = sample
        if self._marker.get("center") and self._marker.get("axis"):
            return await self._marker_fit()
        self.publish_state()
        return {"ok": True, **self.table_cal.public(), "marker": self.marker_status()}

    async def _marker_fit(self) -> dict[str, Any]:
        if self.camera is None:
            return _err("telecamera_non_disponibile", tr("no_frame", self.s.lang))
        frame = self.camera.fresh(2.0)
        if frame is None:
            return _err("telecamera_non_disponibile", tr("no_frame", self.s.lang))
        found = detect(frame.image)
        if found is None:
            return _err("marcatore_non_visto", tr("marker_not_seen", self.s.lang))
        center, axis = self._marker["center"], self._marker["axis"]
        try:
            pairs = pairs_for_plane(found["corners"], center["xy"], axis["xy"], self._marker_size_m())
        except MarkerFitError:
            return _err("marcatore_misura", tr("marker_size", self.s.lang, mm=round(self._marker_size_m() * 1000)))
        except CalibrationError as e:
            return _err("calibrazione_rifiutata", str(e))
        self.table_cal.replace_plane(pairs, center["z"], center["rot"], center["joints"], frame.size, self.s.mode)
        if not self.table_cal.ready:
            return _err("calibrazione_rifiutata", self.table_cal.error or tr("marker_need", self.s.lang))
        try:
            cells = self.planner.table_reach(center["joints"], np.array(center["rot"]), float(center["z"]))
        except SkillError as e:
            return self._corner_error(e)
        self.table_cal.set_reach(cells)
        self.history.add(kind="calibrazione", points=len(self.table_cal.points), marker=True)
        self.publish_state()
        if not self.table_cal.ready:
            return _err("calibrazione_rifiutata", self.table_cal.error or tr("marker_need", self.s.lang))
        return {"ok": True, **self.table_cal.public(), "marker": self.marker_status()}

    def calibration_image(self) -> bytes | None:
        """Latest frame with the calibration points (and the calibrated area) drawn on it."""
        import cv2
        import numpy as np
        frame = self.camera.store.latest() if self.camera else None
        if frame is None:
            return None
        img = frame.image.copy()
        cal = self.table_cal
        if cal.ready:
            inv = np.linalg.inv(cal.fit.homography)
            if cal.reachable:
                hull = cv2.convexHull(np.array(cal.reachable, dtype=np.float32) * 1000).reshape(-1, 2).astype(np.float64)
            else:
                hull = cal.fit.workspace_polygon().astype(np.float64)
            px = cv2.perspectiveTransform(hull.reshape(-1, 1, 2), inv).reshape(-1, 2).astype(np.int32)
            cv2.polylines(img, [px], True, (60, 200, 60), 2)
        for i, p in enumerate(cal.points):
            c = (int(p.px[0]), int(p.px[1]))
            cv2.drawMarker(img, c, (0, 0, 255), cv2.MARKER_CROSS, 22, 2)
            cv2.putText(img, str(i + 1), (c[0] + 8, c[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buf.tobytes() if ok else None

    # ================================================================ infra ===
    def _transition(self, new: GateState, reason: str, **data: Any) -> None:
        old = self.state
        self.state = new
        log_event(log, f"{old.value} -> {new.value}: {reason}", old=old.value, new=new.value, reason=reason, **data)
        self.bus.publish("gate", old=old.value, new=new.value, reason=reason)
        self.publish_state()

    def publish_state(self) -> None:
        self.bus.publish("state", **self.status())

    def status(self) -> dict[str, Any]:
        now = self.clock()
        return {"gate": self.state.value,
                "pending": self.pending.public(self.s.ttl_s, now) if self.pending else None,
                "world": self.world.snapshot(), "robot": self.robot_status.to_dict(), "robot_adapter": self.robot.name,
                "mode": self.s.mode, "fault": self.fault_reason, "last_stop": self.last_stop,
                "last_result": self.last_result.to_dict() if self.last_result else None,
                "metrics": self.metrics.summary(), "history": self.history.list()[:30],
                "lang": self.s.lang, "inspection": self.inspection.public(),
                "camera": self.camera.status() if self.camera else None,
                "calibration": {**self.table_cal.public(), "tip_length_measured": self.planner.tip_length_measured}}

    def on_report(self, cb: Callable[[dict[str, Any]], Any]) -> Callable[[], None]:
        self._report_cbs.append(cb)
        return lambda: self._report_cbs.remove(cb) if cb in self._report_cbs else None

    def _report(self, kind: str, text: str, **data: Any) -> None:
        ev = self.bus.publish("report", kind=kind, text=text, **data)
        for cb in list(self._report_cbs):
            try:
                r = cb(ev)
                if asyncio.iscoroutine(r):
                    asyncio.ensure_future(r)
            except Exception:  # pragma: no cover
                log.exception("report callback failed")

    async def _io(self, fn: Callable, *args: Any, timeout: float = 3.0) -> Any:
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(loop.run_in_executor(self._io_pool, fn, *args), timeout)

    async def start(self) -> None:
        """Safe startup: connect, read state, never resume anything."""
        self.pending = None
        try:
            await self._io(self.robot.connect, timeout=float(self.s.robot["connections"].get("connect_timeout_s", 3)) + 1)
        except Exception as e:
            self.robot_status = RobotStatus(connected=False, moving=False, detail=f"connessione fallita: {e}")
            log_event(log, "robot connect failed", error=str(e))
        await self.refresh_robot()
        loop = asyncio.get_running_loop()
        if hasattr(self.robot, "listeners"):
            last = [0.0]

            def on_joints(q: list[float]) -> None:
                now = time.time()
                if now - last[0] >= 0.05:
                    last[0] = now
                    loop.call_soon_threadsafe(lambda: self.bus.publish("joints", joints=[round(x, 4) for x in q]))
            self.robot.listeners.cbs.append(on_joints)
        if hasattr(self.robot, "progress_cb"):
            def on_progress(done: int, total: int, pose: str | None) -> None:
                loop.call_soon_threadsafe(lambda: self.bus.publish("progress", done=done, total=total, pose=pose))
            self.robot.progress_cb = on_progress
        self._bg.append(asyncio.ensure_future(self._poll_loop()))
        self.publish_state()

    async def shutdown(self) -> None:
        """Safe shutdown: stop motion if any, drop pending, disconnect."""
        for t in self._bg:
            t.cancel()
        if self.state == GateState.EXECUTING:
            await self.stop("shutdown")
        self.pending = None
        try:
            await self._io(self.robot.disconnect)
        except Exception:
            pass
        self._exec_pool.shutdown(wait=False, cancel_futures=True)
        self._io_pool.shutdown(wait=False, cancel_futures=True)

    async def refresh_robot(self) -> RobotStatus:
        try:
            st = await self._io(self.robot.status, timeout=2.5)
        except Exception as e:
            st = RobotStatus(connected=False, moving=False, detail=f"stato non disponibile: {e}")
        changed = st.to_dict() != self.robot_status.to_dict()
        self.robot_status = st
        if st.joints and self.state != GateState.EXECUTING:
            self.world.update_joints(st.joints, self.s.poses, float(self.s.robot["motion"]["joint_tolerance_rad"]))
        if changed:
            self.bus.publish("robot", robot=st.to_dict(), world=self.world.snapshot())
        return st

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self.STATUS_POLL_S)
            try:
                self._expire_pending()
                await self.refresh_robot()   # also while EXECUTING (live "moving"); joint bookkeeping waits
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover
                log.exception("poll failed")

    # ========================================================== utterances ===
    def note_turn_committed(self, source: str = "voice") -> Utterance:
        """The operator finished a turn (VAD commit); its transcript may follow."""
        u = Utterance(id=next(self._utt_ids), t=self.clock(), source=source)
        self.utterance = u
        return u

    def note_transcript(self, text: str | None, *, final: bool = True, source: str = "voice") -> bool:
        """Operator transcript. Returns True if it triggered STOP (handled independently of Grok)."""
        stop = phrases.is_stop(text)
        if final:
            u = self.utterance
            if u is None or u.text is not None or u.source != source:
                u = self.note_turn_committed(source)
            u.text = text or ""
            u.done.set()
            self.bus.publish("transcript", role="user", text=text, final=True, source=source)
            self.history.add(kind="utterance", source=source, text=text)
        if stop:
            asyncio.ensure_future(self.stop(f"transcript:{source}", detail=text or ""))
        return stop

    def note_partial(self, text: str | None, *, source: str = "voice") -> bool:
        """Interim transcript: only used to catch STOP as early as possible."""
        if phrases.is_stop(text) and self.state != GateState.STOPPED:
            asyncio.ensure_future(self.stop(f"transcript:{source}", detail=f"(parziale) {text}"))
            return True
        return False

    # ============================================================ proposal ===
    def _blocked(self) -> dict[str, Any] | None:
        if self.state == GateState.STOPPED:
            return _err("sistema_fermo", "Sistema in STOP: serve il ripristino da parte dell'operatore dall'interfaccia.")
        if self.state == GateState.FAULT:
            return _err("guasto", f"Sistema in GUASTO ({self.fault_reason}): serve l'intervento dell'operatore.")
        if self.state == GateState.EXECUTING:
            return _err("occupato", "Il braccio sta eseguendo un movimento: attendi il risultato o di' stop.")
        if self.inspection.running:
            return _err("occupato", "Ispezione visiva in corso: attendi l'esito.")
        return None

    def propose(self, skill: Any, params: dict[str, Any] | None, *, source: str = "grok") -> dict[str, Any]:
        b = self._blocked()
        if b:
            return b
        if skill == "porta_in_ispezione" and not self.inspection.rule:
            return _err("regola_mancante", "Per portare un pezzo in ispezione usa start_inspection con la regola.")
        try:
            act = self.reg.validate(skill, params, self.world)
        except SkillError as e:
            self.bus.publish("proposal_rejected", skill=str(skill), params=params, result=e.to_dict())
            return e.to_dict()
        return self._set_pending(act, source)

    def propose_sequence(self, steps: list[dict[str, Any]], *, source: str = "grok") -> dict[str, Any]:
        """P2: validate a whole sequence (on a simulated world copy). Each movement still needs its own confirmation."""
        b = self._blocked()
        if b:
            return b
        if not steps or len(steps) > 5:
            return _err("sequenza_non_valida", "La sequenza deve avere da 1 a 5 passi.")
        if any(st.get("skill") in ("porta_in_ispezione", "smista") for st in steps):
            return _err("sequenza_non_valida", "L'ispezione e lo smistamento non possono stare in una sequenza.")
        sim = self.world.copy()
        acts: list[ValidatedAction] = []
        for i, st in enumerate(steps):
            try:
                a = self.reg.validate(st.get("skill"), st.get("params") or st.get("parametri"), sim)
            except SkillError as e:
                d = e.to_dict()
                d["passo"] = i + 1
                return d
            sim.apply_effects(a.skill, a.params)
            acts.append(a)
        plan_id = f"S{next(self._plan_ids)}"
        piano = [{"passo": i + 1, "skill": a.skill, "parametri": a.params, "descrizione": a.conferma}
                 for i, a in enumerate(acts)]
        lines = [f"{i + 1}. {a.conferma.rstrip(' ?.？')}" for i, a in enumerate(acts)]
        acts[0].conferma = tr("batch_question", self.s.lang, n=len(acts), steps=" ".join(lines))
        res = self._set_pending(acts[0], source, plan_id=plan_id, step_total=len(acts),
                                remaining=[{"skill": a.skill, "params": a.params} for a in acts[1:]])
        res["piano"] = piano
        res["istruzione"] = ("Leggi frase_conferma: un solo sì dell'operatore esegue TUTTI i passi in ordine. "
                             "Non chiedere conferma per i passi successivi. STOP interrompe il resto.")
        return res

    def _set_pending(self, act: ValidatedAction, source: str, *, plan_id: str | None = None, step_index: int = 0,
                     step_total: int = 1, remaining: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        replaced = self.pending.id if self.pending else None
        pa = PendingAction(id=f"A{next(self._act_ids)}", action=act, created=self.clock(), source=source,
                           plan_id=plan_id, step_index=step_index, step_total=step_total, remaining=remaining or [])
        self.pending = pa
        self._transition(GateState.PENDING_CONFIRMATION, f"proposta {pa.id} {act.skill}",
                         action=pa.id, skill=act.skill, params=act.params, replaced=replaced)
        self.history.add(kind="proposta", action=pa.id, skill=act.skill, params=act.params, source=source)
        return {"ok": True, "esito": "in_attesa_di_conferma", "action_id": pa.id, "skill": act.skill,
                "parametri": act.params, "frase_conferma": act.conferma, "scade_in_s": self.s.ttl_s,
                "istruzione": "Leggi frase_conferma all'operatore e aspetta la sua risposta. Non chiamare confirm finché "
                              "l'operatore non ha risposto sì in un nuovo turno."}

    def mark_question_asked(self, action_id: str | None = None) -> None:
        pa = self.pending
        if pa and pa.question_asked_at is None and (action_id is None or action_id == pa.id):
            pa.question_asked_at = self.clock()
            # The clock on Windows can stay on the same tick for the whole reply, so a later
            # "yes" compares equal in time. The utterance id still orders the turns.
            pa.question_after_utt = self.utterance.id if self.utterance else 0
            log_event(log, "confirmation question asked", action=pa.id)
            self.publish_state()

    def _expire_pending(self) -> bool:
        pa = self.pending
        if pa and self.clock() - pa.created > self.s.ttl_s:
            self.pending = None
            self.history.add(kind="scaduta", action=pa.id, skill=pa.action.skill)
            if self.state == GateState.PENDING_CONFIRMATION:
                self._transition(GateState.IDLE, f"proposta {pa.id} scaduta")
            self._report("scaduta", f"La proposta {pa.id} è scaduta senza conferma. Nessun movimento.")
            return True
        return False

    def cancel(self, *, source: str = "grok") -> dict[str, Any]:
        pa = self.pending
        self.pending = None
        if pa:
            self.history.add(kind="annullata", action=pa.id, skill=pa.action.skill, source=source)
        if self.state == GateState.PENDING_CONFIRMATION:
            self._transition(GateState.IDLE, f"annullata da {source}")
        return {"ok": True, "annullata": pa.id if pa else None}

    # ======================================================== confirmation ===
    async def confirm(self, action_id: str | None, *, source: str = "grok") -> dict[str, Any]:
        t_req = self.clock()
        if self.state in (GateState.STOPPED, GateState.FAULT, GateState.EXECUTING):
            return self._blocked()  # type: ignore[return-value]
        pa = self.pending
        if pa is None:
            return _err("nessuna_azione_in_attesa", "Non c'è nessuna azione in attesa di conferma.")
        if action_id and action_id != pa.id:
            return _err("azione_diversa", f"L'azione in attesa è {pa.id}: l'azione è cambiata, serve una nuova conferma.")
        if pa.used:
            return _err("duplicato", "Conferma già utilizzata: ignorata.")
        if self._expire_pending():
            return _err("scaduta", "La proposta è scaduta. Va riproposta.")
        if pa.question_asked_at is None:
            return _err("domanda_non_posta", "Prima chiedi conferma all'operatore e aspetta la sua risposta.")
        u = self.utterance
        if u is None or u.id <= pa.question_after_utt:
            return _err("nessuna_risposta", "L'operatore non ha ancora risposto alla domanda di conferma.")
        if u.text is None:  # transcript still in flight (it lags the commit by ~0.7 s)
            try:
                await asyncio.wait_for(u.done.wait(), 2.5)
            except asyncio.TimeoutError:
                return _err("trascrizione_mancante", "Trascrizione della risposta non disponibile: chiedi di ripetere.")
        if u.used_for:
            return _err("duplicato", "Questa risposta ha già autorizzato un'azione.")
        verdict = phrases.confirmation_verdict(u.text)
        if verdict != phrases.VALID:
            self.history.add(kind="conferma_rifiutata", action=pa.id, text=u.text, verdict=verdict, source=source)
            self.bus.publish("confirmation_rejected", action=pa.id, text=u.text, verdict=verdict)
            return _err("conferma_non_valida", f"La risposta “{u.text}” non è una conferma esplicita ({verdict}).",
                        verdetto=verdict)
        st = await self.refresh_robot()
        # anything may have happened while awaiting (STOP, new proposal, expiry)
        if self.pending is not pa or self.state != GateState.PENDING_CONFIRMATION or pa.used:
            return _err("stato_cambiato", "Lo stato è cambiato durante la conferma: nessun movimento.")
        if not st.ok_for_motion:
            return _err("robot_non_disponibile", f"Robot non disponibile: {st.detail or st.safety or st.robot_mode}.")
        start = pa.action.extra.get("start_joints")
        if start and not (st.joints and joints_close(st.joints, start,
                                                     float(self.s.robot["motion"]["joint_tolerance_rad"]) * 3)):
            self.pending = None
            self._transition(GateState.IDLE, f"{pa.id}: il robot si è mosso dopo la proposta")
            return _err("stato_cambiato", "Il robot si è mosso dopo la proposta: movimento calcolato annullato, "
                                          "va richiesto di nuovo.")
        # ---- authorised: exactly this action, exactly once
        pa.used = True
        u.used_for = pa.id
        self.metrics.record("confirmation_response_ms", (t_req - pa.question_asked_at) * 1000, action=pa.id)
        self.history.add(kind="confermata", action=pa.id, skill=pa.action.skill, params=pa.action.params, text=u.text)
        self.pending = None
        self._cancel = threading.Event()
        self.world.active_skill = pa.action.skill
        self._transition(GateState.EXECUTING, f"confermata {pa.id} da “{u.text}”", action=pa.id)
        self._exec_task = asyncio.ensure_future(self._execute(pa, self._cancel, t_req))
        return {"ok": True, "esito": "esecuzione_avviata", "action_id": pa.id,
                "istruzione": "Di' solo 'Procedo.' Il risultato reale arriverà in un messaggio [RAPPORTO SISTEMA]."}

    # =========================================================== execution ===
    async def _execute(self, pa: PendingAction, cancel: threading.Event, t_req: float) -> None:
        act = pa.action
        loop = asyncio.get_running_loop()
        timeout = act.timeout_s + float(self.s.robot["safety"].get("execution_timeout_margin_s", 5))
        res: ExecutionResult | None = None
        try:
            res = await asyncio.wait_for(
                loop.run_in_executor(self._exec_pool, self.robot.execute, act.skill, act.params, act.motion, cancel,
                                     act.timeout_s), timeout)
        except asyncio.TimeoutError:
            cancel.set()
            await self._robot_stop("execution timeout")
            self._fault(f"timeout dopo {timeout:.0f}s: esito sconosciuto", pa)
            return
        except Exception as e:
            cancel.set()
            await self._robot_stop("execution exception")
            self._fault(f"errore di esecuzione: {e}", pa)
            return
        finally:
            self.world.active_skill = None

        self.last_result = res
        self.metrics.record("robot_execution_ms", res.duration * 1000, skill=act.skill)
        self.metrics.record("request_to_completion_ms", (self.clock() - t_req) * 1000, skill=act.skill)
        st = await self.refresh_robot()
        if st.joints:  # refresh_robot skips joint bookkeeping while EXECUTING
            self.world.update_joints(st.joints, self.s.poses, float(self.s.robot["motion"]["joint_tolerance_rad"]))

        if res.outcome == COMPLETED:
            last_target = next((m.joints for m in reversed(act.motion) if m.joints), None)
            q = st.joints or res.final_robot_state.get("joints")
            tol = float(self.s.robot["motion"]["joint_tolerance_rad"]) * 3
            if last_target and q and not joints_close(q, last_target, tol):
                self._fault("posizione finale diversa dal target: esito incerto", pa)
                return
            self.world.apply_effects(act.skill, act.params)
            self.history.add(kind="completata", action=pa.id, skill=act.skill, params=act.params,
                             duration_s=res.duration)
            text = (f"COMPLETATO {pa.id}: {act.risultato} Eseguita la sequenza di movimento configurata in "
                    f"{res.duration:.1f}s, confermata dal feedback del robot. Non ci sono sensori sul vassoio: il suo "
                    f"stato è presunto. Posa attuale: {self.world.known_pose or 'non nominata'}.")
            if pa.remaining and self.state == GateState.EXECUTING and not cancel.is_set():
                nxt = pa.remaining[0]
                try:
                    a2 = self.reg.validate(nxt["skill"], nxt["params"], self.world)
                except SkillError as e:
                    self._transition(GateState.IDLE, f"sequenza interrotta dopo {pa.id}")
                    self._report("completato", text + f" Sequenza interrotta: passo successivo non valido ({e}).",
                                 result=res.to_dict())
                    return
                npa = PendingAction(id=f"A{next(self._act_ids)}", action=a2, created=self.clock(), source=pa.source,
                                    question_asked_at=pa.question_asked_at, question_after_utt=pa.question_after_utt,
                                    used=True, plan_id=pa.plan_id, step_index=pa.step_index + 1,
                                    step_total=pa.step_total, remaining=pa.remaining[1:])
                self.history.add(kind="proposta", action=npa.id, skill=a2.skill, params=a2.params, source="sequenza")
                self._cancel = threading.Event()
                self.world.active_skill = a2.skill
                self._exec_task = asyncio.ensure_future(self._execute(npa, self._cancel, t_req))
                text += (f" Passo {npa.step_index + 1} di {npa.step_total} avviato con la stessa conferma ({npa.id}). "
                         "Non chiedere un altro sì.")
                self._report("completato", text, result=res.to_dict())
                return
            if self.state == GateState.EXECUTING:
                self._transition(GateState.IDLE, f"{pa.id} completata")
            insp = self.s.inspection
            if act.skill == "smista" and insp:
                text += " " + tr("next_part", self.s.lang, tray=self.s.zone_label(act.params["posizione"]),
                                 input_tray=self.s.zone_label(insp["input_zone"]))
            self._report("completato", text, result=res.to_dict())
            if act.skill == "porta_in_ispezione" and self.state == GateState.IDLE:
                self._begin_inspection()
        elif res.outcome == STOPPED:
            for _ in range(20):           # program state can lag the halt by a few ms: report observed standstill
                if not st.moving:
                    break
                await asyncio.sleep(0.05)
                st = await self.refresh_robot()
            if self.state != GateState.STOPPED:
                self._transition(GateState.STOPPED, f"{pa.id} interrotta")
            self.history.add(kind="interrotta", action=pa.id, skill=act.skill, steps=res.steps_completed)
            self._report("fermato", f"FERMATO durante {pa.id} ({act.skill}) dopo {res.steps_completed}/{res.steps_total} "
                                    f"movimenti. Robot: {self._robot_brief(st)}. Serve RIPRISTINA dall'interfaccia.",
                         result=res.to_dict())
        elif res.outcome == NOT_STARTED:
            self.history.add(kind="non_eseguita", action=pa.id, skill=act.skill, error=res.error)
            if self.state == GateState.EXECUTING:
                self._transition(GateState.IDLE, f"{pa.id} non avviata: {res.error}")
            self._report("non_eseguito", f"NON ESEGUITO {pa.id}: {res.error}. Il braccio non si è mosso.",
                         result=res.to_dict())
        else:  # FAILED or UNKNOWN
            self._fault(f"{res.outcome}: {res.error}", pa, res)

    def _fault(self, reason: str, pa: PendingAction | None, res: ExecutionResult | None = None) -> None:
        self.fault_reason = reason
        self.world.fault = reason
        self.world.known_pose = None
        self.pending = None
        self.history.add(kind="guasto", action=pa.id if pa else None, reason=reason)
        if self.state != GateState.STOPPED:
            self._transition(GateState.FAULT, reason)
        self._report("guasto", f"GUASTO: {reason}. Nessun nuovo tentativo automatico. Serve l'intervento dell'operatore.",
                     result=res.to_dict() if res else None)

    def _robot_brief(self, st: RobotStatus) -> str:
        parts = ["in movimento" if st.moving else "fermo", f"posa {self.world.known_pose or 'non nominata'}"]
        if st.safety:
            parts.append(f"sicurezza {st.safety}")
        if not st.connected:
            parts = ["NON connesso"]
        return ", ".join(parts)

    # ================================================================= STOP ===
    async def _robot_stop(self, why: str) -> dict[str, Any]:
        """Robot stop on a dedicated thread (never queued behind the running motion)."""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()

        def run() -> None:
            try:
                ack = self.robot.stop()
                loop.call_soon_threadsafe(fut.set_result, ack.to_dict())
            except Exception as e:  # stop must never raise into the caller
                loop.call_soon_threadsafe(fut.set_result, {"acknowledged": False, "detail": f"stop fallito: {e}"})

        threading.Thread(target=run, name="robot-stop", daemon=True).start()
        try:
            return await asyncio.wait_for(fut, 3.0)
        except asyncio.TimeoutError:
            return {"acknowledged": False, "detail": "nessuna risposta allo stop entro 3s"}

    async def stop(self, source: str, *, detail: str = "") -> dict[str, Any]:
        t0 = time.time()
        m0 = self.clock()
        if self._cancel:
            self._cancel.set()                 # 0. invalidate the running authorisation
        robot_ack = asyncio.ensure_future(self._robot_stop(source))   # 1. request robot stop immediately
        pa = self.pending                       # 3-5. cancel pending / queued, invalidate authorisation
        self.pending = None
        if self.utterance:
            self.utterance.used_for = self.utterance.used_for or "STOP"
        was = self.state
        if was != GateState.STOPPED:            # 6-7. STOPPED + broadcast
            self._transition(GateState.STOPPED, f"STOP da {source}", source=source, detail=detail,
                             cancelled=pa.id if pa else None)
        self.bus.publish("stop", source=source, detail=detail, at=t0, was=was.value)
        ack = await robot_ack
        st = await self.refresh_robot()
        # robot ack = stop commands accepted by the controller (adapter-measured); total = until feedback read back
        total_ms = round((time.time() - t0) * 1000, 1)
        ack_ms = ack.get("ack_latency_ms", total_ms)
        info = {"source": source, "detail": detail, "requested_at": t0, "previous_state": was.value,
                "robot_ack": ack, "ack_latency_ms": ack_ms, "halt_latency_ms": ack.get("halt_latency_ms"),
                "total_latency_ms": total_ms,
                "robot_status": st.to_dict(), "cancelled_pending": pa.id if pa else None}
        if was != GateState.STOPPED or self.last_stop is None:
            self.last_stop = info          # keep the pathway that actually stopped the robot first
        kind = source.split(":")[0]
        self.metrics.record(f"stop_ack_ms[{kind}]", ack_ms, source=source)
        if ack.get("halt_latency_ms") is not None:
            self.metrics.record(f"stop_halt_ms[{kind}]", ack["halt_latency_ms"], source=source)
        log_event(log, "STOP", **{k: v for k, v in info.items() if k != "robot_status"})
        self.history.add(kind="stop", source=source, previous=was.value, ack_ms=ack_ms, robot=self._robot_brief(st))
        self.bus.publish("stop_ack", **info)
        self.publish_state()
        if was not in (GateState.EXECUTING, GateState.STOPPED):  # executing: _execute() reports; already stopped: no repeat
            self._report("fermato", f"STOP ricevuto ({source}). "
                         + (f"Proposta {pa.id} annullata. " if pa else "")
                         + f"Robot: {self._robot_brief(st)}. Nuovi movimenti bloccati fino a RIPRISTINA.")
        _ = m0
        return {"ok": True, "esito": "fermato", **{k: info[k] for k in ("ack_latency_ms", "previous_state")},
                "robot": self._robot_brief(st)}

    # ================================================================ reset ===
    async def reset(self, *, operator: str = "ui") -> dict[str, Any]:
        """Deliberate operator action only (never from voice). Verifies the robot first; never moves it."""
        if self.state == GateState.EXECUTING:
            return _err("occupato", "Impossibile ripristinare durante un movimento.")
        if self.state not in (GateState.STOPPED, GateState.FAULT):
            return {"ok": True, "esito": "gia_pronto", "gate": self.state.value}
        st = await self.refresh_robot()
        if not st.connected:
            try:
                await self._io(self.robot.connect, timeout=5)
            except Exception as e:
                return _err("robot_non_connesso", f"Robot non raggiungibile: {e}")
            st = await self.refresh_robot()
        if not st.connected:
            return _err("robot_non_connesso", st.detail or "Robot non connesso.")
        if st.moving:
            return _err("robot_in_movimento", "Il robot risulta ancora in movimento: attendere l'arresto.")
        if not st.ok_for_motion:
            return _err("robot_non_pronto", f"Robot non pronto (modo {st.robot_mode}, sicurezza {st.safety}). "
                                            "Risolvere sul teach pendant, poi ripristinare.")
        prev = self.state
        self.fault_reason = None
        self.world.fault = None
        self.pending = None
        if self.utterance:
            self.utterance.used_for = self.utterance.used_for or "RESET"
        self._transition(GateState.IDLE, f"ripristino operatore ({operator}) da {prev.value}", operator=operator)
        self.history.add(kind="ripristino", operator=operator, previous=prev.value)
        self._report("ripristino", f"Sistema ripristinato dall'operatore. Robot {self._robot_brief(st)}.")
        return {"ok": True, "esito": "ripristinato", "gate": self.state.value, "robot": st.to_dict()}

    # ========================================================== inspection ===
    def start_inspection(self, rule: str | None, *, source: str = "grok") -> dict[str, Any]:
        """Set the natural-language rule and bring the next part to the camera (that motion needs a confirmation).

        If the part is already held at the camera pose, inspect it again without moving."""
        b = self._blocked()
        if b:
            return b
        insp = self.s.inspection
        if not insp:
            return _err("ispezione_non_configurata", "Ispezione non configurata in robot.yaml.")
        if self.camera is None or self.inspector is None:
            return _err("telecamera_non_disponibile", "Telecamera o ispettore non disponibili.")
        rule = clean_rule(rule) or self.inspection.rule
        if not rule:
            return _err("regola_mancante", "Serve la regola di ispezione, ad esempio: scarta i pezzi con graffi o "
                                           "anomalie.")
        self.inspection.rule = rule
        self.history.add(kind="regola_ispezione", rule=rule, source=source)
        self.publish_state()
        if self.world.holding_tray and self.world.known_pose == insp["inspect_pose"]:
            if self.state == GateState.PENDING_CONFIRMATION:
                self.cancel(source=f"{source}:nuova_ispezione")
            self._begin_inspection()
            return {"ok": True, "esito": "ispezione_avviata", "regola": rule,
                    "istruzione": "Il pezzo è già davanti alla telecamera: di' solo 'Analizzo.' L'esito arriverà in "
                                  "un [RAPPORTO SISTEMA]."}
        res = self.propose("porta_in_ispezione", {"posizione": insp["input_zone"]}, source=source)
        if res.get("ok") and self.pending is not None:
            self.pending.action.conferma = tr("bring", self.s.lang, tray=self.s.zone_label(insp["input_zone"]))
            res["frase_conferma"] = self.pending.action.conferma
            self.publish_state()
        res["regola"] = rule
        return res

    def part_ready(self, *, operator: str = "ui") -> dict[str, Any]:
        """Operator declares a new part in the input tray (bookkeeping only, never moves the robot)."""
        insp = self.s.inspection
        if not insp:
            return _err("ispezione_non_configurata", "Ispezione non configurata.")
        if self.state == GateState.EXECUTING or self.inspection.running:
            return _err("occupato", "Attendi la fine del movimento o dell'ispezione.")
        if self.world.holding_tray:
            return _err("forca_occupata", "La forca ha ancora un pezzo: deposita prima quello.")
        self.world.trays_at.add(insp["input_zone"])
        self.history.add(kind="pezzo_pronto", zone=insp["input_zone"], operator=operator)
        self.publish_state()
        return {"ok": True, "esito": "pezzo_pronto", "zona": insp["input_zone"]}

    def _begin_inspection(self) -> None:
        self.inspection.running = True
        self.bus.publish("inspection", phase="started", rule=self.inspection.rule)
        self.publish_state()
        self._inspect_task = asyncio.ensure_future(self._run_inspection())

    async def _wait_frame(self, after: float, deadline: float) -> Any:
        while True:
            frame = self.camera.store.latest()
            if frame is not None and frame.received_at >= after:
                return frame
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(0.1)

    async def _run_inspection(self) -> None:
        insp, lang, rule = self.s.inspection, self.s.lang, self.inspection.rule
        settle, max_age = float(insp.get("settle_s", 0.8)), float(insp.get("max_frame_age_s", 2.0))
        result: dict[str, Any] | None = None
        frame = None
        try:
            t0 = time.monotonic()
            await asyncio.sleep(settle)
            frame = await self._wait_frame(t0 + settle, t0 + settle + max_age)
            if frame is None:
                result = {"status": "NO_FRAME", "reason": tr("no_frame", lang), "source": "camera"}
            else:
                loop = asyncio.get_running_loop()
                try:
                    r = await asyncio.wait_for(loop.run_in_executor(self._io_pool, self.inspector.inspect, frame.image,
                                                                    rule, lang), 25)
                    result = r.to_dict()
                except asyncio.TimeoutError:
                    result = {"status": UNSURE, "reason": "", "source": getattr(self.inspector, "name", "?"),
                              "error": "timeout"}
        finally:
            self.inspection.running = False
        self._finish_inspection(result, frame, rule, lang)

    def _finish_inspection(self, result: dict[str, Any], frame: Any, rule: str, lang: str) -> None:
        insp = self.s.inspection
        status = result["status"]
        if status == UNSURE and result.get("error") and not result.get("reason"):
            result["reason"] = tr("vlm_error", lang, error=result["error"][:120])
        result.update(rule=rule, at=time.time(), frame_id=frame.frame_id if frame else None)
        self.inspection.last = result
        if frame is not None:
            self.inspection.last_jpeg = frame.jpeg
        if status in self.inspection.counts:
            self.inspection.counts[status] += 1
        self.history.add(kind="ispezione", status=status, reason=result["reason"], rule=rule,
                         source=result.get("source"))
        self._log_inspection(result, frame)
        self.bus.publish("inspection", phase="done", **result)
        self.publish_state()
        if self.state != GateState.IDLE:          # STOP / fault while the model was thinking: no proposal
            return
        if status == "NO_FRAME":
            self._report("ispezione", result["reason"], inspection=result)
            return
        pass_tray, fail_tray = self.s.zone_label(insp["pass_zone"]), self.s.zone_label(insp["fail_zone"])
        if status not in (PASS, FAIL):
            self._report("ispezione", "ISPEZIONE INCERTA. Leggi all'operatore: " +
                         tr("unsure", lang, reason=result["reason"], pass_tray=pass_tray, fail_tray=fail_tray) +
                         f" Se decide, proponi smista con posizione {insp['pass_zone']} (approvato) o "
                         f"{insp['fail_zone']} (scartato).", inspection=result)
            return
        zone = insp["pass_zone"] if status == PASS else insp["fail_zone"]
        try:
            act = self.reg.validate("smista", {"posizione": zone}, self.world)
        except SkillError as e:
            self._report("ispezione", f"Esito {status}: {result['reason']} Deposito non proponibile: {e}",
                         inspection=result)
            return
        act.conferma = tr("question", lang, verdict=tr(f"verdict_{status}", lang), reason=result["reason"],
                          tray=self.s.zone_label(zone))
        res = self._set_pending(act, "inspection")
        if not self._report_cbs:                  # no Grok session: the question is shown in the UI right now
            self.mark_question_asked(res["action_id"])
        self._report("ispezione", f"ISPEZIONE {status}, proposta {res['action_id']} in attesa di conferma. Leggi "
                                  f"ESATTAMENTE all'operatore: «{act.conferma}» Poi aspetta la sua risposta; con un sì "
                                  f"chiama confirm({res['action_id']}).",
                     inspection=result, say=act.conferma, action_id=res["action_id"])

    def _log_inspection(self, result: dict[str, Any], frame: Any) -> None:
        try:
            d = self.s.data_dir / "inspections"
            d.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            if frame is not None:
                (d / f"{stamp}-{frame.frame_id}.jpg").write_bytes(frame.jpeg)
                result = {**result, "image": f"{stamp}-{frame.frame_id}.jpg"}
            with (d / "inspections.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
        except OSError:  # pragma: no cover
            log.exception("could not write the inspection log")

    # ============================================================ P2: poses ===
    async def save_pose(self, name: str) -> dict[str, Any]:
        """Record the robot's CURRENT joints under a new name (never joints from the conversation)."""
        import re

        import yaml
        b = self._blocked()
        if b or self.state == GateState.PENDING_CONFIRMATION:
            return b or _err("occupato", "C'è un'azione in attesa di conferma.")
        key = re.sub(r"[^a-z0-9_]", "", str(name).strip().lower().replace(" ", "_"))
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", key or ""):
            return _err("nome_non_valido", "Nome non valido: usa una o due parole semplici.")
        existing = self.s.poses.get(key)
        if existing and existing.get("fonte") != "voce":
            return _err("nome_riservato", f"'{key}' è una posa configurata: scegli un altro nome.")
        st = await self.refresh_robot()
        if not st.connected or st.moving or not st.joints:
            return _err("robot_non_disponibile", "Posizione attuale non disponibile.")
        pose = {"joints": [round(x, 5) for x in st.joints], "selezionabile": True, "alias": [key.replace("_", " ")],
                "fonte": "voce", "verificata_reale": self.s.mode == "real"}
        path = self.s.data_dir / "user_poses.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}
        data.setdefault("poses", {})[key] = pose
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
        self.s.poses[key] = pose
        self.history.add(kind="posa_salvata", name=key, joints=pose["joints"])
        self.publish_state()
        return {"ok": True, "esito": "posa_salvata", "nome": key, "nota": "Salvata, non eseguita. Usare vai_a_posa."}

    # ======================================================= voice session ===
    async def on_voice_disconnected(self, reason: str) -> None:
        """Clear pending + invalidate confirmations. Never retried, never restored."""
        pa = self.pending
        self.pending = None
        if self.utterance:
            self.utterance.used_for = self.utterance.used_for or "DISCONNECT"
        self.utterance = None
        if pa:
            self.history.add(kind="annullata", action=pa.id, reason=f"voce disconnessa: {reason}")
        if self.state == GateState.PENDING_CONFIRMATION:
            self._transition(GateState.IDLE, f"voce disconnessa ({reason}): proposta {pa.id if pa else ''} annullata")
        elif self.state == GateState.EXECUTING and self.stop_on_voice_loss:
            await self.stop("voice_lost", detail=reason)
        self.publish_state()
