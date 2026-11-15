import { useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { dateDe, useFetch } from "../lib/hooks";
import { Badge, Card, EmptyState, PageHeader } from "../components/ui";
import { Field, Modal, Select, Text } from "../components/Form";

export interface TaskRow { id: number; title: string; description: string | null; priority: string; status: string; due_date: string | null; overdue: boolean; lease_id: number | null; party_id: number | null; property_id: number | null; repair_id: number | null }
export const PRIO: Record<string, string> = { low: "Niedrig", normal: "Normal", high: "Hoch", urgent: "Dringend" };
export const TSTATUS: Record<string, string> = { open: "Offen", in_progress: "In Bearbeitung", waiting: "Wartet auf Rückmeldung", done: "Erledigt", cancelled: "Abgebrochen" };
const tone = (s: string): "ok" | "warn" | "err" => (s === "done" ? "ok" : s === "cancelled" ? "err" : "warn");

export function TaskLinks({ t }: { t: TaskRow }) {
  return <>{t.lease_id && <Link className="link" to={`/vertraege/${t.lease_id}`}>Vertrag #{t.lease_id}</Link>} {t.repair_id && <Link className="link" to={`/reparaturen/${t.repair_id}`}>Reparatur #{t.repair_id}</Link>} {t.party_id && <Link className="link" to={`/parteien/${t.party_id}`}>Partei #{t.party_id}</Link>}</>;
}

export function TaskForm({ defaults, onDone }: { defaults?: Record<string, number>; onDone: () => void }) {
  const [f, setF] = useState<Record<string, string>>({ priority: "normal" }), [err, setErr] = useState("");
  const set = (k: string) => (v: string) => setF({ ...f, [k]: v });
  async function save() {
    setErr("");
    try { await api("/tasks", { method: "POST", json: { title: f.title, description: f.description || null, priority: f.priority, due_date: f.due || null, ...defaults } }); onDone(); } catch (e) { setErr(e instanceof ApiError ? e.message : "Fehler"); }
  }
  return (
    <div className="form-grid">
      <div className="full"><Field label="Titel"><Text value={f.title ?? ""} onChange={set("title")} /></Field></div>
      <Field label="Priorität"><Select value={f.priority} onChange={set("priority")} options={Object.entries(PRIO).map(([value, label]) => ({ value, label }))} /></Field>
      <Field label="Fällig am"><Text type="date" value={f.due ?? ""} onChange={set("due")} /></Field>
      <div className="full"><Field label="Beschreibung"><Text value={f.description ?? ""} onChange={set("description")} /></Field></div>
      <div className="full">{err && <div className="alert err">{err}</div>}<button className="btn primary" onClick={save}>Aufgabe anlegen</button></div>
    </div>
  );
}

export default function TasksPage() {
  const [status, setStatus] = useState(""), [prio, setPrio] = useState(""), [overdue, setOverdue] = useState(false), [q, setQ] = useState(""), [open, setOpen] = useState(false);
  const qs = new URLSearchParams({ ...(status && { status }), ...(prio && { priority: prio }), ...(overdue && { overdue: "true" }), ...(q && { q }) }).toString();
  const { data, error, reload } = useFetch<{ items: TaskRow[] }>(`/tasks?${qs}`);
  async function setS(t: TaskRow, s: string) {
    let note: string | null = null;
    if (s === "cancelled") { note = window.prompt("Begründung für das Abbrechen"); if (!note) return; }
    try { await api(`/tasks/${t.id}/status`, { method: "POST", json: { status: s, note } }); reload(); } catch (e) { window.alert(e instanceof ApiError ? e.message : "Fehler"); }
  }
  return (
    <>
      <PageHeader title="Aufgaben" subtitle="Aufgaben zu Mietern, Objekten, Verträgen, Rechnungen und Reparaturen" />
      <Card>
        <div className="toolbar">
          <input className="field" placeholder="Aufgabe suchen …" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Suche" />
          <Select value={status} onChange={setStatus} empty="Alle Status" options={Object.entries(TSTATUS).map(([value, label]) => ({ value, label }))} />
          <Select value={prio} onChange={setPrio} empty="Alle Prioritäten" options={Object.entries(PRIO).map(([value, label]) => ({ value, label }))} />
          <label style={{ flexDirection: "row", alignItems: "center", fontWeight: 400 }}><input type="checkbox" checked={overdue} onChange={(e) => setOverdue(e.target.checked)} /> nur überfällige</label>
          <div className="grow" /><button className="btn primary" onClick={() => setOpen(true)}>Aufgabe anlegen</button>
        </div>
        {error && <div className="alert err">{error}</div>}
        {data && data.items.length === 0 ? <EmptyState title="Keine Aufgaben" /> : (
          <table><thead><tr><th>Aufgabe</th><th>Priorität</th><th>Fällig</th><th>Bezug</th><th>Status</th></tr></thead>
            <tbody>{data?.items.map((t) => <tr key={t.id}>
              <td><strong>{t.title}</strong>{t.description && <div className="muted">{t.description}</div>}</td><td>{PRIO[t.priority]}</td>
              <td>{dateDe(t.due_date)} {t.overdue && <Badge tone="err">überfällig</Badge>}</td><td><TaskLinks t={t} /></td>
              <td><Badge tone={tone(t.status)}>{TSTATUS[t.status]}</Badge> <select className="field" aria-label={`Status ${t.title}`} value={t.status} onChange={(e) => setS(t, e.target.value)} style={{ padding: "4px 8px", marginLeft: 6 }}>{Object.entries(TSTATUS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></td></tr>)}</tbody></table>)}
      </Card>
      {open && <Modal title="Aufgabe anlegen" onClose={() => setOpen(false)}><TaskForm onDone={() => { setOpen(false); reload(); }} /></Modal>}
    </>
  );
}
