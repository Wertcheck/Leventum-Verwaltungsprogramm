import { useEffect, useId, useRef, useState, useSyncExternalStore, type FormEvent, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

/**
 * Zentrales Popup-System – die einzige Modal-Implementierung der Anwendung (Detailansichten, Formulare, Abfragen, Bestätigungen).
 * Übernimmt: Portal über dem Dashboard, Abdunkelung, Größenvarianten, internes Scrollen (die Fenstergröße bleibt unberührt), Fokus setzen/zurückgeben,
 * Fokusführung (Tab), Escape, X-Schaltfläche, ARIA (Dialog, Titel, Beschreibung), Hintergrund inaktiv (inert), Stapel für zwingend verschachtelte Popups
 * und deutschsprachige Formularvalidierung (statt der Browser-Texte).
 */
export type ModalSize = "sm" | "md" | "lg" | "xl";

// ---- Schichtenstapel: nur das oberste Popup reagiert auf Escape/Tab; alle darunter und der Hintergrund sind inaktiv ----
let stack: number[] = [];
let nextId = 1;
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f); }; };
const topId = () => stack[stack.length - 1];

function syncBackground() {
  const open = stack.length > 0;
  const root = document.getElementById("root");
  if (root) { root.toggleAttribute("inert", open); if (open) root.setAttribute("aria-hidden", "true"); else root.removeAttribute("aria-hidden"); }
  document.body.classList.toggle("modal-open", open);
}

function useLayer(): boolean {
  const [id] = useState(() => nextId++);
  useEffect(() => {
    stack = [...stack, id]; syncBackground(); emit();
    return () => { stack = stack.filter((x) => x !== id); syncBackground(); emit(); };
  }, [id]);
  return useSyncExternalStore(subscribe, topId, topId) === id;
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';
const visible = (el: HTMLElement) => !el.closest("[inert]") && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0);
const focusables = (root: HTMLElement) => Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(visible);

/** Beschriftung eines Formularfelds für die deutsche Fehlermeldung (Text des umgebenden Labels ohne den Feldinhalt). */
function fieldLabel(el: HTMLElement): string {
  const lab = el.closest("label");
  const text = lab ? Array.from(lab.childNodes).filter((n) => n.nodeType === Node.TEXT_NODE).map((n) => n.textContent ?? "").join(" ").trim() : "";
  return text || el.getAttribute("aria-label") || el.getAttribute("name") || "dieses Feld";
}

export interface ModalProps {
  title: string;
  /** Kurze Beschreibung unter dem Titel (aria-describedby). */
  description?: string;
  size?: ModalSize;
  onClose: () => void;
  children: ReactNode;
  /** Fester Fußbereich (z. B. Aktionen), scrollt nicht mit. */
  footer?: ReactNode;
  /** "form": das Popup selbst ist ein <form> (Abfragen/Bestätigungen); onSubmit wird dann aufgerufen. */
  as?: "div" | "form";
  onSubmit?: (e: FormEvent) => void;
  className?: string;
  /** Klick auf den abgedunkelten Hintergrund schließt (nur für reine Ansichten, nicht für Formulare). */
  dismissible?: boolean;
}

