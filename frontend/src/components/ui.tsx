import type { ReactNode } from "react";
import type { StichtagMeta } from "../lib/api";
import { isoDe } from "../lib/hooks";

export const Card = ({ children, className = "" }: { children: ReactNode; className?: string }) => <section className={`card ${className}`}>{children}</section>;

export const Badge = ({ tone, children }: { tone: "ok" | "warn" | "err"; children: ReactNode }) => <span className={`badge ${tone}`}>{children}</span>;

export const PageHeader = ({ title, subtitle }: { title: string; subtitle?: string }) => (
  <div className="page-header"><h1>{title}</h1>{subtitle && <p className="muted">{subtitle}</p>}</div>
);

export const EmptyState = ({ title, children }: { title: string; children?: ReactNode }) => (
  <div className="empty"><strong>{title}</strong>{children}</div>
);

export const eurText = (v: string) => Number(v).toLocaleString("de-DE", { style: "currency", currency: "EUR" });

/** Dezente Zeile „Stand: TT.MM.JJJJ (aktuelle Ansicht)“ aus dem Antwortblock 'stichtag'. Rein anzeigend; keine Auswahl. */
export function StichtagLine({ stichtag }: { stichtag?: StichtagMeta | null }) {
  if (!stichtag?.as_of) return null;
  const kind = stichtag.mode === "datenstand" ? "Datenstand" : stichtag.mode === "historical" ? "historische Ansicht" : "aktuelle Ansicht";
  return <p className="muted stichtag-line" data-testid="stichtag-line" title={stichtag.limitations?.join(" ")}>Stand: {isoDe(stichtag.as_of)} ({kind})</p>;
}

export function KpiCard({ icon, label, value, available, hint, format, definition, badge, badgeTitle }: { icon: ReactNode; label: string; value: number | string | null; available: boolean; hint?: string | null; format?: string; definition?: string; badge?: string; badgeTitle?: string }) {
  return (
    <Card className="kpi" >
      <div className="ic">{icon}</div>
      <div>
        <div className="label" title={definition}>{label}{definition && <span className="kpi-info" aria-label={`Definition: ${definition}`} title={definition}> ⓘ</span>}</div>
        <div className={`value ${available ? "" : "na"} ${format === "eur" ? "money" : ""}`} data-testid={`kpi-${label}`}>{available && value !== null ? (format === "eur" ? eurText(String(value)) : format === "percent" ? `${String(value).replace(".", ",")} %` : value) : "–"}</div>
        {hint && <div className="hint">{hint}</div>}
        {badge && <span className="badge neutral kpi-badge" title={badgeTitle}>{badge}</span>}
      </div>
    </Card>
  );
}
