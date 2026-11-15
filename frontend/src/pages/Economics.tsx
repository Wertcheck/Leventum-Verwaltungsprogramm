import { useMemo, useState } from "react";
import { eur, useFetch } from "../lib/hooks";
import { Card, PageHeader } from "../components/ui";
import { Field, Select, Text } from "../components/Form";

interface Rep {
  scope: { type: string; id: number | null }; status: string;
  soll: Record<string, string>; ist: Record<string, string>; offen_zum_stichtag: Record<string, string>;
  vacancy: { economic_vacancy_cost: string; physical_vacancy_rate_by_count: string | null; note: string };
  contribution: { label: string; rent_margin_soll: string; utility_flow_soll: string; soll_basis: string; ist_basis: string; utility_settlement_upstream: { balance: string; statements_counted: number } | null; soll_basis_incl_upstream_settlement: string | null };
  warnings: { code: string; message: string }[]; assumptions: string[];
}
const monthEnd = (m: string) => { const [y, mo] = m.split("-").map(Number); return `${m}-${String(new Date(y, mo, 0).getDate()).padStart(2, "0")}`; };
const Row = ({ k, v, strong }: { k: string; v: string | null | undefined; strong?: boolean }) => <><dt>{strong ? <strong>{k}</strong> : k}</dt><dd>{strong ? <strong>{eur(v)}</strong> : eur(v)}</dd></>;

export default function EconomicsPage() {
  const now = new Date().toISOString().slice(0, 7);
  const [from, setFrom] = useState(now), [to, setTo] = useState(now), [scope, setScope] = useState("portfolio"), [id, setId] = useState("");
  const props = useFetch<{ items: { id: number; name: string }[] }>("/properties");
  const units = useFetch<{ items: { id: number; unit_number: string; property_id: number }[] }>("/units");
  const rus = useFetch<{ items: { id: number; label: string }[] }>("/rentable-units");
  const q = useMemo(() => (scope !== "portfolio" && !id ? null : `/economics?start=${from}-01&end=${monthEnd(to)}&scope=${scope}${scope !== "portfolio" ? `&id=${id}` : ""}`), [from, to, scope, id]);
  const { data, error } = useFetch<Rep>(q);
  const opts = scope === "property" ? (props.data?.items ?? []).map((p) => ({ value: p.id, label: p.name })) : scope === "unit" ? (units.data?.items ?? []).map((u) => ({ value: u.id, label: `WE ${u.unit_number}` })) : (rus.data?.items ?? []).map((r) => ({ value: r.id, label: r.label }));
  return (
    <>
      <PageHeader title="Wirtschaftlichkeit" subtitle="Vorläufige Auswertung. Soll (Vertrag) und Ist (Zahlungen) werden getrennt gezeigt. Kautionen sind ausgeschlossen." />
      <Card><div className="form-grid">
        <Field label="Bereich"><Select value={scope} onChange={(v) => { setScope(v); setId(""); }} options={[{ value: "portfolio", label: "Gesamtes Portfolio" }, { value: "property", label: "Immobilie" }, { value: "unit", label: "Wohneinheit" }, { value: "rentable_unit", label: "Vermietungseinheit" }]} /></Field>
        {scope !== "portfolio" && <Field label="Auswahl"><Select value={id} onChange={setId} empty="– wählen –" options={opts} /></Field>}
        <Field label="Von (Monat)"><Text type="month" value={from} onChange={setFrom} /></Field><Field label="Bis (Monat)"><Text type="month" value={to} onChange={setTo} /></Field>
      </div></Card>
      {error && <div className="alert err">{error}</div>}
      {data && <div style={{ marginTop: 20 }}>
        <div className="grid two-col">
          <Card><div className="card-head"><h2>Soll (laut Verträgen)</h2></div><dl className="kv">
            <Row k="Untermiete Kaltmiete+Zuschläge" v={data.soll.sub_rent} /><Row k="Untermiete Nebenkosten" v={data.soll.sub_utility} /><Row k="Untermiete gesamt" v={data.soll.sub_total} strong />
            <Row k="Hauptmiete Kaltmiete+Zuschläge" v={data.soll.main_rent} /><Row k="Hauptmiete Nebenkosten" v={data.soll.main_utility} /><Row k="Hauptmiete gesamt" v={data.soll.main_total} strong />
            <Row k="Objektkosten (Rechnungen)" v={data.soll.object_costs} /></dl></Card>
          <Card><div className="card-head"><h2>Ist (Zahlungen)</h2></div><dl className="kv">
            <Row k="Eingänge von Untermietern" v={data.ist.in_from_subleases} /><Row k="Sonstige Eingänge (nicht zugeordnet)" v={data.ist.in_other_unallocated} /><Row k="Eingänge gesamt" v={data.ist.in_total} strong />
            <Row k="Hauptmiete bezahlt" v={data.ist.out_main_rent} /><Row k="Rechnungen bezahlt" v={data.ist.out_invoices} /><Row k="Sonstige Ausgänge (nicht zugeordnet)" v={data.ist.out_other_unallocated} /><Row k="Ausgänge gesamt" v={data.ist.out_total} strong /></dl></Card>
        </div>
        <div style={{ height: 20 }} />
        <div className="grid two-col">
          <Card><div className="card-head"><h2>{data.contribution.label}</h2></div><dl className="kv">
            <Row k="Mietmarge (Soll)" v={data.contribution.rent_margin_soll} /><Row k="Nebenkosten-Durchlauf (Soll)" v={data.contribution.utility_flow_soll} />
            <Row k="Deckungsbeitrag Soll-Basis" v={data.contribution.soll_basis} strong /><Row k="Deckungsbeitrag Ist-Basis (Zahlungsfluss)" v={data.contribution.ist_basis} strong />
            {data.contribution.utility_settlement_upstream && <><Row k="NK-Abrechnung Vermieter (+Nachzahlung / −Guthaben)" v={data.contribution.utility_settlement_upstream.balance} /><Row k="Soll-Basis inkl. NK-Abrechnung" v={data.contribution.soll_basis_incl_upstream_settlement} strong /></>}</dl>
            <p className="muted">Soll- und Ist-Basis nicht addieren. Kein Gewinn, sondern vorläufig.</p></Card>
          <Card><div className="card-head"><h2>Offen &amp; Leerstand</h2></div><dl className="kv">
            <Row k={`Offene Forderungen (Stand ${data.offen_zum_stichtag.as_of})`} v={data.offen_zum_stichtag.receivables} /><Row k="davon überfällig (Rückstand)" v={data.offen_zum_stichtag.receivables_overdue} />
            <Row k="Offene Verbindlichkeiten" v={data.offen_zum_stichtag.payables} /><Row k="Offene Rechnungen" v={data.offen_zum_stichtag.invoices} />
            <Row k="Wirtschaftlicher Leerstand (Teil der Hauptmiete)" v={data.vacancy.economic_vacancy_cost} /><dt>Physischer Leerstand</dt><dd>{data.vacancy.physical_vacancy_rate_by_count ? `${data.vacancy.physical_vacancy_rate_by_count.replace(".", ",")} %` : "–"}</dd></dl></Card>
        </div>
        {data.warnings.map((w, i) => <div key={i} className="alert warn" style={{ marginTop: 12 }}>{w.message}</div>)}
        <details style={{ marginTop: 12 }}><summary>Annahmen &amp; Methode</summary><ul>{data.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul></details>
      </div>}
    </>
  );
}
