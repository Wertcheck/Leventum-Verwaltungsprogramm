import { useState } from "react";
import { api, ApiError } from "../lib/api";
import { dateDe, eur, useFetch } from "../lib/hooks";
import { Badge, Card, EmptyState, PageHeader } from "../components/ui";
import { Field, Modal, Select, Text } from "../components/Form";
import { useDialogs } from "../components/Dialogs";

interface Stmt { id: number; property_id: number; main_lease_id: number; period_start: string; period_end: string; status: string; stated_balance: string | null; line_count?: number }
interface Line { id: number; cost_type: string; amount: string; allocation_key: string; allocable_status: string; description: string | null; weights: Record<string, string> }
interface Computed { total_costs: string; costs_by_allocable_status: Record<string, string>; suggested_prepayments: string | null; prepayments: string | null; prepayments_source: string | null; balance: string | null; direction: string | null; stated_balance: string | null; deviation_from_stated: string | null; warnings: { code: string; message: string }[] }
interface Detail extends Stmt { unit_ids: number[]; lines: Line[]; computed: Computed }
interface Alloc { frozen: boolean; frozen_at?: string; unallocated: string; per_unit: Record<string, string>; lines: { line_id: number; cost_type: string; amount: string; key: string; problem?: string }[]; warnings: { message: string }[] }
interface Cmp { rows: { unit_id: number; unit_number: string; allocated_actual_costs: string; downstream_prepayments_soll: string; downstream_flat_rates_soll: string; claim_possible: boolean; agreements: { lease_id: number; mode: string; claim_status: string }[] }[]; totals: Record<string, string>; unattributable_subleases: unknown[]; warnings: { message: string }[] }
const ST: Record<string, [string, "ok" | "warn" | "err"]> = { draft: ["Entwurf", "warn"], captured: ["Erfasst", "warn"], reviewed: ["Geprüft (gesperrt)", "ok"] };
const KEY: Record<string, string> = { none: "kein Schlüssel", area: "Wohnfläche", equal: "gleich je Einheit", persons: "Personen", consumption: "Verbrauch", custom: "Eigene Gewichte" };
const ALLOC: Record<string, string> = { unreviewed: "ungeprüft", allocable: "umlagefähig", not_allocable: "nicht umlagefähig" };
const SRC: Record<string, string> = { agreed_calculated: "aus Vereinbarung berechnet", statement: "laut Abrechnung", manual: "manuell" };

export default function UtilityPage() {
  const [sel, setSel] = useState<number | null>(null), [creating, setCreating] = useState(false);
  const list = useFetch<{ items: Stmt[] }>("/utility-statements");
  return (
    <>
      <PageHeader title="Betriebskosten" subtitle="Ebene A: Abrechnungen des Vermieters an Leventum (Hauptmietvertrag) · Ebene B: Vergleich mit den Vorauszahlungen/Pauschalen der Untermieter. Keine automatischen Nachforderungen, keine geschätzten Werte." />
      <Card>
        <div className="card-head"><h2>Abrechnungen</h2><button className="btn primary" onClick={() => setCreating(true)}>Abrechnung erfassen</button></div>
        {list.error && <div className="alert err">{list.error}</div>}
        {list.data && list.data.items.length === 0 ? <EmptyState title="Noch keine Abrechnungen">Erfassen Sie die erste Betriebskostenabrechnung eines Vermieters.</EmptyState> : (
          <table><thead><tr><th>Zeitraum</th><th>Hauptmietvertrag</th><th>Positionen</th><th>Status</th><th /></tr></thead>
            <tbody>{list.data?.items.map((s) => <tr key={s.id}><td>{dateDe(s.period_start)} – {dateDe(s.period_end)}</td><td>#{s.main_lease_id}</td><td>{s.line_count ?? 0}</td>
              <td><Badge tone={ST[s.status]?.[1] ?? "warn"}>{ST[s.status]?.[0] ?? s.status}</Badge></td><td><button className="btn small" onClick={() => setSel(s.id)}>Öffnen</button></td></tr>)}</tbody></table>)}
      </Card>
      {creating && <CreateStatement onClose={() => setCreating(false)} onDone={(id) => { setCreating(false); list.reload(); setSel(id); }} />}
      {sel !== null && <StatementEditor id={sel} onClose={() => { setSel(null); list.reload(); }} />}
    </>
  );
}

