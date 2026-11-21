import { act, cleanup, fireEvent, render as rtlRender, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useState, type ReactElement } from "react";
import { DialogProvider, useDialogs } from "./components/Dialogs";
import { Modal } from "./components/Modal";
import { DateInput } from "./components/DateInput";
import AppShell from "./components/AppShell";
import Dashboard from "./pages/Dashboard";
import { dateDe, isoDe, monthDe, parseDateText, parseMonthText, todayIso } from "./lib/hooks";

const render = (ui: ReactElement) => rtlRender(<MemoryRouter>{ui}</MemoryRouter>, { wrapper: DialogProvider });
let calls: string[] = [];
function mockApi(h: (url: string) => unknown) {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => { calls.push(url); return { ok: true, status: 200, json: async () => h(url) } as Response; }));
}
beforeEach(() => {
  vi.restoreAllMocks();
  // jsdom hat kein Layout: Elemente gelten für die Fokusführung als sichtbar
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([{}] as unknown as DOMRectList);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); document.body.innerHTML = ""; document.body.className = ""; });

describe("Zentrales Popup-System (Modal)", () => {
  function Harness({ nested = false }: { nested?: boolean }) {
    const [open, setOpen] = useState(false), [inner, setInner] = useState(false);
    return (
      <div id="root">
        <button onClick={() => setOpen(true)}>Öffnen</button>
        {open && <Modal title="Testpopup" description="Beschreibung" onClose={() => setOpen(false)}>
          <input aria-label="Feld" />
          {nested && <button onClick={() => setInner(true)}>Innen öffnen</button>}
          {inner && <Modal title="Innenpopup" onClose={() => setInner(false)}><input aria-label="Innenfeld" /></Modal>}
        </Modal>}
      </div>
    );
  }

  it("ARIA: Dialog, modal, Titel und Beschreibung verknüpft; Hintergrund ist inaktiv", () => {
    rtlRender(<Harness />);
    fireEvent.click(screen.getByText("Öffnen"));
    const d = screen.getByRole("dialog", { name: "Testpopup" });
    expect(d.getAttribute("aria-modal")).toBe("true");
    expect(d.getAttribute("aria-describedby")).toBeTruthy();
    expect(document.getElementById(d.getAttribute("aria-describedby")!)!.textContent).toBe("Beschreibung");
    expect(document.getElementById("root")!.hasAttribute("inert")).toBe(true);
    expect(document.body.classList.contains("modal-open")).toBe(true);
  });

  it("Fokus: beim Öffnen in das Popup, Escape schließt, Fokus zurück auf das auslösende Element", async () => {
    rtlRender(<Harness />);
    const trigger = screen.getByText("Öffnen");
    trigger.focus(); fireEvent.click(trigger);
    const d = screen.getByRole("dialog");
    expect(d.contains(document.activeElement)).toBe(true);
    expect((document.activeElement as HTMLElement).getAttribute("aria-label")).toBe("Feld");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    expect(document.getElementById("root")!.hasAttribute("inert")).toBe(false);
    expect(document.body.classList.contains("modal-open")).toBe(false);
  });

  it("X-Schaltfläche schließt (zugänglicher Name „Schließen“)", async () => {
    rtlRender(<Harness />);
    fireEvent.click(screen.getByText("Öffnen"));
    fireEvent.click(screen.getByRole("button", { name: "Schließen" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("Tab bleibt im Popup (Fokusführung vorwärts und rückwärts)", () => {
    rtlRender(<Harness />);
    fireEvent.click(screen.getByText("Öffnen"));
    const d = screen.getByRole("dialog");
    const close = screen.getByRole("button", { name: "Schließen" }), field = screen.getByLabelText("Feld");
    field.focus(); fireEvent.keyDown(field, { key: "Tab" });           // letztes fokussierbares Element → zurück zum ersten
    expect(document.activeElement).toBe(close);
    close.focus(); fireEvent.keyDown(close, { key: "Tab", shiftKey: true }); // erstes → zum letzten
    expect(document.activeElement).toBe(field);
    expect(d.contains(document.activeElement)).toBe(true);
  });

  it("verschachtelt: Escape schließt nur das oberste Popup, das untere ist inaktiv", async () => {
    rtlRender(<Harness nested />);
    fireEvent.click(screen.getByText("Öffnen"));
    fireEvent.click(screen.getByText("Innen öffnen"));
    expect(screen.getAllByRole("dialog").length).toBe(2);
    expect(screen.getByRole("dialog", { name: "Testpopup", hidden: true }).hasAttribute("inert")).toBe(true);
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.getAllByRole("dialog").length).toBe(1));
    expect(screen.getByRole("dialog", { name: "Testpopup" }).hasAttribute("inert")).toBe(false);
  });

  it("deutsche Validierung statt Browser-Tooltip: Pflichtfeld wird markiert und benannt", async () => {
    rtlRender(<Modal title="Formular" onClose={() => undefined}><form><label>Bezeichnung<input required /></label><button type="submit">Anlegen</button></form></Modal>);
    const input = screen.getByLabelText("Bezeichnung") as HTMLInputElement;
    const bad = vi.fn((e: Event) => e.defaultPrevented);
    input.addEventListener("invalid", bad);
    act(() => { (screen.getByText("Anlegen").closest("form") as HTMLFormElement).requestSubmit(); });
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Bitte füllen Sie das Pflichtfeld „Bezeichnung“ aus.");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    fireEvent.input(input, { target: { value: "x" } });
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("Abfrage-/Bestätigungsdialoge nutzen dieselbe Popup-Basis (Rolle, Fokus, Escape = Abbrechen)", async () => {
    let result: string | null | undefined;
    function Ask() { const { ask } = useDialogs(); return <button onClick={async () => { result = await ask("Begründung", { title: "Löschen" }); }}>Fragen</button>; }
    rtlRender(<DialogProvider><Ask /></DialogProvider>);
    fireEvent.click(screen.getByText("Fragen"));
    const d = await screen.findByRole("dialog", { name: "Löschen" });
    expect(d.tagName).toBe("FORM");
    expect(document.activeElement).toBe(screen.getByLabelText("Begründung"));
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(result).toBeNull());
  });
});

describe("Datum im deutschen Format", () => {
  it("Parser und Anzeige: TT.MM.JJJJ und ISO werden verstanden, Ungültiges abgelehnt", () => {
    expect(parseDateText("19.11.2026")).toBe("2026-11-19");
    expect(parseDateText("1.2.2026")).toBe("2026-02-01");
    expect(parseDateText("2026-11-19")).toBe("2026-11-19");
    expect(parseDateText("31.02.2026")).toBeNull();
    expect(parseDateText("19.11.")).toBeNull();
    expect(parseDateText("abc")).toBeNull();
    expect(parseMonthText("11.2026")).toBe("2026-11");
    expect(parseMonthText("2026-11")).toBe("2026-11");
    expect(parseMonthText("13.2026")).toBeNull();
    expect(isoDe("2026-11-01")).toBe("01.11.2026");
    expect(dateDe("2026-11-01")).toBe("01.11.2026");       // früher „1.11.2026“
    expect(monthDe("2026-11-01")).toBe("11.2026");
    expect(dateDe(null)).toBe("–");
  });

  it("DateInput: gibt nur gültige Werte als ISO nach außen, formatiert beim Verlassen, übernimmt externe Werte", () => {
    const seen: string[] = [];
    function H() { const [v, setV] = useState("2026-01-05"); return <><DateInput value={v} onChange={(x) => { seen.push(x); setV(x); }} ariaLabel="Datum" /><button onClick={() => setV("2027-02-03")}>extern</button></>; }
    rtlRender(<H />);
    const input = screen.getByLabelText("Datum") as HTMLInputElement;
    expect(input.value).toBe("05.01.2026");
    expect(input.getAttribute("placeholder")).toBe("TT.MM.JJJJ");
    fireEvent.change(input, { target: { value: "19.1" } });        // unvollständig: kein Wert nach außen
    expect(seen).toEqual([]);
    fireEvent.change(input, { target: { value: "19.11.2026" } });
    expect(seen).toEqual(["2026-11-19"]);
    fireEvent.change(input, { target: { value: "2026-12-24" } });  // ISO wird akzeptiert
    expect(seen[seen.length - 1]).toBe("2026-12-24");
    fireEvent.blur(input); expect(input.value).toBe("24.12.2026");
    fireEvent.click(screen.getByText("extern")); expect(input.value).toBe("03.02.2027");
    fireEvent.change(input, { target: { value: "" } }); expect(seen[seen.length - 1]).toBe("");
    fireEvent.change(input, { target: { value: "xx" } }); fireEvent.blur(input);
    expect(input.getAttribute("aria-invalid")).toBe("true");
  });

  it("DateInput: vom Elternteil abgelehnter Wert wird im Feld zurückgesetzt", async () => {
    function H() { const [v, setV] = useState("2026-01-05"); return <DateInput value={v} onChange={(x) => { if (x <= "2026-12-31") setV(x); }} ariaLabel="Datum" />; }
    rtlRender(<H />);
    const input = screen.getByLabelText("Datum") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "01.01.2999" } });
    await waitFor(() => expect(input.value).toBe("05.01.2026"));
  });
});

describe("Dashboard: Popups und keine Demo-Leiste", () => {
  const user = { id: 1, username: "a", display_name: "Admin", role: "admin" };
  const kpi = (key: string, label: string, o = {}) => ({ key, label, value: 3, available: true, planned_phase: "A", definition: "Def", historical_supported: true, ...o });
  const dash = { kpis: [kpi("properties", "Immobilien"), kpi("open_tasks", "Offene Aufgaben"), kpi("unbekannt_xyz", "Unbekannte Kennzahl")], warnings: [], tasks: [],
    stichtag: { view: "dashboard", mode: "current", as_of: todayIso(), historical_supported: true, historical_available: true, limitations: [] } };
  const ECO = { soll: { sub_total: "100.00", main_total: "80.00" }, ist: {}, offen_zum_stichtag: { receivables: "0.00", receivables_overdue: "0.00", payables: "0.00", invoices: "0.00", as_of: todayIso() },
    vacancy: { economic_vacancy_cost: "0.00", physical_vacancy_rate_by_count: null }, contribution: { soll_basis: "20.00", ist_basis: "0.00" }, warnings: [], assumptions: [], prognose_periodenende: null };
  const handler = (url: string) => (url.includes("/economics") ? ECO : url.includes("/dashboard") ? dash : url.includes("/health") ? { status: "ok", demo: true } : url.includes("/tenants") ? { items: [{ party_id: 1, name: "Max Muster", spaces: ["Haus A"], lease_status: "active" }] } : { items: [], last_backup_at: null, stale: false });

  it("Klick auf Kennzahlenkarte öffnet die passende Detailansicht, Escape schließt, Fokus zurück auf die Karte", async () => {
    mockApi(handler);
    render(<Dashboard user={user} />);
    const card = (await screen.findByTestId("kpi-Immobilien")).closest("button") as HTMLButtonElement;
    expect(card.getAttribute("aria-haspopup")).toBe("dialog");
    card.focus(); fireEvent.click(card);
    expect(await screen.findByRole("dialog", { name: "Immobilienübersicht" })).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(card));
    fireEvent.click(screen.getByTestId("kpi-Offene Aufgaben").closest("button")!);
    expect(await screen.findByRole("dialog", { name: "Aufgabenverwaltung" })).toBeTruthy();
  });

  it("Mieter- und Aufgaben-Block sowie Wirtschaftlicher Überblick sind anklickbar (Titel und freie Fläche)", async () => {
    mockApi(handler);
    render(<Dashboard user={user} />);
    fireEvent.click(await screen.findByRole("button", { name: /^Mieter/ }));
    expect(await screen.findByRole("dialog", { name: "Mieterübersicht" })).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const taskBlock = screen.getByRole("button", { name: /^Aufgaben & Hinweise/ }).closest("section")!;
    fireEvent.click(taskBlock.querySelector(".block-body")!);   // freie Fläche des Blocks
    expect(await screen.findByRole("dialog", { name: "Aufgabenverwaltung" })).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    fireEvent.click(await screen.findByRole("button", { name: /^Wirtschaftlicher Überblick/ }));
    expect(await screen.findByRole("dialog", { name: "Wirtschaftlichkeitsauswertung" })).toBeTruthy();
  });

  it("Kennzahl ohne zugeordnete Detailansicht ist nicht klickbar (keine Scheinschaltfläche)", async () => {
    mockApi(handler);
    render(<Dashboard user={user} />);
    const c = (await screen.findByTestId("kpi-Unbekannte Kennzahl")).closest(".kpi") as HTMLElement;
    expect(c.tagName).toBe("SECTION");
    expect(screen.getByTestId("kpi-Immobilien").closest(".kpi")!.tagName).toBe("BUTTON");
  });

  it("AppShell: keine Demo-Leiste (auch wenn der Server Demo meldet) und kein Health-Abruf für die Anzeige", async () => {
    mockApi(handler);
    rtlRender(<MemoryRouter><Routes><Route element={<AppShell user={user} onLogout={() => undefined} />}><Route path="/" element={<p>Inhalt</p>} /></Route></Routes></MemoryRouter>, { wrapper: DialogProvider });
    await screen.findByText("Inhalt");
    await new Promise((r) => setTimeout(r, 50));
    expect(document.querySelector("[data-testid=demo-banner], .demo-banner")).toBeNull();
    expect(document.body.textContent).not.toMatch(/Demo-Modus|erfunden und dienen nur der Vorführung/);
    expect(calls.some((c) => c.includes("/health"))).toBe(false);
  });

  it("Navigation als Drawer: Menüschaltfläche mit aria-expanded, Escape schließt", async () => {
    mockApi(handler);
    rtlRender(<MemoryRouter><Routes><Route element={<AppShell user={user} onLogout={() => undefined} />}><Route path="/" element={<p>Inhalt</p>} /></Route></Routes></MemoryRouter>, { wrapper: DialogProvider });
    const toggle = await screen.findByRole("button", { name: "Navigation" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(document.getElementById("sidebar")!.classList.contains("open")).toBe(true);
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(toggle.getAttribute("aria-expanded")).toBe("false"));
  });
});

describe("Nachbesserungen nach unabhängiger Prüfung", () => {
  it("Tab im gestapelten inneren Popup läuft normal weiter (äußeres, inaktives Popup blockiert nicht)", () => {
    function H() { const [i, setI] = useState(false); return <div id="root"><Modal title="Außen" onClose={() => undefined}><button onClick={() => setI(true)}>Innen öffnen</button>
      {i && <Modal title="Innen" onClose={() => setI(false)}><input aria-label="A" /><input aria-label="B" /><input aria-label="C" /></Modal>}</Modal></div>; }
    rtlRender(<H />);
    fireEvent.click(screen.getByText("Innen öffnen"));
    const b = screen.getByLabelText("B"); b.focus();
    const ev = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    b.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(false);   // mittleres Feld: Browser darf normal weiterspringen
  });

  it("DateInput: unvollständige Eingabe macht das Feld ungültig (Enter kann nicht mit altem Wert absenden)", () => {
    rtlRender(<DateInput value="2026-01-05" onChange={() => undefined} ariaLabel="Datum" />);
    const input = screen.getByLabelText("Datum") as HTMLInputElement;
    expect(input.validity.valid).toBe(true);
    fireEvent.change(input, { target: { value: "19.1" } });
    expect(input.validity.valid).toBe(false);
    fireEvent.change(input, { target: { value: "19.11.2026" } });
    expect(input.validity.valid).toBe(true);
  });

  it("Abfragedialog mit Datum nutzt das deutsche Datumsfeld (kein natives Browserformat)", async () => {
    function Ask() { const { ask } = useDialogs(); return <button onClick={() => void ask("Kündigungsdatum", { type: "date", title: "Kündigung" })}>Fragen</button>; }
    rtlRender(<DialogProvider><Ask /></DialogProvider>);
    fireEvent.click(screen.getByText("Fragen"));
    const f = (await screen.findByLabelText("Kündigungsdatum")) as HTMLInputElement;
    expect(f.getAttribute("data-kind")).toBe("date");
    expect(f.type).toBe("text");
  });
});

describe("Anzeigename des Benutzers", () => {
  it("Begrüßung und Menü zeigen den Profilnamen, ohne Profilnamen den Benutzernamen", async () => {
    const { userName } = await import("./lib/api");
    expect(userName({ username: "jb", display_name: "James" })).toBe("James");
    expect(userName({ username: "jb", display_name: "  " })).toBe("jb");
    expect(userName({ username: "jb", display_name: "" })).toBe("jb");
    mockApi((u) => (u.includes("/dashboard") ? { kpis: [], warnings: [], tasks: [], stichtag: { view: "dashboard", mode: "current", as_of: todayIso(), historical_supported: true, historical_available: true, limitations: [] } } : { items: [], last_backup_at: null, stale: false }));
    render(<Dashboard user={{ id: 1, username: "jb", display_name: "", role: "admin" }} />);
    expect(await screen.findByRole("heading", { level: 1, name: "Guten Tag, jb" })).toBeTruthy();
  });
});
