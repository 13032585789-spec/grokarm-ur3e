"""The ONLY tools Grok receives, and their dispatch to the safety gate.

No tool can send URScript, joints, raw poses, open connections, change robot
configuration or bypass the gate. Every argument is validated by the gate /
registry; unknown tools are rejected.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import LANGUAGES, Settings
from ..safety.gate import Gate

PROMPT_FILE = Path(__file__).resolve().parents[1] / "voice" / "prompt_it.md"

SKILL_IDS = ["vai_a_posa", "indica", "solleva_vassoio", "appoggia_vassoio", "spingi", "smista"]
SEQUENCE_SKILL_IDS = ["vai_a_posa", "indica", "solleva_vassoio", "appoggia_vassoio", "spingi"]


def _params_schema(s: Settings, poses: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "description": "Includi SOLO i parametri detti dall'operatore. Ometti quelli mancanti o incerti.",
        "properties": {
            "posizione": {"type": "string", "enum": s.zones},
            "direzione": {"type": "string", "enum": s.directions},
            "posa": {"type": "string", "enum": poses},
        },
    }


def tool_schemas(s: Settings, poses: list[str], *, stretch: bool = True) -> list[dict[str, Any]]:
    p = _params_schema(s, poses)
    tools = [
        {"type": "function", "name": "propose_skill",
         "description": "Proponi UNA abilità predefinita. Non muove il robot: crea un'azione in attesa di conferma.",
         "parameters": {"type": "object", "properties": {"skill": {"type": "string", "enum": SKILL_IDS}, "parametri": p},
                        "required": ["skill"]}},
        {"type": "function", "name": "confirm",
         "description": "Chiedi l'esecuzione dell'azione in attesa. SOLO dopo che l'operatore ha detto sì nel suo ultimo turno. "
                        "Il sistema verifica la trascrizione dell'operatore.",
         "parameters": {"type": "object", "properties": {"action_id": {"type": "string"}}, "required": ["action_id"]}},
        {"type": "function", "name": "cancel", "description": "Annulla l'azione in attesa.",
         "parameters": {"type": "object", "properties": {}}},
        {"type": "function", "name": "stop", "description": "Ferma subito il robot. Usala appena l'operatore dice stop.",
         "parameters": {"type": "object", "properties": {}}},
        {"type": "function", "name": "status", "description": "Stato del sistema, del robot e dei vassoi presunti.",
         "parameters": {"type": "object", "properties": {}}},
        {"type": "function", "name": "point_at_cup",
         "description": "Indica con la punta il bicchiere di carta del colore detto dall'operatore. Il sistema lo cerca "
                        "nell'immagine della telecamera, trova la zona e crea un'azione indica in attesa di conferma.",
         "parameters": {"type": "object", "properties": {"colore": {
             "type": "string", "enum": ["red", "orange", "yellow", "green", "blue", "purple", "pink", "white", "grey",
                                        "black"]}}, "required": ["colore"]}},
        {"type": "function", "name": "touch_cup",
         "description": "Tocca con la punta il bicchiere del colore detto: il sistema trova il bicchiere nell'immagine della "
                        "telecamera calibrata, calcola la sua posizione sul tavolo e propone: sopra, discesa lenta fino al "
                        "bordo, risalita (serve la conferma). Usala per 'tocca / vai sul / raggiungi il bicchiere'.",
         "parameters": {"type": "object", "properties": {
             "colore": {"type": "string", "enum": ["red", "orange", "yellow", "green", "blue", "purple", "pink", "white",
                                                   "grey", "black"]},
             "posizione": {"type": "string", "enum": s.zones,
                           "description": "Solo se l'operatore la dice o se il sistema chiede quale."}},
             "required": ["colore"]}},
        {"type": "function", "name": "grab_cup",
         "description": "PRENDI e SOLLEVA il bicchiere del colore detto con la pinza a semicerchio: il sistema lo trova "
                        "nella telecamera, passa sopra gli altri bicchieri, scende dietro, infila l'anello alla base e "
                        "lo solleva (serve la conferma). Usala per 'prendi / solleva / alza / afferra / 拿起 / 抓起 / 托起'.",
         "parameters": {"type": "object", "properties": {
             "colore": {"type": "string", "enum": ["red", "orange", "yellow", "green", "blue", "purple", "pink", "white",
                                                   "grey", "black"]},
             "posizione": {"type": "string", "enum": s.zones,
                           "description": "Solo se l'operatore la dice o se il sistema chiede quale."}},
             "required": ["colore"]}},
        {"type": "function", "name": "place_cup",
         "description": "Rimetti giù il bicchiere sollevato con grab_cup, dove era, e sfila l'anello (serve la conferma). "
                        "Per 'posalo / mettilo giù / 放下'.",
         "parameters": {"type": "object", "properties": {}}},
        {"type": "function", "name": "move_tip",
         "description": "Sposta la punta in linea retta nella direzione detta dall'operatore. La DISTANZA non è un "
                        "parametro: il sistema la legge dalle parole dell'operatore (es. '3 centimetri'); se manca, il "
                        "sistema chiede quanto. Serve la conferma.",
         "parameters": {"type": "object", "properties": {"direzione": {
             "type": "string", "enum": ["sinistra", "destra", "avanti", "indietro", "su", "giu"],
             "description": "Sempre questi id, in qualunque lingua: sinistra=left/izquierda/gauche/links/左, "
                            "destra=right/derecha/droite/rechts/右, avanti=forward/adelante/avant/vorne/前, "
                            "indietro=back/atrás/arrière/hinten/后, su=up/arriba/haut/oben/上, giu=down/abajo/bas/unten/下."}},
             "required": ["direzione"]}},
        {"type": "function", "name": "rotate_joint",
         "description": "Ruota UN giunto. L'ANGOLO non è un parametro: il sistema lo legge dalle parole dell'operatore "
                        "(es. '30 gradi', '30 grados', '30 degrés', '30 Grad', '30度'). "
                        "Se l'operatore dice solo 'gira a sinistra / turn left / 向左转' senza nominare il giunto, "
                        "usa giunto=base e verso=sinistra o destra; per su/giu usa giunto=spalla. "
                        "giunto: base, spalla (shoulder/hombro/épaule/Schulter/肩), gomito (elbow/codo/coude/肘), "
                        "polso1, polso2, polso3. Serve la conferma.",
         "parameters": {"type": "object", "properties": {
             "giunto": {"type": "string", "enum": ["base", "spalla", "gomito", "polso1", "polso2", "polso3"]},
             "verso": {"type": "string", "enum": ["sinistra", "destra", "su", "giu", "piu", "meno"]}},
             "required": ["giunto", "verso"]}},
        {"type": "function", "name": "look_cups",
         "description": "Elenca i bicchieri colorati che la telecamera vede adesso e in quale zona. Non muove il robot.",
         "parameters": {"type": "object", "properties": {}}},
        {"type": "function", "name": "start_inspection",
         "description": "Avvia l'ispezione qualità: memorizza la regola e propone di portare il prossimo pezzo dal vassoio di "
                        "ingresso davanti alla telecamera (serve la conferma). Senza regola riusa l'ultima.",
         "parameters": {"type": "object", "properties": {"regola": {
             "type": "string", "description": "Regola in linguaggio naturale, con le parole dell'operatore, es. "
                                              "'scarta i pezzi con graffi o anomalie'."}}}},
    ]
    if stretch:
        tools += [
            {"type": "function", "name": "propose_batch",
             "description": "Più spostamenti della punta e/o rotazioni di giunti detti in una sola frase. NON passare i numeri: "
                            "il sistema li legge in ordine dalle parole dell'operatore. Un solo sì esegue tutti i passi. "
                            "Esempio: '底座向左转10度，然后肘关节向上转5度，再向上2厘米' = ruota base sinistra, ruota gomito su, sposta su.",
             "parameters": {"type": "object", "properties": {"passi": {"type": "array", "minItems": 2, "maxItems": 5,
                            "items": {"type": "object", "properties": {
                                "tipo": {"type": "string", "enum": ["sposta", "ruota"]},
                                "direzione": {"type": "string", "enum": ["sinistra", "destra", "avanti", "indietro", "su", "giu"]},
                                "giunto": {"type": "string", "enum": ["base", "spalla", "gomito", "polso1", "polso2", "polso3"]},
                                "verso": {"type": "string", "enum": ["sinistra", "destra", "su", "giu", "piu", "meno"]}},
                                "required": ["tipo"]}}},
                            "required": ["passi"]}},
            {"type": "function", "name": "propose_sequence",
             "description": "Proponi da 2 a 5 abilità predefinite in sequenza. Un solo sì esegue tutti i passi in ordine.",
             "parameters": {"type": "object", "properties": {"passi": {"type": "array", "minItems": 2, "maxItems": 5,
                            "items": {"type": "object", "properties": {"skill": {"type": "string", "enum": SEQUENCE_SKILL_IDS},
                                                                       "parametri": p}, "required": ["skill"]}}},
                            "required": ["passi"]}},
            {"type": "function", "name": "save_pose",
             "description": "Salva la posizione attuale del robot con un nome, per vai_a_posa. Non muove il robot.",
             "parameters": {"type": "object", "properties": {"nome": {"type": "string"}}, "required": ["nome"]}},
        ]
    return tools


def build_prompt(s: Settings, gate: Gate) -> str:
    st = gate.world.snapshot()["oggetti_presunti"]
    state = json.dumps({"vassoi_presunti_in": st["vassoi_in_zona"], "zone_libere": st["zone_libere"],
                        "vassoio_sulla_forca": st["vassoio_sulla_forca"], "stato": gate.state.value}, ensure_ascii=False)
    wake = ""
    if s.wake_word:
        wake = (f"10. Parola di attivazione: proponi azioni solo se la frase contiene \"{s.wake_word}\". "
                "Stop e risposte sì/no valgono sempre anche senza.")
    insp = s.inspection or {"input_zone": "sinistra", "pass_zone": "centro", "fail_zone": "destra"}
    trays = ", ".join(f"{s.zone_label(z)} = {z}" for z in s.zones)
    return PROMPT_FILE.read_text().format(
        poses=", ".join(gate.reg.selectable_poses()), zones=", ".join(s.zones), directions=", ".join(s.directions),
        state=state, wake=wake, language=LANGUAGES.get(s.lang, s.lang), trays=trays,
        input_tray=s.zone_label(insp["input_zone"]), pass_tray=s.zone_label(insp["pass_zone"]),
        fail_tray=s.zone_label(insp["fail_zone"]), pass_zone=insp["pass_zone"], fail_zone=insp["fail_zone"])


async def dispatch(gate: Gate, name: str, args: dict[str, Any], *, source: str = "grok") -> dict[str, Any]:
    """Execute a tool call against the gate. Never raises."""
    if not isinstance(args, dict):
        return {"ok": False, "esito": "argomenti_non_validi"}
    try:
        if name == "propose_skill":
            return gate.propose(args.get("skill"), args.get("parametri") or args.get("params") or {}, source=source)
        if name == "confirm":
            return await gate.confirm(str(args.get("action_id") or ""), source=source)
        if name == "cancel":
            return gate.cancel(source=source)
        if name == "stop":
            return await gate.stop(f"grok_tool:{source}")
        if name == "status":
            st = gate.status()
            return {"ok": True, "gate": st["gate"], "pending": st["pending"], "world": st["world"],
                    "robot": {k: st["robot"][k] for k in ("connected", "moving", "safety", "robot_mode")}}
        if name == "propose_batch":
            return await gate.propose_batch(args.get("passi") or [], source=source)
        if name == "propose_sequence":
            steps = [{"skill": p.get("skill"), "params": p.get("parametri") or {}} for p in (args.get("passi") or [])
                     if isinstance(p, dict)]
            return gate.propose_sequence(steps, source=source)
        if name == "point_at_cup":
            return await gate.point_at_cup(args.get("colore") or args.get("colour"), source=source)
        if name == "touch_cup":
            return await gate.touch_cup(args.get("colore") or args.get("colour"), zone=args.get("posizione"),
                                        source=source)
        if name == "grab_cup":
            return await gate.grab_cup(args.get("colore") or args.get("colour"), zone=args.get("posizione"),
                                       source=source)
        if name == "place_cup":
            return await gate.place_cup(source=source)
        if name == "move_tip":
            return await gate.propose_move(args.get("direzione"), source=source)
        if name == "rotate_joint":
            return await gate.propose_rotate(args.get("giunto"), args.get("verso"), source=source)
        if name == "look_cups":
            r = gate.scan_cups()
            return {k: v for k, v in r.items() if k != "frame_id"}
        if name == "start_inspection":
            return gate.start_inspection(args.get("regola") or args.get("rule"), source=source)
        if name == "save_pose":
            return await gate.save_pose(str(args.get("nome") or ""))
    except Exception as e:  # pragma: no cover - defensive
        return {"ok": False, "esito": "errore_interno", "messaggio": str(e)}
    return {"ok": False, "esito": "strumento_sconosciuto", "messaggio": f"Strumento {name!r} non disponibile."}
