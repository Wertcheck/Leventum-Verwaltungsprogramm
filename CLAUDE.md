# CLAUDE.md – Leventum Property Management (Rent-to-Rent)

Lokale Windows-Desktop-Verwaltung (FastAPI · SQLAlchemy 2 · Alembic · SQLite · React/TypeScript/Vite · pywebview/WebView2) der Leventum Real Estate GmbH. Diese Datei wird zuerst gelesen. Ausführliche Regeln: `.claude/rules/` · Rollen: `.claude/agents/` · Arbeitsanweisungen: `.claude/skills/` · Überblick: `docs/AGENT_SYSTEM.md`, `docs/AGENT_WORKFLOWS.md`. Änderungen an dieser Datei und an `.claude/**` nur bewusst, begründet und über den Orchestrator.

## Unverzichtbare Grundsätze (gelten auch, wenn Regeldateien nicht geladen werden)
1. **Erst verstehen, dann ändern.** Bestehende Logik und Tests lesen. Nichts über Implementierungsstände behaupten, was nicht gelesen oder ausgeführt wurde.
2. **Keine Testbehauptung ohne Ausführung.** Statusstufen strikt trennen: Geplant · Implementiert · Automatisiert getestet · Manuell getestet · Unter Windows getestet · Unabhängig geprüft · Freigegeben (`.claude/rules/50-evidence-and-status.md`). Grüne Tests ≠ produktionsreif. **Windows/WebView2 ist bisher nicht getestet.**
3. **Finanzdaten sind unantastbar:** Sollstellungen nie überschreiben (nur Konflikt melden/Storno), Zahlungen nur per Gegenbuchung, Konditionen nur als neue Version, keine stille Rückwirkung, Kautionen getrennt von Mieten (`10-finance-invariants.md`).
4. **Keine rechtlichen Bewertungen, keine automatische Kommunikation:** kein Mahnversand, keine Gebühren/Zinsen, keine automatischen Nachforderungen, keine geschätzten Umlagewerte.
5. **Keine unkontrollierten Datenbankumbauten:** nur Alembic, Up/Down + Altdatentest; Dokumente nur weich löschen.
6. **Datenschutz und Sicherheit haben Vorrang:** lokal, keine ausgehenden Verbindungen, keine Secrets/echten Personendaten in Code, Tests, Logs, Berichten. Verschlüsselung ehrlich: nur Backups (optional); Datenbank/Dokumente unverschlüsselt.
7. **Repositories:** Nur Leventum wird verändert. **Lexono ist read-only Referenz** (nichts schreiben, nichts übernehmen außer Muster). Push/PR nur auf Auftrag, nur auf den vorgegebenen Entwicklungsbranch (`40-git-and-repos.md`).
8. **Kritische Änderungen** (Finanzlogik, Datenmodell, Sicherheit, Release) brauchen Review (Autor ≠ Prüfer), Tests und Orchestrator-Freigabe (`60-collaboration.md`). Agenten deklarieren eigene Arbeit nie als unabhängig geprüft.
9. **Unsicherheit dokumentieren, nicht still annehmen.** Fachliche/rechtliche Lücken → Entscheidungsvorlage an den Menschen.

## Orchestrierung (Kurzfassung)
Die Hauptsitzung ist der Orchestrator (`.claude/agents/lead-architect.md`): Aufgabe analysieren → Arbeitspakete mit **disjunkten Dateimengen** → passende Fachagenten per `Agent`-Tool (Subagenten starten keine weiteren Subagenten) → Ergebnisse im Übergabeformat einfordern → kritisch gegenprüfen → Review laut Matrix → zusammenführen und berichten. Zentrale Dateien (Modelle, Migrationen, Finanzservices, Sicherheit, `schemas.py`, `.claude/**`) ändert nur eine Instanz zur Zeit.

## Befehle
```bash
. .venv/bin/activate && (cd backend && python -m pytest -q)         # Backend (~2 min; im Hintergrund, Ausgabedatei vorher löschen)
(cd frontend && npm test && npm run build)                           # Frontend-Tests und Build
(cd frontend && NODE_PATH=$(npm root -g) npm run e2e)                # Browser-E2E (Chromium), startet eigenen Server
python scripts/validate_agent_system.py                              # Selbstprüfung der Agenten-/Skill-Struktur
scripts/ro_run.sh <befehl…>                                          # Read-only-Ausführung (Prüf-Agenten; Linux, root)
python scripts/check_file_set.py snapshot|check|overlap …            # Dateimengen-Kontrolle für delegierte Arbeit
```
Wichtige Dokumente: `docs/ABSCHLUSSBERICHT_MASTER_REVIEW.md` (Ist-Stand/Einschränkungen), `docs/04-sicherheit-backup.md`, `docs/WINDOWS_TESTPLAN.md`, `docs/07-annahmen-und-rechtsfragen.md`.
