"""Deterministic keyword-rule parser for Italian commands.

Used for (1) TEXT MODE when Grok is unavailable and (2) the evaluation
baseline (eval/baseline_rules.py). It never guesses a missing parameter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..safety import phrases
from ..skills.amounts import is_nudge

SKILL_PATTERNS: list[tuple[str, list[str]]] = [
    # order matters: more specific first
    ("appoggia_vassoio", [r"\bappoggi\w*", r"\bdeposit\w*", r"\bmett\w* giu\b", r"\bposa(lo|re)? il vassoio\b",
                          r"\bposalo\b", r"\blascia(lo)? (il vassoio|giu)\b", r"\bmetti(lo)? (nel|nella|in|a)\b",
                          r"\bsgancia\w*", r"\brilascia\w*", "放下", "放到", "搁"]),
    ("solleva_vassoio", [r"\bsolleva\w*", r"\balza\w*", r"\btira(lo)? su\b", r"\bprendi\w*", r"\braccogli\w*",
                         r"\bpreleva\w*", r"\bsollev\w*", r"\bcarica\w*", r"\blift\w*", r"\bpick\w*",
                         "抬", "端起", "叉起", "叉起来"]),
    ("spingi", [r"\bsping\w*", r"\bspinta\b", r"\bspintona\w*", r"\bpush\w*", "推", "怼"]),
    ("indica", [r"\bindic\w*", r"\bmostra\w*", r"\bpunta\w*", r"\bfammi vedere\b", r"\bsegnala\w*", r"\bpoint\w*",
                r"\bshow\w*", "指", "戳"]),
    ("vai_a_posa", [r"\bvai\b", r"\btorna\w*", r"\bporta(ti)? (il braccio|in|a)\b", r"\bposizionat\w*",
                    r"\bspostati\b", r"\bmuoviti\b", r"\bgo to\b", r"\breturn\b", r"\bparcheggia\w*", r"\bin posa\b",
                    r"\bposizione (di )?(attesa|iniziale|home)\b", r"\bhome\b",
                    "回家", "回原位", "初始位置", "等待位置", "回到"]),
]

VAGUE_MOVE = [r"\bspost\w*", r"\bmuov\w*", r"\bportalo\b", r"\bportala\b", r"\bfallo\b", r"\bdall altra parte\b",
              r"\bla\b(?! zona)", r"\bmove\b"]
OUT_OF_SCOPE = [r"\bdisegn\w*", r"\bscriv\w*", r"\bcerchi\w*", r"\bquadrat\w*", r"\bball\w*", r"\bcanta\w*",
                r"\bvelocit\w*", r"\bcoordinat\w*", r"\btraiettori\w*", r"\bruota\w*", r"\bgira\w*", r"\bsald\w*",
                r"\bavvita\w*", r"\bguarda\w*", r"\bvedi\b", r"\bfoto\w*", r"\bcaffe\b",
                r"\bdraw\w*", r"\bdance\w*", "坐标", "速度", "跳舞", "扔", "安全限制"]

ZONE_WORDS = {
    "sinistra": [r"\bsinistr\w*", r"\bsx\b", r"\bleft\b", "左边", "左侧", "左"],
    "centro": [r"\bcentr\w*", r"\bin mezzo\b", r"\bmezzo\b", r"\bmiddle\b", r"\bcenter\b", "中间", "中央", "中"],
    "destra": [r"\bdestr\w*", r"\bdx\b", r"\bright\b", "右边", "右侧", "右"],
}
DIR_MARKERS = r"\b(verso|in direzione|direzione|spostandolo|spingendolo|towards?)\b|往|向"
CAPABILITY_Q = [r"\bcosa (sai|puoi) fare\b", r"\bwhat can you\b", r"\bwhat do you do\b",
                "你能干什么", "你会什么", "你能做什么", "你可以做什么", "能做什么"]
TRANSFER_MARK = ["放到", "指到", "从", "移到", r"\bda\b", r"\bto the\b"]


@dataclass
class Intent:
    kind: str                      # skill | stop | confirm | cancel | clarify | out_of_scope | none
    skill: str | None = None
    params: dict[str, str] = field(default_factory=dict)
    verdict: str | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "skill": self.skill, "params": self.params, "verdict": self.verdict}


def _n(text: str) -> str:
    return phrases.normalize(text).replace("?", " ")


def _any(pats: list[str], t: str) -> bool:
    return any(re.search(p, t) for p in pats)


def _zones_in(t: str) -> list[tuple[int, str]]:
    found = []
    for z, pats in ZONE_WORDS.items():
        for p in pats:
            for m in re.finditer(p, t):
                found.append((m.start(), z))
    return sorted(set(found))


def _pose_pat(c: str) -> str:
    if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", c):
        return re.escape(c)
    return rf"\b{re.escape(c)}\b"


def _pose_in(t: str, poses: dict[str, Any]) -> str | None:
    for name, p in poses.items():
        if not p.get("selezionabile"):
            continue
        cands = [name.replace("_", " ")] + [phrases.normalize(a) for a in p.get("alias", [])]
        if any(re.search(_pose_pat(c), t) for c in cands if c):
            return name
    return None


def _transfer_zones(t: str) -> tuple[str, str] | None:
    """'从左边指到中间' / 'da sinistra al centro' -> (origin, destination). A push is not a transfer."""
    if not _any(TRANSFER_MARK, t):
        return None
    seen: list[str] = []
    for _, zone in _zones_in(t):
        if zone not in seen:
            seen.append(zone)
    if len(seen) < 2:
        return None
    return seen[0], seen[1]


_OTHER_SIDE = {"sinistra": "destra", "destra": "sinistra"}
_OTHER_WORDS = re.compile(r"另一个|另外一个|换另一|换一个")


def earlier_utterance(items: Any, current: str) -> str:
    """The operator line before this one. History is newest-first and already contains ``current``."""
    skipped = False
    for it in items or []:
        if it.get("kind") != "utterance":
            continue
        said = it.get("text") or ""
        if not skipped and said == current:
            skipped = True
            continue
        return said
    return ""


def parse(text: str, *, poses: dict[str, Any] | None = None, pending: bool = False,
          prior: str | None = None) -> Intent:
    t = _n(text)
    if not t:
        return Intent("none")
    if phrases.is_stop(text):
        return Intent("stop")
    if re.search(r"昨天|手动", t):
        return Intent("out_of_scope")
    wants_other = bool(_OTHER_WORDS.search(t))
    if pending:
        v = phrases.confirmation_verdict(text)
        correction = bool(re.search(r"不对|不是", t) and _zones_in(t))
        if v == phrases.VALID and not correction:
            return Intent("confirm", verdict=v)
        if v in (phrases.NEGATIVE, phrases.UNCERTAIN) and not _skill_of(t) and not wants_other and not correction:
            return Intent("cancel" if v == phrases.NEGATIVE else "confirm", verdict=v)
    elif phrases.is_cancel(text) and not _skill_of(t) and not wants_other:
        return Intent("cancel")
    if not pending and _any(CAPABILITY_Q, t) and _skill_of(t) is None:
        return Intent("capabilities")
    transfer = _transfer_zones(t)
    if transfer and _skill_of(t) not in ("spingi", "solleva_vassoio"):
        return Intent("transfer", params={"origine": transfer[0], "destinazione": transfer[1]})
    skill = _skill_of(t, last=bool(re.search(r"不对|不是", t)))
    if skill is None and re.search(r"不对|不是", t):
        zones = _zones_in(t)
        if zones:
            return Intent("skill", skill="indica", params={"posizione": zones[-1][1]})
    if skill is None:
        if _any(OUT_OF_SCOPE, t):
            return Intent("out_of_scope")
        if wants_other:
            previous = _zones_in(_n(prior or ""))
            flipped = _OTHER_SIDE.get(previous[-1][1]) if previous else None
            if flipped is None:
                return Intent("clarify", note="altro lato")
            skill = _skill_of(_n(prior or "")) or "solleva_vassoio"
            if skill == "vai_a_posa":
                skill = "solleva_vassoio"
            return Intent("skill", skill=skill, params={"posizione": flipped})
        if _any(VAGUE_MOVE, t):
            return Intent("clarify", note="movimento vago")
        zones = _zones_in(t)
        if zones:  # parameter only (answer to a clarification question)
            return Intent("clarify", params={"posizione": zones[0][1]}, note="solo parametro")
        return Intent("out_of_scope")
    params: dict[str, str] = {}
    if skill == "vai_a_posa":
        pose = _pose_in(t, poses or {})
        if pose:
            params["posa"] = pose
        else:
            z = _zones_in(t)
            if z:
                params["posa"] = f"{z[0][1]}_sopra"
    else:
        zones = _zones_in(t)
        if re.search(r"不对|不是|改成|换成", t) and zones:
            zones = zones[-1:]
        if wants_other and not zones:
            previous = _zones_in(_n(prior or ""))
            flipped = _OTHER_SIDE.get(previous[-1][1]) if previous else None
            if flipped is None:
                return Intent("clarify", note="altro lato")
            if skill is None:
                skill = _skill_of(_n(prior or "")) or "solleva_vassoio"
            if skill == "vai_a_posa":
                skill = "solleva_vassoio"
            return Intent("skill", skill=skill, params={"posizione": flipped})
        if skill == "spingi":
            m = re.search(DIR_MARKERS, t)
            if m:
                after = [z for pos, z in zones if pos > m.start()]
                before = [z for pos, z in zones if pos < m.start()]
                if after:
                    params["direzione"] = after[0]
                if before:
                    params["posizione"] = before[0]
                leftover = [z for _, z in zones if z not in params.values()]
                if "posizione" not in params and leftover:
                    params["posizione"] = leftover.pop(0)
                if "direzione" not in params and leftover:
                    params["direzione"] = leftover.pop(0)
            elif len(zones) >= 2:
                params["posizione"], params["direzione"] = zones[0][1], zones[1][1]
            elif zones:
                params["posizione"] = zones[0][1]
        elif zones:
            params["posizione"] = zones[0][1]
    return Intent("skill", skill=skill, params=params)


def _skill_of(t: str, last: bool = False) -> str | None:
    found = []
    for skill, pats in SKILL_PATTERNS:
        for p in pats:
            m = re.search(p, t)
            if m:
                found.append((m.start(), skill))
                break
    if not found:
        return None
    found.sort()
    return found[-1][1] if last else found[0][1]


# ------------------------------------------------------------------ inspection (text mode only, not in the eval baseline)
INSPECT_WORDS = [r"\bispezion\w*", r"\bispeziona\w*", r"\binspect\w*", r"\binspecci\w*", r"\binspecter\b",
                 r"\bcontrol(e|ar|la) (la )?qualit\w*", r"\bpruf\w*", r"\bqualitatskontroll\w*", "检测", "检查", "质检",
                 "検査"]
CONTINUE_WORDS = [r"\bcontinua\w*", r"\bprossimo pezzo\b", r"\bnext (part|item|one)\b", r"\bcontinue\b",
                  r"\bsiguiente\b", r"\bsuivant\w*", r"\bnachste\w*", r"\bweiter\b", "下一个", "继续", "次の"]
REJECT_WORDS = [r"\bscart\w*", r"\breject\w*", r"\brechaz\w*", r"\brejet\w*", r"\baussortier\w*", "不合格", "拒绝",
                "报废", "不良", "廃棄"]
APPROVE_WORDS = [r"\bapprov\w*", r"\baccett\w*", r"\bpass\w*", r"\baprueb\w*", r"\bacept\w*", r"\baccept\w*",
                 r"\bin ordnung\b", r"\bannehm\w*", "合格", "通过", "良品"]


POINT_WORDS = [r"\bindic\w*", r"\bpunta\w*", r"\bmostra\w*", r"\bpoint\w*", r"\bshow\w*", r"\bsenal\w*",
               r"\bmontre\w*", r"\bzeig\w*", "指", "找", "哪"]


def parse_cup(text: str) -> Intent | None:
    """'indica il bicchiere rosso' / '指一下红色的纸杯' -> point_at_cup(red)."""
    from ..vision.cups import colour_of
    t = _n(text)
    colour = colour_of(text)
    if colour and _any(POINT_WORDS, t):
        return Intent("cup", params={"colore": colour})
    return None


TOUCH_WORDS = [r"\btocc\w*", r"\btouch\w*", r"\btoca\w*", r"\btouche\w*", r"\bberuhr\w*", r"\breach\w*",
               r"\braggiung\w*", "碰", "触", "摸", "触れ", "タッチ"]
CUP_NOUNS = [r"\bbicchier\w*", r"\bcups?\b", r"\bbecher\b", r"\bvaso\b", "纸杯", "杯子", "コップ"]
GRAB_WORDS = [r"\bprend\w*", r"\bafferr\w*", r"\bgrab\w*", r"\bpick\w*", r"\bsolleva\w*", r"\balza\w*",
              r"\blift\w*", r"\bcoge\w*", "拿", "抓", "托", "举", "提起", "夹", "掴"]
PLACE_WORDS = [r"\bposal\w*", r"\bmettilo giu\b", r"\bput (it )?(back )?down\b", "放下", "放回", "置いて"]
ROTATE_WORDS = [r"\bruot\w*", r"\bgir[aio]\w*", r"\brotat\w*", r"\bturn\w*", r"\btourne\w*", r"\bdreh\w*", "转",
                "旋转", "回して", "回す"]
MOVE_WORDS = [r"\bspost\w*", r"\bmuov\w*", r"\bmove\w*", r"\bmueve\w*", r"\bdesplaz\w*", r"\bsube\b", r"\bbaja\b",
              r"\bdeplace\w*", r"\bbouge\w*", r"\bmonte\b", r"\bdescend\w*", r"\bbeweg\w*", r"\bhebe\w*",
              r"\bsenk\w*", r"\bsali\w*", r"\bscendi\w*", r"\balza\w*", r"\babbassa\w*", "移", "挪", "动", "抬", "降",
              "動かして", "上げて", "下げて"]
DIR_PATTERNS = {
    "sinistra": [r"\bsinistr\w*", r"\bleft\b", r"\bizquierd\w*", r"\bgauche\b", r"\blinks\b", "左", "ひだり"],
    "destra": [r"\bdestr\w*", r"\bright\b", r"\bderech\w*", r"\bdroite\b", r"\brechts\b", "右", "みぎ"],
    "avanti": [r"\bavanti\b", r"\bforwards?\b", r"\badelante\b", r"\bavant\b", r"\bvor(ne|wart\w*)?\b", "前", "まえ"],
    "indietro": [r"\bindietro\b", r"\bback(wards?)?\b", r"\batras\b", r"\barriere\b", r"\bhinten\b", r"\bzuruck\b",
                 "后", "後", "うしろ"],
    "su": [r"\bsu\b", r"\bin alto\b", r"\bsali\w*", r"\balza\w*", r"\bup\b", r"\barriba\b", r"\bhaut\b", r"\boben\b",
           r"\bhoch\b", "上", "抬", "高", "うえ"],
    "giu": [r"\bgiu\b", r"\bin basso\b", r"\bscendi\w*", r"\babbassa\w*", r"\bdown\b", r"\babajo\b", r"\bbas\b",
            r"\bunten\b", r"\brunter\b", "下", "降", "した"],
}
SIDE_PATTERNS = {"piu": [r"\bpositiv\w*", r"\bpiu\b", r"\bplus\b", "正"], "meno": [r"\bnegativ\w*", r"\bmeno\b",
                                                                                     r"\bminus\b", "负", "反"]}
JOINT_PATTERNS = {
    "base": [r"\bbase\b", r"\bbasis\b", "底座", "基座", "ベース", r"\b(giunto|joint) ?1\b", "(第一|1号)关节", "关节1"],
    "spalla": [r"\bspalla\b", r"\bshoulder\b", r"\bhombro\b", r"\bepaule\b", r"\bschulter\b", "肩",
               r"\b(giunto|joint) ?2\b", "(第二|2号)关节", "关节2"],
    "gomito": [r"\bgomito\b", r"\belbow\b", r"\bcodo\b", r"\bcoude\b", r"\bellbogen\b", "肘",
               r"\b(giunto|joint) ?3\b", "(第三|3号)关节", "关节3"],
    "polso1": [r"\b(polso|wrist|muneca|poignet|handgelenk) ?1\b", "(手腕|腕)1", r"\b(giunto|joint) ?4\b", "(第四|4号)关节"],
    "polso2": [r"\b(polso|wrist|muneca|poignet|handgelenk) ?2\b", "(手腕|腕)2", r"\b(giunto|joint) ?5\b", "(第五|5号)关节"],
    "polso3": [r"\b(polso|wrist|muneca|poignet|handgelenk) ?3\b", "(手腕|腕)3", r"\b(giunto|joint) ?6\b", "(第六|6号)关节",
               r"\bflangia\b"],
}


def _first(table: dict[str, list[str]], t: str) -> str | None:
    hits = [(m.start(), k) for k, pats in table.items() for p in pats for m in re.finditer(p, t)]
    return min(hits)[1] if hits else None


def parse_side(text: str) -> str | None:
    t = _n(text)
    return _first(SIDE_PATTERNS, t) or _first(DIR_PATTERNS, t)


_CM_UNIT = re.compile(r"(cm|mm)\b|厘米|公分|毫米|センチ|centimet|millimet|zentimet")
_DEG_UNIT = re.compile(r"°|度|deg|grad")


def _has_unit(text: str, kind: str) -> bool:
    return bool((_CM_UNIT if kind == "cm" else _DEG_UNIT).search(_n(text)))


def parse_jog(text: str) -> Intent | None:
    """Text mode: 'tocca il bicchiere rosso', '往左移动三厘米', 'gira a la izquierda 30 grados'.

    Amounts are NOT parsed here: the gate reads them from the same operator words.
    'Turn left 30 degrees' with no joint named means the base; up/down means the shoulder.
    """
    from ..skills.amounts import distance_cm
    from ..vision.cups import colour_of
    t = _n(text)
    if not t:
        return None
    colour = colour_of(text)
    if _any(PLACE_WORDS, t) and (_any(CUP_NOUNS, t) or len(t) <= 8):
        return Intent("place")
    if _any(GRAB_WORDS, t) and (colour or _any(CUP_NOUNS, t)) and not _any([r"\bvassoi\w*", r"\btrays?\b", "托盘"], t):
        if not colour:
            return Intent("clarify", note="cup_colour")
        return Intent("grab", params={"colore": colour})
    if _any(TOUCH_WORDS, t) and (colour or _any(CUP_NOUNS, t)):
        if not colour:
            return Intent("clarify", note="cup_colour")
        return Intent("touch", params={"colore": colour})
    if is_nudge(text) and _first(DIR_PATTERNS, t) == "su" and not _zones_in(t) and not _any(
            [r"\bvassoi\w*", r"\btrays?\b", "托盘", "トレイ"], t):
        return Intent("move", params={"direzione": "su"}, note="nudge")
    joint = _first(JOINT_PATTERNS, t)
    side = _first(SIDE_PATTERNS, t) or _first(DIR_PATTERNS, t)
    has_cm = distance_cm(text) is not None and _has_unit(text, "cm")
    rotating = _any(ROTATE_WORDS, t) and not has_cm and (joint or (side and _has_unit(text, "deg")))
    if rotating:
        if joint is None:
            joint = "spalla" if side in ("su", "giu") else "base" if side in ("sinistra", "destra") else None
        if joint:
            return Intent("rotate", params={"giunto": joint, **({"verso": side} if side else {})})
    d = _first(DIR_PATTERNS, t)
    if d is None or _any([r"\bvassoi\w*", r"\btrays?\b", "托盘", "トレイ"], t):
        return None
    if has_cm or (_any(MOVE_WORDS, t) or is_nudge(text)) and not _skill_of(t):
        return Intent("move", params={"direzione": d}, note="nudge" if is_nudge(text) and not has_cm else "")
    return None


_SPLIT_STEPS = re.compile(
    r"\s*(?:然后|接着|并且|and then|then|e poi|e dopo|y luego|puis|et ensuite|dann|そして|それから|，|,(?!\d))\s*")


def parse_jog_batch(text: str) -> list[Intent] | None:
    """'底座向左转5度，然后肘关节向上转5度' -> two jog intents. One clause stays a single jog."""
    parts = [p for p in _SPLIT_STEPS.split(text or "") if p.strip()]
    if len(parts) < 2:
        return None
    intents = []
    for part in parts:
        jog = parse_jog(part)
        if jog is None or jog.kind in ("touch", "grab", "place"):
            return None
        if jog.kind == "rotate" and "verso" not in jog.params:
            return None
        intents.append(jog)
    return intents


def parse_inspection(text: str, *, holding: bool) -> Intent | None:
    """'Begin inspection on tray A, reject items with scratches' -> inspect(rule); 'scartalo' -> sort to the fail tray."""
    t = _n(text)
    if not t:
        return None
    if _any(INSPECT_WORDS, t):
        has_rule = _any(REJECT_WORDS + APPROVE_WORDS, t) or len(t.split()) > 6 or len(t) > 12 and " " not in t
        return Intent("inspect", note=text.strip() if has_rule else "")
    if _any(CONTINUE_WORDS, t) and not _skill_of(t):
        return Intent("inspect", note="")
    if holding:
        if _any(REJECT_WORDS, t):
            return Intent("sort", params={"esito": "FAIL"})
        if _any(APPROVE_WORDS, t):
            return Intent("sort", params={"esito": "PASS"})
    return None
