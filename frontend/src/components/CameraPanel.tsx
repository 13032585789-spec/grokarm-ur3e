import { useCallback, useEffect, useRef, useState } from "react";
import { useT } from "../i18n";
import { pointAtCup, pushFrame, scanCups } from "../services/api";
import type { CameraStatus } from "../services/types";

const PUSH_MS = 400;
const STORE_KEY = "voce.webcam";

interface SeenCup { colore: string; zona: string }

export function CameraPanel({ camera, source, zoneLabels, canPoint }: { camera: CameraStatus | null | undefined;
  source: "browser" | "url"; zoneLabels?: Record<string, string>; canPoint: boolean }) {
  const { t } = useT();
  const [cupsOn, setCupsOn] = useState(false);
  const [cups, setCups] = useState<SeenCup[] | null>(null);
  const [scanId, setScanId] = useState(0);
  useEffect(() => {
    if (!cupsOn) return;
    let alive = true;
    const run = async () => {
      try {
        const r = await scanCups();
        if (!alive) return;
        if (r.ok) { setCups(r.cups); setScanId(r.frame_id); setErr(""); } else { setCups(null); setErr(r.messaggio ?? ""); }
      } catch { /* next tick */ }
    };
    run();
    const h = window.setInterval(run, 1000);
    return () => { alive = false; window.clearInterval(h); };
  }, [cupsOn]);
  const point = async (colour: string) => {
    const r = await pointAtCup(colour).catch((e) => ({ ok: false, messaggio: String(e) }));
    if (!r.ok) setErr(r.messaggio ?? r.esito ?? "");
  };
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const timer = useRef<number | null>(null);
  const busy = useRef(false);
  const [on, setOn] = useState(false);
  const [err, setErr] = useState("");
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState<string>(() => localStorage.getItem(`${STORE_KEY}.device`) ?? "");
  const [tick, setTick] = useState(0);

  const stop = useCallback(() => {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = null;
    stream.current?.getTracks().forEach((tr) => tr.stop());
    stream.current = null;
    setOn(false);
    localStorage.setItem(STORE_KEY, "off");
  }, []);

  const start = useCallback(async (id = deviceId) => {
    setErr("");
    try {
      stream.current?.getTracks().forEach((tr) => tr.stop());
      const s = await navigator.mediaDevices.getUserMedia({
        video: { deviceId: id ? { exact: id } : undefined, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false,
      });
      stream.current = s;
      if (video.current) { video.current.srcObject = s; await video.current.play().catch(() => undefined); }
      setDevices((await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput"));
      setOn(true);
      localStorage.setItem(STORE_KEY, "on");
      const canvas = document.createElement("canvas");
      if (timer.current) window.clearInterval(timer.current);
      timer.current = window.setInterval(() => {
        const v = video.current;
        if (!v || busy.current || v.videoWidth === 0) return;
        const scale = Math.min(1, 1280 / v.videoWidth);
        canvas.width = Math.round(v.videoWidth * scale);
        canvas.height = Math.round(v.videoHeight * scale);
        canvas.getContext("2d")?.drawImage(v, 0, 0, canvas.width, canvas.height);
        busy.current = true;
        canvas.toBlob((b) => {
          if (!b) { busy.current = false; return; }
          pushFrame(b).catch(() => undefined).finally(() => { busy.current = false; });
        }, "image/jpeg", 0.85);
      }, PUSH_MS);
    } catch (e: any) {
      setErr(`${t("cam_denied")}: ${e?.message ?? e}`);
      setOn(false);
    }
  }, [deviceId, t]);

  useEffect(() => {
    if (source === "browser" && localStorage.getItem(STORE_KEY) === "on") start();
    return () => stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source]);

  useEffect(() => {
    if (source !== "url") return;
    const h = window.setInterval(() => setTick((x) => x + 1), 1000);
    return () => window.clearInterval(h);
  }, [source]);

  const age = camera?.frame?.age_s;
  return (
    <section className="card camera">
      <div className="card-head">
        <h2>{t("camera")} <span className="sub">{source === "browser" ? t("cam_browser") : t("cam_url")}</span></h2>
        {camera?.frame && <span className={`badge dot ${age !== undefined && age < 2 ? "ok" : "warn"}`}>
          {t("cam_age", { age: (age ?? 0).toFixed(1) })}</span>}
      </div>
      <div className="cam-view">
        {cupsOn && cups && <img className="cups-overlay" src={`/api/vision/cups.jpg?f=${scanId}`} alt={t("cups")} />}
        {source === "browser" ? (
          <video ref={video} muted playsInline className={on && !(cupsOn && cups) ? "" : "hidden"} />
        ) : (
          camera?.frame && !(cupsOn && cups) && <img src={`/api/camera/frame.jpg?t=${tick}`} alt={t("camera")} />
        )}
        {((source === "browser" && !on) || (source === "url" && !camera?.frame)) &&
          <div className="cam-empty">{source === "url" ? t("cam_url_hint") : t("cam_none")}</div>}
      </div>
      {source === "browser" && (
        <div className="cam-actions">
          {on ? <button onClick={stop}>{t("cam_stop")}</button> : <button className="primary" onClick={() => start()}>{t("cam_start")}</button>}
          {devices.length > 1 && (
            <select value={deviceId} aria-label={t("cam_device")} onChange={(e) => {
              setDeviceId(e.target.value); localStorage.setItem(`${STORE_KEY}.device`, e.target.value); start(e.target.value);
            }}>
              {devices.map((d, i) => <option key={d.deviceId} value={d.deviceId}>{d.label || `${t("cam_device")} ${i + 1}`}</option>)}
            </select>
          )}
        </div>
      )}
      <label className="switch cups-switch">
        <input type="checkbox" checked={cupsOn} onChange={(e) => { setCupsOn(e.target.checked); if (!e.target.checked) setCups(null); }} />
        <span>{t("cups")}</span>
      </label>
      {cupsOn && cups && (cups.length === 0 ? <div className="empty">{t("cups_none")}</div> : (
        <ul className="cup-list">
          {cups.map((c, i) => (
            <li key={i}>
              <span className={`cup-dot c-${c.colore}`} aria-hidden />
              <b>{t(`colour_${c.colore}` as any)}</b>
              <span className="sub">{zoneLabels?.[c.zona] ? `${zoneLabels[c.zona]} · ` : ""}{c.zona}</span>
              <button disabled={!canPoint} onClick={() => point(c.colore)}>{t("point")}</button>
            </li>
          ))}
        </ul>
      ))}
      {err && <div className="hint bad">{err}</div>}
      {camera?.error && <div className="hint bad">{camera.error}</div>}
    </section>
  );
}
