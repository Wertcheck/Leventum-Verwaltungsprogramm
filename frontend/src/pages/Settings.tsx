import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type BackupList } from "../lib/api";
import { Card, PageHeader } from "../components/ui";
import { useFetch } from "../lib/hooks";
import { Badge } from "../components/ui";
import { useDialogs } from "../components/Dialogs";

export default function Settings() {
  const { confirmBox, ask } = useDialogs();
  const [integ, setInteg] = useState<{ ok: boolean; findings: { message: string }[]; documents: { problems: { original_name: string; problems?: string[] }[] } } | null>(null);
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
  const create = (encrypted = false) => run(async () => {
    const passphrase = encrypted ? await ask("Passphrase für die Verschlüsselung (mindestens 12 Zeichen). Sie wird NICHT gespeichert – ohne sie ist das Backup nicht wiederherstellbar.", { title: "Verschlüsseltes Backup", type: "password" }) : null;
    if (encrypted && !passphrase) return;
    const r = await api<{ verified: boolean; problems: string[] }>("/system/backups", { method: "POST", json: passphrase ? { passphrase } : {} });
    setMsg(r.verified ? { tone: "ok", text: "Backup erstellt und Integrität geprüft." } : { tone: "err", text: "Backup erstellt, aber Prüfung fehlgeschlagen: " + r.problems.join("; ") });
  });
  const verify = (id: string, enc?: boolean) => run(async () => {
    const passphrase = enc ? await ask("Passphrase des Backups", { type: "password" }) : null;
    if (enc && !passphrase) return;
    const r = await api<{ ok: boolean; problems: string[] }>(`/system/backups/${encodeURIComponent(id)}/verify`, { method: "POST", json: passphrase ? { passphrase } : {} });
    setMsg(r.ok ? { tone: "ok", text: `${id}: intakt` } : { tone: "err", text: `${id}: ${r.problems.join("; ")}` });
  });
  const restore = async (id: string, enc?: boolean) => {
    if (!(await confirmBox("Datenbank UND Dokumente werden durch den Stand dieses Backups ersetzt. Vorher wird automatisch ein Sicherheits-Backup des aktuellen Stands angelegt. Fortfahren?", { title: "Wiederherstellen", danger: true, confirmLabel: "Wiederherstellen" }))) return;
    const passphrase = enc ? await ask("Passphrase des Backups", { type: "password" }) : null;
    if (enc && !passphrase) return;
    run(async () => {
      const r = await api<{ safety_backup: string }>(`/system/backups/${encodeURIComponent(id)}/restore`, { method: "POST", json: { confirm: true, ...(passphrase ? { passphrase } : {}) } });
      setMsg({ tone: "warn", text: `Wiederhergestellt. Sicherheits-Backup: ${r.safety_backup}. Bitte laden Sie die Anwendung neu und melden Sie sich erneut an.` });
    });
  };
  const parties = useFetch<{ items: { id: number; display_name: string; is_own_organization: boolean }[] }>("/parties");
  const own = parties.data?.items.find((p) => p.is_own_organization);
  const [orgName, setOrgName] = useState("Leventum Real Estate");
  return (
    <>
      <PageHeader title="Einstellungen" subtitle="Eigene Organisation, Backup und Wiederherstellung" />
      <Card>
        <div className="card-head"><h2>Eigene Organisation</h2></div>
        <p className="muted" style={{ marginBottom: 12 }}>Leventum tritt als Mieter (Hauptmietvertrag) und als Vermieter (Untermietvertrag) auf. Diese Partei wird dafür benötigt.</p>
        {own ? <div className="alert ok">Angelegt: {own.display_name}</div> : parties.data && (
          <div className="toolbar"><input className="field" value={orgName} onChange={(e) => setOrgName(e.target.value)} aria-label="Firmenname" />
            <button className="btn primary" onClick={() => api("/parties", { method: "POST", json: { kind: "company", company_name: orgName, is_own_organization: true } }).then(parties.reload)}>Anlegen</button></div>)}
      </Card>
      <div style={{ height: 20 }} />
      <Card>
        <div className="card-head"><h2>Backups</h2><div className="toolbar" style={{ margin: 0 }}><button className="btn primary" onClick={() => create(false)} disabled={busy}>Backup jetzt erstellen</button><button className="btn" onClick={() => create(true)} disabled={busy}>Verschlüsseltes Backup erstellen</button></div></div>
        <p className="muted" style={{ marginBottom: 12 }}>Ein Backup enthält Datenbank und Dokumente gemeinsam. Verschlüsselt (AES-256-GCM) wird nur das Backup-Archiv – die laufende Datenbank und die Dokumente im Datenordner sind NICHT verschlüsselt; dafür BitLocker/Geräteverschlüsselung aktivieren. Backups zusätzlich auf ein externes Laufwerk kopieren.</p>
        {msg && <div className={`alert ${msg.tone}`} role="status">{msg.text}</div>}
        {b && !b.last_backup_at && <div className="alert warn">Es wurde noch kein Backup erstellt.</div>}
        {b?.items.map((i) => (
          <div className="list-row" key={i.id}>
            <div className="grow"><div>{i.id} {i.encrypted && <Badge tone="ok">verschlüsselt</Badge>}</div><div className="muted">{new Date(i.created_at).toLocaleString("de-DE")} · {(i.size / 1024).toFixed(0)} KB</div></div>
            <button className="btn" onClick={() => verify(i.id, i.encrypted)} disabled={busy}>Prüfen</button>
            <button className="btn danger" onClick={() => restore(i.id, i.encrypted)} disabled={busy}>Wiederherstellen</button>
          </div>
        ))}
      </Card>
      <div style={{ height: 20 }} />
      <Card>
        <div className="card-head"><h2>Datenprüfung</h2><button className="btn" onClick={() => api<NonNullable<typeof integ>>("/system/integrity").then(setInteg).catch((e) => setMsg({ tone: "err", text: e.message }))}>Datenbestand prüfen</button></div>
        <p className="muted">Prüft verwaiste Verknüpfungen, doppelte Vermietungseinheiten, überlappende Untermietverträge und Überbelegungen. Es wird nichts verändert.</p>
        {integ && (integ.ok ? <div className="alert ok" role="status">Keine Auffälligkeiten.</div> : <>{integ.findings.map((p, i) => <div className="alert warn" key={i}>{p.message}</div>)}{integ.documents.problems.map((d, i) => <div className="alert err" key={`d${i}`}>Dokument „{d.original_name}“: Datei fehlt oder ist verändert.</div>)}</>)}
      </Card>
    </>
  );
}
