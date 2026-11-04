import pytest

from backend.keyword_baseline import parse
from backend.speech_rules import classify_confirmation, has_stop_word


@pytest.mark.parametrize("text", ["Stop!", "fermati", "FERMO", "basta così", "ferma tutto", "alt"])
def test_stop_words(text):
    assert has_stop_word(text)


@pytest.mark.parametrize("text", ["indica a destra", "conferma", "fermamente no", ""])
def test_not_stop_words(text):
    assert not has_stop_word(text)


@pytest.mark.parametrize("text,want", [
    ("Sì", "yes"), ("sì, vai", "yes"), ("va bene", "yes"), ("ok", "yes"), ("conferma", "yes"),
    ("no", "no"), ("sì, anzi no", "no"), ("non farlo", "no"), ("aspetta", "no"), ("sì fermati", "no"),
    ("forse", "unclear"), ("indica a sinistra", "unclear"), ("", "unclear"),
])
def test_confirmation(text, want):
    assert classify_confirmation(text) == want


def test_baseline_is_literal():
    assert parse("Indica a sinistra") == "point_left"
    assert parse("Parcheggia il braccio") == "none"