export function Modal({ title, description, size = "md", onClose, children, footer, as = "div", onSubmit, className = "", dismissible = false }: ModalProps) {
  const isTop = useLayer();
  const ref = useRef<HTMLElement | null>(null);
  const closeRef = useRef(onClose); closeRef.current = onClose;
  const topRef = useRef(isTop); topRef.current = isTop;
  const [invalid, setInvalid] = useState("");
  const tid = useId(), did = useId();

  // Fokus beim Öffnen in das Popup, beim Schließen zurück auf das auslösende Element
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    const el = ref.current;
    if (el) {
      const target = el.querySelector<HTMLElement>("[data-autofocus]") ?? focusables(el.querySelector(".modal-body") as HTMLElement ?? el).find((f) => !f.matches("a, summary")) ?? focusables(el)[0] ?? el;
      target.focus({ preventScroll: true });
    }
    return () => { setTimeout(() => { if (trigger && trigger.isConnected && trigger !== document.body) trigger.focus({ preventScroll: true }); }, 0); };
  }, []);

  // Escape schließt nur das oberste Popup
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape" && topRef.current && !e.defaultPrevented) { e.preventDefault(); closeRef.current(); } };
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, []);

  // Nicht oberste Popups sind inaktiv (verschachtelte Popups nur für Formulare aus Detailansichten)
  useEffect(() => { ref.current?.toggleAttribute("inert", !isTop); }, [isTop]);

  // Deutsche Validierung statt Browser-Tooltip: ungültige Felder markieren, Hinweis im Popup, erstes ungültiges Feld fokussieren
  useEffect(() => {
    const el = ref.current; if (!el) return;
    const bad = (e: Event) => {
      e.preventDefault();
      const t = e.target as HTMLInputElement;
      const v = t.validity; const name = fieldLabel(t);
      const msg = v?.valueMissing ? `Bitte füllen Sie das Pflichtfeld „${name}“ aus.` : v?.patternMismatch || v?.typeMismatch || v?.badInput ? `Bitte prüfen Sie die Eingabe im Feld „${name}“.` : v?.rangeUnderflow || v?.rangeOverflow || v?.tooShort || v?.tooLong ? `Der Wert im Feld „${name}“ liegt außerhalb des zulässigen Bereichs.` : `Bitte prüfen Sie das Feld „${name}“.`;
      t.setAttribute("aria-invalid", "true");
      setInvalid((cur) => cur || msg);
      if (!el.querySelector(":focus[aria-invalid]")) t.focus({ preventScroll: false });
    };
    const clear = (e: Event) => { const t = e.target as HTMLElement; if (t.getAttribute?.("aria-invalid")) { t.removeAttribute("aria-invalid"); setInvalid(""); } };
    el.addEventListener("invalid", bad, true);
    el.addEventListener("input", clear, true);
    el.addEventListener("change", clear, true);
    return () => { el.removeEventListener("invalid", bad, true); el.removeEventListener("input", clear, true); el.removeEventListener("change", clear, true); };
  }, []);

  function onKeyDown(e: ReactKeyboardEvent) {
    // React-Ereignisse laufen durch Portale: ein gestapeltes inneres Popup darf die Tab-Führung des inaktiven äußeren nicht auslösen
    if (e.key !== "Tab" || !ref.current || !topRef.current) return;
    const f = focusables(ref.current);
    if (f.length === 0) { e.preventDefault(); ref.current.focus(); return; }
    const first = f[0], last = f[f.length - 1], active = document.activeElement;
    if (e.shiftKey && (active === first || active === ref.current)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && (active === last || active === ref.current)) { e.preventDefault(); first.focus(); }
    else if (!ref.current.contains(active)) { e.preventDefault(); first.focus(); }
  }

  const Tag = as as "div";
  const formProps = as === "form" ? { onSubmit, noValidate: true } : {};
  return createPortal(
    <div className="modal-bg" role="presentation" onMouseDown={(e) => { if (dismissible && e.target === e.currentTarget) onClose(); }}>
      <Tag ref={ref as never} className={`modal card modal-${size} ${className}`.trim()} role="dialog" aria-modal="true" aria-labelledby={tid} aria-describedby={description ? did : undefined} tabIndex={-1} onKeyDown={onKeyDown} {...formProps}>
        <div className="modal-head">
          <h2 id={tid}>{title}</h2>
          <button type="button" className="modal-close" onClick={onClose} title="Schließen"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg><span className="sr-only">Schließen</span></button>
        </div>
        {description && <p id={did} className="modal-desc muted">{description}</p>}
        <div className="modal-body">
          {invalid && <div className="alert err" role="alert">{invalid}</div>}
          {children}
        </div>
        {footer && <div className="modal-foot">{footer}</div>}
      </Tag>
    </div>,
    document.body,
  );
}
