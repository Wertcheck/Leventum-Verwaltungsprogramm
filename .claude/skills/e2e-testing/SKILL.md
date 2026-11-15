---
name: e2e-testing
description: Browser-E2E mit Playwright/Chromium (`frontend/e2e/suite.cjs`): Abläufe, Selektoren, Server-Start, Fehlerdiagnose. Verwenden bei neuen Nutzerflüssen und Regressionen in der Oberfläche.
---

# Skill: e2e-testing

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Echte Nutzerabläufe automatisiert gegen den echten Server prüfen.

## 2. Einsatzbedingungen
- Neuer/geänderter UI-Fluss; vor Abnahme von Frontend-Änderungen.

## 3. Fachliche Grundlagen
Suite startet eigenen Server (temporäre DB, Port 8791), 21 Abläufe, Exit-Code 0/1; Hilfen `dlg()` (Eingabedialog `form.dialog`), `api()` (Setup per fetch). Läuft in **Chromium**, nicht in pywebview/WebView2. `responsive.cjs` misst Überlauf (4 Viewports).

## 4. Arbeitsanweisungen
1. Ablauf als `await test("NN …", async () => {…})` ergänzen; Setup per API, Prüfung über UI. 2. Selektoren stabil (`data-testid`, Rollen, Beschriftung). 3. Vor Lauf alte Ausgabedatei/Server beenden (`pkill -f leventum.desktop`), im Hintergrund starten, mit `until grep`-Schleife warten. 4. Bei Fehler Screenshot `/tmp/e2e-fail-N.png` **ansehen** (z. B. weiße Seite = React-Absturz). 5. Testnamen müssen zum tatsächlich Geprüften passen.

## 5. Verbindliche Regeln
- Keine Tests, die nur ‚irgendetwas wird angezeigt‘ prüfen, wenn der Name mehr verspricht.
- Nicht in Windows/WebView2 behaupten.

## 6. Typische Fehler
Veraltete Serverprozesse/Ausgabedateien; Locator trifft falschen Knoten; Zustand zwischen Abläufen unterschätzt; Warten auf Text, der schon vorher existierte.

## 7. Qualitätskriterien
Alle Abläufe grün **und** Namen ehrlich; keine JS-Konsolenfehler (Ablauf 21).

## 8. Erforderliche Tests
`cd frontend && npm run build && NODE_PATH=$(npm root -g) npm run e2e`.

## 9. Übergabekriterien
Ergebnis ‚n/n Abläufe‘, Liste fehlgeschlagener Abläufe mit Ursache.

## 10. Grenzen und Eskalationsfälle
Eskalation: UI-Fehler im Produktcode → Frontend Engineer; Windows-Verhalten → Windows & Release Engineer.
