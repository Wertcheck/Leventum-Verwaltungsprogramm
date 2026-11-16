---
name: api-testing
description: "API-Tests mit pytest/TestClient: Erfolgs-, Fehler-, Rechte- und Idempotenzfälle. Verwenden bei jedem neuen/geänderten Endpunkt."
---

# Skill: api-testing

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Verhalten der API belegbar absichern.

## 2. Einsatzbedingungen
- Neue/geänderte Routen oder Services.

## 3. Fachliche Grundlagen
Tests in `backend/tests/`, Fixtures in `conftest.py`/`helpers.py` (Testwelt, Benutzer, Helfer wie `ru_unit`). Hinweis: Testwelt legt Benutzer an – `/auth/setup` nicht erneut. `expire_all()` nach Raw-SQL; Beziehung statt FK-ID setzen.

## 4. Arbeitsanweisungen
1. Bestehendes Testmuster der Nachbardatei kopieren. 2. Fälle: Erfolg, Validierungsfehler (422), fehlendes Recht (403), nicht gefunden (404), Konflikt (409), Idempotenz. 3. Erwartungswerte von Hand/fachlich bestimmen. 4. Betroffene Datei isoliert, dann volle Suite (Hintergrund, Ausgabedatei vorher löschen).

## 5. Verbindliche Regeln
- Keine `or True`/aufgeweichten Asserts; keine deaktivierten Tests.
- Nur erfundene Testdaten.

## 6. Typische Fehler
Test prüft nur Statuscode, nicht Inhalt/Zustand; Erwartung aus Implementierung kopiert; Reihenfolgeabhängigkeit.

## 7. Qualitätskriterien
Jeder Test bricht, wenn die geschützte Invariante verletzt wird (gedanklich/real mutiert).

## 8. Erforderliche Tests
`cd backend && python -m pytest -q`; zuletzt dokumentiert: 272 bestanden (Stand Master-Review) – bei Berichten aktuellen Lauf angeben.

## 9. Übergabekriterien
Testliste, Ausgabe (Zahlen), nicht abgedeckte Fälle.

## 10. Grenzen und Eskalationsfälle
Eskalation: Test deckt Fehler im Produktivcode auf → Besitzer; fachliche Erwartung unklar → Domain & Finance.
