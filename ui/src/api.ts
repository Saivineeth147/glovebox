export type Json = Record<string, any>;

async function req<T = Json>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "content-type": "application/json" }, ...init });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail ?? msg; } catch {}
    throw r.status === 401 ? new NotSignedIn(msg) : new Error(msg);
  }
  return r.json();
}

/** Thrown for 401 so the shell can show the sign-in screen instead of an error. */
export class NotSignedIn extends Error {}

export const api = {
  me: () => req<{ email: string; role: string }>("/api/auth/me"),
  signIn: (email: string, password: string) =>
    req<{ email: string; role: string }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  register: (email: string, password: string) =>
    req<{ email: string; role: string }>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  signOut: () => req("/api/auth/logout", { method: "POST" }),
  overview: () => req("/api/overview"),
  runs: () => req<Json[]>("/api/runs"),
  run: (id: string) => req(`/api/runs/${id}`),
  capabilities: () => req<Json[]>("/api/capabilities"),
  capability: (id: string) => req(`/api/capabilities/${id}`),
  tools: () => req<Json[]>("/api/capabilities/tools"),
  approve: (id: string, notes?: string) => req(`/api/capabilities/${id}/approve`, { method: "POST", body: JSON.stringify({ notes }) }),
  discover: (body: Json) => req("/api/discover", { method: "POST", body: JSON.stringify(body) }),
  replay: (body: Json) => req("/api/replay", { method: "POST", body: JSON.stringify(body) }),
  jobs: () => req<Json[]>("/api/jobs"),
  job: (id: string) => req(`/api/jobs/${id}`),
  operator: (jobId: string) => req(`/api/jobs/${jobId}/operator`),
  command: (jobId: string, body: Json) => req(`/api/jobs/${jobId}/operator/command`, { method: "POST", body: JSON.stringify(body) }),
  policy: () => req("/api/policy"),
  armFault: (name: string) => req(`/api/target/faults/${name}`, { method: "POST" }),
  clearFaults: () => req(`/api/target/faults`, { method: "DELETE" }),
};

export function fmtTime(ts?: string | null) {
  if (!ts) return "";
  try { return new Date(ts).toLocaleTimeString([], { hour12: false }); } catch { return ts; }
}
export function fmtDate(ts?: string | null) {
  if (!ts) return "";
  try { return new Date(ts).toLocaleString([], { hour12: false, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); } catch { return ts; }
}
export function duration(a?: string | null, b?: string | null) {
  if (!a || !b) return "";
  const ms = new Date(b).getTime() - new Date(a).getTime();
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}
