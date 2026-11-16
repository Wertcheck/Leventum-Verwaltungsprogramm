import { useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, type StichtagMeta } from "../lib/api";
import { dateDe, eur, useFetch } from "../lib/hooks";
import { Badge, Card, EmptyState, PageHeader, StichtagLine } from "../components/ui";
import { Field, Modal, Select, Text } from "../components/Form";
import { useDialogs } from "../components/Dialogs";

export interface ChargeRow { id: number; lease_id: number; lease_label: string; direction: string; charge_type: string; period_start: string; due_date: string; amount: string; open_amount: string | null; allocated: string; status: string }
interface PaymentRow { id: number; direction: string; booking_date: string; amount: string; signed_amount: string; is_reversal: boolean; reversed: boolean; allocated: string; unallocated: string; reference: string | null; source: string; is_future_dated?: boolean }
export const CHARGE_LABEL: Record<string, string> = { base_rent: "Kaltmiete", other_charges: "Zuschlag", utility_prepayment: "NK-Vorauszahlung", utility_flat_rate: "NK-Pauschale", other: "Sonstige" };
const ST: Record<string, [string, "ok" | "warn" | "err"]> = { open: ["Offen", "warn"], partial: ["Teilzahlung", "warn"], paid: ["Bezahlt", "ok"], voided: ["Storniert", "err"] };

