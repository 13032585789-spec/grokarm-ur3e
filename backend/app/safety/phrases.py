"""Deterministic phrase checks on the operator's own transcript.

Used independently of Grok for: STOP detection, confirmation validation,
cancellation. Conservative by design: anything uncertain is NOT a yes.

Languages: Italian, English, Spanish, French, German (word tokens) and
Chinese, Japanese (substring match, no word boundaries in those scripts).
"""

from __future__ import annotations

import re
import unicodedata

STOP_TOKENS = {
    # it
    "stop", "stoppa", "fermati", "ferma", "fermo", "fermatevi", "fermare", "fermalo", "basta", "alt", "arresta",
    "arrestati", "arresto", "blocca", "bloccati", "bloccalo", "emergenza",
    # en / de / fr / es
    "halt", "stopp", "freeze", "emergency", "anhalten", "arrete", "arretez", "arreter", "detente", "detengase",
    "parate",
}
# Tokens that are also ordinary words ("para" = "for" in Spanish): STOP only in very short utterances.
SHORT_STOP_TOKENS = {"para", "pare", "parar", "deten", "halte"}
SHORT_STOP_MAX_TOKENS = 2
STOP_PHRASES = ["arresta il robot", "blocca tutto", "fermati immediatamente", "fermo cosi", "halte an", "stop it",
                "no te muevas", "ne bouge pas", "nicht bewegen", "don t move"]
CJK_STOP = ["停", "别动", "不要动", "住手", "急停", "打住", "止まれ", "止まって", "止めて", "止めろ", "ストップ",
            "やめて", "やめろ", "動くな"]

AFFIRM_TOKENS = {
    "si", "confermo", "conferma", "confermato", "confermata", "confermare", "confermi", "confermiamo", "procedi",
    "procedere", "prosegui", "vai", "ok", "okay", "certo", "esatto", "fallo", "fai", "d'accordo",
    "perfetto", "avanti", "affermativo", "accordo", "corretto", "giusto", "certamente", "assolutamente",
    "yes", "yeah", "yep", "confirm", "confirmed", "proceed", "go", "sure", "oui", "ja",
    # es / fr / de
    "adelante", "vale", "claro", "hazlo", "dale", "confirme", "allez", "bestatige", "bestatigt", "genau",
    "jawohl", "klar", "mach",
}
AFFIRM_PHRASES = ["va bene", "puoi farlo", "puoi procedere", "fai pure", "vai pure", "dai pure", "d accord",
                  "go ahead", "do it", "vas y", "de acuerdo", "mach das"]
CJK_AFFIRM = ["是", "好", "可以", "确认", "確認", "确定", "行", "对", "没问题", "执行", "继续", "开始吧", "嗯",
              "はい", "ええ", "うん", "お願い", "どうぞ", "いいよ", "いいです", "オッケー", "了解", "実行", "進めて"]
# Affirmative expressions that contain a negation character and must not count as "no".
CJK_AFFIRM_WITH_NEGATION = ["没问题", "沒問題", "不错", "問題ない"]

NEGATIVE_TOKENS = {"no", "non", "annulla", "annullare", "annullato", "annulliamo", "negativo", "cancella", "cancel",
                   "nope", "nein", "niente", "lascia", "dont", "not", "never", "mai",
                   "nunca", "cancela", "cancelar", "pas", "annule", "jamais", "nicht", "abbrechen", "abbruch", "kein",
                   "abort"}
CJK_NEGATIVE = ["不", "别", "沒", "没", "取消", "否", "算了", "いいえ", "いや", "だめ", "ダメ", "キャンセル", "中止",
                "しないで"]

UNCERTAIN_TOKENS = {"forse", "magari", "credo", "penso", "boh", "dubbio", "aspetta", "aspettate", "attimo", "momento",
                    "sicuro", "sicura", "probabilmente", "mah", "vediamo", "dipende", "maybe", "perhaps", "wait",
                    "possibly", "quasi", "ehm", "quizas", "quiza", "espera", "creo", "attends", "attendez",
                    "vielleicht", "warte", "glaube", "moment"}
