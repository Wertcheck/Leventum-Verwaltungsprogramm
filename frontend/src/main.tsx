import { StrictMode, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./styles.css";
import UtilityPage from "./pages/Utility";
import { DialogProvider } from "./components/Dialogs";
import { api, ApiError, type User } from "./lib/api";
import AppShell from "./components/AppShell";
import Auth from "./pages/Auth";
import Dashboard from "./pages/Dashboard";
import Placeholder from "./pages/Placeholder";
import Settings from "./pages/Settings";
import { OwnersPage, PartyDetail, TenantsPage } from "./pages/Parties";
import { PropertiesPage, PropertyDetail, UnitsPage } from "./pages/Properties";
import { LeaseDetail, LeasesPage } from "./pages/Leases";
import FinancePage from "./pages/Finance";
import DepositsPage from "./pages/Deposits";
import DunningPage from "./pages/Dunning";
import BankPage from "./pages/Bank";
import InvoicesPage from "./pages/Invoices";
import EconomicsPage from "./pages/Economics";
import VacancyPage from "./pages/Vacancy";
import TasksPage from "./pages/Tasks";
import { RepairDetail, RepairsPage } from "./pages/Repairs";
import CommunicationsPage from "./pages/Communications";
import DocumentsPage from "./pages/Documents";
import { NAV, isGroup, type NavLeaf } from "./nav";

type State = { kind: "loading" } | { kind: "setup" } | { kind: "login" } | { kind: "ready"; user: User } | { kind: "error"; msg: string };
const LEAVES: NavLeaf[] = NAV.flatMap((e) => (isGroup(e) ? e.children : [e])).filter((l) => l.phase);

function App() {
  const [s, setS] = useState<State>({ kind: "loading" });
  const boot = useCallback(async () => {
    try {
      const st = await api<{ setup_required: boolean }>("/auth/status");
      if (st.setup_required) return setS({ kind: "setup" });
      try { setS({ kind: "ready", user: await api<User>("/auth/me") }); }
      catch (e) { if (e instanceof ApiError && e.status === 401) setS({ kind: "login" }); else throw e; }
    } catch { setS({ kind: "error", msg: "Der Server ist nicht erreichbar." }); }
  }, []);
  useEffect(() => { boot(); }, [boot]);

  if (s.kind === "loading") return null;
  if (s.kind === "error") return <div className="auth-wrap"><div className="alert err">{s.msg}</div></div>;
  if (s.kind === "setup" || s.kind === "login") return <Auth setup={s.kind === "setup"} onDone={(user) => setS({ kind: "ready", user })} />;
  const logout = async () => { await api("/auth/logout", { method: "POST" }); setS({ kind: "login" }); };
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell user={s.user} onLogout={logout} />}>
          <Route path="/" element={<Dashboard user={s.user} />} />
          <Route path="/einstellungen" element={<Settings />} />
          <Route path="/mieter" element={<TenantsPage />} />
          <Route path="/eigentuemer" element={<OwnersPage />} />
          <Route path="/parteien/:id" element={<PartyDetail />} />
          <Route path="/objekte" element={<PropertiesPage />} />
          <Route path="/objekte/:id" element={<PropertyDetail />} />
          <Route path="/wohneinheiten" element={<UnitsPage />} />
          <Route path="/mietverhaeltnisse" element={<LeasesPage kind="sub" title="Mietverhältnisse" />} />
          <Route path="/vertraege" element={<LeasesPage title="Verträge" />} />
          <Route path="/vertraege/:id" element={<LeaseDetail />} />
          <Route path="/finanzen" element={<FinancePage />} />
          <Route path="/kautionen" element={<DepositsPage />} />
          <Route path="/mahnwesen" element={<DunningPage />} />
          <Route path="/bankimport" element={<BankPage />} />
          <Route path="/betriebskosten" element={<UtilityPage />} />
          <Route path="/rechnungen" element={<InvoicesPage />} />
          <Route path="/auswertungen/wirtschaftlichkeit" element={<EconomicsPage />} />
          <Route path="/auswertungen/leerstand" element={<VacancyPage />} />
          <Route path="/aufgaben" element={<TasksPage />} />
          <Route path="/reparaturen" element={<RepairsPage />} />
          <Route path="/reparaturen/:id" element={<RepairDetail />} />
          <Route path="/kommunikation" element={<CommunicationsPage />} />
          <Route path="/dokumente" element={<DocumentsPage />} />
          {LEAVES.map((l) => <Route key={l.path} path={l.path} element={<Placeholder title={l.label} phase={l.phase!} />} />)}
          <Route path="*" element={<Placeholder title="Seite nicht gefunden" phase="–" />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><DialogProvider><App /></DialogProvider></StrictMode>);
