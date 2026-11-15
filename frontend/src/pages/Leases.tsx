import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { dateDe, eur, useFetch } from "../lib/hooks";
import { Badge, Card, EmptyState, PageHeader } from "../components/ui";
import { Field, Modal, Select, Text } from "../components/Form";

interface LeaseRow { id: number; kind: string; status: string; type: string; start_date: string; end_date: string | null; spaces: string[]; parties: { party_id: number; name: string; role: string }[] }
interface Issue { code: string; message: string }
interface Validation { errors: Issue[]; warnings: Issue[]; hints: Issue[] }
interface Detail extends LeaseRow {
  legal_review_status: string; legal_basis_ref: string | null; legal_basis_note: string | null; fixed_term_reason: string | null; is_fixed_term: boolean; intended_use: string | null;
  terms: { id: number; valid_from: string; valid_to: string | null; base_rent: string; other_charges: string; rent_period: string }[];
  utility_agreements: { id: number; valid_from: string; valid_to: string | null; mode: string; monthly_amount: string | null; settlement_agreed: boolean | null; description: string | null }[];
  notes: { id: number; kind: string; text: string; created_at: string }[];
  monthly_total: { available: boolean; base_rent?: string; other_charges?: string; utility_amount?: string; utility_mode?: string | null; total?: string; reason?: string };
  validation: Validation | null; activation_warnings?: Validation;
}
const STATUS: Record<string, [string, "ok" | "warn" | "err"]> = { active: ["Aktiv", "ok"], terminated: ["Kündigung", "warn"], ended: ["Beendet", "err"], draft: ["Entwurf", "warn"], cancelled: ["Storniert", "err"] };
const MODE: Record<string, string> = { flat_rate: "Nebenkostenpauschale (keine Abrechnung)", prepayment: "Vorauszahlung mit Abrechnung", included: "In der Gesamtmiete enthalten", individual: "Individuelle Vereinbarung", none: "Keine Nebenkosten vereinbart" };
const REVIEW: Record<string, string> = { not_reviewed: "Nicht geprüft", in_review: "In Prüfung", reviewed: "Geprüft (manuell dokumentiert)" };

export function LeasesPage({ kind, title }: { kind?: "main" | "sub"; title: string }) {
  const [status, setStatus] = useState(""), [open, setOpen] = useState(false);
  const nav = useNavigate();
  const { data, error, reload } = useFetch<{ items: LeaseRow[] }>(`/leases?${new URLSearchParams({ ...(kind && { kind }), ...(status && { status }) })}`);
  return (
    <>
      <PageHeader title={title} subtitle={kind === "sub" ? "Untermietverhältnisse (Leventum → Mieter)" : kind === "main" ? "Hauptmietverträge (Vermieter → Leventum)" : "Haupt- und Untermietverträge"} />
      <Card>
        <div className="toolbar">
          <Select value={status} onChange={setStatus} empty="Alle Status" options={Object.entries(STATUS).map(([value, [label]]) => ({ value, label }))} />
          <div className="grow" /><button className="btn primary" onClick={() => setOpen(true)}>Vertrag anlegen</button>
        </div>
        {error && <div className="alert err">{error}</div>}
        {data && data.items.length === 0 ? <EmptyState title="Keine Verträge" /> : (
          <table><thead><tr><th>Art</th><th>Parteien</th><th>Mietgegenstand</th><th>Zeitraum</th><th>Status</th></tr></thead>
            <tbody>{data?.items.map((l) => <tr key={l.id} className="row-link" onClick={() => nav(`/vertraege/${l.id}`)}>
              <td><strong>{l.kind === "main" ? "Hauptmiete" : "Untermiete"}</strong><div className="muted">{l.type}</div></td>
              <td>{l.parties.filter((p) => p.role !== "occupant").map((p) => p.name).join(" → ")}</td><td>{l.spaces.join("; ")}</td>
              <td>{dateDe(l.start_date)} – {l.end_date ? dateDe(l.end_date) : "unbefristet"}</td><td><Badge tone={STATUS[l.status][1]}>{STATUS[l.status][0]}</Badge></td></tr>)}</tbody></table>)}
      </Card>
      {open && <Modal title="Vertrag anlegen (Entwurf)" onClose={() => setOpen(false)}><LeaseForm defaultKind={kind ?? "sub"} onDone={(id) => { setOpen(false); reload(); nav(`/vertraege/${id}`); }} /></Modal>}
    </>
  );
}