UNCERTAIN_PHRASES = ["tal vez", "peut etre", "not sure"]
CJK_UNCERTAIN = ["好像", "也许", "可能", "等一下", "等等", "等下", "吗", "嗎", "呢", "たぶん", "多分", "かも", "待って",
                 "ちょっと", "かな"]

CANCEL_PHRASES = ["annulla", "lascia perdere", "non farlo", "cancella", "lascia stare", "non importa", "cancel",
                  "never mind", "forget it", "cancela", "annule", "abbrechen"]
CJK_CANCEL = ["取消", "算了", "不要", "キャンセル", "やめる", "中止"]

# verdicts
VALID = "valida"
NEGATIVE = "negativa"
UNCERTAIN = "incerta"
ABSENT = "assente"
STOP = "stop"

_CJK_RANGE = "\u3040-\u30ff\u3400-\u9fff"
_CJK = re.compile(f"[{_CJK_RANGE}]")


def _strip_accents(c: str) -> str:
    if c < "\u0250":
        return "".join(x for x in unicodedata.normalize("NFKD", c) if not unicodedata.combining(x))
    return c


def normalize(text: str | None) -> str:
    """Lowercase, accents stripped for Latin letters; CJK characters kept as they are."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text).lower()
    t = "".join(_strip_accents(c) for c in t)
    t = t.replace("'", " ").replace("’", " ")
    return re.sub(r"\s+", " ", re.sub(rf"[^a-z0-9? {_CJK_RANGE}]", " ", t)).strip()


def tokens(text: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalize(text))


def _has_phrase(norm_text: str, phrases: list[str]) -> bool:
    padded = f" {norm_text.replace('?', ' ')} "
    return any(f" {p} " in padded for p in phrases)


def _cjk_has(norm_text: str, words: list[str]) -> bool:
    return bool(_CJK.search(norm_text)) and any(w in norm_text for w in words)


def is_stop(text: str | None) -> bool:
    if not text:
        return False
    n = normalize(text)
    toks = tokens(text)
    if set(toks) & STOP_TOKENS or _has_phrase(n, STOP_PHRASES) or _cjk_has(n, CJK_STOP):
        return True
    return len(toks) <= SHORT_STOP_MAX_TOKENS and bool(set(toks) & SHORT_STOP_TOKENS)


def is_cancel(text: str | None) -> bool:
    n = normalize(text)
    if not n:
        return False
    return (_has_phrase(n, CANCEL_PHRASES) or tokens(text) in (["no"], ["non"], ["nein"]) or n.startswith("no ")
            or _cjk_has(n, CJK_CANCEL))


def confirmation_verdict(text: str | None) -> str:
    """valida | negativa | incerta | assente | stop — only 'valida' authorises motion."""
    if not text or not text.strip():
        return ABSENT
    if is_stop(text):
        return STOP
    n = normalize(text)
    toks = set(tokens(text))
    cjk_neg_text = n
    for phrase in CJK_AFFIRM_WITH_NEGATION:
        cjk_neg_text = cjk_neg_text.replace(phrase, " ")
    if toks & NEGATIVE_TOKENS or _cjk_has(cjk_neg_text, CJK_NEGATIVE):
        return NEGATIVE
    if toks & UNCERTAIN_TOKENS or "?" in n or _has_phrase(n, UNCERTAIN_PHRASES) or _cjk_has(n, CJK_UNCERTAIN):
        return UNCERTAIN
    if toks & AFFIRM_TOKENS or _has_phrase(n, AFFIRM_PHRASES) or _cjk_has(n, CJK_AFFIRM + CJK_AFFIRM_WITH_NEGATION):
        return VALID
    return ABSENT
