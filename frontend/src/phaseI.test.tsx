import { cleanup, fireEvent, render as rtlRender, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";
import { DialogProvider } from "./components/Dialogs";
import Dashboard, { orderKpis } from "./pages/Dashboard";
import { TenantsPage } from "./pages/Parties";
import FinancePage from "./pages/Finance";
import { RepairDetail, RepairsPage } from "./pages/Repairs";
import { isoDe, todayIso } from "./lib/hooks";

const render = (ui: ReactElement) => rtlRender(<MemoryRouter>{ui}</MemoryRouter>, { wrapper: DialogProvider });
type Reply = unknown | { __status: number; body: unknown };
let calls: string[] = [];
function mockApi(h: (url: string) => Reply) {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    const r = h(url) as { __status?: number; body?: unknown };
    if (r && typeof r === "object" && r.__status) return { ok: false, status: r.__status, json: async () => r.body } as Response;
    return { ok: true, status: 200, json: async () => r } as Response;
  }));
}
beforeEach(() => vi.restoreAllMocks());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const user = { id: 1, username: "a", display_name: "Admin", role: "admin" };
const kpi = (key: string, label: string, o = {}) => ({ key, label, value: 3, available: true, planned_phase: "A", definition: "Def", historical_supported: true, ...o });
const money = (key: string, label: string, v: string, o = {}) => kpi(key, label, { value: v, format: "eur", ...o });
const FINANCE = [money("main_rent_obligations", "Hauptmiete-Verpflichtungen", "850.00"), money("open_receivables", "Offene Forderungen", "600.00"), money("overdue_receivables", "Überfällige Forderungen", "100.00"), money("overdue_payments", "Überfällige Zahlungen", "100.00")];
const STICHTAG = { view: "dashboard", mode: "current", as_of: todayIso(), historical_supported: true, historical_available: true, limitations: ["Monatswerte zeigen den heutigen Stand."] };
const dash = (o = {}) => ({ kpis: [kpi("properties", "Objekte", { historical_supported: false }), ...FINANCE, kpi("upcoming_main_lease_ends", "Hauptmietverträge, die enden"), kpi("upcoming_contract_ends", "Vertragsenden gesamt"), kpi("upcoming_sublease_ends", "Untermietverträge, die enden")],
  warnings: [], tasks: [], stichtag: STICHTAG, ...o });
const PAST = "2025-03-05";
const histDash = () => dash({ stichtag: { ...STICHTAG, mode: "historical", as_of: PAST } });
const dashboardMock = (extra: (url: string) => Reply | undefined = () => undefined) => (url: string): Reply => {
  const x = extra(url); if (x !== undefined) return x;
  if (url.includes("/dashboard")) return url.includes("as_of=") ? histDash() : dash();
  if (url.includes("/economics")) return { __status: 403, body: { detail: "x" } };
  if (url.includes("/tenants")) return { items: [] };
  return { items: [], last_backup_at: null, stale: false, age_hours: null };
};
const label = (t: string) => screen.getByTestId(`kpi-${t}`);

