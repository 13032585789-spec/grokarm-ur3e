import { LANGS, useT } from "../i18n";
import type { Config, RobotStatus, UiState, VoiceStatus } from "../services/types";

export function Header({ ui, config, robot, voice, onLang }: { ui: UiState; config: Config | null; robot?: RobotStatus;
  voice: VoiceStatus; onLang: (lang: string) => void }) {
  const { lang, t } = useT();
  const mode = config?.mode;
  const grok = !config?.grok_configured ? [t("not_configured"), "off"]
    : voice === "connected" ? [t("connected"), "ok"]
    : voice === "reconnecting" || voice === "connecting" ? [t("reconnecting"), "warn"]
    : voice === "error" ? [t("error"), "bad"] : [t("idle"), "off"];
  const rob = !robot ? ["—", "off"] : !robot.connected ? [t("not_connected"), "bad"]
    : robot.safety && !["NORMAL", "REDUCED"].includes(robot.safety) ? [robot.safety, "bad"]
    : [robot.moving ? t("moving") : `${robot.robot_mode ?? t("connected")}`, robot.moving ? "warn" : "ok"];
  return (
    <header className="header">
      <div className="brand">
        <div className="logo">VOCE</div>
        <div className="tagline">{t("tagline")}</div>
      </div>
      <div className="badges">
        <label className="lang-switch">
          <span className="sr-only">{t("language")}</span>
          <select value={lang} onChange={(e) => onLang(e.target.value)} aria-label={t("language")}>
            {LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
          </select>
        </label>
        {mode === "real"
          ? <span className="badge real">{t("mode_real")}</span>
          : <span className="badge mode">{mode === "ursim" ? t("mode_ursim") : t("mode_sim")}</span>}
        <span className={`badge dot ${grok[1]}`}>{t("grok")}: {grok[0]}</span>
        <span className={`badge dot ${rob[1]}`}>{t("robot")}: {rob[0]}</span>
        <span className={`state state-${ui}`}>{t(`st_${ui}` as any)}</span>
      </div>
    </header>
  );
}
