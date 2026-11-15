import { cleanup, fireEvent, render as rtlRender, within, screen, waitFor } from "@testing-library/react";
import { DialogProvider } from "./components/Dialogs";
import type { ReactElement } from "react";
const render = (ui: ReactElement) => rtlRender(ui, { wrapper: DialogProvider });
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, vi } from "vitest";
import TasksPage from "./pages/Tasks";
import { RepairDetail } from "./pages/Repairs";
import CommunicationsPage from "./pages/Communications";
import Dashboard from "./pages/Dashboard";
import { DocRow } from "./components/DocPanel";

type Handler = (url: string, init?: RequestInit) => unknown;
let calls: { url: string; init?: RequestInit }[] = [];
function mockApi(h: Handler) {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => { calls.push({ url, init }); return { ok: true, status: 200, json: async () => h(url, init) } as Response; }));
}
beforeEach(() => vi.restoreAllMocks());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.unstubAllGlobals(); });
const posts = () => calls.filter((c) => c.init?.method === "POST");

const task = (o = {}) => ({ id: 1, title: "Schlüssel nachmachen", description: null, priority: "high", status: "open", due_date: "2026-01-01", overdue: true, lease_id: 4, party_id: null, property_id: null, repair_id: null, ...o });

describe("Aufgaben", () => {
  it("zeigt Überfälligkeit und reicht Filter an die API weiter", async () => {
    mockApi(() => ({ items: [task()] }));
    render(<MemoryRouter><TasksPage /></MemoryRouter>);
    await screen.findByText("Schlüssel nachmachen");
    expect(screen.getByText("überfällig")).toBeTruthy();
    fireEvent.click(screen.getByLabelText(/nur überfällige/));
    await waitFor(() => expect(calls.some((c) => c.url.includes("overdue=true"))).toBe(true));
  });

  it("Abbrechen verlangt eine Begründung – ohne Begründung wird nichts gesendet; Erledigt wird gesendet", async () => {
    mockApi(() => ({ items: [task()] }));
    render(<MemoryRouter><TasksPage /></MemoryRouter>);
    await screen.findByText("Schlüssel nachmachen");
    const sel = screen.getByLabelText("Status Schlüssel nachmachen");
    fireEvent.change(sel, { target: { value: "cancelled" } });
    fireEvent.click(await screen.findByText("Abbrechen"));
    expect(posts().length).toBe(0);
    fireEvent.change(sel, { target: { value: "done" } });
    await waitFor(() => expect(posts().length).toBe(1));
    expect(posts()[0].url).toBe("/api/v1/tasks/1/status");
    expect(JSON.parse(String(posts()[0].init?.body)).status).toBe("done");
  });
});

describe("Reparaturen", () => {
  const detail = { id: 9, property_id: 1, unit_id: null, title: "Heizung defekt", category: "heizung", priority: "urgent", status: "in_progress", reported_on: "2026-03-01", scheduled_for: null, completed_on: null, description: null, contractor_party_id: null, is_open: true,
    costs: { estimate: "500.00", actual: "550.00", paid: "300.00", open: "250.00", invoice_ids: [5], deviation_from_estimate: "50.00" },
    events: [{ id: 1, occurred_at: "2026-03-01", kind: "reported", text: "Gemeldet: Heizung defekt" }], tasks: [] };
  it("Kosten stammen aus Rechnungen; verknüpfbar sind nur Rechnungen desselben Objekts, die noch nicht zugeordnet sind", async () => {
    mockApi((url) => url.startsWith("/api/v1/documents") ? { items: [] } : url.startsWith("/api/v1/invoices") ? { items: [
      { id: 5, invoice_number: "A1", amount: "300.00", property_id: 1, status: "paid", description: null }, { id: 6, invoice_number: "A2", amount: "250.00", property_id: 1, status: "open", description: null },
      { id: 7, invoice_number: "FREMD", amount: "9.00", property_id: 2, status: "open", description: null }, { id: 8, invoice_number: "STORNO", amount: "9.00", property_id: 1, status: "voided", description: null }] } : detail);
    render(<MemoryRouter initialEntries={["/reparaturen/9"]}><Routes><Route path="/reparaturen/:id" element={<RepairDetail />} /></Routes></MemoryRouter>);
    await screen.findByText(/Reparatur #9: Heizung defekt/);
    expect(document.body.textContent).toMatch(/550,00\s*€/);
    expect(screen.getByText(/nicht von Hand eingetragen/)).toBeTruthy();
    expect(screen.getByText("Verlauf")).toBeTruthy();
    const optTexts = () => Array.from(document.querySelectorAll("option")).map((o) => (o.textContent ?? "").replace(/\s/g, " "));
    await waitFor(() => expect(optTexts()).toContain("A2 – 250,00 €"));
    const opts = optTexts();
    expect(opts.some((o) => o?.includes("FREMD") || o?.includes("STORNO") || o?.startsWith("A1"))).toBe(false);
  });
});

describe("Kommunikation", () => {
  it("weist darauf hin, dass nichts versendet wird, und bietet keine Versandfunktion", async () => {
    mockApi((url) => url.includes("/communications") ? { items: [{ id: 1, channel: "email", direction: "in", occurred_at: "2026-02-01T10:00:00Z", subject: "Frage zur Heizung", body: null, party_id: 3, lease_id: null, property_id: null }] } : { items: [] });
    render(<MemoryRouter><CommunicationsPage /></MemoryRouter>);
    await screen.findByText("Frage zur Heizung");
    expect(screen.getByText(/es werden keine Nachrichten versendet/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /senden|versenden|abschicken/i })).toBeNull();
  });
});

