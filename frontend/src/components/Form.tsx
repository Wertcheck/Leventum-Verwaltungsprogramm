import type { ReactNode } from "react";
import { DateInput } from "./DateInput";

export { Modal } from "./Modal";

export const Field = ({ label, children }: { label: string; children: ReactNode }) => <label>{label}{children}</label>;

export function Text({ value, onChange, type = "text", ...rest }: { value: string; onChange: (v: string) => void; type?: string; required?: boolean; placeholder?: string; step?: string; id?: string; max?: string; min?: string }) {
  // Datum/Monat immer im deutschen Format (TT.MM.JJJJ / MM.JJJJ); Wert nach außen bleibt ISO
  if (type === "date" || type === "month") return <DateInput kind={type} value={value} onChange={onChange} id={rest.id} max={rest.max} min={rest.min} required={rest.required} placeholder={rest.placeholder} />;
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

/** Dateiauswahl mit deutscher Beschriftung (statt der Browser-Texte „Choose File / No file chosen“). Das echte Feld bleibt für Tastatur und Tests erhalten. */
export function FileInput({ file, onFile, accept, ariaLabel, resetAfter = false }: { file?: File | null; onFile: (f: File | null) => void; accept?: string; ariaLabel: string; resetAfter?: boolean }) {
  return (
    <span className="file-input">
      <input type="file" accept={accept} aria-label={ariaLabel} onChange={(e) => { onFile(e.target.files?.[0] ?? null); if (resetAfter) e.target.value = ""; }} />
      <span className="btn file-btn" aria-hidden="true">Datei auswählen</span>
      <span className="file-name muted">{file ? file.name : "Keine Datei ausgewählt"}</span>
    </span>
  );
}