describe("Dashboard Stichtag", () => {
  it("zeigt die Stichtag-Auswahl nur mit historical_available und begrenzt sie auf heute", async () => {
    mockApi(dashboardMock());
    render(<Dashboard user={user} />);
    const input = (await screen.findByLabelText("Auswertung zum Stichtag")) as HTMLInputElement;
    expect(input.max).toBe(todayIso());
    expect(screen.getByText("Heute")).toBeTruthy();
    expect(screen.queryByTestId("stichtag-banner")).toBeNull();
    cleanup();
    mockApi(dashboardMock((u) => u.includes("/dashboard") ? dash({ stichtag: { ...STICHTAG, historical_available: false } }) : undefined));
    render(<Dashboard user={user} />);
    await screen.findByText("Objekte");
    expect(screen.queryByLabelText("Auswertung zum Stichtag")).toBeNull();
    expect(screen.queryByText("Heute")).toBeNull();
  });

  it("historischer Stichtag: Banner, Badge nur bei historical_supported=false, 'Heute' setzt zurück", async () => {
    mockApi(dashboardMock());
    render(<Dashboard user={user} />);
    const input = await screen.findByLabelText("Auswertung zum Stichtag");
    expect(document.querySelector(".kpi-badge")).toBeNull();
    fireEvent.change(input, { target: { value: PAST } });
    const banner = await screen.findByTestId("stichtag-banner");
    expect(banner.textContent).toContain("Historische Auswertung zum 05.03.2025 – nicht alle Kennzahlen sind historisch verfügbar");
    expect(banner.textContent).toContain("Monatswerte zeigen den heutigen Stand.");
    expect(calls.some((c) => c.includes("/dashboard?as_of=2025-03-05"))).toBe(true);
    // genau die Kennzahl mit historical_supported=false ist als aktueller Stand gekennzeichnet
    const badges = Array.from(document.querySelectorAll(".kpi-badge"));
    expect(badges.length).toBe(1);
    expect(badges[0].textContent).toBe("aktueller Stand");
    expect(badges[0].closest(".kpi")?.textContent).toContain("Objekte");
    expect(label("Offene Forderungen").closest(".kpi")?.querySelector(".kpi-badge")).toBeNull();
    fireEvent.click(screen.getByText("Heute"));
    await waitFor(() => expect(screen.queryByTestId("stichtag-banner")).toBeNull());
    expect((screen.getByLabelText("Auswertung zum Stichtag") as HTMLInputElement).value).toBe(isoDe(todayIso()));  // einheitlich TT.MM.JJJJ
    expect(document.querySelector(".kpi-badge")).toBeNull();
  });

  it("Zukunftsdatum wird nicht übernommen und löst keine Abfrage aus", async () => {
    mockApi(dashboardMock());
    render(<Dashboard user={user} />);
    const input = await screen.findByLabelText("Auswertung zum Stichtag");
    const before = calls.length;
    fireEvent.change(input, { target: { value: "2999-01-01" } });
    expect((await screen.findByTestId("stichtag-msg")).textContent).toMatch(/nicht in der Zukunft/);
    expect(calls.length).toBe(before);
    expect(screen.queryByTestId("stichtag-banner")).toBeNull();
  });

  it("Finanz-KPIs und Beträge: fachliche Reihenfolge, Euro-Format, neue KPIs sichtbar", async () => {
    mockApi(dashboardMock());
    render(<Dashboard user={user} />);
    await screen.findByText("Überfällige Forderungen");
    const order = Array.from(document.querySelectorAll(".kpi .label")).map((e) => e.textContent?.replace(/\s*ⓘ$/, "").trim());
    const idx = (l: string) => order.findIndex((x) => x?.startsWith(l));
    expect(idx("Offene Forderungen")).toBeLessThan(idx("Überfällige Forderungen"));
    expect(idx("Überfällige Forderungen")).toBeLessThan(idx("Überfällige Zahlungen"));
    expect(idx("Überfällige Zahlungen")).toBeLessThan(idx("Vertragsenden gesamt"));
    expect(idx("Vertragsenden gesamt")).toBeLessThan(idx("Hauptmietverträge, die enden"));
    expect(idx("Hauptmietverträge, die enden")).toBeLessThan(idx("Untermietverträge, die enden"));
    expect(label("Überfällige Forderungen").textContent).toMatch(/100,00\s*€/);
    expect(label("Überfällige Forderungen").className).toContain("money");  // money = white-space: nowrap
    expect(label("Hauptmietverträge, die enden").textContent).toBe("3");
  });

  it("ohne Finanzrecht: Finanz-KPIs fehlen komplett, kein Fehler, keine Platzhalter, keine Stichtag-Auswahl, kein Wirtschaftsblock", async () => {
    const noFin = { kpis: [kpi("properties", "Objekte"), kpi("active_subleases", "Aktive Untermietverträge")], warnings: [], tasks: [], stichtag: { ...STICHTAG, historical_available: false } };
    mockApi(dashboardMock((u) => u.includes("/dashboard") ? noFin : undefined));
    render(<Dashboard user={user} />);
    await screen.findByText("Aktive Untermietverträge");
    expect(document.querySelectorAll(".kpi").length).toBe(2);
    expect(document.querySelector(".alert.err")).toBeNull();
    expect(screen.queryByText(/Forderungen/)).toBeNull();
    expect(screen.queryByText("Wirtschaftlicher Überblick")).toBeNull();
    expect(screen.queryByText(/Wird berechnet/)).toBeNull();
    expect(screen.queryByLabelText("Auswertung zum Stichtag")).toBeNull();
    expect(document.body.textContent).not.toMatch(/undefined|NaN/);
  });

  it("422 und 403 werden verständlich gemeldet (keine Rohtexte), Auswahl bleibt bedienbar", async () => {
    let reply: Reply = { __status: 422, body: { detail: { code: "as_of_in_future", detail: "RAW-TEXT" } } };
    mockApi(dashboardMock((u) => u.includes("as_of=") ? reply : undefined));
    render(<Dashboard user={user} />);
    const input = await screen.findByLabelText("Auswertung zum Stichtag");
    fireEvent.change(input, { target: { value: PAST } });
    await waitFor(() => expect(document.querySelector(".alert.err")?.textContent).toMatch(/nicht in der Zukunft liegen/));
    expect(document.body.textContent).not.toContain("RAW-TEXT");
    reply = { __status: 422, body: { detail: { code: "invalid_as_of", detail: "RAW-TEXT" } } };
    fireEvent.change(screen.getByLabelText("Auswertung zum Stichtag"), { target: { value: "2025-03-06" } });
    await waitFor(() => expect(document.querySelector(".alert.err")?.textContent).toMatch(/ungültig/));
    reply = { __status: 403, body: { detail: "Forbidden RAW-TEXT" } };
    fireEvent.change(screen.getByLabelText("Auswertung zum Stichtag"), { target: { value: "2025-03-07" } });
    await waitFor(() => expect(document.querySelector(".alert.err")?.textContent).toMatch(/Berechtigung für Finanzdaten/));
    expect(document.body.textContent).not.toContain("RAW-TEXT");
    expect(screen.getByText("Heute")).toBeTruthy();  // Rückweg bleibt möglich
  });

  it("orderKpis behält die Reihenfolge fremder KPIs und ordnet nur die Forderungs-/Fristgruppe", () => {
    const ks = ["a", "upcoming_sublease_ends", "b", "overdue_payments", "open_receivables", "c"].map((k) => kpi(k, k));
    const out = orderKpis(ks).map((k) => k.key);
    expect(out).toEqual(["a", "open_receivables", "overdue_payments", "upcoming_sublease_ends", "b", "c"]);
  });
});

