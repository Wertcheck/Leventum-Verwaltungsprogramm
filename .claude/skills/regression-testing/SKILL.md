---
name: regression-testing
description: Regressionsabsicherung: volle Suiten, Baseline, Testisolation, Vorher/Nachher-Vergleich. Verwenden nach jeder relevanten Änderung und vor Abschluss.
---

# Skill: regression-testing

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Sicherstellen, dass Änderungen bestehendes Verhalten nicht verschlechtern.

## 2. Einsatzbedingungen
- Nach Implementierung; vor Commit; vor Release.

## 3. Fachliche Grundlagen
Baseline zuletzt (Stand Master-Review, Linux): Backend 272 bestanden; vitest 19; E2E-Suite 21/21; phase-c/d/e-Skripte grün. Zahlen immer mit aktuellem Lauf bestätigen.

## 4. Arbeitsanweisungen
1. Betroffene Tests isoliert. 2. Volle Backend-Suite (Hintergrund; Ausgabedatei vorher löschen). 3. `npm test`, `npm run build`. 4. E2E-Suite bei UI-/Flussänderung. 5. Abweichung von der Baseline analysieren, nicht wegdiskutieren. 6. Ergebnis mit Zahlen berichten.

## 5. Verbindliche Regeln
- Tests nie deaktivieren/abschwächen, um grün zu werden.
- Nicht gelaufen = nicht getestet.

## 6. Typische Fehler
Nur geänderte Datei testen; Teilergebnis als Gesamtergebnis berichten; veralteter Output.

## 7. Qualitätskriterien
Keine neuen Fehler; keine neu übersprungenen Tests; Zahlen nachvollziehbar.

## 8. Erforderliche Tests
Siehe Befehle in `CLAUDE.md`.

## 9. Übergabekriterien
Tabelle Suite → Ergebnis → Datum/Stand.

## 10. Grenzen und Eskalationsfälle
Eskalation: unerklärliche Flakiness, Zeitüberschreitungen, ordnungsabhängige Fehler.
