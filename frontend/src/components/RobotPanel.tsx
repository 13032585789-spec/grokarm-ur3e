import { useT } from "../i18n";
import type { Layout, Status } from "../services/types";

// Schematic top view: base-joint angle only (not a kinematic rendering).
function TopView({ layout, joints, trays, holding, labels }: { layout: Layout; joints: number[] | null; trays: string[];
  holding: boolean; labels: Record<string, string> }) {
  const { t } = useT();
  const W = 320, H = 190, cx = W / 2, cy = H - 18, R = 140;
  const zones = Object.entries(layout.zones);
  // map base angle so the zone fan is centred and spread over ±70°
  const angs = zones.map(([, a]) => a);
  const mid = (Math.max(...angs) + Math.min(...angs)) / 2;
  const toScreen = (a: number) => -Math.PI / 2 - (a - mid) * 1.4;
  const pt = (a: number, r: number) => [cx + r * Math.cos(toScreen(a)), cy + r * Math.sin(toScreen(a))];
  const base = joints?.[0];
  const reach = joints ? 70 + 55 * Math.min(1, Math.abs(Math.cos(joints[1] ?? 0)) + 0.3) : 90;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="topview" role="img" aria-label="Vista schematica dall'alto">
      <path d={`M ${cx - R} ${cy} A ${R} ${R} 0 0 1 ${cx + R} ${cy}`} className="reach" />
      {zones.map(([z, a]) => {
        const [x, y] = pt(a, R - 18);
        const has = trays.includes(z);
        return (
          <g key={z}>
            <rect x={x - 30} y={y - 16} width={60} height={32} rx={6} className={`zone ${has ? "has" : ""}`} />
            <text x={x} y={y + 30} className="zone-label">{labels[z] ? `${labels[z]} · ${z}` : z}</text>
            {has && <text x={x} y={y + 5} className="tray-label">{t("tray")}</text>}
          </g>
        );
      })}
      {base !== undefined && (() => {
        const [x, y] = pt(base, reach);
        return (
          <g>
            <line x1={cx} y1={cy} x2={x} y2={y} className="arm" />
            <circle cx={x} cy={y} r={holding ? 10 : 7} className={`tool ${holding ? "holding" : ""}`} />
          </g>
        );
      })()}
      <circle cx={cx} cy={cy} r={13} className="base" />
    </svg>
  );
}

export function RobotPanel({ status, layout, joints, zoneLabels }: { status: Status | null; layout: Layout | null;
  joints: number[] | null; zoneLabels?: Record<string, string> }) {
  const { t } = useT();
  if (!status) return null;
  const r = status.robot;
  const w = status.world;
  const q = joints ?? r.joints;
  return (
    <section className="card robot">
      <h2>Robot <span className="sub">{status.robot_adapter}</span></h2>
      {layout && <TopView layout={layout} joints={q} trays={w.oggetti_presunti.vassoi_in_zona} holding={w.oggetti_presunti.vassoio_sulla_forca} labels={zoneLabels ?? {}} />}
      <div className="kv">
        <div><span>{t("known_pose")}</span><b>{w.robot_verificato.posa_nota ?? "—"}</b></div>
        <div><span>{t("mode")}</span><b>{r.robot_mode ?? "—"}</b></div>
        <div><span>{t("safety")}</span><b className={r.safety && r.safety !== "NORMAL" ? "bad" : ""}>{r.safety ?? "—"}</b></div>
        <div><span>{t("program")}</span><b>{r.program ?? "—"}</b></div>
        {r.remote_control !== null && <div><span>Remote Control</span><b>{r.remote_control ? t("yes") : t("no")}</b></div>}
        <div><span>{t("joints")}</span><b className="mono">{q ? q.map((x) => x.toFixed(2)).join("  ") : "—"}</b></div>
      </div>
      <h3>{t("trays")} <span className="sub">{t("trays_sub")}</span></h3>
      <div className="kv">
        <div><span>{t("in_zone")}</span><b>{w.oggetti_presunti.vassoi_in_zona.map((z) => (zoneLabels?.[z] ? `${zoneLabels[z]} (${z})` : z)).join(", ") || t("none")}</b></div>
        <div><span>{t("on_fork")}</span><b>{w.oggetti_presunti.vassoio_sulla_forca ? t("yes_assumed") : t("no")}</b></div>
      </div>
      {status.fault && <div className="fault-box">{t("fault")}: {status.fault}</div>}
    </section>
  );
}
