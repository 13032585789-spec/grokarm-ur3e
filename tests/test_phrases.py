import pytest

from app.safety.phrases import ABSENT, NEGATIVE, STOP, UNCERTAIN, VALID, confirmation_verdict, is_cancel, is_stop


# spec §9: stop expressions
@pytest.mark.parametrize("t", ["Stop", "Fermati", "Fermati immediatamente", "Ferma", "Basta", "Alt", "Arresta il robot",
                               "Blocca tutto", "FERMATI IMMEDIATAMENTE!", "fermo!", "stop stop", "halt"])
def test_stop_phrases(t):
    assert is_stop(t)


@pytest.mark.parametrize("t", ["solleva il vassoio a sinistra", "indica la zona centrale", "alto", "stoppino", "basso",
                               "sì confermo"])
def test_not_stop(t):
    assert not is_stop(t)


# spec §8: valid confirmations
@pytest.mark.parametrize("t", ["Sì.", "Sì, confermo.", "Confermo.", "Procedi.", "Va bene.", "Puoi farlo.", "ok vai",
                               "yes", "Certo, procedi"])
def test_valid_confirmations(t):
    assert confirmation_verdict(t) == VALID


# spec §8: invalid confirmations
@pytest.mark.parametrize("t,v", [("Forse.", UNCERTAIN), ("Va bene, forse.", UNCERTAIN), ("No.", NEGATIVE),
                                 ("Aspetta.", UNCERTAIN), ("Non sono sicuro.", NEGATIVE), ("Annulla.", NEGATIVE),
                                 ("Sì?", UNCERTAIN), ("sì no aspetta", NEGATIVE), ("", ABSENT),
                                 ("la zona destra", ABSENT), ("sì stop", STOP)])
def test_invalid_confirmations(t, v):
    assert confirmation_verdict(t) == v


@pytest.mark.parametrize("t", ["annulla", "lascia perdere", "no", "no grazie", "non farlo"])
def test_cancel(t):
    assert is_cancel(t)


@pytest.mark.parametrize("t", ["停", "停下！", "快停下来", "别动", "急停", "止まって", "ストップ！", "やめて",
                               "Arrête !", "Halt!", "Stopp", "¡Para!", "para ya", "no te muevas", "Detente"])
def test_stop_multilingual(t):
    assert is_stop(t)


@pytest.mark.parametrize("t", ["lleva la bandeja para la derecha", "inspecciona la bandeja A",
                               "检查托盘A里的零件", "トレイAを検査して", "prüfe das Teil"])
def test_not_stop_multilingual(t):
    assert not is_stop(t)


@pytest.mark.parametrize("t", ["是的", "好的，确认", "可以", "没问题", "はい", "はい、お願いします", "Oui, vas-y",
                               "Sí, adelante", "Ja, genau", "yes, reject it", "Sì, scartalo"])
def test_valid_confirmations_multilingual(t):
    assert confirmation_verdict(t) == VALID


@pytest.mark.parametrize("t,v", [("不", NEGATIVE), ("不要", NEGATIVE), ("不是", NEGATIVE), ("是不是", NEGATIVE),
                                 ("好像可以", UNCERTAIN), ("可以吗", UNCERTAIN), ("等一下", UNCERTAIN),
                                 ("いいえ", NEGATIVE), ("たぶん", UNCERTAIN), ("Non", NEGATIVE),
                                 ("peut-être", UNCERTAIN), ("nein", NEGATIVE), ("vielleicht", UNCERTAIN),
                                 ("los vasos", ABSENT), ("托盘B", ABSENT)])
def test_invalid_confirmations_multilingual(t, v):
    assert confirmation_verdict(t) == v


@pytest.mark.parametrize("t", ["取消", "算了", "キャンセル", "never mind", "nein"])
def test_cancel_multilingual(t):
    assert is_cancel(t)
