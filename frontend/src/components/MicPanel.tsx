import { spokenName, useT } from "../i18n";
import type { VoiceState } from "../services/voice";

export function MicPanel({ state, detail, level, onStart, onPause, onStop, available }: {
  state: VoiceState; detail: string; level: number; available: boolean;
  onStart: () => void; onPause: (p: boolean) => void; onStop: () => void;
}) {
  const { lang, t } = useT();
  const live = state === "live" || state === "paused" || state === "reconnecting";
  const pct = Math.min(100, Math.round(Math.sqrt(level) * 220));
  return (
    <section className="card mic">
      {!live ? (
        <button className="mic-start" onClick={onStart} disabled={!available || state === "starting"}>
          <span className="mic-icon" aria-hidden>●</span>
          {state === "starting" ? t("mic_starting") : t("mic_start")}
        </button>
      ) : (
        <div className="mic-live">
          <div className={`mic-orb ${state}`} style={{ ["--lvl" as any]: `${pct}%` }} aria-hidden />
          <div className="mic-info">
            <div className="mic-title">
              {state === "paused" ? t("mic_paused") : state === "reconnecting" ? t("mic_reconnecting")
                : t("mic_live", { lang: spokenName(lang) })}
            </div>
            <div className="meter"><div className="meter-fill" style={{ width: `${state === "live" ? pct : 0}%` }} /></div>
            <div className="mic-actions">
              <button onClick={() => onPause(state !== "paused")}>{state === "paused" ? t("mic_resume") : t("mic_pause")}</button>
              <button onClick={onStop}>{t("mic_close")}</button>
            </div>
          </div>
        </div>
      )}
      {!available && <p className="hint">{t("mic_no_grok")}</p>}
      {state === "error" && <p className="hint bad">{detail || t("mic_error")}</p>}
    </section>
  );
}
