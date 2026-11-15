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
    { path: "/finanzen", label: "Sollstellungen & Zahlungen", icon: "euro" },
    { path: "/kautionen", label: "Kautionen", icon: "key" },
    { path: "/mahnwesen", label: "Mahnwesen", icon: "bell" },
    { path: "/bankimport", label: "Bankimport", icon: "file" },
    { path: "/rechnungen", label: "Rechnungen & Belege", icon: "receipt" },
    { path: "/betriebskosten", label: "Betriebskosten", icon: "calc" },
  ] },
  { label: "Betrieb", icon: "check", children: [
    { path: "/aufgaben", label: "Aufgaben", icon: "check" },
    { path: "/reparaturen", label: "Reparaturen", icon: "wrench" },
    { path: "/kommunikation", label: "Kommunikation", icon: "chat" },
    { path: "/dokumente", label: "Dokumente", icon: "folder" },
  ] },
  { label: "Auswertungen", icon: "chart", children: [
    { path: "/auswertungen/wirtschaftlichkeit", label: "Wirtschaftlichkeit", icon: "chart" },
    { path: "/auswertungen/leerstand", label: "Leerstand", icon: "door" },
  ] },
  { path: "/einstellungen", label: "Einstellungen", icon: "gear" },
];
