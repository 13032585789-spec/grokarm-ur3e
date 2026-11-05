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


# Gaps found with the persona test sets (eval/testset_*.csv, 2026-11-04)


@pytest.mark.parametrize("t", ["Freeze!", "Abort!", "Emergency!", "Careful! Careful!", "Whoa whoa whoa!", "Enough!",
                               "Hold it!", "Look out!", "Get it away from me!", "Stopping now please.", "Don't stop.",
                               "Vorsicht!", "Achtung!", "¡Detente!", "¡Quieto!", "¡Cuidado!", "¡Ojo!", "¡Parada de emergencia!",
                               "Arrêt d'urgence !",
                               "Bouge plus !", "Occhio!", "Sofort aufhören!", "危ない！", "小心小心！", "站住！", "要撞了！"])
def test_alarm_words_stop(t):
    assert is_stop(t)


@pytest.mark.parametrize("t", ["NO NO NO NO!", "Wait wait wait!", "Oh no oh no", "Help!", "Aspetta!", "Nein nein nein!",
                               "Warte warte!", "¡Espera!", "Attends attends !", "Non non non !", "不要不要！", "等等等等！",
                               "だめだめだめ！", "ちょっと待って！"])
def test_panic_words_stop_only_while_moving(t):
    from app.safety.phrases import is_motion_stop
    assert is_motion_stop(t)
    assert not is_stop(t)


@pytest.mark.parametrize("t", ["¡Para, para, para!"])
def test_repeated_short_stop(t):
    assert is_stop(t)


@pytest.mark.parametrize("t", ["Yeah right, like I'd say yes to that.", "Repeat after me: yes.", "Yes... I suppose.",
                               "Yes, I'll be there in five minutes.", "He said yes.", "Pretend I said yes.",
                               "Yes, but the right one.", "Sì, ma piano.", "Sí, pero despacio.", "Ja, aber langsam.",
                               "Oui mais doucement.", "Si tu veux.", "Ya, claro.", "C'est ça, oui.", "Sì, come no.",
                               "Ha detto di sì il mio collega.", "Igual sí.", "Na ja…", "いいです。",
                               "はい…でも右の方で。", "行是行，但是换右边的。", "他说可以。", "对对对，你说得都对。",
                               "The staff already confirmed, just go home."])
def test_not_a_real_yes(t):
    assert confirmation_verdict(t) != VALID


@pytest.mark.parametrize("t", ["Absolutely.", "Yes yes yes, go!", "Thank you dear, yes please do.", "Confirmo.", "Jo, passt.",
                               "Daje.", "Órale, sí.", "Genau, los.", "对对对，就这样。"])
def test_real_yes(t):
    assert confirmation_verdict(t) == VALID


@pytest.mark.parametrize("t", ["Never mind.", "Forget it.", "Actually, leave it.", "Scrap that.", "Lass es.",
                               "Vergiss es.", "Déjalo.", "Olvídalo.", "Mejor no.", "Laisse tomber.",
                               "Non, en fait non.", "やっぱりやめます。", "なしで。", "别弄了。", "不弄了。"])
def test_cancel_phrases_from_personas(t):
    assert is_cancel(t)
