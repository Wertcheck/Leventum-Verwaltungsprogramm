---
name: architecture-review
description: "Architekturprüfung für Leventum: Schichtung, Modulgrenzen, Abhängigkeiten, Datenfluss, Risiko einer Änderung bewerten und Entscheidungsvorlagen schreiben. Verwenden bei neuen Modulen, Schnittstellenänderungen, Datenmodell-/Sicherheits-/Release-Änderungen oder wenn eine Aufgabe mehrere Schichten berührt."
---

# Skill: architecture-review

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Bewerten, ob eine Änderung zur Architektur passt, welche Module/Daten sie berührt, welches Risiko sie trägt und ob eine Entscheidungsdokumentation nötig ist.

## 2. Einsatzbedingungen
- Vor jeder Änderung mit Querschnittswirkung (Backend+Frontend, Modell, Finanzlogik, Sicherheit).
- Vor Einführung neuer Abhängigkeiten, Endpunktgruppen oder Seiten.
- Beim Orchestrator-Review kritischer Änderungen.

## 3. Fachliche Grundlagen
- Schichten: `models/` → `services/` (Logik, kein Commit außer `auth`) → `api/` (Routen, Rechte, Commit) → Frontend (`frontend/src`). Daten: SQLite via SQLAlchemy 2, Alembic, Dokumentenspeicher `storage/`.
- Zentrale Definitionen: `services/leases.py` (`is_running`, `phase`), `services/integrity.py`, `domain.py`. Finanzkern: `charges, payments, deposits, utility, dunning, economics`.
- Bestehende Architektur- und Entscheidungsdokumente: `docs/01-architektur.md`, `02/06-datenmodell*.md`, `07-annahmen-und-rechtsfragen.md`, `docs/decisions/`.

## 4. Arbeitsanweisungen
1. Betroffene Module per `Grep`/`Read` ermitteln (nicht raten). 2. Prüfen, ob Funktionalität bereits existiert (wiederverwenden). 3. Risikoklasse bestimmen: niedrig (UI-Text), mittel (neue Endpunkte), hoch (Modell, Finanzen, Sicherheit, Release). 4. Schnittstellen/Datenverträge beschreiben (Felder, Fehlercodes, Rechte). 5. Alternativen und Folgen notieren; bei hoch → ADR `docs/decisions/NNNN-titel.md`. 6. Arbeitspakete mit Dateimengen und Reviews vorschlagen.

## 5. Verbindliche Regeln
- Keine parallele Neudefinition zentraler Begriffe.
- Hohe Risiken nur mit Entscheidungseintrag und Orchestrator-Freigabe.
- Keine Architektur-Behauptung ohne gelesene Stelle.

## 6. Typische Fehler
- Architektur aus Erinnerung statt aus Code beschreiben.
- Logik im Frontend duplizieren.
- Services committen lassen; Rechte an Routen vergessen.
- Schemaänderung ohne Migrationsplan.

## 7. Qualitätskriterien
Jede Aussage mit Dateipfad belegt; Risikoklasse und Pflichtreviews genannt; Alternativen und Folgen benannt.

## 8. Erforderliche Tests
Prüfplan nennen: welche vorhandenen Tests die Änderung absichern, welche fehlen (Details: `regression-testing`, `api-testing`).

## 9. Übergabekriterien
Entscheidungsvorlage/ADR (falls hoch), Arbeitspaketliste mit Dateimengen, Review-Liste, offene Fragen.

## 10. Grenzen und Eskalationsfälle
Eskalation an den Menschen: fachliche/rechtliche Unklarheit, Löschung von Daten, neue Abhängigkeiten mit Sicherheitsrelevanz, Abweichung von Invarianten.
