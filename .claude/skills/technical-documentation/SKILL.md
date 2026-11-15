---
name: technical-documentation
description: Technische Dokumentation: ADRs, API-Doku, Berichte, Betriebs-/Sicherheitsdoku. Verwenden bei Entscheidungen, API-Änderungen, Phasenabschluss.
---

# Skill: technical-documentation

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Dokumentation korrekt, nicht duplizierend und mit Statusstufen pflegen.

## 2. Einsatzbedingungen
- Nach Implementierung; bei Entscheidungen; Berichte.

## 3. Fachliche Grundlagen
Bestehend: `docs/01–09`, `03-api-module.md`, `04-sicherheit-backup.md`, Abschlussberichte, `docs/decisions/`, Agentensystem `docs/AGENT_*.md`. ADR-Format: Kontext, Entscheidung, Folgen, Alternativen, Status, Datum.

## 4. Arbeitsanweisungen
1. Vorhandenes Dokument erweitern statt neues anlegen. 2. Aussagen nur aus Code/Testausgabe/Übergabeformaten. 3. Pfade und Befehle prüfen (existieren sie?). 4. Statusstufen getrennt. 5. Selbstprüfung `python scripts/validate_agent_system.py` bei Änderungen an `.claude/`.

## 5. Verbindliche Regeln
- Keine Secrets, echten Personendaten, Lexono-Inhalte.
- Keine Aufwertung von Status.

## 6. Typische Fehler
Dokumentation beschreibt Gewünschtes als Ist; tote Verweise; doppelte Wahrheiten.

## 7. Qualitätskriterien
Jede Zahl/Behauptung belegbar; Verweise gültig.

## 8. Erforderliche Tests
Validierungsskript; Stichprobe der Befehle.

## 9. Übergabekriterien
Aktualisierte Dateien, offene Dokumentationslücken.

## 10. Grenzen und Eskalationsfälle
Eskalation: Dokumentation widerspricht Code → Besitzer/Orchestrator klären.
