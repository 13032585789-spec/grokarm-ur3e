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
    "arrestati", "arresto", "blocca", "bloccati", "bloccalo", "emergenza", "occhio",
    # en / de / fr / es — alarm words, including ones the 2026-11-04 persona set found missing
    "halt", "stopp", "freeze", "emergency", "anhalten", "arrete", "arretez", "arreter", "arret", "detente",
    "detengase", "parate", "stopping", "stopped", "stops", "abort", "careful", "whoa", "enough",
    "aufhoren", "vorsicht", "achtung", "quieto", "cuidado", "ojo", "attention", "emergencia",
}
# Tokens that are also ordinary words ("para" = "for" in Spanish): STOP only in very short utterances.
SHORT_STOP_TOKENS = {"para", "pare", "parar", "deten", "halte"}
SHORT_STOP_MAX_TOKENS = 2
STOP_PHRASES = ["arresta il robot", "blocca tutto", "fermati immediatamente", "fermo cosi", "halte an", "stop it",
                "no te muevas", "ne bouge pas", "nicht bewegen", "don t move", "bouge plus",
                "hold it", "hold on", "look out", "watch out", "get away", "get it away"]
CJK_STOP = ["停", "别动", "不要动", "住手", "急停", "打住", "站住", "小心", "要撞了", "停止", "非常停止",
            "止まれ", "止まって", "止めて", "止めろ", "ストップ", "やめて", "やめろ", "動くな", "危ない"]
# Panic words that stop the arm only while it is moving. Before motion they keep their other meaning
# (cancel, or "not a yes").
MOTION_STOP_TOKENS = {"no", "wait", "aspetta", "help", "aiuto", "attenzione", "attento", "nein", "non",
                      "warte", "espera", "attends", "attendez"}
CJK_MOTION_STOP = ["待って", "だめ", "ダメ", "不要", "等等", "等一下", "等下"]

AFFIRM_TOKENS = {
    "si", "confermo", "conferma", "confermato", "confermata", "confermare", "confermi", "confermiamo", "procedi",
    "procedere", "prosegui", "vai", "ok", "okay", "certo", "esatto", "fallo", "fai", "d'accordo",
    "perfetto", "avanti", "affermativo", "accordo", "corretto", "giusto", "certamente", "assolutamente",
    "yes", "yeah", "yep", "confirm", "confirmed", "proceed", "go", "sure", "oui", "ja",
    "absolutely", "definitely", "correct", "affirmative",
    # es / fr / de / it colloquial
    "adelante", "vale", "claro", "hazlo", "dale", "confirme", "confirmo", "allez", "bestatige", "bestatigt", "genau",
    "jawohl", "klar", "mach", "jo", "passt", "daje",
}
AFFIRM_PHRASES = ["va bene", "puoi farlo", "puoi procedere", "fai pure", "vai pure", "dai pure", "d accord",
                  "go ahead", "do it", "you can", "all right", "that s right", "vas y", "de acuerdo", "mach das"]
CJK_AFFIRM = ["是", "好", "可以", "确认", "確認", "确定", "行", "对", "没问题", "执行", "继续", "开始吧", "嗯",
              "はい", "ええ", "うん", "お願い", "どうぞ", "いいよ", "オッケー", "了解", "実行", "進めて"]
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
                    "vielleicht", "warte", "glaube", "moment", "suppose", "guess", "think", "kinda", "probably",
                    "kidding", "joking", "but", "ma", "pero", "aber", "mais", "tranne", "igual"}
UNCERTAIN_PHRASES = ["tal vez", "peut etre", "not sure"]
CJK_UNCERTAIN = ["好像", "也许", "可能", "等一下", "等等", "等下", "吗", "嗎", "呢", "たぶん", "多分", "かも", "待って",
                 "ちょっと", "かな", "但是", "可是", "不过", "でも"]
# A "yes" inside these is not the operator agreeing (sarcasm, quoting, talking to someone else).
NOT_A_YES_PHRASES = ["yeah right", "repeat after me", "say yes", "said yes", "already confirmed", "ripeti dopo di me", "i ll be there",
                     "arrivo", "pretend", "ha detto", "dice si", "come no", "si tu veux", "ya claro", "c est ca"]
CJK_NOT_A_YES = ["他说", "她说", "他說", "她說", "你说得都对", "いらない"]

