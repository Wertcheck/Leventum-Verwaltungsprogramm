import { StrictMode, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./styles.css";
import { api, ApiError, type User } from "./lib/api";
import AppShell from "./components/AppShell";
import Auth from "./pages/Auth";
import Dashboard from "./pages/Dashboard";
import Placeholder from "./pages/Placeholder";
import Settings from "./pages/Settings";
import { OwnersPage, PartyDetail, TenantsPage } from "./pages/Parties";
import { PropertiesPage, PropertyDetail, UnitsPage } from "./pages/Properties";
import { LeaseDetail, LeasesPage } from "./pages/Leases";
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
          {LEAVES.map((l) => <Route key={l.path} path={l.path} element={<Placeholder title={l.label} phase={l.phase!} />} />)}
          <Route path="*" element={<Placeholder title="Seite nicht gefunden" phase="–" />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
