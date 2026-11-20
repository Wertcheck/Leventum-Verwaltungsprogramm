import { useEffect, useRef, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Modal } from "./Modal";
import { EmbeddedCtx } from "./ui";
import { PropertiesPage, UnitsPage } from "../pages/Properties";
import { LeasesPage } from "../pages/Leases";
import { TenantsPage } from "../pages/Parties";
import FinancePage from "../pages/Finance";
import UtilityPage from "../pages/Utility";
import TasksPage from "../pages/Tasks";
import { RepairsPage } from "../pages/Repairs";
import VacancyPage from "../pages/Vacancy";
import EconomicsPage from "../pages/Economics";

/**
 * Zuordnung Dashboard-Element → Detailansicht im Popup. Die Inhalte sind die vorhandenen Seiten (gleiche Daten, gleiche API, gleiche Geschäftslogik –
 * nichts wird dupliziert); die Seitenüberschrift entfällt, der Titel steht im Popup-Kopf. Ein Wechsel auf eine andere Seite (z. B. Klick auf eine
 * Tabellenzeile) schließt das Popup.
 */
export interface DetailDef { title: string; description: string; path: string; render: () => ReactNode }

const forderungen: DetailDef = { title: "Forderungsübersicht", description: "Sollstellungen und Zahlungen – Soll und Ist getrennt", path: "/finanzen", render: () => <FinancePage /> };
const sollstellungen: DetailDef = { title: "Sollstellungen und Zahlungen", description: "Forderungen, Verbindlichkeiten und Zahlungen", path: "/finanzen", render: () => <FinancePage /> };
const vertraege: DetailDef = { title: "Verträge und Vertragsenden", description: "Haupt- und Untermietverträge", path: "/vertraege", render: () => <LeasesPage title="Verträge" /> };
const aufgaben: DetailDef = { title: "Aufgabenverwaltung", description: "Aufgaben und Fristen", path: "/aufgaben", render: () => <TasksPage /> };
const mieter: DetailDef = { title: "Mieterübersicht", description: "Mieter mit Mietverhältnis und Zahlungsstatus", path: "/mieter", render: () => <TenantsPage /> };
const belegung: DetailDef = { title: "Belegungsübersicht", description: "Auslastung und Leerstand je Objekt", path: "/auswertungen/leerstand", render: () => <VacancyPage /> };

export const DETAILS: Record<string, DetailDef> = {
  properties: { title: "Immobilienübersicht", description: "Alle Objekte mit Wohneinheiten und Eigentümern", path: "/objekte", render: () => <PropertiesPage /> },
  units: { title: "Einheitenübersicht", description: "Alle Wohneinheiten mit Belegung", path: "/wohneinheiten", render: () => <UnitsPage /> },
  active_main_leases: { title: "Hauptmietverträge", description: "Hauptmietverträge (Vermieter → Leventum)", path: "/vertraege", render: () => <LeasesPage kind="main" title="Hauptmietverträge" /> },
  active_subleases: { title: "Untermietverträge", description: "Untermietverhältnisse (Leventum → Mieter)", path: "/mietverhaeltnisse", render: () => <LeasesPage kind="sub" title="Untermietverträge" /> },
  active_tenants: mieter, tenants: mieter,
  main_rent_obligations: sollstellungen, sublease_receivables: sollstellungen,
  open_receivables: forderungen, overdue_receivables: forderungen, overdue_payments: forderungen,
  upcoming_contract_ends: vertraege, upcoming_main_lease_ends: vertraege, upcoming_sublease_ends: vertraege,
  monthly_utility_costs: { title: "Betriebskosten", description: "Betriebskostenabrechnungen", path: "/betriebskosten", render: () => <UtilityPage /> },
  open_tasks: aufgaben, overdue_tasks: aufgaben, tasks: aufgaben,
  open_repairs: { title: "Reparaturübersicht", description: "Reparaturen und Instandhaltung", path: "/reparaturen", render: () => <RepairsPage /> },
  physical_vacancy: belegung, occupancy_rate: belegung, economic_vacancy_cost: belegung,
  economics: { title: "Wirtschaftlichkeitsauswertung", description: "Soll und Ist getrennt, Deckungsbeitrag vorläufig", path: "/auswertungen/wirtschaftlichkeit", render: () => <EconomicsPage /> },
};

export function DetailPopup({ detail, onClose }: { detail: string; onClose: () => void }) {
  const def = DETAILS[detail];
  const loc = useLocation(), nav = useNavigate();
  const start = useRef(loc.key);
  useEffect(() => { if (loc.key !== start.current) onClose(); }, [loc.key, onClose]);
  if (!def) return null;
  return (
    <Modal title={def.title} description={def.description} size="xl" dismissible onClose={onClose}
      footer={<button type="button" className="btn" onClick={() => { onClose(); nav(def.path); }}>Vollständige Seite öffnen</button>}>
      <EmbeddedCtx.Provider value={true}>{def.render()}</EmbeddedCtx.Provider>
    </Modal>
  );
}