function LeaseForm({ defaultKind, onDone }: { defaultKind: "main" | "sub"; onDone: (id: number) => void }) {
  const [kind, setKind] = useState<string>(defaultKind);
  const parties = useFetch<{ items: { id: number; display_name: string; roles: string[]; is_own_organization: boolean }[] }>("/parties");
  const types = useFetch<{ items: { id: number; name: string; applies_to: string }[] }>("/lease-types");
  const props = useFetch<{ items: { id: number }[] }>("/properties");
  const rus = useFetch<{ items: { id: number; label: string }[] }>("/rentable-units");
  const [f, setF] = useState<Record<string, string>>({ mode: "prepayment" });
  const [ruIds, setRuIds] = useState<number[]>([]);
  const [err, setErr] = useState("");
  const set = (k: string) => (v: string) => setF({ ...f, [k]: v });
  const own = parties.data?.items.find((p) => p.is_own_organization);
  const pOpts = (pred: (p: { roles: string[]; is_own_organization: boolean }) => boolean) => (parties.data?.items ?? []).filter(pred).map((p) => ({ value: p.id, label: p.display_name }));
  async function submit(e: FormEvent) {
    e.preventDefault(); setErr("");
    if (!own) return setErr("Legen Sie zuerst Ihre eigene Organisation (Leventum) als Partei an.");
    const lessor = kind === "main" ? Number(f.counterparty) : own.id, lessee = kind === "main" ? own.id : Number(f.counterparty);
    try {
      const lease = await api<{ id: number }>("/leases", { method: "POST", json: {
        kind, lease_type_id: Number(f.type), start_date: f.start, end_date: f.end || null, is_fixed_term: !!f.end && f.fixed === "1", intended_use: f.use || null,
        subletting_permitted: kind === "main" ? (f.sublet === "" || f.sublet === undefined ? null : f.sublet === "1") : null,
        parties: [{ party_id: lessor, role: "lessor" }, { party_id: lessee, role: "lessee" }], rentable_unit_ids: ruIds } });
      if (f.rent) await api(`/leases/${lease.id}/terms`, { method: "POST", json: { valid_from: f.start, base_rent: f.rent, other_charges: f.other || "0.00" } });
      await api(`/leases/${lease.id}/utility-agreements`, { method: "POST", json: { valid_from: f.start, mode: f.mode, monthly_amount: ["flat_rate", "prepayment"].includes(f.mode) ? f.nk || "0.00" : null, description: f.mode === "individual" ? f.desc : null } });
      onDone(lease.id);
    } catch (x) { setErr(x instanceof ApiError ? x.message : "Fehler"); }
  }
  void props;
  return (
    <form onSubmit={submit} className="form-grid">
      <Field label="Vertragsart (Haupt/Unter)"><Select value={kind} onChange={setKind} options={[{ value: "main", label: "Hauptmietvertrag" }, { value: "sub", label: "Untermietvertrag" }]} /></Field>
      <Field label="Vertragstyp"><Select value={f.type ?? ""} onChange={set("type")} empty="– wählen –" options={(types.data?.items ?? []).filter((t) => t.applies_to !== (kind === "main" ? "sub" : "main")).map((t) => ({ value: t.id, label: t.name }))} /></Field>
      <Field label={kind === "main" ? "Vermieter (Eigentümer)" : "Mieter"}><Select value={f.counterparty ?? ""} onChange={set("counterparty")} empty="– wählen –" options={pOpts((p) => !p.is_own_organization && (kind === "main" ? p.roles.some((r) => r === "owner" || r === "landlord") : p.roles.includes("tenant")))} /></Field>
      <Field label="Mietgegenstand (Strg/Cmd für Mehrfachauswahl)">
        <select className="field" multiple size={4} value={ruIds.map(String)} onChange={(e) => setRuIds(Array.from(e.target.selectedOptions, (o) => Number(o.value)))}>
          {(rus.data?.items ?? []).map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}</select></Field>
      <Field label="Vertragsbeginn"><Text type="date" value={f.start ?? ""} onChange={set("start")} required /></Field>
      <Field label="Vertragsende (leer = unbefristet)"><Text type="date" value={f.end ?? ""} onChange={set("end")} /></Field>
      <Field label="Befristet?"><Select value={f.fixed ?? ""} onChange={set("fixed")} options={[{ value: "", label: "Nein / unbefristet" }, { value: "1", label: "Ja, befristeter Vertrag" }]} /></Field>
      <Field label="Vereinbarte Nutzung (Freitext)"><Text value={f.use ?? ""} onChange={set("use")} placeholder="z. B. Dauerwohnen, Monteur …" /></Field>
      {kind === "main" && <Field label="Untervermietung erlaubt?"><Select value={f.sublet ?? ""} onChange={set("sublet")} options={[{ value: "", label: "Ungeklärt" }, { value: "1", label: "Ja" }, { value: "0", label: "Nein" }]} /></Field>}
      <Field label="Kaltmiete / Monat (€)"><Text value={f.rent ?? ""} onChange={set("rent")} placeholder="850.00" /></Field>
      <Field label="Sonstige Zuschläge (€)"><Text value={f.other ?? ""} onChange={set("other")} placeholder="0.00" /></Field>
      <Field label="Nebenkostenvereinbarung"><Select value={f.mode} onChange={set("mode")} options={Object.entries(MODE).map(([value, label]) => ({ value, label }))} /></Field>
      {["flat_rate", "prepayment"].includes(f.mode) && <Field label="Nebenkosten / Monat (€)"><Text value={f.nk ?? ""} onChange={set("nk")} placeholder="180.00" /></Field>}
      {f.mode === "individual" && <Field label="Beschreibung der Vereinbarung"><Text value={f.desc ?? ""} onChange={set("desc")} required /></Field>}
      <div className="full"><p className="muted">Der Vertrag wird als Entwurf angelegt und erst nach Konsistenzprüfung aktiviert. Es erfolgt keine rechtliche Einordnung.</p>
        {err && <div className="alert err">{err}</div>}<button className="btn primary">Entwurf anlegen</button></div>
    </form>
  );
}

