"""Baseline: fixed keyword rules over the same skills, with no language model."""
from __future__ import annotations

from .speech_rules import normalize

RULES = [
    ("point_left", ("sinistra",)),
    ("point_right", ("destra",)),
    ("go_to_safe_pose", ("home", "sicura", "riposo")),
]


def parse(text: str) -> str:
    """Return a skill id, or "none" when no rule matches."""
    words = normalize(text).split()
    for skill_id, keywords in RULES:
        if any(k in words for k in keywords):
            return skill_id
    return "none"
