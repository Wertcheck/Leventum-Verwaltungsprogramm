import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type BackupList } from "../lib/api";
import { Card, PageHeader } from "../components/ui";

export default function Settings() {
  const [b, setB] = useState<BackupList | null>(null);
  const [msg, setMsg] = useState<{ tone: "ok" | "err" | "warn"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api<BackupList>("/system/backups").then(setB).catch((e) => setMsg({ tone: "err", text: e.message })), []);
  useEffect(() => { load(); }, [load]);

  async function run(fn: () => Promise<void>) {
    setBusy(true); setMsg(null);
    try { await fn(); } catch (e) { setMsg({ tone: "err", text: e instanceof ApiError ? e.message : "Fehler" }); }
    finally { setBusy(false); load(); }
  }
  const create = () => run(async () => {
    const r = await api<{ verified: boolean; problems: string[] }>("/system/backups", { method: "POST" });
    setMsg(r.verified ? { tone: "ok", text: "Backup erstellt und Integrität geprüft." } : { tone: "err", text: "Backup erstellt, aber Prüfung fehlgeschlagen: " + r.problems.join("; ") });
  });
  const verify = (id: string) => run(async () => {
    const r = await api<{ ok: boolean; problems: string[] }>(`/system/backups/${encodeURIComponent(id)}/verify`, { method: "POST" });
    setMsg(r.ok ? { tone: "ok", text: `${id}: intakt` } : { tone: "err", text: `${id}: ${r.problems.join("; ")}` });
  });
  const restore = (id: string) => {
    if (!window.confirm("Datenbank UND Dokumente werden durch den Stand dieses Backups ersetzt. Vorher wird automatisch ein Sicherheits-Backup des aktuellen Stands angelegt. Fortfahren?")) return;
    run(async () => {
      const r = await api<{ safety_backup: string }>(`/system/backups/${encodeURIComponent(id)}/restore`, { method: "POST", json: { confirm: true } });
      setMsg({ tone: "warn", text: `Wiederhergestellt. Sicherheits-Backup: ${r.safety_backup}. Bitte laden Sie die Anwendung neu und melden Sie sich erneut an.` });
    });
  };
  return (
    <>
      <PageHeader title="Einstellungen" subtitle="Backup und Wiederherstellung" />
      <Card>
        <div className="card-head"><h2>Backups</h2><button className="btn primary" onClick={create} disabled={busy}>Backup jetzt erstellen</button></div>
        <p className="muted" style={{ marginBottom: 12 }}>Ein Backup enthält Datenbank und Dokumente gemeinsam. Empfehlung: Backups zusätzlich auf ein externes Laufwerk kopieren und BitLocker aktivieren.</p>
        {msg && <div className={`alert ${msg.tone}`} role="status">{msg.text}</div>}
        {b && !b.last_backup_at && <div className="alert warn">Es wurde noch kein Backup erstellt.</div>}
        {b?.items.map((i) => (
          <div className="list-row" key={i.id}>
            <div className="grow"><div>{i.id}</div><div className="muted">{new Date(i.created_at).toLocaleString("de-DE")} · {(i.size / 1024).toFixed(0)} KB</div></div>
            <button className="btn" onClick={() => verify(i.id)} disabled={busy}>Prüfen</button>
            <button className="btn danger" onClick={() => restore(i.id)} disabled={busy}>Wiederherstellen</button>
          </div>
        ))}
      </Card>
    </>
  );
}