const IssueList = ({ title, tone, items }: { title: string; tone: "err" | "warn" | "ok"; items: Issue[] }) => items.length === 0 ? null : (
  <div className={`alert ${tone}`}><strong>{title}</strong><ul style={{ margin: "6px 0 0 18px", padding: 0 }}>{items.map((i, k) => <li key={k}>{i.message}</li>)}</ul></div>);

export function LeaseDetail() {
  const { id } = useParams();
  const { data, error, reload } = useFetch<Detail>(`/leases/${id}`);
  const [issues, setIssues] = useState<Validation | null>(null);
  const [msg, setMsg] = useState("");
  if (error) return <div className="alert err">{error}</div>;
  if (!data) return null;
  async function run(fn: () => Promise<unknown>) {
    setMsg(""); setIssues(null);
    try { await fn(); reload(); } catch (x) {
      if (x instanceof ApiError && x.code === "validation_failed") { setMsg("Aktivierung nicht möglich:"); await api<Validation>(`/leases/${id}/validation`).then(setIssues); } else setMsg(x instanceof ApiError ? x.message : "Fehler");
    }
  }
  const v = issues ?? data.validation;
  return (
    <>
      <PageHeader title={`${data.kind === "main" ? "Hauptmietvertrag" : "Untermietvertrag"} #${data.id}`} subtitle={`${data.type} · ${data.spaces.join("; ")}`} />
      <div className="toolbar">
        <Badge tone={STATUS[data.status][1]}>{STATUS[data.status][0]}</Badge>
        {data.status === "draft" && <button className="btn primary" onClick={() => run(() => api(`/leases/${id}/activate`, { method: "POST" }))}>Prüfen &amp; aktivieren</button>}
        {data.status === "active" && <button className="btn" onClick={() => { const eff = window.prompt("Beendigungsdatum (JJJJ-MM-TT)"); if (eff) run(() => api(`/leases/${id}/terminate`, { method: "POST", json: { terminated_on: new Date().toISOString().slice(0, 10), effective_on: eff } })); }}>Kündigung erfassen</button>}
      </div>
      {msg && <div className="alert err">{msg}</div>}
      {v && <><IssueList title="Fehler" tone="err" items={v.errors} /><IssueList title="Warnungen" tone="warn" items={v.warnings} /><IssueList title="Hinweise (keine Rechtsauskunft)" tone="ok" items={v.hints} /></>}
      <div className="grid two-col">
        <Card><div className="card-head"><h2>Parteien &amp; Laufzeit</h2></div>
          <dl className="kv">{data.parties.map((p) => <><dt key={`t${p.party_id}${p.role}`}>{({ lessor: "Vermieter", lessee: "Mieter", co_lessee: "Mitmieter", occupant: "Bewohner", guarantor: "Bürge" } as Record<string, string>)[p.role]}</dt><dd key={`d${p.party_id}${p.role}`}><Link className="link" to={`/parteien/${p.party_id}`}>{p.name}</Link></dd></>)}
            <dt>Beginn</dt><dd>{dateDe(data.start_date)}</dd><dt>Ende</dt><dd>{data.end_date ? dateDe(data.end_date) : "unbefristet"}</dd>
            <dt>Befristungsgrund</dt><dd>{data.fixed_term_reason ?? "–"}</dd><dt>Vereinbarte Nutzung</dt><dd>{data.intended_use ?? "–"}</dd></dl></Card>
        <Card><div className="card-head"><h2>Konditionen (Soll)</h2></div>
          {data.monthly_total.available ? <dl className="kv"><dt>Kaltmiete</dt><dd>{eur(data.monthly_total.base_rent)}</dd><dt>Sonstige Zuschläge</dt><dd>{eur(data.monthly_total.other_charges)}</dd>
            <dt>Nebenkosten</dt><dd>{eur(data.monthly_total.utility_amount)} <span className="muted">({data.monthly_total.utility_mode ? MODE[data.monthly_total.utility_mode] : "keine Vereinbarung"})</span></dd><dt><strong>Gesamt</strong></dt><dd><strong>{eur(data.monthly_total.total)}</strong></dd></dl>
            : <p className="muted">{data.monthly_total.reason ?? "Keine Mietkonditionen erfasst."}</p>}
          <h2 style={{ margin: "18px 0 8px" }}>Nebenkostenvereinbarungen</h2>
          {data.utility_agreements.map((a) => <div className="list-row" key={a.id}><div className="grow"><strong>{MODE[a.mode]}</strong><div className="muted">ab {dateDe(a.valid_from)}{a.valid_to ? ` bis ${dateDe(a.valid_to)}` : ""} · Abrechnung vereinbart: {a.settlement_agreed === null ? "ungeklärt" : a.settlement_agreed ? "ja" : "nein"}</div></div><span>{a.monthly_amount ? eur(a.monthly_amount) : ""}</span></div>)}
        </Card>
      </div>
      <Card className="" >
        <div className="card-head"><h2>Rechtliche Dokumentation</h2></div>
        <p className="muted" style={{ marginBottom: 10 }}>Die Software ordnet Verträge nicht rechtlich ein. Hier dokumentieren Sie nur Ihre eigene bzw. anwaltliche Einordnung.</p>
        <dl className="kv"><dt>Prüfstatus</dt><dd>{REVIEW[data.legal_review_status]}</dd><dt>Rechtliche Grundlage</dt><dd>{data.legal_basis_ref ?? "–"}</dd><dt>Prüfvermerk</dt><dd>{data.legal_basis_note ?? "–"}</dd></dl>
        <div className="toolbar" style={{ marginTop: 12 }}>
          <button className="btn" onClick={() => { const ref = window.prompt("Rechtliche Grundlage (Freitext, z. B. § 549 BGB) – leer lassen, wenn keine"); const note = window.prompt("Prüfvermerk (wer hat wann geprüft?)"); if (note) run(() => api(`/leases/${id}/legal-review`, { method: "POST", json: { status: "reviewed", basis_ref: ref || null, basis_note: note } })); }}>Prüfung dokumentieren</button>
          <button className="btn" onClick={() => { const t = window.prompt("Interner Hinweis / Vermerk"); if (t) run(() => api(`/leases/${id}/notes`, { method: "POST", json: { kind: "note", text: t } })); }}>Vermerk hinzufügen</button>
        </div>
        {data.notes.map((n) => <div className="list-row" key={n.id}><span className="muted">{dateDe(n.created_at)}</span><span>{n.text}</span></div>)}
      </Card>
    </>
  );
}