describe("Dashboard Hinweise", () => {
  const base = { kpis: [], tasks: [{ id: 3, title: "Kündigung prüfen", due_date: "2026-04-01", overdue: false, priority: "normal", status: "open" }],
    warnings: [{ key: "contract_end:2:2026-12-31", type: "contract_end", severity: "warning", title: "Untermietvertrag #2 endet am 31.12.2026", detail: "Noch 21 Tage.", due_date: "2026-12-31", task_id: null },
               { key: "overdue:2:2026-01-01", type: "overdue_payment", severity: "critical", title: "Überfällige Zahlung – Vertrag #2: 1370.00 € offen", detail: "1 Sollstellung(en)", due_date: "2026-01-01", task_id: 12 }] };
  it("zeigt echte Hinweise; Aufgabe nur erstellbar, wenn noch keine existiert (Duplikatschutz in der UI)", async () => {
    const eco = { soll: { sub_total: "1370.00", main_total: "1030.00" }, ist: {}, offen_zum_stichtag: { receivables: "2740.00", receivables_overdue: "2740.00" }, vacancy: { economic_vacancy_cost: "412.00" }, contribution: { soll_basis: "340.00", ist_basis: "-30.00" } };
    mockApi((url, init) => init?.method === "POST" ? { id: 13 } : url.includes("/dashboard") ? base : url.includes("/economics") ? eco : { items: [], last_backup_at: null, stale: false, age_hours: null });
    render(<MemoryRouter><Dashboard user={{ id: 1, username: "a", display_name: "Admin", role: "admin" }} /></MemoryRouter>);
    await screen.findByText(/Untermietvertrag #2 endet/);
    expect(screen.getByText("Dringend")).toBeTruthy();
    expect(screen.getAllByText("Aufgabe erstellen").length).toBe(1); // für die Erinnerung mit vorhandener Aufgabe (#12) gibt es nur den Link
    expect(screen.getByText("Aufgabe #12")).toBeTruthy();
    expect(screen.getByText("Kündigung prüfen")).toBeTruthy();
    await screen.findByText("Wirtschaftlicher Überblick");
    await waitFor(() => expect(document.body.textContent).toMatch(/340,00\s*€/));  // echte Zahlen statt Platzhaltertext
    expect(document.body.textContent).not.toMatch(/Wird in Phase D/);
    fireEvent.click(screen.getByText("Aufgabe erstellen"));
    await waitFor(() => expect(posts().length).toBe(1));
    expect(JSON.parse(String(posts()[0].init?.body))).toEqual({ key: "contract_end:2:2026-12-31" });
  });
});

describe("Dokumente", () => {
  const doc = { id: 4, original_name: "Mietvertrag.pdf", mime: "application/pdf", size: 2048, doc_type: "mietvertrag", uploaded_at: "2026-01-01T00:00:00Z", links: [] };
  it("Löschen verlangt eine Begründung; gelöschte Dokumente haben keinen Download-Link", async () => {
    mockApi(() => ({}));
    const changed = vi.fn();
    const { rerender } = render(<DocRow d={doc} onChanged={changed} />);
    expect(screen.getByText("Mietvertrag.pdf").closest("a")?.getAttribute("href")).toBe("/api/v1/documents/4/download");
    fireEvent.click(screen.getByText("Löschen"));
    fireEvent.click(await screen.findByText("Abbrechen"));
    expect(posts().length).toBe(0);
    fireEvent.click(screen.getByText("Löschen"));
    fireEvent.change(await screen.findByRole("textbox"), { target: { value: "Doppelt hochgeladen" } });
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Löschen"));
    await waitFor(() => expect(changed).toHaveBeenCalled());
    expect(JSON.parse(String(posts()[0].init?.body))).toEqual({ reason: "Doppelt hochgeladen" });
    rerender(<DocRow d={{ ...doc, deleted_at: "2026-02-01", delete_reason: "Doppelt" }} onChanged={changed} />);
    expect(screen.getByText("Mietvertrag.pdf").closest("a")).toBeNull();
    expect(screen.queryByText("Löschen")).toBeNull();
  });
});
