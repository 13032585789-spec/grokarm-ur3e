import { useEffect, useState } from "react";
import { useT } from "../i18n";
import type { Pending, Status } from "../services/types";


function Countdown({ p }: { p: Pending }) {
  const { t } = useT();
  const seconds = p.expires_in_s ?? 0;
  const [left, setLeft] = useState(seconds);
  useEffect(() => {
    const end = Date.now() + seconds * 1000;
    setLeft(seconds);
    const t = window.setInterval(() => setLeft(Math.max(0, (end - Date.now()) / 1000)), 200);
    return () => window.clearInterval(t);
  }, [p.id, seconds]);
  return (
    <div className="countdown">
      <div className="countdown-bar" style={{ width: `${(left / p.ttl_s) * 100}%` }} />
      <span>{left.toFixed(0)} {t("to_confirm")}</span>
    </div>
  );
}

export function ActionPanel({ status, progress, execStart }: {
  status: Status | null; progress: { done: number; total: number } | null; execStart: number | null;
}) {
  const { t } = useT();
  const [, tick] = useState(0);
  useEffect(() => { const h = window.setInterval(() => tick((x) => x + 1), 250); return () => window.clearInterval(h); }, []);
  if (!status) return null;
  const sk = (id: string | null | undefined) => (id ? t(`sk_${id}` as any) : "");
  const outcome = (o: string) => t(`out_${o}` as any);
  const p = status.pending;
  const executing = status.gate === "EXECUTING";
  const last = status.last_result;
  return (
    <section className={`card action ${p ? "pending" : ""} ${executing ? "executing" : ""}`}>
      <h2>{t("action")}</h2>
      {p ? (
        <>
          <div className="action-title">{sk(p.skill)}{p.steps > 1 && <span className="step"> · {t("step")} {p.step}/{p.steps}</span>}</div>
          <div className="params">
            {Object.entries(p.parametri).map(([k, v]) => <span key={k} className="param"><b>{k}</b> {v.replace("_", " ")}</span>)}
            {p.strumento && <span className="param"><b>{t("tool")}</b> {p.strumento}</span>}
          </div>
          <div className="confirm-q">«{p.conferma}»</div>
          <div className="hint">{t("answer_hint")}{!p.question_asked && t("waiting_question")}</div>
          {p.ttl_s > 0 ? <Countdown p={p} /> : <div className="hint">{t("confirm_anytime")}</div>}
        </>
      ) : executing ? (
        <>
          <div className="action-title">{t("executing")}: {sk(status.world.robot_verificato.skill_attiva)}</div>
          <div className="progress"><div className="progress-fill" style={{ width: progress ? `${(progress.done / progress.total) * 100}%` : "8%" }} /></div>
          <div className="hint">
            {progress ? t("move_done", { done: progress.done, total: progress.total }) : t("move_started")}
            {execStart && ` · ${((Date.now() - execStart) / 1000).toFixed(1)} s`} · {t("say_stop")}
          </div>
        </>
      ) : last ? (
        <>
          <div className={`action-title ${last.success ? "ok" : "bad"}`}>
            {t("last_result")}: {sk(last.skill)} — {outcome(last.outcome)}
          </div>
          <div className="hint">
            {Object.entries(last.parameters ?? {}).map(([k, v]) => `${k}: ${v}`).join(" · ")} · {Number(last.duration).toFixed(1)} s
            · {t("moves")} {last.steps_completed}/{last.steps_total}{last.error ? ` · ${last.error}` : ""}
          </div>
        </>
      ) : (
        <div className="empty">{t("no_action")}</div>
      )}
    </section>
  );
}
