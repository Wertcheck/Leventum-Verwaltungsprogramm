# Agenten-Workflows und Vorlagen

## 1. Standardablauf (Orchestrator)
1. **Analyse** – Aufgabe, betroffene Module, Risikoklasse (niedrig/mittel/hoch), vorhandene Tests/Doku lesen (`architecture-review`).
2. **Zerlegung** – Arbeitspakete: Ziel · Besitzer-Agent · **Dateimenge** · Abnahme · Pflichtreviews.
3. **Parallelisierbarkeit** – nur disjunkte Dateimengen ohne Schnittstellenabhängigkeit; Schnittstellen vorher festlegen.
4. **Delegation** – Briefing nach Vorlage 2; Prüfer nur lesend.
5. **Gegenprüfung** – Behauptungen der Agenten gegen Code/Testausgabe stichprobenartig prüfen.
6. **Review** laut Matrix (Autor ≠ Prüfer); Hochrisiko zusätzlich Orchestrator-Review + ADR.
7. **Zusammenführung** – Konflikte entscheiden; Gesamtbericht mit getrennten Statusstufen; Git-Status prüfen; Commit/Push nur auf Auftrag.

## 2. Briefing-Vorlage (Orchestrator → Agent)
```
Rolle: <agent-name> (lies .claude/agents/<agent-name>.md, CLAUDE.md, .claude/rules/*, die dort genannten Skills)
Ziel: <ein Satz>
Kontext/bereits ausgeschlossen: <…>
Dateimenge (nur diese darfst du ändern): <Pfade>  |  Prüfauftrag: NUR LESEN
Abnahme: <Kriterien>
Verboten: Änderungen außerhalb der Dateimenge; Commit/Push; Lexono schreiben; erfundene Ergebnisse
Antwortformat: 10-Punkte-Übergabe (unten)
```

## 3. Übergabeformat (Agent → Orchestrator)
```
1. Aufgabe
2. Ausgangslage (gelesene Dateien, Stand)
3. Geänderte Dateien (oder „keine – Prüfauftrag“)
4. Technische Entscheidungen
5. Implementierungsstatus (Statusstufe laut 50-evidence-and-status.md)
6. Ausgeführte Tests (Befehle)
7. Testergebnisse (Zahlen; „nicht ausgeführt“ explizit)
8. Offene Fehler
9. Risiken
10. Nächste Schritte (inkl. benötigter Reviews, Eskalationen)
```

## 4. Review-Matrix
Siehe `.claude/rules/60-collaboration.md`. Zusammenfassung: Finanzwirkung → Domain & Finance + QA · Migration → Database Architect + QA · Sicherheit → Security & Privacy · Frontend → Frontend (zweiter Durchgang) + QA · Windows-Build → Windows & Release · kritisch → zusätzlich Orchestrator.

## 5. ADR-Vorlage (`docs/decisions/NNNN-titel.md`)
`Status · Datum · Kontext · Entscheidung · Folgen · Alternativen · Betroffene Dateien · Pflichtreviews · Nachweise`

## 6. Beispiel-Workflows
**A. Neue Finanzfunktion (z. B. weiterer Zahlungsrhythmus):** Orchestrator (ADR, Dateimenge: `services/charges.py`, `api/schemas.py`, Tests) → Domain & Finance (Handrechnung, Annahmen) → Backend (Implementierung) → QA (Tests, volle Suite) → Frontend (Maske) → QA (E2E) → Documentation. Sequenziell wegen gemeinsamer Schnittstelle.
**B. Migration:** Database Architect (Entwurf + Altdatentest) → QA (Up/Down/Altdaten, volle Suite) → Orchestrator-Review.
**C. Sicherheitsänderung:** Backend (Umsetzung) → Security & Privacy (Review, Veto möglich) → QA (Beweistests).
**D. Windows-Release:** Windows & Release (Testplan W1–W9 auf echtem Windows) → Documentation (Bericht); ohne Windows-Rechner: Status „nicht getestet“.
**E. Kennzahlenprüfung (Testlauf, nur lesend):** siehe Bericht – Backend + Domain & Finance parallel (disjunkt, nur lesend), QA danach (abhängig von deren Befunden), Orchestrator führt zusammen.
