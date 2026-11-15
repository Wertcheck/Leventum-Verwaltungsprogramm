import { useEffect, useState } from "react";
import { api, type BackupList, type DashboardData, type User } from "../lib/api";
import { Link } from "react-router-dom";
import { PHASE } from "../components/TenantPanel";
import { Badge, Card, EmptyState, KpiCard, PageHeader } from "../components/ui";
import { eur } from "../lib/hooks";
import { Icons } from "../components/icons";

const ICONS: Record<string, keyof typeof Icons> = {
  properties: "building", units: "door", active_main_leases: "file", active_subleases: "contract", active_tenants: "users",
  main_rent_obligations: "euro", sublease_receivables: "euro", open_receivables: "receipt", overdue_payments: "bell",
  monthly_utility_costs: "calc", overdue_tasks: "bell", open_repairs: "wrench", physical_vacancy: "door", economic_vacancy_cost: "euro", open_tasks: "check", upcoming_contract_ends: "key",
};

export default function Dashboard({ user }: { user: User }) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [backup, setBackup] = useState<BackupList | null>(null);
  const [error, setError] = useState("");
  const [eco, setEco] = useState<{ soll: Record<string, string>; ist: Record<string, string>; offen_zum_stichtag: Record<string, string>; vacancy: { economic_vacancy_cost: string }; contribution: { soll_basis: string; ist_basis: string } } | null>(null);
  const [tenants, setTenants] = useState<{ party_id: number; name: string; spaces?: string[]; lease_status?: string }[]>([]);
  useEffect(() => {
    api<DashboardData>("/dashboard").then(setData).catch((e) => setError(e.message));
    api<{ items: typeof tenants }>("/tenants").then((r) => setTenants(r.items.slice(0, 5))).catch(() => undefined);
    const n = new Date(), m = `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}`;
    api<NonNullable<typeof eco>>(`/economics?start=${m}-01&end=${m}-${String(new Date(n.getFullYear(), n.getMonth() + 1, 0).getDate()).padStart(2, "0")}&scope=portfolio`).then(setEco).catch(() => undefined);
    api<BackupList>("/system/backups").then(setBackup).catch(() => undefined);
  }, []);
  return (
    <>
      <PageHeader title={`Guten Tag, ${user.display_name}`} subtitle="Hier finden Sie alle wichtigen Informationen zu Ihren Mietern und Objekten." />
      {error && <div className="alert err">{error}</div>}
      <div className="grid kpis">
        {data?.kpis.map((k) => {
          const I = Icons[ICONS[k.key] ?? "home"];
          return <KpiCard key={k.key} icon={<I size={28} />} label={k.label} value={k.value} available={k.available} format={k.format} definition={k.definition} hint={k.available ? k.hint : (k.hint ?? "derzeit nicht verfügbar")} />;
        })}
      </div>
      <div className="grid two-col">
        <Card>
          <div className="card-head"><h2>Mieter</h2></div>
          {tenants.length === 0 ? <EmptyState title="Noch keine Mieter erfasst">Mieter legen Sie unter „Stammdaten → Mieter“ an.</EmptyState> : (
            <table><tbody>{tenants.map((t, i) => <tr key={i}><td><Link className="link" to={`/parteien/${t.party_id}`}>{t.name}</Link></td><td>{t.spaces?.join("; ") ?? "–"}</td><td>{t.lease_status && <Badge tone={PHASE[t.lease_status]?.[1] ?? "warn"}>{PHASE[t.lease_status]?.[0] ?? t.lease_status}</Badge>}</td></tr>)}</tbody></table>)}
        </Card>
        <Card>
          <div className="card-head"><h2>Aufgaben &amp; Hinweise</h2></div>
          {backup && backup.stale && (
            <div className="alert warn">{backup.last_backup_at ? `Das letzte Backup ist ${Math.round(backup.age_hours ?? 0)} Stunden alt.` : "Es wurde noch kein Backup erstellt."} Unter „Einstellungen“ ein Backup anlegen.</div>
          )}
          {backup && !backup.stale && <div className="alert ok">Letztes Backup: {new Date(backup.last_backup_at!).toLocaleString("de-DE")}</div>}
          {data?.warnings.length === 0 && <p className="muted">Keine Hinweise. Fristen, Zahlungen, Dokumente und Reparaturen werden laufend aus Ihren Daten geprüft.</p>}
          {data?.warnings.map((w) => (
            <div className="list-row wrap" key={w.key}>
              <Badge tone={w.severity === "critical" ? "err" : w.severity === "warning" ? "warn" : "ok"}>{w.severity === "critical" ? "Dringend" : w.severity === "warning" ? "Hinweis" : "Info"}</Badge>
              <div className="grow"><div>{w.title}</div><div className="muted">{w.detail}</div></div>
              {w.task_id ? <Link className="link" to="/aufgaben">Aufgabe #{w.task_id}</Link> : <button className="btn small" onClick={async () => { await api("/reminders/task", { method: "POST", json: { key: w.key } }); api<DashboardData>("/dashboard").then(setData); }}>Aufgabe erstellen</button>}
            </div>))}
          {data && data.tasks.length > 0 && <><h2 style={{ margin: "16px 0 8px" }}>Nächste Aufgaben</h2>{data.tasks.map((t) => <div className="list-row" key={t.id}><span className="grow">{t.title}</span><span className="muted">{t.due_date ?? "ohne Termin"}</span>{t.overdue && <Badge tone="err">überfällig</Badge>}</div>)}</>}
        </Card>
      </div>
      <Card>
        <div className="card-head"><h2>Wirtschaftlicher Überblick</h2><span className="muted">laufender Monat · vorläufig</span></div>
        {eco ? <>
          <div className="stat-grid">
            <div className="stat"><div className="k">Untermiete (Soll)</div><div className="v">{eur(eco.soll.sub_total)}</div></div>
            <div className="stat"><div className="k">Hauptmiete (Soll)</div><div className="v">{eur(eco.soll.main_total)}</div></div>
            <div className="stat"><div className="k">Vorläufiger Deckungsbeitrag (Soll)</div><div className={`v ${Number(eco.contribution.soll_basis) < 0 ? "neg" : ""}`}>{eur(eco.contribution.soll_basis)}</div></div>
            <div className="stat"><div className="k">Zahlungsfluss (Ist: Eingänge − Ausgänge)</div><div className={`v ${Number(eco.contribution.ist_basis) < 0 ? "neg" : ""}`}>{eur(eco.contribution.ist_basis)}</div></div>
            <div className="stat"><div className="k">Offene Forderungen</div><div className="v">{eur(eco.offen_zum_stichtag.receivables)}</div></div>
            <div className="stat"><div className="k">davon überfällig (Rückstand)</div><div className={`v ${Number(eco.offen_zum_stichtag.receivables_overdue) > 0 ? "neg" : ""}`}>{eur(eco.offen_zum_stichtag.receivables_overdue)}</div></div>
            <div className="stat"><div className="k">Wirtschaftlicher Leerstand</div><div className="v">{eur(eco.vacancy.economic_vacancy_cost)}</div></div>
          </div>
          <p className="muted">Soll (laut Verträgen) und Ist (tatsächliche Zahlungen) sind getrennte Betrachtungen und nicht addierbar; der Deckungsbeitrag ist vorläufig und kein Gewinn. Details unter <Link className="link" to="/auswertungen/wirtschaftlichkeit">Auswertungen → Wirtschaftlichkeit</Link>.</p>
        </> : <p className="muted">Wird berechnet …</p>}
      </Card>
    </>
  );
}
