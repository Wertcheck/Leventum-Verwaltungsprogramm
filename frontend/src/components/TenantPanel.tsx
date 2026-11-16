import { Link } from "react-router-dom";
import { dateDe, eur, useFetch } from "../lib/hooks";
import { Badge } from "./ui";

export const PHASE: Record<string, [string, "ok" | "warn" | "err"]> = {
  upcoming: ["Anstehend (noch nicht begonnen)", "warn"], active: ["Aktiv", "ok"], notice: ["Gekündigt – läuft noch", "warn"], ended: ["Beendet", "err"],
  draft: ["Entwurf", "warn"], no_lease: ["Ohne Untermietvertrag", "warn"], cancelled: ["Storniert", "err"],
};

interface Overview {
  party: { id: number; display_name: string; email: string | null; phone: string | null; city: string | null; street?: string | null; postal_code?: string | null };
  leases: { id: number; kind: string; role: string; type: string; phase: string; start_date: string; end_date: string | null; spaces: string[]; monthly: { available: boolean; total?: string }; payment_rhythm: string; payment_status: string | null; overdue_amount: string | null;
    deposit: { agreed_amount: string; paid: string; open: string; held: string; status: string } | null }[];
  /** Fehlt ohne Finanzrecht (Schlüssel wird serverseitig weggelassen). */
  finance?: { open_total: string; overdue_total: string; monthly_soll_total: string; open_items: { charge_id: number; charge_type: string; period_start: string; due_date: string; amount: string; open_amount: string; overdue: boolean }[];
    recent_payments: { payment_id: number; booking_date: string; amount: string; is_reversal: boolean; allocated: string }[] };
  documents: { id: number; original_name: string; doc_type: string }[];
  tasks: { id: number; title: string; status: string; due_date: string | null }[];
  repairs: { id: number; title: string; status: string; reported_on: string }[];
  activity: { at: string; summary: string; actor: string | null; source: string }[];
}
const CT: Record<string, string> = { base_rent: "Kaltmiete", other_charges: "Zuschlag", utility_prepayment: "NK-Vorauszahlung", utility_flat_rate: "NK-Pauschale", other: "Sonstige" };
const DEP: Record<string, string> = { open: "offen", partially_paid: "teilweise gezahlt", paid: "gezahlt", partially_refunded: "teilweise zurückgezahlt", settled: "abgewickelt" };

/** Rechtes Detailpanel der Mieterliste: eine gebündelte Abfrage (/tenants/{id}/overview). */
export default function TenantPanel({ partyId, onClose }: { partyId: number; onClose: () => void }) {
  const { data, error } = useFetch<Overview>(`/tenants/${partyId}/overview`);
  return (
    <aside className="tenant-panel card" aria-label="Mieterdetails" data-testid="tenant-panel">
      <div className="card-head"><h2>{data?.party.display_name ?? "Mieter"}</h2><button className="btn small" onClick={onClose} aria-label="Detailpanel schließen">Schließen</button></div>
      {error && <div className="alert err">{error}</div>}
      {!data && !error && <p className="muted" role="status">Lade Mieterdaten …</p>}
      {data && <>
        <p className="muted">{[data.party.email, data.party.phone, [data.party.postal_code, data.party.city].filter(Boolean).join(" ")].filter(Boolean).join(" · ") || "Keine Kontaktdaten"}</p>
        <p><Link className="link" to={`/parteien/${data.party.id}`}>Vollständige Mieterakte öffnen</Link></p>

        <h3>Verträge</h3>
        {data.leases.length === 0 ? <p className="muted">Kein Untermietvertrag.</p> : data.leases.map((l) => (
          <div className="panel-block" key={l.id}>
            <div><Link className="link" to={`/vertraege/${l.id}`}>{l.type} #{l.id}</Link> <Badge tone={PHASE[l.phase]?.[1] ?? "warn"}>{PHASE[l.phase]?.[0] ?? l.phase}</Badge></div>
            <div className="muted">{l.spaces.join("; ") || "–"}</div>
            <div>{dateDe(l.start_date)} – {l.end_date ? dateDe(l.end_date) : "unbefristet"} · {l.monthly.available ? `${eur(l.monthly.total)} / Monat (Soll)` : "Konditionen fehlen"}</div>
            {l.payment_status === "arrears" && <div><Badge tone="err">Rückstand {eur(l.overdue_amount)}</Badge></div>}
            {l.deposit && <div className="muted">Kaution (außerhalb der Mietforderungen): vereinbart {eur(l.deposit.agreed_amount)}, gezahlt {eur(l.deposit.paid)}, gehalten {eur(l.deposit.held)} – {DEP[l.deposit.status] ?? l.deposit.status}</div>}
          </div>))}

        {data.finance && <>
        <h3>Offene Posten</h3>
        <p>Offen gesamt <strong>{eur(data.finance.open_total)}</strong> · davon überfällig <strong>{eur(data.finance.overdue_total)}</strong></p>
        {data.finance.open_items.length > 0 && <table><thead><tr><th>Art</th><th>Zeitraum</th><th>Fällig</th><th>Offen</th></tr></thead>
          <tbody>{data.finance.open_items.map((i) => <tr key={i.charge_id}><td>{CT[i.charge_type] ?? i.charge_type}</td><td>{i.period_start.slice(0, 7)}</td><td>{dateDe(i.due_date)}{i.overdue && <> <Badge tone="err">überfällig</Badge></>}</td><td>{eur(i.open_amount)}</td></tr>)}</tbody></table>}

        <h3>Letzte Zahlungen</h3>
        {data.finance.recent_payments.length === 0 ? <p className="muted">Keine zugeordneten Zahlungen.</p> : <ul className="plain">{data.finance.recent_payments.map((p) => <li key={p.payment_id}>{dateDe(p.booking_date)} · {eur(p.amount)}{p.is_reversal && " (Storno)"}</li>)}</ul>}
        </>}

        <h3>Dokumente</h3>
        {data.documents.length === 0 ? <p className="muted">Keine Dokumente.</p> : <ul className="plain">{data.documents.map((d) => <li key={d.id}><a className="link" href={`/api/v1/documents/${d.id}/download`}>{d.original_name}</a></li>)}</ul>}

        <h3>Aufgaben &amp; Reparaturen</h3>
        {data.tasks.length + data.repairs.length === 0 ? <p className="muted">Nichts offen.</p> : <ul className="plain">
          {data.tasks.map((t) => <li key={`t${t.id}`}>Aufgabe: {t.title}{t.due_date && ` (fällig ${dateDe(t.due_date)})`}</li>)}
          {data.repairs.map((r) => <li key={`r${r.id}`}><Link className="link" to={`/reparaturen/${r.id}`}>Reparatur: {r.title}</Link></li>)}</ul>}

        <h3>Letzte Aktivität</h3>
        {data.activity.length === 0 ? <p className="muted">Keine Einträge.</p> : <ul className="plain">{data.activity.map((a, i) => <li key={i}><span className="muted">{dateDe(a.at)}</span> {a.summary}</li>)}</ul>}
      </>}
    </aside>
  );
}
