import { useState } from "react";
import { api, ApiError, upload } from "../lib/api";
import { dateDe, eur, useFetch } from "../lib/hooks";
import { Badge, Card, EmptyState, PageHeader } from "../components/ui";
import { Field, Select } from "../components/Form";

interface Sugg { kind: string; score: number; reasons: string[]; lease_id?: number; lease_label?: string; invoice_id?: number; invoice_label?: string; deposit_id?: number; deposit_kind?: string; allocations?: { charge_id?: number; invoice_id?: number; amount: string }[]; unallocated_remainder?: string }
interface Txn { id: number; booking_date: string; amount: string; counterparty_name: string | null; reference: string | null; status: string; suggestions?: Sugg[]; unmatched?: boolean; ignore_reason: string | null }
interface Preview { errors: { row: number; message: string }[]; total_rows: number; new_rows: number; duplicate_rows: number; file_already_imported: boolean }

export function SuggestionRow({ t, onDone }: { t: Txn; onDone: () => void }) {
  const [err, setErr] = useState("");
  async function confirm(s: Sugg) {
    setErr("");
    try {
      const body = s.kind === "deposit" ? { confirm: true, kind: "deposit", deposit_id: s.deposit_id, deposit_kind: s.deposit_kind } : { confirm: true, allocations: (s.allocations ?? []).map((a) => ({ ...(a.charge_id ? { charge_id: a.charge_id } : {}), ...(a.invoice_id ? { invoice_id: a.invoice_id } : {}), amount: a.amount })), lease_id: s.lease_id };
      await api(`/bank/transactions/${t.id}/confirm`, { method: "POST", json: body }); onDone();
    } catch (e) { setErr(e instanceof ApiError ? e.message : "Fehler"); }
  }
  return (
    <tr>
      <td>{dateDe(t.booking_date)}</td><td>{t.counterparty_name ?? "–"}<div className="muted">{t.reference}</div></td><td>{eur(t.amount)}</td>
      <td>{t.status === "open" ? (t.suggestions?.length ? t.suggestions.map((s, i) => (
        <div key={i} style={{ marginBottom: 8 }}><Badge tone="ok">Vorschlag ({s.score})</Badge> {s.kind === "charges" ? `${s.lease_label ?? `Vertrag #${s.lease_id}`}: ${s.allocations?.length} Sollstellung(en)` : s.kind === "invoice" ? `Rechnung ${s.invoice_label ?? `#${s.invoice_id}`}` : `Kaution #${s.deposit_id}`}
          <div className="muted">{s.reasons.join("; ")}{s.unallocated_remainder && s.unallocated_remainder !== "0.00" ? ` · Rest ${eur(s.unallocated_remainder)} bleibt unzugeordnet` : ""}</div>
          <button className="btn small primary" onClick={() => confirm(s)}>Zuordnung bestätigen</button></div>)) : <Badge tone="err">Nicht zuordenbar – manuell prüfen</Badge>) : <Badge tone={t.status === "confirmed" ? "ok" : "warn"}>{t.status === "confirmed" ? "Bestätigt" : `Ausgeblendet: ${t.ignore_reason}`}</Badge>}
        {err && <div className="alert err">{err}</div>}</td>
      <td>{t.status === "open" && <button className="btn small" onClick={async () => { const r = window.prompt("Begründung (z. B. Privatbuchung)"); if (r) { await api(`/bank/transactions/${t.id}/ignore`, { method: "POST", json: { reason: r } }); onDone(); } }}>Ausblenden</button>}
        {t.status !== "open" && <button className="btn small" onClick={async () => { const r = window.prompt("Begründung für Wiedereröffnung"); if (r) { await api(`/bank/transactions/${t.id}/reopen`, { method: "POST", json: { reason: r } }); onDone(); } }}>Wieder öffnen</button>}</td>
    </tr>
  );
}

export default function BankPage() {
  const accounts = useFetch<{ items: { id: number; name: string }[] }>("/bank/accounts");
  const [filter, setFilter] = useState("open");
  const txns = useFetch<{ items: Txn[] }>(`/bank/transactions?suggestions=true&status=${filter}`);
  const [acc, setAcc] = useState(""), [file, setFile] = useState<File | null>(null), [prev, setPrev] = useState<Preview | null>(null), [msg, setMsg] = useState<{ tone: "ok" | "err"; text: string } | null>(null), [newAcc, setNewAcc] = useState("");
  const form = () => { const f = new FormData(); f.set("account_id", acc); f.set("file", file!); return f; };
  async function doPreview() { setMsg(null); try { setPrev(await upload<Preview>("/bank/imports/preview", form())); } catch (e) { setMsg({ tone: "err", text: e instanceof ApiError ? e.message : "Fehler" }); } }
  async function doImport() {
    setMsg(null);
    try { const r = await upload<{ new_rows: number; duplicate_rows: number }>("/bank/imports", form()); setMsg({ tone: "ok", text: `Import abgeschlossen: ${r.new_rows} neu, ${r.duplicate_rows} Duplikate übersprungen. Es wurde noch nichts gebucht – bitte Zuordnungen prüfen und bestätigen.` }); setPrev(null); setFile(null); txns.reload(); }
    catch (e) { const d = (e as { details?: { row: number; message: string }[] }).details; setMsg({ tone: "err", text: (e instanceof ApiError ? e.message : "Fehler") + (d ? " " + d.slice(0, 5).map((x) => `Zeile ${x.row}: ${x.message}`).join("; ") : "") }); }
  }
  return (
    <>
      <PageHeader title="Bankimport" subtitle="CSV-Kontoauszüge lokal importieren. Zuordnungen sind nur Vorschläge – jede Buchung wird erst nach Ihrer Bestätigung übernommen. Es werden keine Online-Banking-Zugangsdaten gespeichert." />
      {msg && <div className={`alert ${msg.tone}`} role="status">{msg.text}</div>}
      <Card>
        <div className="card-head"><h2>Kontoauszug importieren</h2></div>
        {accounts.data && accounts.data.items.length === 0 && <div className="toolbar"><input className="field" placeholder="Name des Bankkontos" value={newAcc} onChange={(e) => setNewAcc(e.target.value)} aria-label="Kontoname" /><button className="btn" onClick={async () => { await api("/bank/accounts", { method: "POST", json: { name: newAcc } }); accounts.reload(); }}>Konto anlegen</button></div>}
        <div className="form-grid">
          <Field label="Bankkonto"><Select value={acc} onChange={setAcc} empty="– wählen –" options={(accounts.data?.items ?? []).map((a) => ({ value: a.id, label: a.name }))} /></Field>
          <Field label="CSV-Datei"><input className="field" type="file" accept=".csv,text/csv" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPrev(null); }} aria-label="CSV-Datei" /></Field>
          <div className="full toolbar"><button className="btn" disabled={!acc || !file} onClick={doPreview}>Prüfen (Vorschau)</button><button className="btn primary" disabled={!prev || prev.errors.length > 0} onClick={doImport}>Importieren</button></div>
        </div>
        {prev && <div className={`alert ${prev.errors.length ? "err" : "ok"}`}>{prev.errors.length ? <>Datei enthält Fehler und kann nicht importiert werden:<ul>{prev.errors.slice(0, 10).map((e, i) => <li key={i}>Zeile {e.row}: {e.message}</li>)}</ul></> : `${prev.total_rows} Zeilen: ${prev.new_rows} neu, ${prev.duplicate_rows} bereits importiert.${prev.file_already_imported ? " Diese Datei wurde schon einmal importiert." : ""}`}</div>}
      </Card>
      <div style={{ height: 20 }} />
      <Card>
        <div className="card-head"><h2>Buchungen</h2><Select value={filter} onChange={setFilter} options={[{ value: "open", label: "Zu prüfen" }, { value: "confirmed", label: "Bestätigt" }, { value: "ignored", label: "Ausgeblendet" }]} /></div>
        {txns.data && txns.data.items.length === 0 ? <EmptyState title="Keine Buchungen" /> : (
          <table><thead><tr><th>Datum</th><th>Gegenpartei / Zweck</th><th>Betrag</th><th>Zuordnung</th><th /></tr></thead><tbody>{txns.data?.items.map((t) => <SuggestionRow key={t.id} t={t} onDone={txns.reload} />)}</tbody></table>)}
      </Card>
    </>
  );
}