CANCEL_PHRASES = ["annulla", "lascia perdere", "non farlo", "cancella", "lascia stare", "non importa", "cancel",
                  "never mind", "nevermind", "forget it", "forget about it", "leave it", "scrap that",
                  "cancela", "annule", "abbrechen", "lass es", "vergiss es", "dejalo", "olvidalo", "mejor no",
                  "laisse tomber", "en fait non", "ci ho ripensato"]
CJK_CANCEL = ["取消", "算了", "不要", "キャンセル", "やめる", "やめます", "中止", "别弄了", "不弄了", "なしで"]

# Words the recogniser should expect in the language the operator selected.
# Italian terms used to be sent in every language, which pulled Spanish/French/German/Japanese
# transcripts toward Italian.
KEYTERMS = {
    "it": ["sinistra", "destra", "avanti", "indietro", "su", "giù", "centimetri", "gradi", "base", "spalla",
           "confermo", "annulla", "fermati", "vassoio"],
    "en": ["left", "right", "forward", "back", "up", "down", "centimetres", "degrees", "base", "shoulder",
           "confirm", "cancel", "stop", "tray"],
    "zh": ["向左", "向右", "向前", "向后", "向上", "向下", "厘米", "度", "底座", "肩膀", "确认", "取消", "停", "托盘"],
    "es": ["izquierda", "derecha", "adelante", "atrás", "arriba", "abajo", "centímetros", "grados", "base",
           "hombro", "confirma", "cancela", "para", "bandeja"],
    "fr": ["gauche", "droite", "avant", "arrière", "haut", "bas", "centimètres", "degrés", "base", "épaule",
           "confirme", "annule", "arrête", "plateau"],
    "de": ["links", "rechts", "vorne", "hinten", "oben", "unten", "Zentimeter", "Grad", "Basis", "Schulter",
           "bestätige", "abbrechen", "halt", "Tablett"],
    "ja": ["左", "右", "前", "後ろ", "上", "下", "センチ", "度", "ベース", "肩", "はい", "キャンセル", "止まって", "トレイ"],
}


def keyterms_for(lang: str | None) -> list[str]:
    """Active language first, then a few stop words from every language. Capped at 100 by the caller."""
    primary = KEYTERMS.get(lang or "", KEYTERMS["en"])
    stops = ["stop", "halt", "停", "止まって", "arrête", "para", "fermati"]
    return list(dict.fromkeys([*primary, *stops]))


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


def _short_stop(toks: list[str]) -> bool:
    """Ordinary words such as Spanish "para" ("for") stop only in a very short utterance,
    or when the whole utterance is that word repeated ("para, para, para")."""
    hit = set(toks) & SHORT_STOP_TOKENS
    if not hit:
        return False
    if len(toks) <= SHORT_STOP_MAX_TOKENS:
        return True
    return set(toks) <= SHORT_STOP_TOKENS


def is_stop(text: str | None) -> bool:
    if not text:
        return False
    n = normalize(text)
    toks = tokens(text)
    if set(toks) & STOP_TOKENS or _has_phrase(n, STOP_PHRASES) or _cjk_has(n, CJK_STOP):
        return True
    return _short_stop(toks)


def is_motion_stop(text: str | None) -> bool:
    """STOP check used while the arm is moving: is_stop, plus panic words like "no!" or "wait!"."""
    if is_stop(text):
        return True
    n = normalize(text)
    if not n:
        return False
    return bool(set(tokens(text)) & MOTION_STOP_TOKENS) or _cjk_has(n, CJK_MOTION_STOP)


def is_cancel(text: str | None) -> bool:
    n = normalize(text)
    if not n:
        return False
    return (_has_phrase(n, CANCEL_PHRASES) or tokens(text) in (["no"], ["non"], ["nein"]) or n.startswith("no ")
            or _cjk_has(n, CJK_CANCEL))


def _hesitant(text: str | None) -> bool:
    """A trailing pause ("yes…", "na ja…") is not a clean yes."""
    return bool(text) and ("…" in text or "..." in text)


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
    if (toks & UNCERTAIN_TOKENS or "?" in n or _hesitant(text) or _has_phrase(n, UNCERTAIN_PHRASES)
            or _has_phrase(n, NOT_A_YES_PHRASES) or _cjk_has(n, CJK_UNCERTAIN) or _cjk_has(n, CJK_NOT_A_YES)):
        return UNCERTAIN
    if toks & AFFIRM_TOKENS or _has_phrase(n, AFFIRM_PHRASES) or _cjk_has(n, CJK_AFFIRM + CJK_AFFIRM_WITH_NEGATION):
        return VALID
    return ABSENT
