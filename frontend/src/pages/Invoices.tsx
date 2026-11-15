import { useState } from "react";
import { api, ApiError, upload } from "../lib/api";
import { dateDe, eur, useFetch } from "../lib/hooks";
import { Badge, Card, EmptyState, PageHeader } from "../components/ui";
import { Field, Modal, Select, Text } from "../components/Form";

interface Inv { id: number; property_id: number; invoice_number: string | null; invoice_date: string; amount: string; open_amount: string | null; status: string; description: string | null; supplier_party_id: number | null }
const ST: Record<string, [string, "ok" | "warn" | "err"]> = { open: ["Offen", "warn"], partial: ["Teilweise bezahlt", "warn"], paid: ["Bezahlt", "ok"], voided: ["Storniert", "err"] };

export default function InvoicesPage() {
  const { data, error, reload } = useFetch<{ items: Inv[] }>("/invoices");
  const props = useFetch<{ items: { id: number; name: string }[] }>("/properties");
  const sup = useFetch<{ items: { id: number; display_name: string }[] }>("/parties?role=service_provider");
  const [open, setOpen] = useState(false), [f, setF] = useState<Record<string, string>>({}), [err, setErr] = useState(""), [file, setFile] = useState<File | null>(null);
  const set = (k: string) => (v: string) => setF({ ...f, [k]: v });
  async function save() {
    setErr("");
    try {
      const inv = await api<Inv>("/invoices", { method: "POST", json: { property_id: Number(f.property), amount: f.amount, invoice_date: f.date, invoice_number: f.number || null, description: f.desc || null, supplier_party_id: f.supplier ? Number(f.supplier) : null } });
      if (file) { const fd = new FormData(); fd.set("file", file); fd.set("entity_type", "invoice"); fd.set("entity_id", String(inv.id)); fd.set("doc_type", "rechnung"); await upload("/documents", fd); }
      setOpen(false); setFile(null); reload();
    } catch (e) { setErr(e instanceof ApiError ? e.message : "Fehler"); }
  }
  return (
    <>
      <PageHeader title="Rechnungen & Belege" subtitle="Objektbezogene Kosten. Belege werden lokal und nur für angemeldete Benutzer abrufbar gespeichert." />
      {error && <div className="alert err">{error}</div>}
      <Card>
        <div className="toolbar"><div className="grow" /><button className="btn primary" onClick={() => setOpen(true)}>Rechnung erfassen</button></div>
        {data && data.items.length === 0 ? <EmptyState title="Keine Rechnungen" /> : (
          <table><thead><tr><th>Datum</th><th>Nr.</th><th>Beschreibung</th><th>Betrag</th><th>Offen</th><th>Status</th></tr></thead>
            <tbody>{data?.items.map((i) => <tr key={i.id}><td>{dateDe(i.invoice_date)}</td><td>{i.invoice_number ?? "–"}</td><td>{i.description ?? "–"}</td><td>{eur(i.amount)}</td><td>{eur(i.open_amount)}</td><td><Badge tone={ST[i.status][1]}>{ST[i.status][0]}</Badge></td></tr>)}</tbody></table>)}
      </Card>
      {open && <Modal title="Rechnung erfassen" onClose={() => setOpen(false)}><div className="form-grid">
        <Field label="Objekt"><Select value={f.property ?? ""} onChange={set("property")} empty="– wählen –" options={(props.data?.items ?? []).map((p) => ({ value: p.id, label: p.name }))} /></Field>
        <Field label="Lieferant"><Select value={f.supplier ?? ""} onChange={set("supplier")} empty="– keiner –" options={(sup.data?.items ?? []).map((p) => ({ value: p.id, label: p.display_name }))} /></Field>
        <Field label="Rechnungsnummer"><Text value={f.number ?? ""} onChange={set("number")} /></Field><Field label="Rechnungsdatum"><Text type="date" value={f.date ?? ""} onChange={set("date")} /></Field>
        <Field label="Betrag (€)"><Text value={f.amount ?? ""} onChange={set("amount")} /></Field><Field label="Beschreibung"><Text value={f.desc ?? ""} onChange={set("desc")} /></Field>
        <Field label="Beleg (PDF, Bild)"><input className="field" type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} aria-label="Belegdatei" /></Field>
        <div className="full">{err && <div className="alert err">{err}</div>}<button className="btn primary" onClick={save}>Speichern</button></div></div></Modal>}
    </>
  );
}
