"""Deterministic speech rules. These gates do not depend on the model."""
from __future__ import annotations

import re
import unicodedata

STOP_WORDS = {
    "stop", "fermati", "fermo", "ferma", "fermatevi", "basta", "alt", "halt",
    "blocca", "bloccati", "arresta", "arrestati",
}
YES_WORDS = {
    "si", "certo", "conferma", "confermo", "confermato", "vai", "procedi",
    "esegui", "ok", "okay", "fallo", "yes", "confirm", "go",
}
YES_PHRASES = ("va bene", "d accordo", "fai pure")
NO_WORDS = {
    "no", "non", "annulla", "annullare", "negativo", "aspetta", "cancel",
    "cancella", "nope", "lascia",
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def has_stop_word(text: str) -> bool:
    return bool(STOP_WORDS.intersection(normalize(text).split()))


def classify_confirmation(text: str) -> str:
    """Return yes, no or unclear. Any negation or stop word beats any yes."""
    norm = normalize(text)
    words = set(norm.split())
    if words & NO_WORDS or words & STOP_WORDS:
        return "no"
    if words & YES_WORDS or any(p in norm for p in YES_PHRASES):
        return "yes"
    return "unclear"
