import { cleanup, fireEvent, render as rtlRender, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";
import { DialogProvider, useDialogs } from "./components/Dialogs";
import { TenantsPage } from "./pages/Parties";

const render = (ui: ReactElement) => rtlRender(ui, { wrapper: DialogProvider });
let calls: string[] = [];
function mockApi(h: (url: string) => unknown) {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => { calls.push(url); return { ok: true, status: 200, json: async () => h(url) } as Response; }));
}
beforeEach(() => vi.restoreAllMocks());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const row = (o = {}) => ({ party_id: 7, name: "Max Muster", lease_id: 3, lease_status: "notice", spaces: ["Haus A · WE 1 · Bett 1"], start_date: "2026-01-01", end_date: "2026-12-31", monthly_total: { available: true, total: "420.00" }, payment_status: "arrears", overdue_amount: "420.00", ...o });
const overview = { party: { id: 7, display_name: "Max Muster", email: "m@example.org", phone: null, city: "Berlin" },
  leases: [{ id: 3, kind: "sub", role: "lessee", type: "Untermietvertrag", phase: "notice", start_date: "2026-01-01", end_date: "2026-12-31", spaces: ["Haus A · WE 1 · Bett 1"], monthly: { available: true, total: "420.00" }, payment_rhythm: "monthly", payment_status: "arrears", overdue_amount: "420.00", deposit: { agreed_amount: "840.00", paid: "840.00", open: "0.00", held: "840.00", status: "paid" } }],
  finance: { open_total: "420.00", overdue_total: "420.00", monthly_soll_total: "420.00", open_items: [{ charge_id: 1, charge_type: "base_rent", period_start: "2026-03-01", due_date: "2026-03-03", amount: "420.00", open_amount: "420.00", overdue: true }], recent_payments: [] },
  documents: [], tasks: [], repairs: [], activity: [{ at: "2026-03-01", summary: "Vertrag gekündigt", actor: "admin", source: "audit" }] };

describe("Mieterliste mit Detailpanel", () => {
  it("zeigt Phase (gekündigt, läuft noch), lädt Panel erst nach Klick mit einer gebündelten Abfrage", async () => {
    mockApi((u) => (u.includes("/overview") ? overview : { items: [row()], total: 1, limit: 200, offset: 0 }));
    render(<MemoryRouter><TenantsPage /></MemoryRouter>);
    await screen.findByText("Max Muster");
    expect(screen.getAllByText("Gekündigt – läuft noch").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("tenant-panel")).toBeNull();
    expect(calls.some((c) => c.includes("/overview"))).toBe(false);
    fireEvent.click(screen.getByText("Max Muster"));
    const panel = await screen.findByTestId("tenant-panel");
    await within(panel).findByText("Offene Posten");
    expect(calls.filter((c) => c.includes("/overview")).length).toBe(1);
    expect(within(panel).getByText(/Kaution \(außerhalb der Mietforderungen\)/)).toBeTruthy();
    fireEvent.click(within(panel).getByLabelText("Detailpanel schließen"));
    expect(screen.queryByTestId("tenant-panel")).toBeNull();
  });
});

function Probe({ onResult }: { onResult: (v: unknown) => void }) {
  const d = useDialogs();
  return <>
    <button onClick={async () => onResult(await d.ask("Name?"))}>ask</button>
    <button onClick={async () => onResult(await d.confirmBox("Sicher?"))}>conf</button>
  </>;
}
describe("Dialoge", () => {
  it("Pflichteingabe verhindert leere Antworten; Abbrechen liefert null/false; Bestätigen true", async () => {
    const res = vi.fn();
    render(<Probe onResult={res} />);
    fireEvent.click(screen.getByText("ask"));
    const dlg = await screen.findByRole("dialog");
    fireEvent.click(within(dlg).getByText("OK"));
    expect(await within(dlg).findByRole("alert")).toBeTruthy();
    expect(res).not.toHaveBeenCalled();
    fireEvent.click(within(dlg).getByText("Abbrechen"));
    await waitFor(() => expect(res).toHaveBeenCalledWith(null));
    fireEvent.click(screen.getByText("conf"));
    fireEvent.click(await screen.findByText("Bestätigen"));
    await waitFor(() => expect(res).toHaveBeenLastCalledWith(true));
  });
});
