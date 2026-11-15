import { useState } from "react";
import { api, ApiError } from "../lib/api";
import { Field, Modal, Select, Text } from "./Form";

export interface EditField { key: string; label: string; type?: "text" | "date" | "number" | "select"; options?: { value: string | number; label: string }[]; hint?: string }

/** Generischer Bearbeiten-Dialog: sendet nur geänderte Felder per PATCH; Änderungen landen im Audit-Protokoll (Vorher/Nachher). */
export default function EditDialog({ title, path, method = "PATCH", fields, initial, extra, note, onClose, onSaved }: {
  title: string; path: string; method?: "PATCH" | "POST"; fields: EditField[]; initial: Record<string, unknown>; extra?: Record<string, unknown>; note?: string; onClose: () => void; onSaved: () => void;
}) {
  const start = Object.fromEntries(fields.map((f) => [f.key, initial[f.key] == null ? "" : String(initial[f.key])]));
  const [v, setV] = useState<Record<string, string>>(start), [err, setErr] = useState(""), [warn, setWarn] = useState<string[]>([]), [busy, setBusy] = useState(false);
  const changed = method === "POST" ? fields.filter((f) => v[f.key] !== "") : fields.filter((f) => v[f.key] !== start[f.key]);
  async function save() {
    setErr(""); setBusy(true);
    const body: Record<string, unknown> = { ...(extra ?? {}) };
    for (const f of changed) body[f.key] = f.type === "number" ? Number(v[f.key]) : v[f.key] === "" ? null : v[f.key];
    try {
      const r = await api<{ warnings?: { message: string }[] | string[]; impact?: { message?: string } }>(path, { method, json: body });
      const w = [...(r?.warnings ?? []).map((x) => (typeof x === "string" ? x : x.message)), ...(r?.impact?.message ? [r.impact.message] : [])];
      if (w.length) { setWarn(w); onSaved(); } else { onSaved(); onClose(); }
    } catch (e) { setErr(e instanceof ApiError ? e.message : "Fehler"); } finally { setBusy(false); }
  }
  return (
    <Modal title={title} onClose={warn.length ? () => { onClose(); } : onClose}>
      {warn.length > 0 ? <><div className="alert ok" role="status">Gespeichert.</div>{warn.map((w, i) => <div className="alert warn" key={i}>{w}</div>)}<button className="btn primary" onClick={onClose}>Schließen</button></> : <div className="form-grid">
        {note && <p className="full muted">{note}</p>}
        {fields.map((f) => <Field key={f.key} label={f.label}>
          {f.type === "select" ? <Select value={v[f.key]} onChange={(x) => setV({ ...v, [f.key]: x })} options={f.options ?? []} empty="–" />
            : <Text type={f.type === "number" ? "number" : f.type ?? "text"} value={v[f.key]} onChange={(x) => setV({ ...v, [f.key]: x })} />}
          {f.hint && <span className="muted">{f.hint}</span>}</Field>)}
        <div className="full">{err && <div className="alert err" role="alert">{err}</div>}
          <button className="btn primary" disabled={busy || changed.length === 0} onClick={save}>{method === "POST" ? "Als neue Version speichern" : "Speichern"}</button>
          {method === "PATCH" && changed.length === 0 && <span className="muted"> Keine Änderung.</span>}</div></div>}
    </Modal>
  );
}
