import type { ReactNode } from "react";

export const Card = ({ children, className = "" }: { children: ReactNode; className?: string }) => <section className={`card ${className}`}>{children}</section>;

export const Badge = ({ tone, children }: { tone: "ok" | "warn" | "err"; children: ReactNode }) => <span className={`badge ${tone}`}>{children}</span>;

export const PageHeader = ({ title, subtitle }: { title: string; subtitle?: string }) => (
  <div className="page-header"><h1>{title}</h1>{subtitle && <p className="muted">{subtitle}</p>}</div>
);

export const EmptyState = ({ title, children }: { title: string; children?: ReactNode }) => (
  <div className="empty"><strong>{title}</strong>{children}</div>
);

export const eurText = (v: string) => Number(v).toLocaleString("de-DE", { style: "currency", currency: "EUR" });

export function KpiCard({ icon, label, value, available, hint, format }: { icon: ReactNode; label: string; value: number | string | null; available: boolean; hint?: string; format?: string }) {
  return (
    <Card className="kpi">
      <div className="ic">{icon}</div>
      <div>
        <div className="label">{label}</div>
        <div className={`value ${available ? "" : "na"}`} data-testid={`kpi-${label}`}>{available && value !== null ? (format === "eur" ? eurText(String(value)) : value) : "–"}</div>
        {!available && hint && <div className="hint">{hint}</div>}
      </div>
    </Card>
  );
}
