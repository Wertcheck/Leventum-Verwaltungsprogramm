import { createContext, useContext, type ReactNode } from "react";
import type { StichtagMeta } from "../lib/api";
import { isoDe } from "../lib/hooks";
import { Icons } from "./icons";

export const Card = ({ children, className = "" }: { children: ReactNode; className?: string }) => <section className={`card ${className}`}>{children}</section>;

export const Badge = ({ tone, children }: { tone: "ok" | "warn" | "err"; children: ReactNode }) => <span className={`badge ${tone}`}>{children}</span>;

/** Wird eine Seite als Detailansicht in einem Popup gezeigt, steht der Titel im Popup-Kopf; die Seitenüberschrift entfällt dann. */
export const EmbeddedCtx = createContext(false);

export function PageHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  const embedded = useContext(EmbeddedCtx);
  if (embedded) return null;  // Titel und Beschreibung stehen im Popup-Kopf
  return <div className="page-header"><h1>{title}</h1>{subtitle && <p className="muted">{subtitle}</p>}</div>;
}

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

export function KpiCard({ icon, label, value, available, hint, format, definition, badge, badgeTitle, onOpen }: { icon: ReactNode; label: string; value: number | string | null; available: boolean; hint?: string | null; format?: string; definition?: string; badge?: string; badgeTitle?: string; onOpen?: () => void }) {
  const shown = available && value !== null ? (format === "eur" ? eurText(String(value)) : format === "percent" ? `${String(value).replace(".", ",")} %` : value) : "–";
  const body = (
    <>
      <span className="ic">{icon}</span>
      <span className="kpi-text">
        <span className="label" title={definition}>{label}{definition && <span className="kpi-info" aria-label={`Definition: ${definition}`} title={definition}>&nbsp;ⓘ</span>}</span>
        <span className={`value ${available ? "" : "na"} ${format === "eur" ? "money" : ""}`} data-testid={`kpi-${label}`}>{shown}</span>
        {hint && <span className="hint">{hint}</span>}
        {badge && <span className="badge neutral kpi-badge" title={badgeTitle}>{badge}</span>}
      </span>
    </>
  );
  // Klickbar: echte Schaltfläche (Tastatur, Fokus, Screenreader); öffnet die zugehörige Detailansicht im Popup
  if (onOpen) return <button type="button" className="card kpi kpi-btn" onClick={onOpen} aria-haspopup="dialog" title="Details anzeigen">{body}</button>;
  return <section className="card kpi">{body}</section>;
}

/** Eigenständiger, begrenzter Dashboard-Block. Mit onOpen: Titel ist eine Schaltfläche, ein Klick auf freie Fläche des Blocks öffnet ebenfalls die Detailansicht. */
export function Block({ title, subtitle, onOpen, children, className = "" }: { title: string; subtitle?: ReactNode; onOpen?: () => void; children: ReactNode; className?: string }) {
  return (
    <section className={`card block ${onOpen ? "block-open" : ""} ${className}`.trim()}
      onClick={onOpen ? (e) => { if (!(e.target as HTMLElement).closest("a, button, input, select, textarea, summary, label, details")) onOpen(); } : undefined}>
      <div className="block-head">
        <h2>{onOpen ? <button type="button" className="block-title" onClick={onOpen} aria-haspopup="dialog">{title}<span className="block-more">Alle anzeigen<Icons.chevronRight size={16} /></span></button> : title}</h2>
        {subtitle && <span className="muted block-sub">{subtitle}</span>}
      </div>
      <div className="block-body">{children}</div>
    </section>
  );
}
