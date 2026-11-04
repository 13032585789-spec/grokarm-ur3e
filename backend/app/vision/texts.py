"""Localised operator messages for the inspection flow (spoken by Grok, shown in the UI)."""

from __future__ import annotations

T: dict[str, dict[str, str]] = {
    "verdict_PASS": {"it": "APPROVATO", "en": "PASS", "zh": "合格", "es": "APROBADO", "fr": "CONFORME", "de": "IN ORDNUNG",
                     "ja": "合格"},
    "verdict_FAIL": {"it": "SCARTATO", "en": "FAIL", "zh": "不合格", "es": "RECHAZADO", "fr": "NON CONFORME",
                     "de": "FEHLERHAFT", "ja": "不合格"},
    "question": {
        "it": "Ispezione completata. Esito: {verdict}. {reason} Lo deposito nel vassoio {tray}. Confermi?",
        "en": "Inspection complete. Result: {verdict}. {reason} I will place it in tray {tray}. Proceed?",
        "zh": "检测完成。结果：{verdict}。{reason} 我将把它放进 {tray} 托盘。确认吗？",
        "es": "Inspección completada. Resultado: {verdict}. {reason} Lo dejo en la bandeja {tray}. ¿Confirmas?",
        "fr": "Inspection terminée. Résultat : {verdict}. {reason} Je le dépose dans le bac {tray}. Tu confirmes ?",
        "de": "Prüfung abgeschlossen. Ergebnis: {verdict}. {reason} Ich lege es in Schale {tray}. Bestätigst du?",
        "ja": "検査完了。結果：{verdict}。{reason} トレイ{tray}に置きます。よろしいですか？",
    },
    "unsure": {
        "it": "Non riesco a giudicare il pezzo. {reason} Decidi tu: approvato (vassoio {pass_tray}) o scartato "
              "(vassoio {fail_tray})?",
        "en": "I cannot judge this part. {reason} Your call: approve (tray {pass_tray}) or reject (tray {fail_tray})?",
        "zh": "我无法判断这个零件。{reason} 请你决定：合格（{pass_tray} 托盘）还是不合格（{fail_tray} 托盘）？",
        "es": "No puedo juzgar la pieza. {reason} Decide tú: aprobar (bandeja {pass_tray}) o rechazar "
              "(bandeja {fail_tray}).",
        "fr": "Je ne peux pas juger la pièce. {reason} À toi de décider : accepter (bac {pass_tray}) ou rejeter "
              "(bac {fail_tray}) ?",
        "de": "Ich kann das Teil nicht beurteilen. {reason} Deine Entscheidung: annehmen (Schale {pass_tray}) oder "
              "aussortieren (Schale {fail_tray})?",
        "ja": "この部品は判断できません。{reason} 合格（トレイ{pass_tray}）か不合格（トレイ{fail_tray}）か決めてください。",
    },
    "no_frame": {
        "it": "Nessuna immagine recente dalla telecamera: controlla la telecamera, poi chiedi di ripetere l'ispezione.",
        "en": "No recent camera image: check the camera, then ask me to inspect again.",
        "zh": "没有收到最新的相机画面：请检查相机，然后让我重新检测。",
        "es": "No hay imagen reciente de la cámara: revísala y pídeme repetir la inspección.",
        "fr": "Aucune image récente de la caméra : vérifie-la puis demande-moi de refaire l'inspection.",
        "de": "Kein aktuelles Kamerabild: prüfe die Kamera und bitte mich dann, erneut zu prüfen.",
        "ja": "カメラの最新画像がありません。カメラを確認してから再検査を指示してください。",
    },
    "vlm_error": {
        "it": "Il modello di visione non ha risposto ({error}).", "en": "The vision model did not answer ({error}).",
        "zh": "视觉模型没有给出结果（{error}）。", "es": "El modelo de visión no respondió ({error}).",
        "fr": "Le modèle de vision n'a pas répondu ({error}).", "de": "Das Bildmodell hat nicht geantwortet ({error}).",
        "ja": "画像モデルが応答しませんでした（{error}）。",
    },
    "next_part": {
        "it": "Pezzo depositato nel vassoio {tray}. Metti il prossimo pezzo nel vassoio {input_tray} e dimmi di "
              "continuare l'ispezione.",
        "en": "Part placed in tray {tray}. Put the next part in tray {input_tray} and tell me to continue the inspection.",
        "zh": "零件已放进 {tray} 托盘。请把下一个零件放进 {input_tray} 托盘，然后让我继续检测。",
        "es": "Pieza dejada en la bandeja {tray}. Pon la siguiente en la bandeja {input_tray} y dime que continúe.",
        "fr": "Pièce déposée dans le bac {tray}. Mets la suivante dans le bac {input_tray} et dis-moi de continuer.",
        "de": "Teil in Schale {tray} abgelegt. Lege das nächste Teil in Schale {input_tray} und sag mir, ich soll "
              "weitermachen.",
        "ja": "部品をトレイ{tray}に置きました。次の部品をトレイ{input_tray}に置いて、検査の続行を指示してください。",
    },
}


def t(key: str, lang: str, **kw: object) -> str:
    table = T[key]
    return table.get(lang, table["en"]).format(**kw)
