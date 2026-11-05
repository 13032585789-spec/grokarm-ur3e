"""TEXT MODE — NOT VOICE.

A conversation driven by typed text and the deterministic rules parser, so the
whole pipeline (validation, clarification, confirmation, execution, STOP) can
be exercised when Grok is unavailable. Development and evaluation only.
"""

from __future__ import annotations

from typing import Any

from ..safety.gate import Gate, GateState
from ..skills.amounts import angle_deg, distance_cm, is_repeat
from ..vision.texts import t as tr
from .rules import Intent, parse, parse_cup, parse_inspection, parse_jog, parse_jog_batch, parse_side

TEXT_MODE_LABEL = "TEXT MODE — NOT VOICE"


class TextConversation:
    def __init__(self, gate: Gate) -> None:
        self.gate = gate
        self.context: dict[str, Any] | None = None   # last incomplete intent (for clarifications/corrections)

    async def handle(self, text: str) -> dict[str, Any]:
        g = self.gate
        g.note_turn_committed("text")
        stopped = g.note_transcript(text, source="text")
        if stopped:
            self.context = None
            return self._out(text, Intent("stop"), "Fermato. Nuovi movimenti bloccati fino a RIPRISTINA.", None)

        batch = parse_jog_batch(text)
        if batch is not None:
            if g.pending:
                g.cancel(source="rules:correzione")
            return await self._jog_batch(text, batch)

        jog = parse_jog(text)
        ctx = self.context if self.context and self.context.get("jog") else None
        if jog is None and ctx:   # answer to "how much?" / "which way?"
            extra = {}
            if ctx["jog"] == "rotate" and "verso" not in ctx["params"] and parse_side(text):
                extra["verso"] = parse_side(text)
            if extra or distance_cm(text) is not None or angle_deg(text) is not None or is_repeat(text):
                jog = Intent(ctx["jog"], params={**ctx["params"], **extra})
        if jog is not None:
            if jog.note == "cup_colour":
                return self._out(text, jog, tr("which_cup_colour", g.s.lang), None)
            if g.pending:
                g.cancel(source="rules:correzione")
            return await self._jog(text, jog)

        if g.pending is None:
            cup = parse_cup(text)
            if cup is not None:
                return await self._cup(text, cup)
            insp = parse_inspection(text, holding=g.world.holding_tray)
            if insp is not None:
                return await self._inspection(text, insp)

        intent = parse(text, poses=g.s.poses, pending=g.pending is not None)

        if intent.kind == "confirm":
            if intent.verdict != "valida":
                return self._out(text, intent, "Serve una conferma esplicita: sì o no?", None)
            res = await g.confirm(g.pending.id if g.pending else None, source="rules")
            reply = "Procedo." if res.get("ok") else res.get("messaggio", "Conferma non valida.")
            return self._out(text, intent, reply, res)

        if intent.kind == "cancel":
            res = g.cancel(source="rules")
            self.context = None
            return self._out(text, intent, "Annullato. Il robot non si muove." if res.get("annullata") else
                             "Non c'è nulla da annullare.", res)

        if intent.kind == "out_of_scope":
            self.context = None
            return self._out(text, intent, tr("out_of_scope", g.s.lang), None)

        if intent.kind == "clarify":
            if intent.params and self.context:     # answer to the previous question: merge
                skill = self.context["skill"]
                params = {**self.context["params"], **self._map_param(skill, intent.params)}
                return await self._propose(text, Intent("skill", skill=skill, params=params))
            self.context = None
            return self._out(text, intent, "Non ho capito cosa spostare e dove. Vuoi sollevare, appoggiare o spingere un "
                                           "vassoio, oppure indicare una zona? Zone: sinistra, centro, destra.", None)

        if intent.kind == "skill":
            if g.pending:  # a new command while one is pending = correction: replace it
                g.cancel(source="rules:correzione")
            return await self._propose(text, intent)

        return self._out(text, intent, "Non ho capito. Puoi ripetere?", None)

    async def _cup(self, text: str, intent: Intent) -> dict[str, Any]:
        g = self.gate
        self.context = None
        res = await g.point_at_cup(intent.params["colore"], source="rules")
        if res.get("ok"):
            g.mark_question_asked(res["action_id"])
            return self._out(text, intent, res["frase_conferma"], res)
        extra = res.get("visti") or res.get("opzioni_valide") or []
        return self._out(text, intent, res.get("messaggio", "") + (f" ({', '.join(extra)})" if extra else ""), res)

    async def _jog(self, text: str, intent: Intent) -> dict[str, Any]:
        g = self.gate
        p = intent.params
        if intent.kind == "touch":
            res = await g.touch_cup(p["colore"], source="rules")
        elif intent.kind == "grab":
            res = await g.grab_cup(p["colore"], source="rules")
        elif intent.kind == "place":
            res = await g.place_cup(source="rules")
        elif intent.kind == "rotate":
            if "verso" not in p:
                self.context = {"jog": "rotate", "params": p}
                return self._out(text, intent, "In che verso? (sinistra/destra, su/giù, più/meno)", None)
            res = await g.propose_rotate(p["giunto"], p["verso"], source="rules")
        else:
            res = await g.propose_move(p["direzione"], source="rules")
        if res.get("ok"):
            self.context = None
            g.mark_question_asked(res["action_id"])
            return self._out(text, intent, res["frase_conferma"], res)
        asks_amount = "quantita" in (res.get("param"), res.get("parametro"))
        self.context = {"jog": intent.kind, "params": p} if asks_amount else None
        extra = res.get("visti") or res.get("opzioni_valide") or []
        return self._out(text, intent, res.get("messaggio", "") + (f" ({', '.join(extra)})" if extra else ""), res)

    async def _jog_batch(self, text: str, intents: list[Intent]) -> dict[str, Any]:
        g = self.gate
        steps = []
        for intent in intents:
            p = intent.params
            if intent.kind == "rotate":
                steps.append({"kind": "rotate", "giunto": p["giunto"], "verso": p["verso"]})
            else:
                steps.append({"kind": "move", "direzione": p["direzione"]})
        res = await g.propose_batch(steps, source="rules")
        intent = Intent("batch", params={"passi": str(len(steps))})
        if res.get("ok"):
            self.context = None
            g.mark_question_asked(res["action_id"])
            return self._out(text, intent, res["frase_conferma"], res)
        return self._out(text, intent, res.get("messaggio", ""), res)

    async def _inspection(self, text: str, intent: Intent) -> dict[str, Any]:
        g = self.gate
        self.context = None
        if intent.kind == "sort":
            insp = g.s.inspection
            zone = insp.get("pass_zone") if intent.params["esito"] == "PASS" else insp.get("fail_zone")
            return await self._propose(text, Intent("skill", skill="smista", params={"posizione": zone}))
        res = g.start_inspection(intent.note or None, source="rules")
        if res.get("ok") and res.get("action_id"):
            g.mark_question_asked(res["action_id"])
            return self._out(text, intent, f"Regola: «{res['regola']}». {res['frase_conferma']}", res)
        if res.get("ok"):
            return self._out(text, intent, f"Regola: «{res['regola']}». Analizzo il pezzo davanti alla telecamera.", res)
        return self._out(text, intent, res.get("messaggio", "Ispezione non avviata."), res)

    def _map_param(self, skill: str, p: dict[str, str]) -> dict[str, str]:
        z = p.get("posizione")
        if skill == "vai_a_posa" and z:
            return {"posa": f"{z}_sopra"}
        if skill == "spingi" and z and "posizione" in (self.context or {}).get("params", {}):
            return {"direzione": z}
        return p

    async def _propose(self, text: str, intent: Intent) -> dict[str, Any]:
        g = self.gate
        res = g.propose(intent.skill, intent.params, source="rules")
        if res.get("ok"):
            self.context = None
            g.mark_question_asked(res["action_id"])
            return self._out(text, intent, res["frase_conferma"], res)
        if res.get("esito") in ("richiesta_ambigua", "precondizione_non_soddisfatta"):
            self.context = {"skill": intent.skill, "params": intent.params}
            opts = res.get("opzioni_valide") or []
            q = res["messaggio"] + (f" Opzioni: {', '.join(opts)}." if opts else "")
            return self._out(text, intent, q, res)
        return self._out(text, intent, res.get("messaggio", "Richiesta non valida."), res)

    def _out(self, text: str, intent: Intent, reply: str, result: dict[str, Any] | None) -> dict[str, Any]:
        self.gate.bus.publish("assistant_done", text=reply, mode=TEXT_MODE_LABEL)
        return {"mode": TEXT_MODE_LABEL, "input": text, "intent": intent.to_dict(), "reply": reply, "result": result,
                "gate": self.gate.state.value}

    @property
    def blocked(self) -> bool:
        return self.gate.state in (GateState.STOPPED, GateState.FAULT)
