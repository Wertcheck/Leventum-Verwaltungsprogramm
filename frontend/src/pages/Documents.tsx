import { useState } from "react";
import { upload, ApiError } from "../lib/api";
import { useFetch } from "../lib/hooks";
import { Card, EmptyState, PageHeader } from "../components/ui";
import { Field, Modal, Select } from "../components/Form";
import { DOC_TYPES, DocRow, type Doc } from "../components/DocPanel";

const ENT: Record<string, string> = { party: "Partei", property: "Objekt", lease: "Vertrag", repair: "Reparatur" };

export default function DocumentsPage() {
  const [q, setQ] = useState(""), [type, setType] = useState(""), [deleted, setDeleted] = useState(false), [open, setOpen] = useState(false);
  const qs = new URLSearchParams({ ...(q && { q }), ...(type && { doc_type: type }), ...(deleted && { include_deleted: "true" }) }).toString();
  const { data, error, reload } = useFetch<{ items: Doc[] }>(`/documents/search?${qs}`);
  const parties = useFetch<{ items: { id: number; display_name: string }[] }>("/parties");
  const props = useFetch<{ items: { id: number; name: string }[] }>("/properties");
  const leases = useFetch<{ items: { id: number; kind: string; spaces: string[] }[] }>("/leases");
  const repairs = useFetch<{ items: { id: number; title: string }[] }>("/repairs");
  const [f, setF] = useState<Record<string, string>>({ entity: "lease", type: "sonstige" }), [file, setFile] = useState<File | null>(null), [err, setErr] = useState("");
  const set = (k: string) => (v: string) => setF({ ...f, [k]: v });
  const targets = f.entity === "party" ? (parties.data?.items ?? []).map((p) => ({ value: p.id, label: p.display_name })) : f.entity === "property" ? (props.data?.items ?? []).map((p) => ({ value: p.id, label: p.name }))
    : f.entity === "repair" ? (repairs.data?.items ?? []).map((r) => ({ value: r.id, label: `#${r.id} ${r.title}` })) : (leases.data?.items ?? []).map((l) => ({ value: l.id, label: `#${l.id} ${l.kind === "main" ? "Hauptmiete" : "Untermiete"} – ${l.spaces.join("; ")}` }));
  async function save() {
    setErr("");
    if (!file || !f.target) return setErr("Datei und Zuordnung wählen.");
    const fd = new FormData(); fd.set("file", file); fd.set("entity_type", f.entity); fd.set("entity_id", f.target); fd.set("doc_type", f.type);
    try { await upload("/documents", fd); setOpen(false); setFile(null); reload(); } catch (e) { setErr(e instanceof ApiError ? e.message : "Fehler"); }
  }
  return (
    <>
      <PageHeader title="Dokumente" subtitle="Zentrale Ablage. Dokumente sind nur nach Anmeldung abrufbar und werden lokal gespeichert. Gelöschte Dokumente bleiben aus Aufbewahrungsgründen im Speicher." />
      <Card>
        <div className="toolbar"><input className="field" placeholder="Dateiname suchen …" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Suche" />
          <Select value={type} onChange={setType} empty="Alle Typen" options={Object.entries(DOC_TYPES).map(([value, label]) => ({ value, label }))} />
          <label style={{ flexDirection: "row", alignItems: "center", fontWeight: 400 }}><input type="checkbox" checked={deleted} onChange={(e) => setDeleted(e.target.checked)} /> gelöschte anzeigen</label>
          <div className="grow" /><button className="btn primary" onClick={() => setOpen(true)}>Dokument hochladen</button></div>
        {error && <div className="alert err">{error}</div>}
        {data && data.items.length === 0 ? <EmptyState title="Keine Dokumente" /> : data?.items.map((d) => <div key={d.id}><DocRow d={d} onChanged={reload} /><div className="muted" style={{ marginTop: -8, marginBottom: 8 }}>{d.links.map((l) => `${ENT[l.entity_type] ?? l.entity_type} #${l.entity_id}`).join(", ")}</div></div>)}
      </Card>
      {open && <Modal title="Dokument hochladen" onClose={() => setOpen(false)}><div className="form-grid">
        <Field label="Zuordnung zu"><Select value={f.entity} onChange={(v) => setF({ ...f, entity: v, target: "" })} options={Object.entries(ENT).map(([value, label]) => ({ value, label }))} /></Field>
        <Field label="Ziel"><Select value={f.target ?? ""} onChange={set("target")} empty="– wählen –" options={targets} /></Field>
        <Field label="Dokumenttyp"><Select value={f.type} onChange={set("type")} options={Object.entries(DOC_TYPES).map(([value, label]) => ({ value, label }))} /></Field>
        <Field label="Datei (PDF, Bild, Office, CSV/TXT)"><input className="field" type="file" aria-label="Datei" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
        <div className="full">{err && <div className="alert err">{err}</div>}<button className="btn primary" onClick={save}>Hochladen</button></div></div></Modal>}
    </>
  );
}