function CreateStatement({ onClose, onDone }: { onClose: () => void; onDone: (id: number) => void }) {
  const leases = useFetch<{ items: { id: number; spaces: string[]; parties: { name: string; role: string }[] }[] }>("/leases?kind=main");
  const [f, setF] = useState<Record<string, string>>({}), [units, setUnits] = useState<number[]>([]), [err, setErr] = useState("");
  const props = useFetch<{ items: { id: number; name: string }[] }>("/properties");
  const prop = useFetch<{ units: { id: number; unit_number: string }[] }>(f.property ? `/properties/${f.property}` : null);
  const set = (k: string) => (v: string) => setF({ ...f, [k]: v });
  async function save() {
    setErr("");
    try { const r = await api<{ id: number }>("/utility-statements", { method: "POST", json: { main_lease_id: Number(f.lease), period_start: f.start, period_end: f.end, unit_ids: units, ...(f.stated ? { stated_balance: f.stated } : {}) } }); onDone(r.id); }
    catch (e) { setErr(e instanceof ApiError ? e.message : "Fehler"); }
  }
  return (
    <Modal title="Abrechnung erfassen" onClose={onClose}><div className="form-grid">
      <Field label="Objekt"><Select value={f.property ?? ""} onChange={(v) => { setF({ ...f, property: v }); setUnits([]); }} empty="– wählen –" options={(props.data?.items ?? []).map((p) => ({ value: p.id, label: p.name }))} /></Field>
      <Field label="Hauptmietvertrag"><Select value={f.lease ?? ""} onChange={set("lease")} empty="– wählen –" options={(leases.data?.items ?? []).map((l) => ({ value: l.id, label: `#${l.id} ${l.parties.map((p) => p.name).join(", ")} – ${l.spaces.join("; ")}` }))} /></Field>
      <Field label="Zeitraum von"><Text type="date" value={f.start ?? ""} onChange={set("start")} /></Field>
      <Field label="Zeitraum bis"><Text type="date" value={f.end ?? ""} onChange={set("end")} /></Field>
      <Field label="Vom Vermieter ausgewiesenes Ergebnis (€, + Nachzahlung / − Guthaben, optional)"><Text value={f.stated ?? ""} onChange={set("stated")} placeholder="-120.50" /></Field>
      <div className="full"><strong>Einbezogene Wohneinheiten</strong>
        {!f.property ? <p className="muted">Erst ein Objekt wählen.</p> : <div>{prop.data?.units.map((u) => <label className="check" key={u.id} style={{ marginRight: 14 }}><input type="checkbox" checked={units.includes(u.id)} onChange={(e) => setUnits(e.target.checked ? [...units, u.id] : units.filter((x) => x !== u.id))} /> {u.unit_number}</label>)}</div>}</div>
      <div className="full">{err && <div className="alert err" role="alert">{err}</div>}<button className="btn primary" disabled={!f.lease || !f.start || !f.end || units.length === 0} onClick={save}>Anlegen</button></div>
    </div></Modal>
  );
}

