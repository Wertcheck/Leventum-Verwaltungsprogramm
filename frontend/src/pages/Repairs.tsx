import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { dateDe, eur, useFetch } from "../lib/hooks";
import { Badge, Card, EmptyState, PageHeader } from "../components/ui";
import { Field, Modal, Select, Text } from "../components/Form";
import DocPanel from "../components/DocPanel";
import { useDialogs } from "../components/Dialogs";
import { PRIO, TaskForm, TaskLinks, TSTATUS, type TaskRow } from "./Tasks";

interface Costs { estimate: string | null; actual: string; paid: string; open: string; invoice_ids: number[]; deviation_from_estimate: string | null }
interface RepairRow { id: number; property_id: number; unit_id: number | null; title: string; category: string; priority: string; status: string; reported_on: string; scheduled_for: string | null; completed_on: string | null; description: string | null; contractor_party_id: number | null; costs: Costs; is_open: boolean }
interface Detail extends RepairRow { events: { id: number; occurred_at: string; kind: string; text: string }[]; tasks: TaskRow[] }
export const RSTATUS: Record<string, string> = { reported: "Gemeldet", scheduled: "Terminiert", in_progress: "In Arbeit", waiting: "Wartet", done: "Erledigt", cancelled: "Abgebrochen" };
const CAT: Record<string, string> = { heizung: "Heizung", wasserschaden: "Wasserschaden", elektrik: "Elektrik", sanitaer: "Sanitär", fenster: "Fenster", tuerschloss: "Türschloss", instandhaltung: "Instandhaltung", sonstige: "Sonstige" };
const tone = (s: string): "ok" | "warn" | "err" => (s === "done" ? "ok" : s === "cancelled" ? "err" : "warn");

export function RepairsPage() {
  const [openOnly, setOpenOnly] = useState(true), [open, setOpen] = useState(false), nav = useNavigate();
  const { data, error, reload } = useFetch<{ items: RepairRow[] }>(`/repairs?${openOnly ? "open_only=true" : ""}`);
  const props = useFetch<{ items: { id: number; name: string }[] }>("/properties");
  const [f, setF] = useState<Record<string, string>>({ category: "sonstige", priority: "normal" }), [err, setErr] = useState("");
  const set = (k: string) => (v: string) => setF({ ...f, [k]: v });
  async function save() {
    setErr("");
    try { const r = await api<{ id: number }>("/repairs", { method: "POST", json: { property_id: Number(f.property), title: f.title, reported_on: f.date || new Date().toISOString().slice(0, 10), category: f.category, priority: f.priority, description: f.desc || null, cost_estimate: f.estimate || null, scheduled_for: f.sched || null } }); setOpen(false); reload(); nav(`/reparaturen/${r.id}`); }
    catch (e) { setErr(e instanceof ApiError ? e.message : "Fehler"); }
  }
  return (
    <>
      <PageHeader title="Reparaturen & Instandhaltung" subtitle="Tatsächliche Kosten ergeben sich aus den verknüpften Rechnungen." />
      <Card>
        <div className="toolbar"><label style={{ flexDirection: "row", alignItems: "center", fontWeight: 400 }}><input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} /> nur offene</label><div className="grow" /><button className="btn primary" onClick={() => setOpen(true)}>Reparatur melden</button></div>
        {error && <div className="alert err">{error}</div>}
        {data && data.items.length === 0 ? <EmptyState title="Keine Reparaturen" /> : (
          <table><thead><tr><th>Reparatur</th><th>Kategorie</th><th>Priorität</th><th>Gemeldet</th><th>Termin</th><th>Schätzung</th><th>Tatsächlich</th><th>Status</th></tr></thead>
            <tbody>{data?.items.map((r) => <tr key={r.id} className="row-link" onClick={() => nav(`/reparaturen/${r.id}`)}><td><strong>{r.title}</strong></td><td>{CAT[r.category]}</td><td>{PRIO[r.priority]}</td><td>{dateDe(r.reported_on)}</td><td>{dateDe(r.scheduled_for)}</td><td>{eur(r.costs.estimate)}</td><td>{eur(r.costs.actual)}</td><td><Badge tone={tone(r.status)}>{RSTATUS[r.status]}</Badge></td></tr>)}</tbody></table>)}
      </Card>
      {open && <Modal title="Reparatur melden" onClose={() => setOpen(false)}><div className="form-grid">
        <Field label="Objekt"><Select value={f.property ?? ""} onChange={set("property")} empty="– wählen –" options={(props.data?.items ?? []).map((p) => ({ value: p.id, label: p.name }))} /></Field>
        <Field label="Titel"><Text value={f.title ?? ""} onChange={set("title")} /></Field>
        <Field label="Kategorie"><Select value={f.category} onChange={set("category")} options={Object.entries(CAT).map(([value, label]) => ({ value, label }))} /></Field>
        <Field label="Priorität"><Select value={f.priority} onChange={set("priority")} options={Object.entries(PRIO).map(([value, label]) => ({ value, label }))} /></Field>
        <Field label="Meldedatum"><Text type="date" value={f.date ?? ""} onChange={set("date")} /></Field><Field label="Termin"><Text type="date" value={f.sched ?? ""} onChange={set("sched")} /></Field>
        <Field label="Kostenschätzung (€)"><Text value={f.estimate ?? ""} onChange={set("estimate")} /></Field><Field label="Beschreibung"><Text value={f.desc ?? ""} onChange={set("desc")} /></Field>
        <div className="full">{err && <div className="alert err">{err}</div>}<button className="btn primary" onClick={save}>Melden</button></div></div></Modal>}
    </>
  );
}

