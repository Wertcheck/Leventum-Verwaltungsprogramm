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

export async function upload<T = unknown>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`/api/v1${path}`, { method: "POST", credentials: "same-origin", headers: { "X-Leventum-Client": "1" }, body: form });
  if (!res.ok) {
    let code = "error", msg = `Fehler ${res.status}`, details: unknown;
    try { const b = await res.json(); const d = b.detail; if (d && typeof d === "object") { code = d.code ?? code; msg = d.detail ?? msg; details = d.details; } } catch { /* kein JSON */ }
    const e = new ApiError(res.status, code, msg); (e as ApiError & { details?: unknown }).details = details; throw e;
  }
  return (await res.json()) as T;
}

export interface User { id: number; username: string; display_name: string; role: string }
export interface Kpi { key: string; label: string; value: number | string | null; format?: string; available: boolean; planned_phase: string; definition?: string; hint?: string | null }
export interface Reminder { key: string; type: string; severity: "critical" | "warning" | "info"; title: string; detail: string; due_date: string | null; task_id: number | null }
export interface DashTask { id: number; title: string; due_date: string | null; overdue: boolean; priority: string; status: string }
export interface DashboardData { kpis: Kpi[]; warnings: Reminder[]; tasks: DashTask[] }
export interface BackupList { items: { id: string; size: number; created_at: string }[]; last_backup_at: string | null; age_hours: number | null; stale: boolean }