function StatementEditor({ id, onClose }: { id: number; onClose: () => void }) {
  const { ask, confirmBox } = useDialogs();
  const d = useFetch<Detail>(`/utility-statements/${id}`);
  const alloc = useFetch<Alloc>(`/utility-statements/${id}/allocation`);
  const cmp = useFetch<Cmp>(`/utility-statements/${id}/comparison`);
  const types = useFetch<{ items: { id: number; name: string }[] }>("/cost-types");
  const [line, setLine] = useState<Record<string, string>>({ key: "none", status: "unreviewed" }), [msg, setMsg] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const reloadAll = () => { d.reload(); alloc.reload(); cmp.reload(); };
  async function run(fn: () => Promise<unknown>, ok?: string) { setMsg(null); try { await fn(); if (ok) setMsg({ tone: "ok", text: ok }); reloadAll(); } catch (e) { setMsg({ tone: "err", text: e instanceof ApiError ? e.message : "Fehler" }); } }
  const st = d.data; const locked = st?.status === "reviewed";
  async function setPrepay(source: string) {
    let amount = st?.computed.suggested_prepayments ?? null;
    if (source === "manual" || source === "statement" || amount === null) { const a = await ask("Vorauszahlungen insgesamt (€)", { title: "Vorauszahlungen erfassen" }); if (!a) return; amount = a; }
    run(() => api(`/utility-statements/${id}/prepayments`, { method: "PUT", json: { amount, source } }), "Vorauszahlungen gespeichert.");
  }
  async function status(next: string) {
    if (next === "reviewed" && !(await confirmBox("Mit der Prüfung wird die Verteilung eingefroren und die Abrechnung gesperrt. Spätere Änderungen an Flächen oder Stammdaten ändern sie nicht mehr.", { title: "Abrechnung als geprüft markieren", confirmLabel: "Als geprüft markieren" }))) return;
    run(() => api(`/utility-statements/${id}/status`, { method: "POST", json: { status: next } }), "Status gesetzt.");
  }
  return (
    <Modal title={st ? `Abrechnung ${dateDe(st.period_start)} – ${dateDe(st.period_end)}` : "Abrechnung"} onClose={onClose}>
      {d.error && <div className="alert err">{d.error}</div>}
      {msg && <div className={`alert ${msg.tone}`} role="status">{msg.text}</div>}
      {st && <>
        <p><Badge tone={ST[st.status]?.[1] ?? "warn"}>{ST[st.status]?.[0] ?? st.status}</Badge> · Hauptmietvertrag #{st.main_lease_id}{locked && " · gesperrt, Verteilung eingefroren"}</p>
        <h3>Positionen</h3>
        {st.lines.length === 0 ? <p className="muted">Noch keine Positionen.</p> : <div className="table-wrap"><table><thead><tr><th>Kostenart</th><th>Betrag</th><th>Verteilung</th><th>Umlagefähig</th></tr></thead>
          <tbody>{st.lines.map((l) => <tr key={l.id}><td>{l.cost_type}{l.description && <div className="muted">{l.description}</div>}</td><td className="num">{eur(l.amount)}</td><td>{KEY[l.allocation_key] ?? l.allocation_key}</td><td>{ALLOC[l.allocable_status] ?? l.allocable_status}</td></tr>)}</tbody></table></div>}
        {!locked && <div className="form-grid" style={{ marginTop: 10 }}>
          <Field label="Kostenart"><Select value={line.type ?? ""} onChange={(v) => setLine({ ...line, type: v })} empty="– wählen –" options={(types.data?.items ?? []).map((t) => ({ value: t.id, label: t.name }))} /></Field>
          <Field label="Betrag (€)"><Text value={line.amount ?? ""} onChange={(v) => setLine({ ...line, amount: v })} placeholder="480.00" /></Field>
          <Field label="Verteilungsschlüssel"><Select value={line.key} onChange={(v) => setLine({ ...line, key: v })} options={Object.entries(KEY).filter(([k]) => k !== "custom").map(([value, label]) => ({ value, label }))} /></Field>
          <Field label="Umlagefähig?"><Select value={line.status} onChange={(v) => setLine({ ...line, status: v })} options={Object.entries(ALLOC).map(([value, label]) => ({ value, label }))} /></Field>
          <div className="full"><button className="btn" disabled={!line.type || !line.amount} onClick={() => run(async () => { await api(`/utility-statements/${id}/lines`, { method: "POST", json: { cost_type_id: Number(line.type), amount: line.amount, allocation_key: line.key, allocable_status: line.status } }); setLine({ key: "none", status: "unreviewed" }); }, "Position hinzugefügt.")}>Position hinzufügen</button></div></div>}
        <h3>Vorauszahlungen &amp; Ergebnis</h3>
        <dl className="kv">
          <dt>Gesamtkosten</dt><dd>{eur(st.computed.total_costs)}</dd>
          <dt>Vorauszahlungen</dt><dd>{st.computed.prepayments !== null ? `${eur(st.computed.prepayments)} (${SRC[st.computed.prepayments_source ?? ""] ?? "–"})` : "noch nicht erfasst"}</dd>
          <dt>Ergebnis</dt><dd>{st.computed.balance !== null ? `${eur(st.computed.balance)} ${st.computed.direction === "nachzahlung" ? "(Nachzahlung an den Vermieter)" : st.computed.direction === "guthaben" ? "(Guthaben von Vermieter)" : "(ausgeglichen)"}` : "nicht berechnet (Vorauszahlungen fehlen)"}</dd>
          {st.computed.stated_balance !== null && <><dt>Ausgewiesen vom Vermieter</dt><dd>{eur(st.computed.stated_balance)}{st.computed.deviation_from_stated && ` · Abweichung ${eur(st.computed.deviation_from_stated)}`}</dd></>}
        </dl>
        {st.computed.warnings.map((w, i) => <div key={i} className="alert warn">{w.message}</div>)}
        {!locked && <div className="toolbar"><button className="btn" onClick={() => setPrepay("agreed_calculated")}>Aus Vereinbarung übernehmen{st.computed.suggested_prepayments ? ` (${eur(st.computed.suggested_prepayments)})` : ""}</button><button className="btn" onClick={() => setPrepay("manual")}>Manuell eingeben</button></div>}
        <h3>Verteilung auf Wohneinheiten {alloc.data?.frozen && <Badge tone="ok">eingefroren</Badge>}</h3>
        {alloc.data && <>
          <table><thead><tr><th>Wohneinheit</th><th>Anteil</th></tr></thead><tbody>{Object.entries(alloc.data.per_unit).map(([u, v]) => <tr key={u}><td>{cmp.data?.rows.find((r) => String(r.unit_id) === u)?.unit_number ?? `WE-ID ${u}`}</td><td className="num">{eur(v)}</td></tr>)}</tbody></table>
          <p>Nicht zuordenbar: <strong>{eur(alloc.data.unallocated)}</strong> <span className="muted">(Beträge ohne Schlüssel oder nicht umlagefähig werden nicht verteilt und nicht geschätzt)</span></p>
          {alloc.data.warnings.map((w, i) => <div key={i} className="alert warn">{w.message}</div>)}</>}
        <h3>Vergleich mit Untermietern (Ebene B)</h3>
        {cmp.data && <>
          <table><thead><tr><th>Wohneinheit</th><th>Tatsächliche Kosten</th><th>Vorauszahlungen (Soll)</th><th>Pauschalen (Soll)</th><th>Nachforderung möglich?</th></tr></thead>
            <tbody>{cmp.data.rows.map((r) => <tr key={r.unit_id}><td>{r.unit_number}</td><td className="num">{eur(r.allocated_actual_costs)}</td><td className="num">{eur(r.downstream_prepayments_soll)}</td><td className="num">{eur(r.downstream_flat_rates_soll)}</td><td>{r.claim_possible ? "Prüfung nötig" : "nein / nicht vereinbart"}</td></tr>)}</tbody></table>
          <p className="muted">Es wird nichts automatisch nachgefordert; Ergebnisse sind Prüfgrundlage.</p>
          {cmp.data.warnings.map((w, i) => <div key={i} className="alert warn">{w.message}</div>)}</>}
        <div className="toolbar" style={{ marginTop: 12 }}>
          {st.status === "draft" && <button className="btn primary" onClick={() => status("captured")}>Als erfasst markieren</button>}
          {st.status === "captured" && <button className="btn primary" disabled={st.computed.prepayments === null} onClick={() => status("reviewed")}>Als geprüft markieren (sperren)</button>}
        </div>
      </>}
    </Modal>
  );
}
