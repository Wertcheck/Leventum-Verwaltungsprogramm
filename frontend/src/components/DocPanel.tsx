import { useState } from "react";
import { api, ApiError, upload } from "../lib/api";
import { dateDe, useFetch } from "../lib/hooks";
import { Card } from "./ui";
import { Select } from "./Form";

export interface Doc { id: number; original_name: string; mime: string; size: number; doc_type: string; uploaded_at: string; links: { entity_type: string; entity_id: number }[]; deleted_at?: string | null; delete_reason?: string | null }
export const DOC_TYPES: Record<string, string> = { mietvertrag: "Mietvertrag", nachtrag: "Nachtrag", uebergabeprotokoll: "Übergabeprotokoll", rechnung: "Rechnung", betriebskostenabrechnung: "Betriebskostenabrechnung", schriftverkehr: "Schriftverkehr", versicherung: "Versicherung", reparaturbeleg: "Reparaturbeleg", kaution: "Kaution", sonstige: "Sonstige Unterlagen" };

export function DocRow({ d, onChanged, extra }: { d: Doc; onChanged: () => void; extra?: string }) {
  async function del() {
    const r = window.prompt("Begründung für das Löschen (die Datei bleibt aus Aufbewahrungsgründen gespeichert)");
    if (r) { await api(`/documents/${d.id}/delete`, { method: "POST", json: { reason: r } }); onChanged(); }
  }
  return (
    <div className="list-row">
      <div className="grow">{d.deleted_at ? <span>{d.original_name}</span> : <a className="link" href={`/api/v1/documents/${d.id}/download`}>{d.original_name}</a>}
        <div className="muted">{DOC_TYPES[d.doc_type] ?? d.doc_type} · {dateDe(d.uploaded_at)} · {d.size < 1024 ? "< 1 KB" : `${(d.size / 1024).toFixed(0)} KB`}{extra ? ` · ${extra}` : ""}{d.deleted_at ? ` · gelöscht: ${d.delete_reason}` : ""}</div></div>
      {!d.deleted_at && <button className="btn small danger" onClick={del}>Löschen</button>}
    </div>
  );
}

export default function DocPanel({ entityType, entityId, title = "Dokumente", defaultType = "sonstige" }: { entityType: string; entityId: number; title?: string; defaultType?: string }) {
  const { data, reload } = useFetch<{ items: Doc[] }>(`/documents?entity_type=${entityType}&entity_id=${entityId}`);
  const [type, setType] = useState(defaultType), [err, setErr] = useState("");
  async function onFile(f: File | null) {
    if (!f) return;
    setErr("");
    const fd = new FormData(); fd.set("file", f); fd.set("entity_type", entityType); fd.set("entity_id", String(entityId)); fd.set("doc_type", type);
    try { await upload("/documents", fd); reload(); } catch (e) { setErr(e instanceof ApiError ? e.message : "Fehler"); }
  }
  return (
    <Card>
      <div className="card-head"><h2>{title}</h2></div>
      {data?.items.length === 0 && <p className="muted">Keine Dokumente.</p>}
      {data?.items.map((d) => <DocRow key={d.id} d={d} onChanged={reload} />)}
      <div className="toolbar" style={{ marginTop: 12 }}>
        <Select value={type} onChange={setType} options={Object.entries(DOC_TYPES).map(([value, label]) => ({ value, label }))} />
        <input className="field" type="file" aria-label="Dokument hochladen" onChange={(e) => { onFile(e.target.files?.[0] ?? null); e.target.value = ""; }} />
      </div>
      {err && <div className="alert err">{err}</div>}
    </Card>
  );
}
