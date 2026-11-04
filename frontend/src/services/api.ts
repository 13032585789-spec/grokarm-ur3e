// REST calls. STOP goes straight to the backend: it never depends on the voice session or Grok.

export async function stopRobot(source: "button" | "space"): Promise<any> {
  const r = await fetch("/api/stop", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source }), keepalive: true,
  });
  return r.json();
}

export async function resetSystem(): Promise<{ ok: boolean; messaggio?: string }> {
  const r = await fetch("/api/reset", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ operator_confirmed: true }),
  });
  return r.json();
}

export async function textCommand(text: string, engine: "rules" | "grok"): Promise<any> {
  const r = await fetch("/api/text-command", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, engine, request_id: crypto.randomUUID() }),
  });
  if (!r.ok) throw new Error((await r.json()).detail ?? r.statusText);
  return r.json();
}

export async function fetchEval(): Promise<any> {
  return (await fetch("/api/eval/latest")).json();
}

async function post(url: string, body?: unknown): Promise<any> {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (r.status >= 500) throw new Error(data.detail ?? r.statusText);
  return data;
}

export const setLanguage = (lang: string) => post("/api/language", { lang });
export const startInspection = (rule: string) => post("/api/inspection/start", { rule: rule || null });
export const pointAtCup = (colour: string) => post("/api/vision/point", { colour });
export const scanCups = async () => (await fetch("/api/vision/cups")).json();
export const partReady = () => post("/api/world/part-ready");

export async function pushFrame(jpeg: Blob): Promise<void> {
  await fetch("/api/camera/frame", { method: "POST", headers: { "Content-Type": "image/jpeg" }, body: jpeg });
}
