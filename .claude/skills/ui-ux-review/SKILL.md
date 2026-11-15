---
name: ui-ux-review
description: UX-/UI-Review gegen Leventum-Standards: Responsivität, Klarheit der Zahlen, Dialoge, Zustände, Accessibility. Verwenden als unabhängiger Review frontendseitiger Änderungen.
---

# Skill: ui-ux-review

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Oberflächen auf Bedienbarkeit, Konsistenz und Fachverständlichkeit prüfen (nur melden, nicht selbst ändern).

## 2. Einsatzbedingungen
- Nach Frontend-Änderungen vor Abnahme; bei Screenshot-Befunden.

## 3. Fachliche Grundlagen
Referenz: `docs/UI_PRUEFBERICHT_SCREENSHOTS.md`, Dashboard-Referenzbild, Viewports 1536×1024, 1366×768, 1280×800, 1024×768; Tooltips/Definitionen der KPIs (`DEFINITIONS` in `services/dashboard.py`).

## 4. Arbeitsanweisungen
1. App starten (`python -m leventum.desktop --browser`), Demodaten via `seed-and-shoot.cjs`. 2. Je Viewport Screenshots ansehen (nicht nur Messwerte). 3. Prüfen: Beträge ohne Umbruch, Statusbegriffe konsistent (Phasen), Leer-/Fehler-/Ladezustände, Fokus/Tastatur in Dialogen, Beschriftungen, Zahl-/Datumsformat, keine toten Buttons. 4. Befunde mit Screenshot-Beleg, Schweregrad und Vorschlag melden.

## 5. Verbindliche Regeln
- Prüfer ändert nichts; Befunde belegt (Screenshot/Selektor).
- Fachliche Begriffe nur wie in Domain-Regeln.

## 6. Typische Fehler
Nur Messung ohne Ansehen; Prüfung nur im größten Viewport; Annahme, dass Demodaten die Randfälle abdecken.

## 7. Qualitätskriterien
Jeder Befund reproduzierbar und mit Beleg; Positives nicht als ‚geprüft‘ verallgemeinert.

## 8. Erforderliche Tests
Bestätigung per `responsive.cjs` und E2E-Suite nach Behebung.

## 9. Übergabekriterien
Befundliste (Schweregrad, Beleg, betroffene Datei) im Übergabeformat.

## 10. Grenzen und Eskalationsfälle
Accessibility-Zertifizierung ist nicht Teil des Skills; Screenreader-Tests nicht abgedeckt. Eskalation bei Designsystem-Entscheidungen.
