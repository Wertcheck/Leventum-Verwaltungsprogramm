import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { dateDe, eur, useFetch } from "../lib/hooks";
import { Badge, Card, EmptyState, PageHeader } from "../components/ui";
import { Field, Modal, Select, Text } from "../components/Form";
import EditDialog from "../components/EditDialog";
import TenantPanel, { PHASE } from "../components/TenantPanel";

interface Party { id: number; display_name: string; kind: string; email: string | null; phone: string | null; city: string | null; roles: string[]; is_active: boolean }
interface TenantRow { party_id: number; name: string; lease_id: number | null; lease_status?: string; spaces?: string[]; start_date?: string; end_date?: string | null; monthly_total?: { available: boolean; total?: string } | null; payment_status?: string | null; overdue_amount?: string; last_activity: string | null }
const STATUS: Record<string, [string, "ok" | "warn" | "err"]> = { active: ["Aktiv", "ok"], terminated: ["Kündigung", "warn"], ended: ["Beendet", "err"], draft: ["Entwurf", "warn"] };

function PartyForm({ role, onDone }: { role: string; onDone: () => void }) {
  const [kind, setKind] = useState("person");
  const [f, setF] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");
  const set = (k: string) => (v: string) => setF({ ...f, [k]: v });
  async function submit(e: FormEvent) {
    e.preventDefault();
    const body: Record<string, unknown> = { kind, roles: [role] };
    for (const [k, v] of Object.entries(f)) if (v.trim()) body[k] = v.trim();
    try { await api("/parties", { method: "POST", json: body }); onDone(); } catch (x) { setErr(x instanceof ApiError ? x.message : "Fehler"); }
  }
  return (
    <form onSubmit={submit} className="form-grid">
      <Field label="Art"><Select value={kind} onChange={setKind} options={[{ value: "person", label: "Person" }, { value: "company", label: "Firma" }]} /></Field>
      {kind === "company" ? <Field label="Firmenname"><Text value={f.company_name ?? ""} onChange={set("company_name")} required /></Field> : <>
        <Field label="Vorname"><Text value={f.first_name ?? ""} onChange={set("first_name")} /></Field>
        <Field label="Nachname"><Text value={f.last_name ?? ""} onChange={set("last_name")} required /></Field></>}
      <Field label="E-Mail"><Text value={f.email ?? ""} onChange={set("email")} /></Field>
      <Field label="Telefon"><Text value={f.phone ?? ""} onChange={set("phone")} /></Field>
      <Field label="Straße"><Text value={f.street ?? ""} onChange={set("street")} /></Field>
      <Field label="PLZ"><Text value={f.postal_code ?? ""} onChange={set("postal_code")} /></Field>
      <Field label="Ort"><Text value={f.city ?? ""} onChange={set("city")} /></Field>
      <div className="full">{err && <div className="alert err">{err}</div>}<button className="btn primary">Anlegen</button></div>
    </form>
  );
}

export function TenantsPage() {
  const [params, setParams] = useSearchParams();
  const sel = params.get("mieter") ? Number(params.get("mieter")) : null;
  const [status, setStatus] = useState(""), [q, setQ] = useState(""), [open, setOpen] = useState(false);
  const { data, error, reload } = useFetch<{ items: TenantRow[]; total: number; limit: number }>(`/tenants?${new URLSearchParams({ ...(status && { status }), ...(q && { q }) })}`);
  const select = (id: number | null) => { const n = new URLSearchParams(params); if (id) n.set("mieter", String(id)); else n.delete("mieter"); setParams(n, { replace: true }); };
  return (
    <>
      <PageHeader title="Mieter" subtitle="Untermieter von Leventum – Zeile anklicken für die Details" />
      <div className={`split ${sel ? "with-panel" : ""}`}>
        <Card>
          <div className="toolbar">
            <input className="field" placeholder="Mieter suchen …" aria-label="Mieter suchen" value={q} onChange={(e) => setQ(e.target.value)} />
            <Select value={status} onChange={setStatus} empty="Alle Status" options={[{ value: "active", label: "Aktiv" }, { value: "upcoming", label: "Anstehend" }, { value: "notice", label: "Gekündigt (läuft noch)" }, { value: "ended", label: "Beendet" }, { value: "draft", label: "Entwurf" }, { value: "arrears", label: "Mit Rückstand" }]} />
            <div className="grow" /><button className="btn primary" onClick={() => setOpen(true)}>Mieter anlegen</button>
          </div>
          {error && <div className="alert err">{error}</div>}
          {data && data.items.length === 0 ? <EmptyState title="Keine Mieter">Keine Treffer – oder legen Sie den ersten Mieter an.</EmptyState> : (
            <div className="table-wrap"><table><thead><tr><th>Name</th><th>Mietgegenstand</th><th>Zeitraum</th><th>Status</th><th>Soll / Monat</th><th>Zahlung</th></tr></thead>
              <tbody>{data?.items.map((r, i) => (
                <tr key={i} className={`row-link ${sel === r.party_id ? "selected" : ""}`} tabIndex={0} aria-selected={sel === r.party_id} onClick={() => select(r.party_id)} onKeyDown={(e) => e.key === "Enter" && select(r.party_id)}>
                  <td><strong>{r.name}</strong></td><td>{r.spaces?.join("; ") ?? "–"}</td><td>{r.start_date ? `${dateDe(r.start_date)} – ${r.end_date ? dateDe(r.end_date) : "offen"}` : "–"}</td>
                  <td>{r.lease_status ? <Badge tone={PHASE[r.lease_status]?.[1] ?? "warn"}>{PHASE[r.lease_status]?.[0] ?? r.lease_status}</Badge> : "–"}</td>
                  <td className="num">{r.monthly_total?.available ? eur(r.monthly_total.total) : "–"}</td>
                  <td>{r.payment_status === "arrears" ? <Badge tone="err">Rückstand {eur(r.overdue_amount)}</Badge> : r.payment_status === "current" ? <Badge tone="ok">Ausgeglichen</Badge> : "–"}</td></tr>))}</tbody></table></div>)}
          {data && <p className="muted" style={{ marginTop: 10 }}>{data.items.length} von {data.total} Einträgen</p>}
        </Card>
        {sel && <TenantPanel key={sel} partyId={sel} onClose={() => select(null)} />}
      </div>
      {open && <Modal title="Mieter anlegen" onClose={() => setOpen(false)}><PartyForm role="tenant" onDone={() => { setOpen(false); reload(); }} /></Modal>}
    </>
  );
}