export function RepairDetail() {
  const { id } = useParams();
  const { data, error, reload } = useFetch<Detail>(`/repairs/${id}`);
  const invs = useFetch<{ items: { id: number; invoice_number: string | null; amount: string; property_id: number; status: string; description: string | null }[] }>("/invoices");
  const { ask } = useDialogs();
  const [taskOpen, setTaskOpen] = useState(false), [msg, setMsg] = useState("");
  if (error) return <div className="alert err">{error}</div>;
  if (!data) return null;
  async function run(fn: () => Promise<unknown>) { setMsg(""); try { await fn(); reload(); invs.reload(); } catch (e) { setMsg(e instanceof ApiError ? e.message : "Fehler"); } }
  const linkable = (invs.data?.items ?? []).filter((i) => i.property_id === data.property_id && !data.costs.invoice_ids.includes(i.id) && i.status !== "voided");
  return (
    <>
      <PageHeader title={`Reparatur #${data.id}: ${data.title}`} subtitle={`${CAT[data.category]} · Priorität ${PRIO[data.priority]} · gemeldet ${dateDe(data.reported_on)}`} />
      {msg && <div className="alert err">{msg}</div>}
      <div className="toolbar"><Badge tone={tone(data.status)}>{RSTATUS[data.status]}</Badge>
        <Select value={data.status} onChange={async (s) => { if (s === "cancelled") { const n = await ask("Begründung für das Abbrechen", { danger: true }); if (n) run(() => api(`/repairs/${id}/status`, { method: "POST", json: { status: s, note: n } })); } else run(() => api(`/repairs/${id}/status`, { method: "POST", json: { status: s } })); }} options={Object.entries(RSTATUS).map(([value, label]) => ({ value, label }))} />
        <button className="btn" onClick={async () => { const t = await ask("Notiz zum Verlauf", { type: "textarea" }); if (t) run(() => api(`/repairs/${id}/notes`, { method: "POST", json: { text: t } })); }}>Notiz</button></div>
      <div className="grid two-col">
        <Card><div className="card-head"><h2>Verlauf</h2></div>{data.events.map((e) => <div className="list-row" key={e.id}><span className="muted">{dateDe(e.occurred_at)}</span><span>{e.text}</span></div>)}</Card>
        <Card><div className="card-head"><h2>Kosten</h2></div>
          <dl className="kv"><dt>Kostenschätzung</dt><dd>{eur(data.costs.estimate)}</dd><dt>Tatsächlich (Rechnungen)</dt><dd><strong>{eur(data.costs.actual)}</strong></dd><dt>davon bezahlt</dt><dd>{eur(data.costs.paid)}</dd><dt>noch offen</dt><dd>{eur(data.costs.open)}</dd>
            <dt>Abweichung zur Schätzung</dt><dd>{data.costs.deviation_from_estimate ? eur(data.costs.deviation_from_estimate) : "–"}</dd></dl>
          <div className="toolbar" style={{ marginTop: 12 }}><Select value="" onChange={(v) => v && run(() => api(`/repairs/${id}/invoices`, { method: "POST", json: { invoice_id: Number(v) } }))} empty="Rechnung verknüpfen …" options={linkable.map((i) => ({ value: i.id, label: `${i.invoice_number ?? "#" + i.id} – ${eur(i.amount)}` }))} /></div>
          <p className="muted">Kosten werden nicht von Hand eingetragen, sondern aus den verknüpften Rechnungen berechnet (Ausgaben).</p></Card>
      </div>
      <div style={{ height: 20 }} />
      <div className="grid two-col">
        <Card><div className="card-head"><h2>Aufgaben</h2><button className="btn small" onClick={() => setTaskOpen(true)}>+ Aufgabe</button></div>
          {data.tasks.length === 0 ? <p className="muted">Keine Aufgaben.</p> : data.tasks.map((t) => <div className="list-row" key={t.id}><span className="grow">{t.title} <TaskLinks t={t} hideRepair /></span><Badge tone={t.status === "done" ? "ok" : "warn"}>{TSTATUS[t.status]}</Badge></div>)}</Card>
        <DocPanel entityType="repair" entityId={data.id} defaultType="reparaturbeleg" title="Fotos & Belege" />
      </div>
      <p style={{ marginTop: 12 }}><Link className="link" to={`/objekte/${data.property_id}`}>Zum Objekt</Link></p>
      {taskOpen && <Modal title="Aufgabe zur Reparatur" onClose={() => setTaskOpen(false)}><TaskForm defaults={{ repair_id: data.id, property_id: data.property_id }} onDone={() => { setTaskOpen(false); reload(); }} /></Modal>}
    </>
  );
}
