import { Icons } from "./components/icons";

export interface NavLeaf { path: string; label: string; icon: keyof typeof Icons; phase?: string }
export interface NavGroup { label: string; icon: keyof typeof Icons; children: NavLeaf[] }
export type NavEntry = NavLeaf | NavGroup;
export const isGroup = (e: NavEntry): e is NavGroup => "children" in e;

// Die 16 Hauptbereiche laut Masterprompt; Phase = geplante Umsetzung (nicht umgesetzte Bereiche sind als solche gekennzeichnet).
export const NAV: NavEntry[] = [
  { path: "/", label: "Dashboard", icon: "home" },
  { label: "Stammdaten", icon: "users", children: [
    { path: "/mieter", label: "Mieter", icon: "user" },
    { path: "/eigentuemer", label: "Eigentümer & Vermieter", icon: "key" },
    { path: "/objekte", label: "Objekte", icon: "building" },
    { path: "/wohneinheiten", label: "Wohneinheiten", icon: "door" },
  ] },
  { label: "Verträge", icon: "contract", children: [
    { path: "/mietverhaeltnisse", label: "Mietverhältnisse", icon: "key" },
    { path: "/vertraege", label: "Verträge", icon: "file" },
  ] },
  { label: "Finanzen", icon: "euro", children: [
    { path: "/finanzen", label: "Finanzen", icon: "euro", phase: "D" },
    { path: "/betriebskosten", label: "Betriebskosten", icon: "calc", phase: "D" },
    { path: "/rechnungen", label: "Rechnungen & Belege", icon: "receipt", phase: "D" },
  ] },
  { label: "Betrieb", icon: "check", children: [
    { path: "/aufgaben", label: "Aufgaben", icon: "check", phase: "E" },
    { path: "/reparaturen", label: "Reparaturen", icon: "wrench", phase: "E" },
    { path: "/kommunikation", label: "Kommunikation", icon: "chat", phase: "E" },
    { path: "/dokumente", label: "Dokumente", icon: "folder", phase: "E" },
  ] },
  { path: "/auswertungen", label: "Auswertungen", icon: "chart", phase: "E" },
  { path: "/einstellungen", label: "Einstellungen", icon: "gear" },
];
