import { createContext, useCallback, useContext, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

/** Eigene Dialoge statt window.prompt/confirm/alert (in pywebview/WebView2 nicht verlässlich, schlechte Bedienung). */
export interface AskOptions { title?: string; type?: "text" | "date" | "textarea"; initial?: string; required?: boolean; confirmLabel?: string; danger?: boolean }
export interface ConfirmOptions { title?: string; confirmLabel?: string; danger?: boolean }
interface Ctx { ask: (message: string, o?: AskOptions) => Promise<string | null>; confirmBox: (message: string, o?: ConfirmOptions) => Promise<boolean>; notify: (message: string) => Promise<void> }
type Req = { kind: "ask"; message: string; o: AskOptions; resolve: (v: string | null) => void } | { kind: "confirm"; message: string; o: ConfirmOptions; resolve: (v: boolean) => void } | { kind: "notify"; message: string; resolve: () => void };

const DialogCtx = createContext<Ctx | null>(null);

export function useDialogs(): Ctx {
  const c = useContext(DialogCtx);
  if (!c) throw new Error("useDialogs benötigt einen DialogProvider");
  return c;
}

export function DialogProvider({ children }: { children: ReactNode }) {
  const [queue, setQueue] = useState<Req[]>([]);
  const push = useCallback((r: Req) => setQueue((q) => [...q, r]), []);
  const ctx: Ctx = {
    ask: (message, o = {}) => new Promise((resolve) => push({ kind: "ask", message, o, resolve })),
    confirmBox: (message, o = {}) => new Promise((resolve) => push({ kind: "confirm", message, o, resolve })),
    notify: (message) => new Promise((resolve) => push({ kind: "notify", message, resolve })),
  };
  const cur = queue[0];
  const done = () => setQueue((q) => q.slice(1));
  return <DialogCtx.Provider value={ctx}>{children}{cur && <DialogView key={queue.length + cur.message} req={cur} onDone={done} />}</DialogCtx.Provider>;
}

function DialogView({ req, onDone }: { req: Req; onDone: () => void }) {
  const [value, setValue] = useState(req.kind === "ask" ? req.o.initial ?? "" : "");
  const [err, setErr] = useState("");
  const ref = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  useEffect(() => { ref.current?.focus(); }, []);
  const cancel = () => { if (req.kind === "ask") req.resolve(null); else if (req.kind === "confirm") req.resolve(false); else req.resolve(); onDone(); };
  useEffect(() => { const k = (e: KeyboardEvent) => e.key === "Escape" && cancel(); window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (req.kind === "ask") {
      const v = value.trim();
      if ((req.o.required ?? true) && !v) { setErr("Bitte einen Wert eingeben."); return; }
      req.resolve(v);
    } else if (req.kind === "confirm") req.resolve(true); else req.resolve();
    onDone();
  }
  const o = req.kind === "ask" ? req.o : req.kind === "confirm" ? req.o : {};
  const danger = "danger" in o && o.danger;
  const title = ("title" in o && o.title) || (req.kind === "confirm" ? "Bitte bestätigen" : req.kind === "notify" ? "Hinweis" : "Eingabe erforderlich");
  return (
    <div className="modal-bg" role="dialog" aria-modal="true" aria-label={title}>
      <form className="modal card dialog" onSubmit={submit}>
        <h2>{title}</h2>
        <p style={{ whiteSpace: "pre-wrap" }}>{req.message}</p>
        {req.kind === "ask" && (req.o.type === "textarea"
          ? <textarea ref={ref} className="field" rows={4} value={value} onChange={(e) => setValue(e.target.value)} aria-label={req.message} />
          : <input ref={ref} className="field" type={req.o.type ?? "text"} value={value} onChange={(e) => setValue(e.target.value)} aria-label={req.message} />)}
        {err && <div className="alert err" role="alert">{err}</div>}
        <div className="toolbar" style={{ justifyContent: "flex-end", margin: 0 }}>
          {req.kind !== "notify" && <button type="button" className="btn" onClick={cancel}>Abbrechen</button>}
          <button type="submit" className={`btn ${danger ? "danger" : "primary"}`}>{("confirmLabel" in o && o.confirmLabel) || (req.kind === "confirm" ? "Bestätigen" : "OK")}</button>
        </div>
      </form>
    </div>
  );
}