describe("Mieterliste und Panel ohne Finanzrecht", () => {
  const row = (o = {}) => ({ party_id: 7, name: "Max Muster", lease_id: 3, lease_status: "active", spaces: ["Haus A"], start_date: "2026-01-01", end_date: null, monthly_total: { available: true, total: "420.00" }, payment_status: null, overdue_amount: null, last_activity: null, ...o });
  const listOf = (items: unknown[]) => ({ items, total: items.length, limit: 200, offset: 0 });

  it("payment_status null: '–' ohne Fehler, Filter 'Mit Rückstand' wird nicht angeboten", async () => {
    mockApi(() => listOf([row()]));
    render(<TenantsPage />);
    await screen.findByText("Max Muster");
    expect(document.querySelector(".alert.err")).toBeNull();
    expect(screen.queryByText(/Rückstand/)).toBeNull();
    expect(screen.queryByText("Ausgeglichen")).toBeNull();
    expect(Array.from(document.querySelectorAll("tbody tr td:last-child")).map((e) => e.textContent)).toEqual(["–"]);
    expect(Array.from(document.querySelectorAll("option")).map((o) => o.textContent)).not.toContain("Mit Rückstand");
  });

  it("mit Zahlungsstatus: Filter 'Mit Rückstand' vorhanden", async () => {
    mockApi(() => listOf([row({ payment_status: "arrears", overdue_amount: "420.00" })]));
    render(<TenantsPage />);
    await screen.findByText(/Rückstand 420,00/);
    await waitFor(() => expect(Array.from(document.querySelectorAll("option")).map((o) => o.textContent)).toContain("Mit Rückstand"));
  });

  const overviewNoFin = { party: { id: 7, display_name: "Max Muster", email: null, phone: null, city: null },
    leases: [{ id: 3, kind: "sub", role: "lessee", type: "Untermietvertrag", phase: "active", start_date: "2026-01-01", end_date: null, spaces: ["Haus A"], monthly: { available: true, total: "420.00" }, payment_rhythm: "monthly", payment_status: null, overdue_amount: null, deposit: null }],
    documents: [], tasks: [], repairs: [], activity: [] };

  it("Panel ohne 'finance'-Block: kein Absturz, keine Finanzabschnitte, keine Kaution", async () => {
    mockApi((u) => u.includes("/overview") ? overviewNoFin : listOf([row()]));
    render(<TenantsPage />);
    fireEvent.click(await screen.findByText("Max Muster"));
    const panel = await screen.findByTestId("tenant-panel");
    await within(panel).findByText("Dokumente");
    expect(within(panel).queryByText("Offene Posten")).toBeNull();
    expect(within(panel).queryByText("Letzte Zahlungen")).toBeNull();
    expect(panel.textContent).not.toMatch(/Kaution|Rückstand|undefined|NaN/);
    expect(within(panel).getByText(/Untermietvertrag #3/)).toBeTruthy();
  });
});

describe("Zahlungen: zukünftig gebucht", () => {
  const pay = (o = {}) => ({ id: 1, direction: "in", booking_date: "2999-01-05", amount: "400.00", signed_amount: "400.00", is_reversal: false, reversed: false, allocated: "0.00", unallocated: "400.00", reference: "Miete", source: "manual", is_future_dated: true, ...o });

  it("Badge und Hinweis nur für is_future_dated; Stand-Zeile der Forderungsliste", async () => {
    mockApi((u) => u.startsWith("/api/v1/payments") ? { items: [pay(), pay({ id: 2, booking_date: "2026-01-02", is_future_dated: false, reference: "Alt" })] }
      : { items: [], stichtag: { view: "charges", mode: "current", as_of: "2026-11-16", historical_supported: true } });
    render(<FinancePage />);
    await screen.findByText("Zahlungen (Ist)");
    await waitFor(() => expect(screen.getAllByText("zukünftig gebucht").length).toBe(1));
    expect(screen.getByTestId("future-note").textContent).toMatch(/mindern Forderungen erst ab diesem Datum/);
    expect(screen.getByTestId("stichtag-line").textContent).toBe("Stand: 16.11.2026 (aktuelle Ansicht)");
    expect(screen.queryByLabelText(/Stichtag/)).toBeNull();  // bewusst keine Auswahl in der Forderungsliste
  });

  it("ohne zukünftige Zahlungen weder Badge noch Hinweis", async () => {
    mockApi((u) => u.startsWith("/api/v1/payments") ? { items: [pay({ is_future_dated: false, booking_date: "2026-01-02" })] } : { items: [] });
    render(<FinancePage />);
    await screen.findByText("Zahlungen (Ist)");
    await screen.findByText("Miete");
    expect(screen.queryByText("zukünftig gebucht")).toBeNull();
    expect(screen.queryByTestId("future-note")).toBeNull();
  });
});

describe("Reparaturen ohne Kostenblock", () => {
  const base = { id: 9, property_id: 1, unit_id: null, title: "Heizung defekt", category: "heizung", priority: "urgent", status: "in_progress", reported_on: "2026-03-01", scheduled_for: null, completed_on: null, description: null, contractor_party_id: null, is_open: true };

  it("Liste: keine Kostenspalten, kein 'undefined €'", async () => {
    mockApi((u) => u.includes("/repairs") ? { items: [base] } : { items: [] });
    render(<RepairsPage />);
    await screen.findByText("Heizung defekt");
    expect(screen.queryByText("Schätzung")).toBeNull();
    expect(document.body.textContent).not.toMatch(/undefined|NaN/);
  });

  it("Detail: kein Absturz, Hinweis statt Kosten", async () => {
    mockApi((u) => u.startsWith("/api/v1/documents") ? { items: [] } : u.startsWith("/api/v1/invoices") ? { __status: 403, body: { detail: "x" } } : { ...base, events: [], tasks: [] });
    rtlRender(<MemoryRouter initialEntries={["/reparaturen/9"]}><Routes><Route path="/reparaturen/:id" element={<RepairDetail />} /></Routes></MemoryRouter>, { wrapper: DialogProvider });
    await screen.findByText(/Reparatur #9: Heizung defekt/);
    expect(screen.getByText(/nur mit Berechtigung für Finanzdaten sichtbar/)).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/undefined|NaN/);
  });
});
