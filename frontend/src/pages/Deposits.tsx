import { useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { dateDe, eur, useFetch } from "../lib/hooks";
import { Badge, Card, EmptyState, PageHeader } from "../components/ui";
import { Field, Modal, Select, Text } from "../components/Form";

interface Dep { id: number; lease_id: number; lease_kind: string; agreed_amount: string; due_date: string | null; paid: string; open: string; refunded: string; retained: string; held: string; status: string; overdue: boolean; direction_note: string;
  parties: { name: string; role: string }[]; transactions: { id: number; kind: string; amount: string; transaction_date: string; reason: string | null; voided_at: string | null }[] }
const STATUS: Record<string, string> = { open: "Offen", partially_paid: "Teilweise gezahlt", paid: "Gezahlt", partially_refunded: "Teilweise zurückgezahlt/einbehalten", settled: "Abgeschlossen" };
const KIND: Record<string, string> = { paid: "Einzahlung", refunded: "Rückzahlung", retained: "Einbehalt" };

export default function DepositsPage() {
  const { data, error, reload } = useFetch<{ items: Dep[] }>("/deposits");
  const leases = useFetch<{ items: { id: number; kind: string; status: string; spaces: string[] }[] }>("/leases");
  const [open, setOpen] = useState(false), [tx, setTx] = useState<Dep | null>(null);
  const [f, setF] = useState<Record<string, string>>({ kind: "paid" }); const [err, setErr] = useState("");
  const set = (k: string) => (v: string) => setF({ ...f, [k]: v });
  async function run(fn: () => Promise<unknown>) { setErr(""); try { await fn(); setOpen(false); setTx(null); reload(); } catch (e) { setErr(e instanceof ApiError ? e.message : "Fehler"); } }
  const group = (kind: string, title: string) => (
    <Card><div className="card-head"><h2>{title}</h2></div>
      {(data?.items.filter((d) => d.lease_kind === kind) ?? []).length === 0 ? <EmptyState title="Keine Kautionen" /> : (
        <table><thead><tr><th>Vertrag</th><th>Vereinbart</th><th>Gezahlt</th><th>Offen</th><th>Gehalten</th><th>Status</th><th /></tr></thead>
          <tbody>{data?.items.filter((d) => d.lease_kind === kind).map((d) => <tr key={d.id}>
            <td><Link className="link" to={`/vertraege/${d.lease_id}`}>#{d.lease_id}</Link> <span className="muted">{d.parties.filter((p) => p.role !== "lessor").map((p) => p.name).join(", ")}</span></td>
            <td>{eur(d.agreed_amount)}</td><td>{eur(d.paid)}</td><td>{eur(d.open)} {d.overdue && <Badge tone="err">überfällig</Badge>}</td><td>{eur(d.held)}</td><td>{STATUS[d.status]}</td>
            <td><button className="btn small" onClick={() => { setTx(d); setF({ kind: "paid" }); }}>Buchung</button></td></tr>)}</tbody></table>)}
    </Card>);
  return (
    <>
      <PageHeader title="Kautionen" subtitle="Getrennt je Vertrag. Keine Verrechnung zwischen Haupt- und Untermietkaution; Kautionen sind weder Ertrag noch Kosten." />
      {error && <div className="alert err">{error}</div>}
      <div className="toolbar"><div className="grow" /><button className="btn primary" onClick={() => { setOpen(true); setF({}); }}>Kaution vereinbaren</button></div>
      {group("sub", "Untermietkautionen (Mieter → Leventum)")}<div style={{ height: 20 }} />{group("main", "Hauptmietkautionen (Leventum → Vermieter)")}
      {open && <Modal title="Kaution vereinbaren" onClose={() => setOpen(false)}><div className="form-grid">
        <Field label="Vertrag"><Select value={f.lease ?? ""} onChange={set("lease")} empty="– wählen –" options={(leases.data?.items ?? []).filter((l) => ["active", "terminated", "draft"].includes(l.status)).map((l) => ({ value: l.id, label: `#${l.id} ${l.kind === "main" ? "Hauptmiete" : "Untermiete"} – ${l.spaces.join("; ")}` }))} /></Field>
        <Field label="Vereinbarter Betrag (€)"><Text value={f.amount ?? ""} onChange={set("amount")} /></Field><Field label="Fällig am"><Text type="date" value={f.due ?? ""} onChange={set("due")} /></Field>
        <div className="full">{err && <div className="alert err">{err}</div>}<button className="btn primary" onClick={() => run(() => api("/deposits", { method: "POST", json: { lease_id: Number(f.lease), agreed_amount: f.amount, due_date: f.due || null } }))}>Speichern</button></div></div></Modal>}
      {tx && <Modal title={`Kautionsbuchung – Vertrag #${tx.lease_id}`} onClose={() => setTx(null)}>
        <p className="muted">{tx.direction_note}</p>
        {tx.transactions.map((t) => <div className="list-row" key={t.id}><span>{dateDe(t.transaction_date)}</span><span className="grow">{KIND[t.kind]} {eur(t.amount)} {t.reason && <span className="muted">– {t.reason}</span>} {t.voided_at && <Badge tone="err">storniert</Badge>}</span></div>)}
        <div className="form-grid"><Field label="Art"><Select value={f.kind} onChange={set("kind")} options={Object.entries(KIND).map(([value, label]) => ({ value, label }))} /></Field>
          <Field label="Betrag (€)"><Text value={f.amount ?? ""} onChange={set("amount")} /></Field><Field label="Datum"><Text type="date" value={f.date ?? ""} onChange={set("date")} /></Field>
          <Field label={f.kind === "retained" ? "Begründung (Pflicht)" : "Begründung / Notiz"}><Text value={f.reason ?? ""} onChange={set("reason")} /></Field>
          <div className="full">{err && <div className="alert err">{err}</div>}<button className="btn primary" onClick={() => run(() => api(`/deposits/${tx.id}/transactions`, { method: "POST", json: { kind: f.kind, amount: f.amount, transaction_date: f.date, reason: f.reason || null } }))}>Buchen</button></div></div></Modal>}
    </>
  );
}
