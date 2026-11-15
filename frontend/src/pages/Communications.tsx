import { useState } from "react";
import { api, ApiError } from "../lib/api";
import { dateDe, useFetch } from "../lib/hooks";
import { Card, EmptyState, PageHeader } from "../components/ui";
import { Field, Modal, Select, Text } from "../components/Form";

interface Comm { id: number; channel: string; direction: string; occurred_at: string; subject: string; body: string | null; party_id: number | null; lease_id: number | null; property_id: number | null }
const CH: Record<string, string> = { email: "E-Mail", phone: "Telefon", letter: "Brief", in_person: "Persönlich", messenger: "Messenger", other: "Sonstige" };

export default function CommunicationsPage() {
  const [channel, setChannel] = useState(""), [open, setOpen] = useState(false);
  const { data, error, reload } = useFetch<{ items: Comm[] }>(`/communications${channel ? `?channel=${channel}` : ""}`);
  const parties = useFetch<{ items: { id: number; display_name: string }[] }>("/parties");
  const leases = useFetch<{ items: { id: number; kind: string; spaces: string[] }[] }>("/leases");
  const [f, setF] = useState<Record<string, string>>({ channel: "email", direction: "in" }), [err, setErr] = useState("");
  const set = (k: string) => (v: string) => setF({ ...f, [k]: v });
  const name = (id: number | null) => parties.data?.items.find((p) => p.id === id)?.display_name;
  async function save() {
    setErr("");
    try {
      await api("/communications", { method: "POST", json: { channel: f.channel, direction: f.direction, subject: f.subject, body: f.body || null, party_id: f.party ? Number(f.party) : null, lease_id: f.lease ? Number(f.lease) : null,
        follow_up: f.followup ? { title: f.followup, due_date: f.due || null } : null } });
      setOpen(false); setF({ channel: "email", direction: "in" }); reload();
    } catch (e) { setErr(e instanceof ApiError ? e.message : "Fehler"); }
  }
  return (
    <>
      <PageHeader title="Kommunikation" subtitle="Protokoll aller Kontakte. Hier wird nur dokumentiert – es werden keine Nachrichten versendet. Einträge sind unveränderlich." />
      <Card>
        <div className="toolbar"><Select value={channel} onChange={setChannel} empty="Alle Kanäle" options={Object.entries(CH).map(([value, label]) => ({ value, label }))} /><div className="grow" /><button className="btn primary" onClick={() => setOpen(true)}>Kontakt erfassen</button></div>
        {error && <div className="alert err">{error}</div>}
        {data && data.items.length === 0 ? <EmptyState title="Keine Kommunikation erfasst" /> : (
          <table><thead><tr><th>Datum</th><th>Kanal</th><th>Richtung</th><th>Betreff</th><th>Partei</th><th>Vertrag</th></tr></thead>
            <tbody>{data?.items.map((c) => <tr key={c.id}><td>{dateDe(c.occurred_at)}</td><td>{CH[c.channel]}</td><td>{c.direction === "in" ? "Eingang" : "Ausgang"}</td><td><strong>{c.subject}</strong>{c.body && <div className="muted">{c.body.slice(0, 120)}</div>}</td><td>{name(c.party_id) ?? "–"}</td><td>{c.lease_id ? `#${c.lease_id}` : "–"}</td></tr>)}</tbody></table>)}
      </Card>
      {open && <Modal title="Kontakt erfassen" onClose={() => setOpen(false)}><div className="form-grid">
        <Field label="Kanal"><Select value={f.channel} onChange={set("channel")} options={Object.entries(CH).map(([value, label]) => ({ value, label }))} /></Field>
        <Field label="Richtung"><Select value={f.direction} onChange={set("direction")} options={[{ value: "in", label: "Eingang" }, { value: "out", label: "Ausgang" }]} /></Field>
        <div className="full"><Field label="Betreff"><Text value={f.subject ?? ""} onChange={set("subject")} /></Field></div>
        <Field label="Partei"><Select value={f.party ?? ""} onChange={set("party")} empty="–" options={(parties.data?.items ?? []).map((p) => ({ value: p.id, label: p.display_name }))} /></Field>
        <Field label="Vertrag"><Select value={f.lease ?? ""} onChange={set("lease")} empty="–" options={(leases.data?.items ?? []).map((l) => ({ value: l.id, label: `#${l.id} ${l.kind === "main" ? "Hauptmiete" : "Untermiete"} – ${l.spaces.join("; ")}` }))} /></Field>
        <div className="full"><Field label="Inhalt / Notiz"><Text value={f.body ?? ""} onChange={set("body")} /></Field></div>
        <Field label="Folgeaufgabe (optional)"><Text value={f.followup ?? ""} onChange={set("followup")} placeholder="z. B. Rückruf" /></Field><Field label="Fällig am"><Text type="date" value={f.due ?? ""} onChange={set("due")} /></Field>
        <div className="full">{err && <div className="alert err">{err}</div>}<button className="btn primary" onClick={save}>Speichern</button></div></div></Modal>}
    </>
  );
}
