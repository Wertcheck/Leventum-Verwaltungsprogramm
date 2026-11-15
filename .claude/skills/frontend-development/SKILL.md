---
name: frontend-development
description: Frontend-Entwicklung in Leventum (React 18, TypeScript, Vite, eigene CSS-Tokens, vitest). Verwenden für Seiten, Komponenten, Formulare, Tabellen, Dialoge.
---

# Skill: frontend-development

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Frontend-Änderungen konsistent, robust und ohne duplizierte Fachlogik umsetzen.

## 2. Einsatzbedingungen
- Neue/geänderte Seiten oder Komponenten unter `frontend/src`.
- Anbindung neuer Endpunkte.

## 3. Fachliche Grundlagen
- Struktur: `pages/`, `components/` (`Dialogs`, `EditDialog`, `TenantPanel`, `Form`, `ui`), `lib/api.ts` (fetch mit `X-Leventum-Client`), `lib/hooks.ts` (`useFetch`, `eur`, `dateDe`), `nav.ts`, `main.tsx` (Routen).
- Dialoge ausschließlich über `useDialogs()` (ask/confirmBox/notify); Test `noNativeDialogs.test.ts` verbietet native Dialoge.

## 4. Arbeitsanweisungen
1. Vorhandene Komponente wiederverwenden. 2. API-Typen lokal definieren, Backend-Felder nicht umbenennen. 3. Hooks vor jedem frühen `return`. 4. Fehler-/Lade-/Leerzustände behandeln. 5. Formatierung über `eur`/`dateDe`. 6. vitest-Test mit gemocktem `fetch` ergänzen; E2E-Ablauf in `frontend/e2e/suite.cjs`, wenn Nutzerfluss neu. 7. `npm run build`, `npm test`.

## 5. Verbindliche Regeln
- Keine Finanzberechnung im Frontend; Beträge als Strings vom Backend.
- Keine Bedienelemente ohne Funktion; destruktive Aktionen mit Bestätigung/Begründung.
- Keine externen Ressourcen/CDNs; keine nativen Browser-Dialoge.

## 6. Typische Fehler
- Hook nach frühem Return (weiße Seite).
- Überlauf bei schmalen Fenstern (Tabellen/KPI).
- Erfolgsmeldung vor erfolgreicher API-Antwort.
- Fehlermeldung wird durch nachfolgende Meldung überschrieben.

## 7. Qualitätskriterien
Build ohne Fehler; keine Konsolenfehler; 4 Viewports ohne Überlauf; Texte deutsch, EUR/Datum einheitlich.

## 8. Erforderliche Tests
`cd frontend && npm test && npm run build`; E2E `npm run e2e` bei Flussänderungen; `e2e/responsive.cjs` bei Layoutänderungen (Demodaten per `seed-and-shoot.cjs`).

## 9. Übergabekriterien
Übergabeformat; Screenshots/Messwerte bei UI-Änderungen; Pflichtreview Frontend (anderer Durchgang) + QA.

## 10. Grenzen und Eskalationsfälle
Eskalation bei Fachdefinitionen, die die UI ändern würde (Domain & Finance), und bei Designsystem-Grundsatzänderungen.
