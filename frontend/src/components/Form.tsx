import type { ReactNode } from "react";

export const Field = ({ label, children }: { label: string; children: ReactNode }) => <label>{label}{children}</label>;

export function Text({ value, onChange, type = "text", ...rest }: { value: string; onChange: (v: string) => void; type?: string; required?: boolean; placeholder?: string; step?: string }) {
  return <input className="field" type={type} value={value} onChange={(e) => onChange(e.target.value)} {...rest} />;
}

export function Select({ value, onChange, options, empty }: { value: string; onChange: (v: string) => void; options: { value: string | number; label: string }[]; empty?: string }) {
  return (
    <select className="field" value={value} onChange={(e) => onChange(e.target.value)}>
      {empty !== undefined && <option value="">{empty}</option>}
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="modal-bg" role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal card">
        <div className="card-head"><h2>{title}</h2><button className="btn" onClick={onClose}>Schließen</button></div>
        {children}
      </div>
    </div>
  );
}
