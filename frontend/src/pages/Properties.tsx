import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { pref, useFetch } from "../lib/hooks";
import { Badge, Card, EmptyState, PageHeader } from "../components/ui";
import { Field, Modal, Select, Text } from "../components/Form";

interface Prop { id: number; name: string; street: string | null; postal_code: string | null; city: string | null; property_type: string; unit_count: number; owner_name: string | null }
interface Bed { id: number; label: string }
interface Room { id: number; name: string; area: string | null; beds: Bed[] }
interface UnitT { id: number; unit_number: string; living_area: string | null; rooms: Room[] }
interface RU { id: number; level: string; label: string }
const TYPES = [["mehrfamilienhaus", "Mehrfamilienhaus"], ["wohnung", "Wohnung"], ["einfamilienhaus", "Einfamilienhaus"], ["gewerbeeinheit", "Gewerbeeinheit"], ["sonstige", "Sonstige Immobilie"]].map(([value, label]) => ({ value, label }));
const LEVEL: Record<string, string> = { property: "Objekt", unit: "Wohneinheit", room: "Zimmer", bed: "Bett" };

export function PropertiesPage() {
  const { data, error, reload } = useFetch<{ items: Prop[] }>("/properties");
  const [open, setOpen] = useState(false);
  const owners = useFetch<{ items: { id: number; display_name: string }[] }>("/parties?role=owner");
  const [f, setF] = useState<Record<string, string>>({ property_type: "mehrfamilienhaus" });
  const [err, setErr] = useState("");
  const nav = useNavigate();
  const set = (k: string) => (v: string) => setF({ ...f, [k]: v });
  async function submit(e: FormEvent) {
    e.preventDefault();
    const body: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(f)) if (v.trim()) body[k] = k === "owner_party_id" || k === "year_built" ? Number(v) : v.trim();
    try { await api("/properties", { method: "POST", json: body }); setOpen(false); reload(); } catch (x) { setErr(x instanceof ApiError ? x.message : "Fehler"); }
  }
  return (
    <>
      <PageHeader title="Objekte" subtitle="Immobilien mit ihren Wohneinheiten" />
      <Card>
        <div className="toolbar"><div className="grow" /><button className="btn primary" onClick={() => setOpen(true)}>Objekt anlegen</button></div>
        {error && <div className="alert err">{error}</div>}
        {data && data.items.length === 0 ? <EmptyState title="Keine Objekte">Legen Sie das erste Objekt an.</EmptyState> : (
          <table><thead><tr><th>Objekt</th><th>Adresse</th><th>Art</th><th>Wohneinheiten</th><th>Eigentümer</th></tr></thead>
            <tbody>{data?.items.map((p) => <tr key={p.id} className="row-link" onClick={() => nav(`/objekte/${p.id}`)}><td><strong>{p.name}</strong></td><td>{[p.street, p.postal_code, p.city].filter(Boolean).join(", ")}</td><td>{TYPES.find((t) => t.value === p.property_type)?.label}</td><td>{p.unit_count}</td><td>{p.owner_name ?? "–"}</td></tr>)}</tbody></table>)}
      </Card>
      {open && <Modal title="Objekt anlegen" onClose={() => setOpen(false)}>
        <form onSubmit={submit} className="form-grid">
          <Field label="Bezeichnung"><Text value={f.name ?? ""} onChange={set("name")} required /></Field>
          <Field label="Objektart"><Select value={f.property_type} onChange={set("property_type")} options={TYPES} /></Field>
          <Field label="Straße"><Text value={f.street ?? ""} onChange={set("street")} /></Field>
          <Field label="PLZ"><Text value={f.postal_code ?? ""} onChange={set("postal_code")} /></Field>
          <Field label="Ort"><Text value={f.city ?? ""} onChange={set("city")} /></Field>
          <Field label="Eigentümer"><Select value={f.owner_party_id ?? ""} onChange={set("owner_party_id")} empty="– keiner –" options={(owners.data?.items ?? []).map((o) => ({ value: o.id, label: o.display_name }))} /></Field>
          <div className="full">{err && <div className="alert err">{err}</div>}<button className="btn primary">Anlegen</button></div>
        </form></Modal>}
    </>
  );
}

