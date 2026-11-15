import { useState } from "react";
import { eur, useFetch } from "../lib/hooks";
import { Card, PageHeader } from "../components/ui";
import { Field, Select, Text } from "../components/Form";

interface V { snapshot: { as_of: string; leaves_total: number; leaves_occupied: number; leaves_vacant: number }; physical: { vacancy_rate_by_count_percent: string | null; vacancy_rate_by_weight_percent: string | null; definition: string };
  economic: { cost: string; days_vacant_with_main_obligation: number; definition: string };
  rows: { label: string; days_total: number; days_occupied: number; days_vacant: number; days_with_main_obligation: number; days_vacant_with_main_obligation: number; economic_vacancy_cost: string }[]; warnings: { message: string }[] }
const monthEnd = (m: string) => { const [y, mo] = m.split("-").map(Number); return `${m}-${String(new Date(y, mo, 0).getDate()).padStart(2, "0")}`; };
const pct = (v: string | null) => (v ? `${v.replace(".", ",")} %` : "–");

export default function VacancyPage() {
  const now = new Date().toISOString().slice(0, 7);
  const [from, setFrom] = useState(now), [to, setTo] = useState(now), [prop, setProp] = useState("");
  const props = useFetch<{ items: { id: number; name: string }[] }>("/properties");
  const { data, error } = useFetch<V>(`/vacancy?start=${from}-01&end=${monthEnd(to)}${prop ? `&property_id=${prop}` : ""}`);
  return (
    <>
      <PageHeader title="Leerstand" subtitle="Zwei getrennte Kennzahlen – Berechnung je Bett, Zimmer bzw. Wohneinheit (kleinste Einheit), ohne Doppelzählung." />
      <Card><div className="form-grid">
        <Field label="Objekt"><Select value={prop} onChange={setProp} empty="Alle Objekte" options={(props.data?.items ?? []).map((p) => ({ value: p.id, label: p.name }))} /></Field><div />
        <Field label="Von (Monat)"><Text type="month" value={from} onChange={setFrom} /></Field><Field label="Bis (Monat)"><Text type="month" value={to} onChange={setTo} /></Field></div></Card>
      {error && <div className="alert err">{error}</div>}
      {data && <>
        <div className="grid two-col" style={{ marginTop: 20 }}>
          <Card><div className="card-head"><h2>A · Physischer Leerstand</h2></div>
            <p style={{ fontSize: 32, fontWeight: 700 }} data-testid="phys">{pct(data.physical.vacancy_rate_by_count_percent)}</p><p className="muted">{data.physical.definition}</p>
            <p>Stichtag {data.snapshot.as_of}: {data.snapshot.leaves_vacant} von {data.snapshot.leaves_total} Einheiten unbelegt.</p></Card>
          <Card><div className="card-head"><h2>B · Wirtschaftlicher Leerstand</h2></div>
            <p style={{ fontSize: 32, fontWeight: 700 }} data-testid="econ">{eur(data.economic.cost)}</p><p className="muted">{data.economic.definition}</p>
            <p>{data.economic.days_vacant_with_main_obligation} Leerstandstage mit Mietverpflichtung.</p></Card>
        </div>
        {data.warnings.map((w, i) => <div key={i} className="alert warn" style={{ marginTop: 12 }}>{w.message}</div>)}
        <Card className=""><div className="card-head" style={{ marginTop: 20 }}><h2>Je Einheit (Bett / Zimmer / Wohneinheit)</h2></div>
          <table><thead><tr><th>Einheit</th><th>Tage leer</th><th>Tage mit Hauptmietpflicht</th><th>davon leer</th><th>Leerstandskosten</th></tr></thead>
            <tbody>{data.rows.map((r, i) => <tr key={i}><td>{r.label}</td><td>{r.days_vacant} / {r.days_total}</td><td>{r.days_with_main_obligation}</td><td>{r.days_vacant_with_main_obligation}</td><td>{eur(r.economic_vacancy_cost)}</td></tr>)}</tbody></table></Card></>}
    </>
  );
}
