export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init;
  const res = await fetch(`/api/v1${path}`, {
    credentials: "same-origin",
    ...rest,
    headers: { "X-Leventum-Client": "1", ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...rest.headers },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (!res.ok) {
    let code = "error", msg = `Fehler ${res.status}`;
    try { const b = await res.json(); const d = b.detail; if (d && typeof d === "object") { code = d.code ?? code; msg = d.detail ?? msg; } else if (typeof d === "string") msg = d; } catch { /* kein JSON */ }
    throw new ApiError(res.status, code, msg);
  }
  return (await res.json()) as T;
}

export interface User { id: number; username: string; display_name: string; role: string }
export interface Kpi { key: string; label: string; value: number | null; available: boolean; planned_phase: string }
export interface DashboardData { kpis: Kpi[] }
export interface BackupList { items: { id: string; size: number; created_at: string }[]; last_backup_at: string | null; age_hours: number | null; stale: boolean }
