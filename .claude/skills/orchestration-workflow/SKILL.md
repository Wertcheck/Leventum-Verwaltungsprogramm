---
name: orchestration-workflow
description: Arbeitsablauf des Orchestrators: Aufgabenanalyse, Zerlegung in Pakete mit disjunkten Dateimengen, Delegation per Agent-Tool, Briefing, Gegenprüfung, Review-Matrix, Zusammenführung, Eskalation. Verwenden, sobald eine Aufgabe mehr als einen Fachbereich berührt oder Agenten delegiert werden.
---

# Skill: orchestration-workflow

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Mehrere Agenten kontrolliert, konfliktfrei und nachvollziehbar einsetzen.

## 2. Einsatzbedingungen
- Aufgabe berührt ≥ 2 Fachbereiche oder ist größer als ein eng verzahnter Eingriff.
- Eine Aufgabe soll durch einen unabhängigen Prüfer gegengeprüft werden.

## 3. Fachliche Grundlagen
- Subagenten (`.claude/agents/*.md`) haben eigenen Kontext, sehen die Unterhaltung nicht und können keine weiteren Subagenten starten. Alle Information muss im Briefing stehen.
- Dateibesitz und Review-Matrix: `.claude/rules/60-collaboration.md`. Übergabeformat: `docs/AGENT_WORKFLOWS.md`.

## 4. Arbeitsanweisungen
1. Aufgabe und Risiko klassifizieren (`architecture-review`). 2. Pakete bilden: Ziel, Besitzer, **Dateimenge**, Abnahme, Reviews. 3. Parallelisierbarkeit prüfen: disjunkte Dateien **und** keine Schnittstellenabhängigkeit, sonst sequenziell. 4. Pro Delegation Briefing schreiben: Ziel, Kontext/Ausgeschlossenes, Dateien, zu lesende Skills/Rules, Verbot von Änderungen außerhalb der Dateimenge, erwartetes Übergabeformat, Hinweis ‚nur lesend‘ bei Prüfern. 5. Ergebnisse gegen den Code/die Testausgabe stichprobenartig prüfen (Aussagen von Agenten sind Behauptungen, keine Belege). 6. Review laut Matrix beauftragen (Autor ≠ Prüfer). 7. Zusammenführen, Konflikte entscheiden, Gesamtstatus mit getrennten Statusstufen berichten. 8. Git-Status prüfen; committen/pushen nur auf Auftrag.

## 5. Verbindliche Regeln
- Nie zwei Agenten dieselbe Datei gleichzeitig ändern lassen.
- Zentrale Dateien nur eine Instanz zur Zeit.
- Keine Delegation von Aufgaben, deren Ergebnis nicht unabhängig prüfbar ist oder die engen Dateikontext brauchen.
- Hochrisiko → zusätzlich eigener Review und ADR.

## 6. Typische Fehler
- Briefings ohne Kontext (‚fix das‘).
- Agentenzusammenfassung ungeprüft übernehmen.
- Parallele Agenten mit versteckter Schnittstellenabhängigkeit.
- Prüfer mit Schreibrechten, die selbst korrigieren statt melden.

## 7. Qualitätskriterien
Jedes Paket hat Besitzer, Dateimenge, Abnahme und Review; Ergebnisse sind gegengeprüft; Status je Stufe ausgewiesen.

## 8. Erforderliche Tests
Beispielablauf: `docs/AGENT_WORKFLOWS.md` (Testlauf ‚KPI-Berechnung prüfen‘); Selbstprüfung `python scripts/validate_agent_system.py`.

## 9. Übergabekriterien
Paketliste, Briefings, Ergebnisse je Agent im Übergabeformat, Reviewergebnisse, Entscheidung, Gesamtbericht.

## 10. Grenzen und Eskalationsfälle
Rückfall auf Einzelarbeit, wenn Delegation mehr Risiko als Nutzen bringt. Eskalation an den Menschen laut `60-collaboration.md`.
