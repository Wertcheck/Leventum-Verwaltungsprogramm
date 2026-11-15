import { cleanup, fireEvent, render as rtlRender, screen, waitFor } from "@testing-library/react";
import { DialogProvider } from "./components/Dialogs";
import type { ReactElement } from "react";
const render = (ui: ReactElement) => rtlRender(ui, { wrapper: DialogProvider });
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, vi } from "vitest";
import { KpiCard } from "./components/ui";
import { NoticeEditor } from "./pages/Dunning";
import { SuggestionRow } from "./pages/Bank";
import EconomicsPage from "./pages/Economics";
import VacancyPage from "./pages/Vacancy";
import FinancePage from "./pages/Finance";

type Handler = (url: string, init?: RequestInit) => unknown;
let calls: { url: string; init?: RequestInit }[] = [];
function mockApi(h: Handler) {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const body = h(url, init);
    return { ok: true, status: 200, json: async () => body } as Response;
  }));
}
beforeEach(() => vi.restoreAllMocks());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const wrap = (ui: JSX.Element) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe("KpiCard Geldformat", () => {
  it("formatiert Geldwerte als Euro und zeigt 0 nicht als 'nicht verfügbar'", () => {
    render(<KpiCard icon={null} label="Offene Mietforderungen" value="0.00" available format="eur" />);
    expect(screen.getByTestId("kpi-Offene Mietforderungen").textContent).toMatch(/0,00\s*€/);
  });
});

describe("Mahnwesen", () => {
  const notice = (status: string) => ({ id: 7, lease_id: 2, level: 1, level_name: "Zahlungserinnerung", status, recipient_name: "Max Mustermann", subject: "s", body: "Text [Frist eintragen]", total_open: "1370.00",
    review_hint: "ENTWURF – vor Versand prüfen. kein automatischer Versand.", sent_on: null, history: [{ at: "2026-02-10", summary: "Zahlungserinnerung vorbereitet (Entwurf)" }] });

  it("Entwurf: Prüfhinweis, editierbarer Text, Freigabe nur per Klick – kein Versenden-Button", async () => {
    mockApi(() => notice("draft"));
    render(<NoticeEditor id={7} onClose={() => {}} />);
    await screen.findByText(/ENTWURF – vor Versand prüfen/);
    expect((screen.getByLabelText("Mahnschreiben") as HTMLTextAreaElement).disabled).toBe(false);
    expect(screen.getByText("Geprüft – freigeben")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^(senden|versenden|abschicken|jetzt senden)/i })).toBeNull();
    expect(calls.every((c) => !c.init || c.init.method === undefined)).toBe(true); // bisher nur Lesezugriffe
  });

  it("Freigegeben: Text gesperrt, nur manuelle Versanddokumentation möglich", async () => {
    mockApi(() => notice("approved"));
    render(<NoticeEditor id={7} onClose={() => {}} />);
    await screen.findByText("Als versandt dokumentieren");
    expect((screen.getByLabelText("Mahnschreiben") as HTMLTextAreaElement).disabled).toBe(true);
    expect(screen.queryByText("Geprüft – freigeben")).toBeNull();
    expect(screen.getByText(/Die Software versendet nichts/)).toBeTruthy();
  });
});

describe("Bankimport – manuelle Bestätigung", () => {
  const t = { id: 5, booking_date: "2026-01-02", amount: "1370.00", counterparty_name: "Max Mustermann", reference: "Miete", status: "open", ignore_reason: null,
    suggestions: [{ kind: "charges", score: 120, reasons: ["IBAN stimmt mit Partei überein"], lease_id: 2, allocations: [{ charge_id: 11, amount: "1150.00", charge_type: "base_rent", due_date: "2026-01-01", open_before: "1150.00" }, { charge_id: 12, amount: "220.00", charge_type: "utility_prepayment", due_date: "2026-01-01", open_before: "220.00" }], unallocated_remainder: "0.00" }] };

  it("Vorschlag bucht nichts; erst der Klick sendet confirm:true mit genau den vorgeschlagenen Zuordnungen", async () => {
    mockApi(() => ({}));
    const done = vi.fn();
    render(<table><tbody><SuggestionRow t={t} onDone={done} /></tbody></table>);
    expect(screen.getByText(/Vorschlag \(120\)/)).toBeTruthy();
    expect(calls.length).toBe(0);
    fireEvent.click(screen.getByText("Zuordnung bestätigen"));
    await waitFor(() => expect(done).toHaveBeenCalled());
    expect(calls[0].url).toBe("/api/v1/bank/transactions/5/confirm");
    const body = JSON.parse(String(calls[0].init?.body));
    expect(body.confirm).toBe(true);
    expect(body.allocations).toEqual([{ charge_id: 11, amount: "1150.00" }, { charge_id: 12, amount: "220.00" }]); // nur die von der API erlaubten Felder
  });

  it("Ohne Vorschlag: als nicht zuordenbar markiert, keine Bestätigungsschaltfläche", () => {
    mockApi(() => ({}));
    render(<table><tbody><SuggestionRow t={{ ...t, suggestions: [] }} onDone={() => {}} /></tbody></table>);
    expect(screen.getByText(/Nicht zuordenbar/)).toBeTruthy();
    expect(screen.queryByText("Zuordnung bestätigen")).toBeNull();
  });
});

