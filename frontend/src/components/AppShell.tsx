import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../lib/api";
import { Icons } from "./icons";
import { NAV, isGroup } from "../nav";
import type { User } from "../lib/api";

function Sidebar({ open: drawerOpen }: { open: boolean }) {
  const loc = useLocation();
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const settings = NAV[NAV.length - 1];
  return (
    <aside id="sidebar" className={`sidebar ${drawerOpen ? "open" : ""}`} aria-label="Hauptnavigation">
      <div className="logo"><img src="/logo.png" alt="Leventum Real Estate" /></div>
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

interface Hit { type: string; id: number; title: string; subtitle: string; path: string }
function GlobalSearch() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [open, setOpen] = useState(false);
  const run = (v: string) => {
    setQ(v);
    if (v.trim().length < 2) { setHits([]); return; }
    api<{ items: Hit[] }>(`/search?q=${encodeURIComponent(v.trim())}`).then((r) => { setHits(r.items); setOpen(true); }).catch(() => setHits([]));
  };
  return (
    <div className="search-wrap">
      <div className="search"><Icons.search size={20} />
        <input value={q} onChange={(e) => run(e.target.value)} onFocus={() => setOpen(true)} placeholder="Mieter, Objekt oder Vorgang suchen …" aria-label="Globale Suche" />
      </div>
      {open && q.trim().length >= 2 && (
        <div className="search-results">
          {hits.length === 0 && <div className="empty">Keine Treffer</div>}
          {hits.map((h) => <Link key={`${h.type}${h.id}`} to={h.path} onClick={() => { setOpen(false); setQ(""); setHits([]); }}><strong>{h.title}</strong><div className="muted">{h.subtitle}</div></Link>)}
        </div>
      )}
    </div>
  );
}

function Topbar({ user, onLogout, navOpen, onToggleNav }: { user: User; onLogout: () => void; navOpen: boolean; onToggleNav: () => void }) {
  const [menu, setMenu] = useState(false);
  return (
    <header className="topbar">
      <button type="button" className="icon-btn nav-toggle" id="nav-toggle" aria-label="Navigation" aria-controls="sidebar" aria-expanded={navOpen} onClick={onToggleNav}><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" /></svg></button>
      <GlobalSearch />
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
  // Fester Rahmen: Seitenleiste und Kopfzeile bleiben stehen, nur der Inhaltsbereich scrollt; bei schmalen Fenstern ist die Navigation ein Drawer.
  const [navOpen, setNavOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => { setNavOpen(false); }, [loc.pathname]);
  useEffect(() => {
    if (!navOpen) return;
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") { setNavOpen(false); document.getElementById("nav-toggle")?.focus(); } };
    document.addEventListener("keydown", k);
    document.querySelector<HTMLElement>("#sidebar .nav-item")?.focus();
    return () => document.removeEventListener("keydown", k);
  }, [navOpen]);
  return (
    <div className="shell">
      <Sidebar open={navOpen} />
      {navOpen && <div className="nav-scrim" onClick={() => setNavOpen(false)} aria-hidden="true" />}
      <div className="main">
        <Topbar user={user} onLogout={onLogout} navOpen={navOpen} onToggleNav={() => setNavOpen((o) => !o)} />
        <main className="content"><Outlet /></main>
      </div>
    </div>
  );
}
