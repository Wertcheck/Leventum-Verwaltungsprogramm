import { useState } from "react";
import { api, ApiError } from "../lib/api";
import { dateDe, eur, useFetch } from "../lib/hooks";
import { Badge, Card, EmptyState, PageHeader } from "../components/ui";
import { Modal } from "../components/Form";

interface Cand { charge_id: number; lease_id: number; due_date: string; open_amount: string; days_overdue: number; proposed_level: number; state: string; charge_type: string }
interface Notice { id: number; lease_id: number; level: number; level_name: string; status: string; recipient_name: string; subject: string; body: string; total_open: string; review_hint: string | null; sent_on: string | null; lines?: unknown[] }
const STATE: Record<string, string> = { due: "Mahnung fällig", waiting: "Wartefrist läuft", draft_exists: "Entwurf vorhanden", max_level_reached: "Höchste Stufe erreicht" };
const NST: Record<string, [string, "ok" | "warn" | "err"]> = { draft: ["Entwurf", "warn"], approved: ["Freigegeben (nicht versandt)", "warn"], sent: ["Versandt (manuell dokumentiert)", "ok"], cancelled: ["Verworfen", "err"] };

export function NoticeEditor({ id, onClose }: { id: number; onClose: () => void }) {
  const { data, reload } = useFetch<Notice & { history: { at: string; summary: string }[] }>(`/dunning/notices/${id}`);
  const [body, setBody] = useState<string | null>(null), [err, setErr] = useState("");
  if (!data) return null;
  async function run(fn: () => Promise<unknown>) { setErr(""); try { await fn(); reload(); } catch (e) { setErr(e instanceof ApiError ? e.message : "Fehler"); } }
  const text = body ?? data.body;
  return (
    <Modal title={`${data.level_name} – ${data.recipient_name}`} onClose={onClose}>
      <div className="alert warn">{data.review_hint}</div>
      <p><Badge tone={NST[data.status][1]}>{NST[data.status][0]}</Badge> Gesamt offen: <strong>{eur(data.total_open)}</strong></p>
      <textarea className="field" rows={14} value={text} disabled={data.status !== "draft"} onChange={(e) => setBody(e.target.value)} aria-label="Mahnschreiben" />
      {err && <div className="alert err" role="alert">{err}</div>}
      <div className="toolbar">
        {data.status === "draft" && <>
          <button className="btn" onClick={() => run(() => api(`/dunning/notices/${id}`, { method: "PATCH", json: { body: text } }))}>Text speichern</button>
          <button className="btn primary" onClick={() => run(async () => { await api(`/dunning/notices/${id}`, { method: "PATCH", json: { body: text } }); await api(`/dunning/notices/${id}/approve`, { method: "POST" }); })}>Geprüft – freigeben</button>
          <button className="btn danger" onClick={() => { const r = window.prompt("Grund für das Verwerfen"); if (r) run(() => api(`/dunning/notices/${id}/cancel`, { method: "POST", json: { reason: r } })); }}>Verwerfen</button></>}
        {data.status === "approved" && <>
          <button className="btn primary" onClick={() => { const via = window.prompt("Wie wurde das Schreiben versandt? (z. B. Brief, E-Mail)"); if (via) run(() => api(`/dunning/notices/${id}/mark-sent`, { method: "POST", json: { sent_on: new Date().toISOString().slice(0, 10), via } })); }}>Als versandt dokumentieren</button>
          <button className="btn danger" onClick={() => { const r = window.prompt("Grund"); if (r) run(() => api(`/dunning/notices/${id}/cancel`, { method: "POST", json: { reason: r } })); }}>Verwerfen</button></>}
      </div>
      <p className="muted">Die Software versendet nichts. Der Versand erfolgt außerhalb und wird hier nur dokumentiert.</p>
      <h2>Protokoll</h2>{data.history.map((h, i) => <div className="list-row" key={i}><span className="muted">{dateDe(h.at)}</span><span>{h.summary}</span></div>)}
    </Modal>
  );
}

export default function DunningPage() {
  const cands = useFetch<{ items: Cand[]; note: string }>("/dunning/overdue");
  const notices = useFetch<{ items: Notice[] }>("/dunning/notices");
  const [open, setOpen] = useState<number | null>(null), [msg, setMsg] = useState("");
  const due = cands.data?.items.filter((c) => c.state === "due") ?? [];
  async function prepare() { const r = await api<{ created: Notice[] }>("/dunning/prepare", { method: "POST", json: {} }); setMsg(`${r.created.length} Entwurf/Entwürfe angelegt – bitte prüfen und freigeben.`); cands.reload(); notices.reload(); }
  return (
    <>
      <PageHeader title="Mahnwesen" subtitle="Zahlungserinnerung → 1. Mahnung → 2. Mahnung. Entwürfe müssen manuell geprüft und freigegeben werden; kein automatischer Versand, keine Gebühren/Zinsen." />
      {msg && <div className="alert ok" role="status">{msg}</div>}
      <Card>
        <div className="card-head"><h2>Überfällige Forderungen</h2><button className="btn primary" disabled={due.length === 0} onClick={prepare}>Entwürfe vorbereiten ({due.length})</button></div>
        {cands.data && cands.data.items.length === 0 ? <EmptyState title="Keine überfälligen Forderungen" /> : (
          <table><thead><tr><th>Vertrag</th><th>Fällig</th><th>Offen (nach Teilzahlungen)</th><th>Überfällig</th><th>Nächste Stufe</th><th>Status</th></tr></thead>
            <tbody>{cands.data?.items.map((c) => <tr key={c.charge_id}><td>#{c.lease_id}</td><td>{dateDe(c.due_date)}</td><td>{eur(c.open_amount)}</td><td>{c.days_overdue} Tage</td><td>{c.state === "max_level_reached" ? "–" : c.proposed_level}</td><td>{STATE[c.state]}</td></tr>)}</tbody></table>)}
      </Card>
      <div style={{ height: 20 }} />
      <Card><div className="card-head"><h2>Mahnvorgänge</h2></div>
        {notices.data && notices.data.items.length === 0 ? <EmptyState title="Noch keine Mahnvorgänge" /> : (
          <table><thead><tr><th>Stufe</th><th>Empfänger</th><th>Betrag</th><th>Status</th><th /></tr></thead>
            <tbody>{notices.data?.items.map((n) => <tr key={n.id}><td>{n.level_name}</td><td>{n.recipient_name}</td><td>{eur(n.total_open)}</td><td><Badge tone={NST[n.status][1]}>{NST[n.status][0]}</Badge></td><td><button className="btn small" onClick={() => setOpen(n.id)}>Öffnen</button></td></tr>)}</tbody></table>)}
      </Card>
      {open !== null && <NoticeEditor id={open} onClose={() => { setOpen(null); notices.reload(); cands.reload(); }} />}
    </>
  );
}
