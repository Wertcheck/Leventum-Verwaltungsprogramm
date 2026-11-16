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
export const dateDe = (v: string | null | undefined) => (v ? new Date(v).toLocaleDateString("de-DE") : "–");
export const dateDeFull = dateDe;
/** Reines ISO-Datum (JJJJ-MM-TT) → TT.MM.JJJJ ohne Zeitzonenverschiebung. Nur Darstellung. */
export const isoDe = (v: string | null | undefined) => { const m = v ? /^(\d{4})-(\d{2})-(\d{2})/.exec(v) : null; return m ? `${m[3]}.${m[2]}.${m[1]}` : "–"; };
/** Heutiges Datum (lokal) als JJJJ-MM-TT, z. B. als Obergrenze für Stichtagsfelder. */
export const todayIso = () => { const n = new Date(), p = (x: number) => String(x).padStart(2, "0"); return `${n.getFullYear()}-${p(n.getMonth() + 1)}-${p(n.getDate())}`; };
/** 'WE' + '03' → 'WE 03'; enthält die Bezeichnung das Präfix bereits ('WE 03'), bleibt sie unverändert. */
export const pref = (prefix: string, value: string) => (value.trim().toLowerCase().startsWith(prefix.toLowerCase()) ? value : `${prefix} ${value}`);
