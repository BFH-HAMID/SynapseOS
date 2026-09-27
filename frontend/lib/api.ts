// Thin client for the SynapseOS REST API.
// All calls go through the Next.js server-side rewrite /backend-api/* → FastAPI /api/v1/*,
// so the browser never references a backend host directly.
const BASE = "/backend-api";

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text.slice(0, 300)}`);
  }
  return res.json();
}

export const post = <T = any>(path: string, body?: any) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });

export const get = <T = any>(path: string) => api<T>(path);

export function fmt(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

export function timeAgo(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