export function PropertyDetail() {
  const { id } = useParams();
  const { data, error, reload } = useFetch<Prop & { units: UnitT[]; rentable_units: RU[] }>(`/properties/${id}`);
  const [err, setErr] = useState("");
  async function act(fn: () => Promise<unknown>) { setErr(""); try { await fn(); reload(); } catch (x) { setErr(x instanceof ApiError ? x.message : "Fehler"); } }
  const ask = (q: string) => window.prompt(q)?.trim() || null;
  if (error) return <div className="alert err">{error}</div>;
  if (!data) return null;
  const rentable = (extra: Record<string, number>) => act(() => api("/rentable-units", { method: "POST", json: { property_id: data.id, ...extra } }));
  const has = (level: string, key: string, v: number) => data.rentable_units.some((r) => r.level === level && (r as unknown as Record<string, number>)[key] === v);
  return (
    <>
      <PageHeader title={data.name} subtitle={[data.street, data.postal_code, data.city].filter(Boolean).join(", ")} />
      {err && <div className="alert err">{err}</div>}
      <div className="grid two-col">
        <Card>
          <div className="card-head"><h2>Wohneinheiten, Zimmer, Betten</h2>
            <button className="btn small" onClick={() => { const n = ask("Nummer der Wohneinheit"); if (n) act(() => api(`/properties/${data.id}/units`, { method: "POST", json: { unit_number: n } })); }}>+ Wohneinheit</button></div>
          <div className="tree"><ul style={{ margin: 0, padding: 0, border: 0 }}>{data.units.map((u) => (
            <li key={u.id}><div className="node"><strong>{pref("WE", u.unit_number)}</strong><span className="muted">{u.living_area ? `${u.living_area} m²` : "Fläche fehlt"}</span>
              <button className="btn small" onClick={() => { const n = ask("Name des Zimmers"); if (n) act(() => api(`/units/${u.id}/rooms`, { method: "POST", json: { name: n } })); }}>+ Zimmer</button></div>
              <ul>{u.rooms.map((r) => (
                <li key={r.id}><div className="node">{pref("Zimmer", r.name)}
                  <button className="btn small" onClick={() => { const n = ask("Bezeichnung des Betts"); if (n) act(() => api(`/rooms/${r.id}/beds`, { method: "POST", json: { label: n } })); }}>+ Bett</button></div>
                  <ul>{r.beds.map((b) => <li key={b.id}>{pref("Bett", b.label)}</li>)}</ul></li>))}</ul></li>))}</ul></div>
          {data.units.length === 0 && <EmptyState title="Noch keine Wohneinheiten" />}
        </Card>
        <Card>
          <div className="card-head"><h2>Vermietungseinheiten</h2></div>
          <p className="muted" style={{ marginBottom: 12 }}>Die tatsächlich vermietbaren Einheiten: ganzes Objekt, Wohnung, Zimmer oder Bett. Verträge werden Vermietungseinheiten zugeordnet.</p>
          <div className="list-row"><span className="grow">Gesamtes Objekt</span>{data.rentable_units.some((r) => r.level === "property") ? <Badge tone="ok">angelegt</Badge> : <button className="btn small" onClick={() => rentable({})}>anlegen</button>}</div>
          {data.units.map((u) => (<div key={u.id}>
            <div className="list-row"><span className="grow">{pref("WE", u.unit_number)}</span>{has("unit", "unit_id", u.id) ? <Badge tone="ok">angelegt</Badge> : <button className="btn small" onClick={() => rentable({ unit_id: u.id })}>anlegen</button>}</div>
            {u.rooms.map((r) => (<div key={r.id}>
              <div className="list-row" style={{ paddingLeft: 20 }}><span className="grow">{pref("Zimmer", r.name)}</span>{has("room", "room_id", r.id) ? <Badge tone="ok">angelegt</Badge> : <button className="btn small" onClick={() => rentable({ room_id: r.id })}>anlegen</button>}</div>
              {r.beds.map((b) => <div className="list-row" key={b.id} style={{ paddingLeft: 40 }}><span className="grow">{pref("Bett", b.label)}</span>{has("bed", "bed_id", b.id) ? <Badge tone="ok">angelegt</Badge> : <button className="btn small" onClick={() => rentable({ bed_id: b.id })}>anlegen</button>}</div>)}</div>))}</div>))}
          <p className="muted" style={{ marginTop: 12 }}>Angelegt: {data.rentable_units.length === 0 ? "–" : Object.entries(data.rentable_units.reduce<Record<string, number>>((a, r) => ({ ...a, [LEVEL[r.level]]: (a[LEVEL[r.level]] ?? 0) + 1 }), {})).map(([l, n]) => `${n}× ${l}`).join(", ")}. <Link className="link" to="/vertraege">Zu den Verträgen</Link></p>
        </Card>
      </div>
    </>
  );
}

export function UnitsPage() {
  const { data, error } = useFetch<{ items: { id: number; property_id: number; unit_number: string; floor: string | null; living_area: string | null; occupancy_status: string }[] }>("/units");
  const props = useFetch<{ items: Prop[] }>("/properties");
  const name = (id: number) => props.data?.items.find((p) => p.id === id)?.name ?? "";
  const tone = (s: string): "ok" | "warn" | "err" => (s === "occupied" ? "ok" : s === "vacant" ? "err" : "warn");
  const label: Record<string, string> = { occupied: "Vermietet", vacant: "Leerstehend", reserved: "Reserviert", renovation: "In Renovierung", unavailable: "Nicht verfügbar" };
  return (
    <>
      <PageHeader title="Wohneinheiten" subtitle="Belegung wird aus den laufenden Untermietverträgen berechnet (auch bei Zimmer-/Bettenvermietung)." />
      <Card>
        {error && <div className="alert err">{error}</div>}
        {data && data.items.length === 0 ? <EmptyState title="Keine Wohneinheiten">Wohneinheiten legen Sie in der Objektakte an.</EmptyState> : (
          <table><thead><tr><th>Objekt</th><th>Wohneinheit</th><th>Etage</th><th>Fläche</th><th>Belegung heute</th></tr></thead>
            <tbody>{data?.items.map((u) => <tr key={u.id}><td><Link className="link" to={`/objekte/${u.property_id}`}>{name(u.property_id)}</Link></td><td>{u.unit_number}</td><td>{u.floor ?? "–"}</td><td>{u.living_area ? `${u.living_area} m²` : "–"}</td><td><Badge tone={tone(u.occupancy_status)}>{label[u.occupancy_status]}</Badge></td></tr>)}</tbody></table>)}
      </Card>
    </>
  );
}
