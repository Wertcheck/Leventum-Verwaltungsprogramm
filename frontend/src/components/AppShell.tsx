import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { Icons } from "./icons";
import { NAV, isGroup } from "../nav";
import type { User } from "../lib/api";

function Sidebar() {
  const loc = useLocation();
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const settings = NAV[NAV.length - 1];
  return (
    <aside className="sidebar" aria-label="Hauptnavigation">
      <div className="logo"><img src="/logo.svg" alt="Leventum Real Estate" /></div>
      {NAV.slice(0, -1).map((e) => {
        if (!isGroup(e)) {
          const I = Icons[e.icon];
          return <NavLink key={e.path} to={e.path} end className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}><I />{e.label}</NavLink>;
        }
        const active = e.children.some((c) => loc.pathname.startsWith(c.path));
        const isOpen = open[e.label] ?? active;
        const I = Icons[e.icon];
        return (
          <div key={e.label} className="nav-group-label">
            <button className="nav-item" aria-expanded={isOpen} onClick={() => setOpen({ ...open, [e.label]: !isOpen })}>
              <I />{e.label}<span className="chev">{isOpen ? <Icons.chevronDown size={18} /> : <Icons.chevronRight size={18} />}</span>
            </button>
            {isOpen && <div className="nav-sub">{e.children.map((c) => (
              <NavLink key={c.path} to={c.path} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>{c.label}</NavLink>
            ))}</div>}
          </div>
        );
      })}
      <div className="grow" />
      {!isGroup(settings) && <NavLink to={settings.path} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}><Icons.gear />{settings.label}</NavLink>}
    </aside>
  );
}

function Topbar({ user, onLogout }: { user: User; onLogout: () => void }) {
  const [menu, setMenu] = useState(false);
  return (
    <header className="topbar">
      {/* Globale Suche folgt ab Phase C (Daten vorhanden). Bewusst deaktiviert statt Fake-Funktion. */}
      <div className="search" title="Die globale Suche wird mit den Stammdaten (Phase C) aktiviert.">
        <Icons.search size={20} />
        <input disabled placeholder="Mieter, Objekt oder Vorgang suchen … (ab Phase C)" aria-label="Globale Suche" />
      </div>
      <button className="icon-btn" aria-label="Benachrichtigungen" title="Keine Benachrichtigungen"><Icons.bell size={26} /></button>
      <div className="user-menu" onClick={() => setMenu(!menu)} role="button" tabIndex={0} aria-haspopup="menu" aria-expanded={menu}>
        <div className="avatar">{user.display_name.slice(0, 1).toUpperCase()}</div>
        <span>{user.display_name}</span><Icons.chevronDown size={18} />
        {menu && <div className="menu" role="menu"><button role="menuitem" onClick={onLogout}>Abmelden</button></div>}
      </div>
    </header>
  );
}

export default function AppShell({ user, onLogout }: { user: User; onLogout: () => void }) {
  return (
    <div className="shell">
      <Sidebar />
      <div className="main">
        <Topbar user={user} onLogout={onLogout} />
        <main className="content"><Outlet /></main>
      </div>
    </div>
  );
}
