import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

export function useFetch<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (path === null) return;
    let live = true;
    api<T>(path).then((d) => live && (setData(d), setError(""))).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [path, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, reload };
}

// Nur zur Anzeige. Berechnet wird ausschließlich im Backend.
export const eur = (v: string | null | undefined) => (v == null ? "–" : Number(v).toLocaleString("de-DE", { style: "currency", currency: "EUR" }));
/** Einheitliches Datumsformat TT.MM.JJJJ (immer zweistellig). Reine Datumswerte ohne Zeitzonenverschiebung; Zeitstempel in lokaler Zeit. */
export const dateDe = (v: string | null | undefined) => (!v ? "–" : /^\d{4}-\d{2}-\d{2}$/.test(v) ? isoDe(v) : new Date(v).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" }));
export const dateDeFull = dateDe;
/** Reines ISO-Datum (JJJJ-MM-TT) → TT.MM.JJJJ ohne Zeitzonenverschiebung. Nur Darstellung. */
export const isoDe = (v: string | null | undefined) => { const m = v ? /^(\d{4})-(\d{2})-(\d{2})/.exec(v) : null; return m ? `${m[3]}.${m[2]}.${m[1]}` : "–"; };
/** JJJJ-MM (oder JJJJ-MM-TT) → MM.JJJJ. Nur Darstellung. */
export const monthDe = (v: string | null | undefined) => { const m = v ? /^(\d{4})-(\d{2})/.exec(v) : null; return m ? `${m[2]}.${m[1]}` : "–"; };
const validYmd = (y: number, m: number, d: number) => { const t = new Date(Date.UTC(y, m - 1, d)); return y >= 1900 && y <= 2999 && t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d; };
const p2 = (n: number) => String(n).padStart(2, "0");
/** Eingabetext (TT.MM.JJJJ oder ISO JJJJ-MM-TT) → ISO-Datum; ungültig/unvollständig → null. */
export function parseDateText(text: string): string | null {
  const t = text.trim();
  let m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(t); if (m && validYmd(+m[1], +m[2], +m[3])) return `${m[1]}-${p2(+m[2])}-${p2(+m[3])}`;
  m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(t); if (m && validYmd(+m[3], +m[2], +m[1])) return `${m[3]}-${p2(+m[2])}-${p2(+m[1])}`;
  return null;
}
/** Eingabetext (MM.JJJJ oder ISO JJJJ-MM) → JJJJ-MM; ungültig/unvollständig → null. */
export function parseMonthText(text: string): string | null {
  const t = text.trim();
  let m = /^(\d{4})-(\d{1,2})$/.exec(t); if (m && +m[2] >= 1 && +m[2] <= 12 && +m[1] >= 1900) return `${m[1]}-${p2(+m[2])}`;
  m = /^(\d{1,2})\.(\d{4})$/.exec(t); if (m && +m[1] >= 1 && +m[1] <= 12 && +m[2] >= 1900) return `${m[2]}-${p2(+m[1])}`;
  return null;
}
/** Heutiges Datum (lokal) als JJJJ-MM-TT, z. B. als Obergrenze für Stichtagsfelder. */
export const todayIso = () => { const n = new Date(), p = (x: number) => String(x).padStart(2, "0"); return `${n.getFullYear()}-${p(n.getMonth() + 1)}-${p(n.getDate())}`; };
/** 'WE' + '03' → 'WE 03'; enthält die Bezeichnung das Präfix bereits ('WE 03'), bleibt sie unverändert. */
export const pref = (prefix: string, value: string) => (value.trim().toLowerCase().startsWith(prefix.toLowerCase()) ? value : `${prefix} ${value}`);