const rep = { scope: { type: "portfolio", id: null }, status: "vorläufig",
  soll: { sub_rent: "1150.00", sub_utility: "220.00", sub_total: "1370.00", main_rent: "850.00", main_utility: "180.00", main_total: "1030.00", object_costs: "0.00" },
  ist: { in_from_subleases: "1000.00", in_other_unallocated: "0.00", in_total: "1000.00", out_main_rent: "1030.00", out_invoices: "0.00", out_other_unallocated: "0.00", out_total: "1030.00" },
  offen_zum_stichtag: { as_of: "2026-01-31", receivables: "370.00", receivables_overdue: "370.00", payables: "0.00", invoices: "0.00" },
  vacancy: { economic_vacancy_cost: "412.00", physical_vacancy_rate_by_count: "50.00", note: "" },
  contribution: { label: "Vorläufiger Deckungsbeitrag (kein Gewinn)", rent_margin_soll: "300.00", utility_flow_soll: "40.00", soll_basis: "340.00", ist_basis: "-30.00", utility_settlement_upstream: null, soll_basis_incl_upstream_settlement: null },
  warnings: [], assumptions: ["Soll = aus Mietkonditionen"] };

describe("Auswertungen", () => {
  it("Wirtschaftlichkeit: Soll und Ist getrennt, 'vorläufig', kein Gewinn-Begriff als Ergebnis", async () => {
    mockApi(() => rep);
    render(<EconomicsPage />);
    await screen.findByText("Soll (laut Verträgen)");
    expect(screen.getByText("Ist (Zahlungen)")).toBeTruthy();
    expect(screen.getByText(/Vorläufiger Deckungsbeitrag \(kein Gewinn\)/)).toBeTruthy();
    expect(screen.getByText("Deckungsbeitrag Soll-Basis")).toBeTruthy();
    expect(screen.getByText("Deckungsbeitrag Ist-Basis (Zahlungsfluss)")).toBeTruthy();
    expect(document.body.textContent).toMatch(/340,00\s*€/);
    expect(document.body.textContent).toMatch(/Soll- und Ist-Basis nicht addieren/);
    expect(calls.some((c) => c.url.includes("/economics") && c.url.includes("scope=portfolio"))).toBe(true);
  });

  it("Leerstand: zwei getrennte Kennzahlen mit eigenen Definitionen", async () => {
    mockApi((url) => url.includes("/properties") ? { items: [] } : ({ snapshot: { as_of: "2026-01-31", leaves_total: 3, leaves_occupied: 2, leaves_vacant: 1 },
      physical: { vacancy_rate_by_count_percent: "33.33", vacancy_rate_by_weight_percent: "33.33", definition: "Anteil der Blatt-Tage ohne Untermietvertrag" },
      economic: { cost: "300.00", days_vacant_with_main_obligation: 31, definition: "Hauptmiete-Soll bei Mietverpflichtung ohne Untermiete" }, rows: [], warnings: [] }));
    render(<VacancyPage />);
    await screen.findByText("A · Physischer Leerstand");
    expect(screen.getByTestId("phys").textContent).toBe("33,33 %");
    expect(screen.getByTestId("econ").textContent).toMatch(/300,00\s*€/);
    expect(screen.getByText("B · Wirtschaftlicher Leerstand")).toBeTruthy();
    expect(screen.getByText(/1 von 3 Einheiten unbelegt/)).toBeTruthy();
  });
});

describe("Zahlungen", () => {
  it("Stornieren nur für unveränderte Zahlungen, Stornobuchungen sind gekennzeichnet; Kautionen tauchen nicht auf", async () => {
    mockApi((url) => url.startsWith("/api/v1/payments") ? { items: [
      { id: 1, direction: "in", booking_date: "2026-01-05", amount: "400.00", signed_amount: "400.00", is_reversal: false, reversed: true, allocated: "400.00", unallocated: "0.00", reference: "Miete", source: "manual" },
      { id: 2, direction: "in", booking_date: "2026-01-12", amount: "400.00", signed_amount: "-400.00", is_reversal: true, reversed: false, allocated: "-400.00", unallocated: "0.00", reference: "Storno", source: "manual" },
      { id: 3, direction: "out", booking_date: "2026-01-13", amount: "50.00", signed_amount: "50.00", is_reversal: false, reversed: false, allocated: "0.00", unallocated: "50.00", reference: null, source: "manual" }] } : { items: [] });
    wrap(<FinancePage />);
    await screen.findByText("Zahlungen (Ist)");
    await waitFor(() => expect(screen.getAllByText("Stornieren").length).toBe(1));
    expect(Array.from(document.querySelectorAll(".badge")).map((b) => b.textContent)).toContain("Storno");
    expect(screen.getByText("storniert")).toBeTruthy();
    expect(screen.getByText(/Kautionen erscheinen hier nicht/)).toBeTruthy();
  });
});