export function OwnersPage() {
  const [open, setOpen] = useState(false);
  const owners = useFetch<{ items: Party[] }>("/parties?role=owner");
  const landlords = useFetch<{ items: Party[] }>("/parties?role=landlord");
  const nav = useNavigate();
  const items = [...(owners.data?.items ?? []), ...(landlords.data?.items ?? []).filter((l) => !owners.data?.items.some((o) => o.id === l.id))];
  return (
    <>
      <PageHeader title="Eigentümer & Vermieter" subtitle="Vertragspartner der Hauptmietverträge" />
      <Card>
        <div className="toolbar"><div className="grow" /><button className="btn primary" onClick={() => setOpen(true)}>Eigentümer anlegen</button></div>
        {items.length === 0 ? <EmptyState title="Keine Eigentümer">Legen Sie den ersten Eigentümer an.</EmptyState> : (
          <table><thead><tr><th>Name</th><th>Rollen</th><th>Ort</th><th>E-Mail</th></tr></thead>
            <tbody>{items.map((p) => <tr key={p.id} className="row-link" onClick={() => nav(`/parteien/${p.id}`)}><td><strong>{p.display_name}</strong></td><td>{p.roles.join(", ")}</td><td>{p.city ?? "–"}</td><td>{p.email ?? "–"}</td></tr>)}</tbody></table>)}
      </Card>
      {open && <Modal title="Eigentümer anlegen" onClose={() => setOpen(false)}><PartyForm role="owner" onDone={() => { setOpen(false); owners.reload(); landlords.reload(); }} /></Modal>}
    </>
  );
}

export function PartyDetail() {
  const { id } = useParams();
  const hist = useFetch<{ items: { at: string; summary: string; actor: string | null; source: string }[] }>(`/history?entity_type=party&entity_id=${id}`);
  const [editing, setEditing] = useState(false);
  const { data, error, reload } = useFetch<Party & { leases: { id: number; kind: string; status: string; type: string; spaces: string[]; start_date: string; end_date: string | null }[]; history: { at: string; summary: string }[]; notes: string | null }>(`/parties/${id}`);
  if (error) return <div className="alert err">{error}</div>;
  if (!data) return null;
  return (
    <>
      <PageHeader title={data.display_name} subtitle={data.roles.join(", ")} />
      <div className="toolbar"><button className="btn" onClick={() => setEditing(true)}>Stammdaten bearbeiten</button></div>
      {editing && <EditDialog title="Stammdaten bearbeiten" path={`/parties/${data.id}`} initial={data as unknown as Record<string, unknown>} onClose={() => setEditing(false)} onSaved={reload}
        note="Änderungen werden mit Vorher/Nachher im Protokoll festgehalten (IBAN und Geburtsdatum maskiert)."
        fields={[{ key: "first_name", label: "Vorname" }, { key: "last_name", label: "Nachname" }, { key: "company_name", label: "Firmenname" }, { key: "email", label: "E-Mail" }, { key: "phone", label: "Telefon" }, { key: "street", label: "Straße" }, { key: "postal_code", label: "PLZ" }, { key: "city", label: "Ort" }, { key: "iban", label: "IBAN" }]} />}
      <div className="grid two-col">
        <Card><div className="card-head"><h2>Verträge</h2></div>
          {data.leases.length === 0 ? <EmptyState title="Keine Verträge" /> : <table><thead><tr><th>Art</th><th>Mietgegenstand</th><th>Zeitraum</th><th>Status</th></tr></thead>
            <tbody>{data.leases.map((l) => <tr key={l.id}><td><Link className="link" to={`/vertraege/${l.id}`}>{l.type}</Link></td><td>{l.spaces.join("; ")}</td><td>{dateDe(l.start_date)} – {l.end_date ? dateDe(l.end_date) : "unbefristet"}</td><td><Badge tone={STATUS[l.status]?.[1] ?? "warn"}>{STATUS[l.status]?.[0] ?? l.status}</Badge></td></tr>)}</tbody></table>}
        </Card>
        <Card><div className="card-head"><h2>Stammdaten</h2></div>
          <dl className="kv"><dt>E-Mail</dt><dd>{data.email ?? "–"}</dd><dt>Telefon</dt><dd>{data.phone ?? "–"}</dd><dt>Ort</dt><dd>{data.city ?? "–"}</dd></dl>
          <h2 style={{ margin: "20px 0 8px" }}>Historie (Vorgänge, Kommunikation, Reparaturen, Aufgaben)</h2>
          {!hist.data || hist.data.items.length === 0 ? <p className="muted">Keine Einträge.</p> : hist.data.items.map((h, i) => <div className="list-row" key={i}><span className="muted">{dateDe(h.at)}</span><span className="grow">{h.summary}</span>{h.actor && <span className="muted">{h.actor}</span>}</div>)}
        </Card>
      </div>
    </>
  );
}
