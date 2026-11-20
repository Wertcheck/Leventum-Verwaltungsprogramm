import { useEffect, useRef, useState } from "react";
import { isoDe, monthDe, parseDateText, parseMonthText } from "../lib/hooks";

/**
 * Einheitliches Datums-/Monatsfeld im deutschen Format (TT.MM.JJJJ bzw. MM.JJJJ) – unabhängig vom Browser-/WebView2-Gebietsschema.
 * Der Wert nach außen ist immer ISO (JJJJ-MM-TT bzw. JJJJ-MM) oder leer; eingegeben werden darf deutsch oder ISO.
 * Unvollständige/ungültige Eingaben werden nicht nach außen gegeben (kein falscher Wert), sondern am Feld markiert (aria-invalid).
 */
export function DateInput({ value, onChange, kind = "date", id, max, min, required, placeholder, disabled, ariaLabel }: {
  value: string; onChange: (iso: string) => void; kind?: "date" | "month"; id?: string; max?: string; min?: string; required?: boolean; placeholder?: string; disabled?: boolean; ariaLabel?: string;
}) {
  const parse = kind === "month" ? parseMonthText : parseDateText;
  const show = (v: string) => (v ? (kind === "month" ? monthDe(v) : isoDe(v)) : "");
  const [text, setText] = useState(show(value));
  const [bad, setBad] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  // ungültige Eingabe verhindert das Absenden eines umgebenden Formulars (Meldung kommt aus dem Popup-System, deutsch)
  useEffect(() => { ref.current?.setCustomValidity(bad || (text.trim() !== "" && !parse(text)) ? "Ungültiges Datum" : ""); }, [bad, text]);  // auch unvollständige Eingabe blockiert das Absenden (Enter ohne Blur)
  // Wert von außen (z. B. „Heute“, Zurücksetzen) übernehmen, ohne laufende Eingabe zu überschreiben
  useEffect(() => { if ((parse(text) ?? "") !== value && !(text.trim() === "" && value === "")) { setText(show(value)); setBad(false); } /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [value]);
  const [check, setCheck] = useState("");
  // Wird ein gültig eingegebener Wert vom Elternteil nicht übernommen (z. B. Zukunftsdatum beim Stichtag), zeigt das Feld wieder den gültigen Wert.
  useEffect(() => { if (check && value !== check) { setText(show(value)); setBad(false); } if (check) setCheck(""); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [check]);
  function change(raw: string) {
    setText(raw); setBad(false);
    if (raw.trim() === "") { onChange(""); return; }
    const iso = parse(raw);
    if (iso) { onChange(iso); setCheck(iso); }
  }
  function blur() {
    if (text.trim() === "") { setBad(false); return; }
    const iso = parse(text);
    if (iso) { setText(show(iso)); setBad(false); } else setBad(true);
  }
  return <input ref={ref} className="field date-input" id={id} type="text" inputMode="numeric" autoComplete="off" data-kind={kind} value={text} max={max} min={min} required={required} disabled={disabled}
    placeholder={placeholder ?? (kind === "month" ? "MM.JJJJ" : "TT.MM.JJJJ")} aria-label={ariaLabel} aria-invalid={bad || undefined}
    title={bad ? (kind === "month" ? "Bitte im Format MM.JJJJ eingeben." : "Bitte im Format TT.MM.JJJJ eingeben.") : undefined}
    onChange={(e) => change(e.target.value)} onBlur={blur} />;
}