export default function FinancePage() {
  const { ask } = useDialogs();
  const [dir, setDir] = useState(""), [status, setStatus] = useState(""), [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const charges = useFetch<{ items: ChargeRow[]; stichtag?: StichtagMeta }>(`/charges?${new URLSearchParams({ ...(dir && { direction: dir }), ...(status && { status }), ...(month && { month }) })}`);
  const pays = useFetch<{ items: PaymentRow[] }>("/payments");
  const [msg, setMsg] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const [open, setOpen] = useState<null | "pay" | "gen">(null);
  const [f, setF] = useState<Record<string, string>>({ direction: "in" });
  const set = (k: string) => (v: string) => setF({ ...f, [k]: v });
  const reload = () => { charges.reload(); pays.reload(); };
  async function run(fn: () => Promise<unknown>, ok: string) { setMsg(null); try { await fn(); if (ok) setMsg({ tone: "ok", text: ok }); setOpen(null); reload(); } catch (e) { setMsg({ tone: "err", text: e instanceof ApiError ? e.message : "Fehler" }); } }
  interface Preview { would_create: { lease_id: number; lease_label?: string; charge_type: string; period_start: string; period_end: string; amount: string; due_date: string; backdated: boolean }[]; would_create_count: number; backdated_count: number; skipped_existing: number; conflicts: { lease_id: number; month: string; reason: string }[]; errors: { message: string }[]; notes: { message: string }[] }
  const [prev, setPrev] = useState<Preview | null>(null), [backdatedOk, setBackdatedOk] = useState(false), [busy, setBusy] = useState(false);
  const body = () => ({ from_month: f.from, through_month: f.to });
  async function preview() { setMsg(null); setBusy(true); setBackdatedOk(false); try { setPrev(await api<Preview>("/charges/preview", { method: "POST", json: body() })); } catch (e) { setMsg({ tone: "err", text: e instanceof ApiError ? e.message : "Fehler" }); } finally { setBusy(false); } }
  const gen = () => run(async () => { const r = await api<{ created_count: number; skipped_existing: number; conflicts: unknown[] }>("/charges/generate", { method: "POST", json: { ...body(), allow_backdated: backdatedOk } });
    if (f.from) setMonth(f.from.slice(0, 7));  // Liste springt zum ersten erzeugten Monat, damit das Ergebnis sichtbar ist
    setPrev(null);
    setMsg({ tone: r.conflicts.length ? "err" : "ok", text: `${r.created_count} erzeugt, ${r.skipped_existing} bereits vorhanden, ${r.conflicts.length} Konflikte (abweichender Betrag – bestehende Sollstellung wurde nicht verändert).` }); }, "");
  return (
    <>
      <PageHeader title="Sollstellungen & Zahlungen" subtitle="Soll (Forderungen/Verbindlichkeiten) und Ist (tatsächliche Zahlungen) getrennt" />
      {msg && msg.text && <div className={`alert ${msg.tone}`} role="status">{msg.text}</div>}
      <Card>
        <div className="card-head"><h2>Sollstellungen</h2><div className="toolbar" style={{ margin: 0 }}>
          <Select value={dir} onChange={setDir} empty="Alle" options={[{ value: "receivable", label: "Forderungen (Untermieter)" }, { value: "payable", label: "Verbindlichkeiten (Vermieter)" }]} />
          <Select value={status} onChange={setStatus} empty="Alle Status" options={[{ value: "open", label: "Offen" }, { value: "partial", label: "Teilzahlung" }, { value: "paid", label: "Bezahlt" }, { value: "overdue", label: "Überfällig" }]} />
          <Text type="month" value={month} onChange={setMonth} /><button className="btn primary" onClick={() => setOpen("gen")}>Sollstellungen erzeugen</button></div></div>
        <StichtagLine stichtag={charges.data?.stichtag} />
        {charges.data && charges.data.items.length === 0 ? <EmptyState title="Keine Sollstellungen" /> : (
          <table><thead><tr><th>Vertrag</th><th>Art</th><th>Monat</th><th>Fällig</th><th>Betrag</th><th>Offen</th><th>Status</th></tr></thead>
            <tbody>{charges.data?.items.map((c) => <tr key={c.id}><td><Link className="link" to={`/vertraege/${c.lease_id}`}>{c.lease_label}</Link><div className="muted">{c.direction === "receivable" ? "Forderung gegen Mieter" : "Verbindlichkeit an Vermieter"}</div></td><td>{CHARGE_LABEL[c.charge_type]}</td><td>{c.period_start.slice(0, 7)}</td><td>{dateDe(c.due_date)}</td><td>{eur(c.amount)}</td><td>{eur(c.open_amount)}</td><td><Badge tone={ST[c.status][1]}>{ST[c.status][0]}</Badge></td></tr>)}</tbody></table>)}
      </Card>
      <div style={{ height: 20 }} />
      <Card>
        <div className="card-head"><h2>Zahlungen (Ist)</h2><button className="btn primary" onClick={() => setOpen("pay")}>Zahlung erfassen</button></div>
        <p className="muted" style={{ marginBottom: 10 }}>Zahlungen sind unveränderlich. Korrekturen erfolgen per Stornobuchung. Kautionen erscheinen hier nicht.</p>
        {pays.data?.items.some((p) => p.is_future_dated) && <p className="alert warn" role="status" data-testid="future-note">Zahlungen mit der Kennzeichnung „zukünftig gebucht“ haben ein Buchungsdatum in der Zukunft und mindern Forderungen erst ab diesem Datum.</p>}
        {pays.data && pays.data.items.length === 0 ? <EmptyState title="Keine Zahlungen" /> : (
          <table><thead><tr><th>Datum</th><th>Richtung</th><th>Betrag</th><th>Zugeordnet</th><th>Nicht zugeordnet</th><th>Verwendungszweck</th><th /></tr></thead>
            <tbody>{pays.data?.items.map((p) => <tr key={p.id}><td>{dateDe(p.booking_date)}</td><td>{p.direction === "in" ? "Eingang" : "Ausgang"}{p.is_reversal && <> <Badge tone="err">Storno</Badge></>}{p.reversed && <> <Badge tone="warn">storniert</Badge></>}{p.is_future_dated && <> <span className="badge neutral" title="Das Buchungsdatum liegt in der Zukunft. Die Zahlung mindert Forderungen erst ab dem Buchungsdatum.">zukünftig gebucht</span></>}</td>
              <td>{eur(p.signed_amount)}</td><td>{eur(p.allocated)}</td><td>{eur(p.unallocated)}</td><td>{p.reference ?? "–"}</td>
              <td>{!p.is_reversal && !p.reversed && <button className="btn small danger" onClick={async () => { const r = await ask("Begründung für die Stornobuchung", { title: "Zahlung stornieren", danger: true }); if (r) run(() => api(`/payments/${p.id}/reverse`, { method: "POST", json: { reason: r } }), "Zahlung storniert (Gegenbuchung)."); }}>Stornieren</button>}</td></tr>)}</tbody></table>)}
      </Card>
      {open === "gen" && <Modal title="Sollstellungen erzeugen" onClose={() => { setOpen(null); setPrev(null); }}><div className="form-grid">
        <Field label="Von (Monat)"><Text type="month" value={f.from?.slice(0, 7) ?? ""} onChange={(v) => { setPrev(null); set("from")(v ? v + "-01" : ""); }} /></Field>
        <Field label="Bis (Monat)"><Text type="month" value={f.to?.slice(0, 7) ?? ""} onChange={(v) => { setPrev(null); set("to")(v ? v + "-01" : ""); }} /></Field>
        <div className="full"><p className="muted">Idempotent: bereits vorhandene Sollstellungen werden nie doppelt angelegt oder überschrieben. Zuerst wird eine Vorschau berechnet – es wird nichts gespeichert.</p>
          <button className="btn" disabled={!f.from || !f.to || busy} onClick={preview}>{busy ? "Berechne …" : "Vorschau berechnen"}</button></div>
        {prev && <div className="full" data-testid="charge-preview">
          <p><strong>{prev.would_create_count}</strong> würden erzeugt, {prev.skipped_existing} sind bereits vorhanden{prev.conflicts.length > 0 && <>, <strong>{prev.conflicts.length} Konflikte</strong></>}.</p>
          {prev.errors.map((e, i) => <div key={i} className="alert err">{e.message}</div>)}
          {prev.conflicts.length > 0 && <div className="alert warn">Konflikte (abweichender Betrag oder andere Periodenlänge bereits abgerechnet) werden nicht verändert: {prev.conflicts.map((c) => `Vertrag ${c.lease_id} ${c.month}`).join(", ")}</div>}
          {prev.notes.length > 0 && <p className="muted">{prev.notes.map((n) => n.message).join(" ")}</p>}
          {prev.would_create.length > 0 && <div style={{ maxHeight: 220, overflow: "auto" }}><table><thead><tr><th>Vertrag</th><th>Art</th><th>Zeitraum</th><th>Fällig</th><th>Betrag</th></tr></thead>
            <tbody>{prev.would_create.map((x, i) => <tr key={i}><td>{x.lease_label ?? `#${x.lease_id}`}</td><td>{CHARGE_LABEL[x.charge_type] ?? x.charge_type}{x.backdated && <> <Badge tone="warn">rückwirkend</Badge></>}</td><td>{dateDe(x.period_start)} – {dateDe(x.period_end)}</td><td>{dateDe(x.due_date)}</td><td>{eur(x.amount)}</td></tr>)}</tbody></table></div>}
          {prev.backdated_count > 0 && <label className="check"><input type="checkbox" checked={backdatedOk} onChange={(e) => setBackdatedOk(e.target.checked)} /> {prev.backdated_count} Sollstellung(en) betreffen vergangene Zeiträume – ich bestätige die rückwirkende Erzeugung.</label>}
          <div style={{ marginTop: 10 }}><button className="btn primary" disabled={prev.would_create_count === 0 || (prev.backdated_count > 0 && !backdatedOk)} onClick={gen}>{prev.would_create_count} Sollstellung(en) erzeugen</button></div></div>}
      </div></Modal>}
      {open === "pay" && <Modal title="Zahlung erfassen" onClose={() => setOpen(null)}><div className="form-grid">
        <Field label="Richtung"><Select value={f.direction} onChange={set("direction")} options={[{ value: "in", label: "Eingang" }, { value: "out", label: "Ausgang" }]} /></Field>
        <Field label="Buchungsdatum"><Text type="date" value={f.date ?? ""} onChange={set("date")} /></Field>
        <Field label="Betrag (€)"><Text value={f.amount ?? ""} onChange={set("amount")} placeholder="1370.00" /></Field>
        <Field label="Verwendungszweck"><Text value={f.ref ?? ""} onChange={set("ref")} /></Field>
        <Field label="Sollstellung zuordnen (optional)"><Select value={f.charge ?? ""} onChange={set("charge")} empty="– nicht zuordnen –" options={(charges.data?.items ?? []).filter((c) => c.status === "open" || c.status === "partial").filter((c) => (c.direction === "receivable") === (f.direction === "in")).map((c) => ({ value: c.id, label: `${c.lease_label} – ${CHARGE_LABEL[c.charge_type]} ${c.period_start.slice(0, 7)} – offen ${eur(c.open_amount)}` }))} /></Field>
        <div className="full"><button className="btn primary" onClick={() => run(() => api("/payments", { method: "POST", json: { direction: f.direction, booking_date: f.date, amount: f.amount, reference: f.ref || null, allocations: f.charge ? [{ charge_id: Number(f.charge), amount: f.amount }] : [] } }), "Zahlung erfasst.")}>Speichern</button></div></div></Modal>}
    </>
  );
}
