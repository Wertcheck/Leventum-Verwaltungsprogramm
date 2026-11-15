import { render, screen } from "@testing-library/react";
import { KpiCard } from "./components/ui";

describe("KpiCard", () => {
  it("zeigt keine Zahl, wenn die Kennzahl nicht verfügbar ist", () => {
    render(<KpiCard icon={null} label="Immobilien" value={null} available={false} hint="ab Phase C" />);
    expect(screen.getByTestId("kpi-Immobilien").textContent).toBe("–");
  });
  it("zeigt den echten Wert, wenn verfügbar (auch 0)", () => {
    render(<KpiCard icon={null} label="Immobilien" value={0} available />);
    expect(screen.getByTestId("kpi-Immobilien").textContent).toBe("0");
  });
});
