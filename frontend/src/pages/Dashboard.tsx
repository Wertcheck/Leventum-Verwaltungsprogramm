import { useEffect, useState } from "react";
import { api, type BackupList, type DashboardData, type User } from "../lib/api";
import { Link } from "react-router-dom";
import { Badge, Card, EmptyState, KpiCard, PageHeader } from "../components/ui";
import { Icons } from "../components/icons";

const ICONS: Record<string, keyof typeof Icons> = {
  properties: "building", units: "door", active_main_leases: "file", active_subleases: "contract", active_tenants: "users",
  main_rent_obligations: "euro", sublease_receivables: "euro", open_receivables: "receipt", overdue_payments: "bell",
  monthly_utility_costs: "calc", physical_vacancy: "door", economic_vacancy_cost: "euro", open_tasks: "check", upcoming_contract_ends: "key",
};

export default function Dashboard({ user }: { user: User }) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [backup, setBackup] = useState<BackupList | null>(null);
  const [error, setError] = useState("");
  const [tenants, setTenants] = useState<{ party_id: number; name: string; spaces?: string[]; lease_status?: string }[]>([]);
  useEffect(() => {
    api<DashboardData>("/dashboard").then(setData).catch((e) => setError(e.message));
    api<{ items: typeof tenants }>("/tenants").then((r) => setTenants(r.items.slice(0, 5))).catch(() => undefined);
    api<BackupList>("/system/backups").then(setBackup).catch(() => undefined);
  }, []);
  return (
    <>
      <PageHeader title={`Guten Tag, ${user.display_name}`} subtitle="Hier finden Sie alle wichtigen Informationen zu Ihren Mietern und Objekten." />
      {error && <div className="alert err">{error}</div>}
      <div className="grid kpis">
        {data?.kpis.map((k) => {
          const I = Icons[ICONS[k.key] ?? "home"];
          return <KpiCard key={k.key} icon={<I size={28} />} label={k.label} value={k.value} available={k.available} format={k.format} hint={`verfügbar ab Phase ${k.planned_phase}`} />;
        })}
      </div>
      <div className="grid two-col">
        <Card>
          <div className="card-head"><h2>Mieter</h2></div>
          {tenants.length === 0 ? <EmptyState title="Noch keine Mieter erfasst">Mieter legen Sie unter „Stammdaten → Mieter“ an.</EmptyState> : (
            <table><tbody>{tenants.map((t, i) => <tr key={i}><td><Link className="link" to={`/parteien/${t.party_id}`}>{t.name}</Link></td><td>{t.spaces?.join("; ") ?? "–"}</td><td>{t.lease_status && <Badge tone={t.lease_status === "active" ? "ok" : "warn"}>{t.lease_status === "active" ? "Aktiv" : t.lease_status}</Badge>}</td></tr>)}</tbody></table>)}
        </Card>
        <Card>
          <div className="card-head"><h2>Aufgaben &amp; Hinweise</h2></div>
          {backup && backup.stale && (
            <div className="alert warn">{backup.last_backup_at ? `Das letzte Backup ist ${Math.round(backup.age_hours ?? 0)} Stunden alt.` : "Es wurde noch kein Backup erstellt."} Unter „Einstellungen“ ein Backup anlegen.</div>
          )}
          {backup && !backup.stale && <div className="alert ok">Letztes Backup: {new Date(backup.last_backup_at!).toLocaleString("de-DE")}</div>}
          <p className="muted">Hinweise zu Fristen, Zahlungen und Dokumenten erscheinen, sobald die jeweiligen Module vorhanden sind.</p>
        </Card>
      </div>
      <Card className="" >
        <div className="card-head" style={{ marginTop: 0 }}><h2>Wirtschaftlicher Überblick</h2></div>
        <p className="muted" style={{ marginBottom: 12 }}>Wird in Phase D aus tatsächlichen Daten berechnet. Es werden strikt getrennt ausgewiesen:</p>
        <dl className="defs">
          <dt>Soll</dt><dd>vereinbarte bzw. gestellte Beträge (Haupt- und Untermiete getrennt)</dd>
          <dt>Ist</dt><dd>tatsächlich eingegangene und geleistete Zahlungen</dd>
          <dt>Offen</dt><dd>Forderungen und Verbindlichkeiten abzüglich zugeordneter Zahlungen</dd>
          <dt>Ergebnis</dt><dd>„vorläufiger Deckungsbeitrag“ – kein Gewinn</dd>
        </dl>
      </Card>
    </>
  );
}
