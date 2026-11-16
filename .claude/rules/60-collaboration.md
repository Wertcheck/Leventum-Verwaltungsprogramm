# Zusammenarbeit der Agenten

## Rollenmodell
Die **Hauptsitzung** ist der Orchestrator (`lead-architect`). Fachagenten sind Subagenten (`.claude/agents/`), starten keine weiteren Subagenten. Delegation nur für klar abgegrenzte, unabhängig prüfbare Aufgaben; eng verzahnte Änderungen im selben Dateikontext macht ein einzelner Agent.

## Dateibesitz und Parallelität
- Pro Arbeitspaket eine **explizite Dateimenge**. Zwei Agenten dürfen nie gleichzeitig dieselbe Datei ändern; parallel nur bei disjunkten Dateimengen **und** ohne Schnittstellenabhängigkeit.
- Zentrale Dateien nur über den Orchestrator: `models/*`, `alembic/versions/*`, `domain.py`, `services/{charges,payments,deposits,utility,dunning,economics}.py`, `security/*`, `api/schemas.py`, `main.py`, `CLAUDE.md`, `.claude/**`.
- Änderungen an Datenmodell/Finanzlogik/Sicherheit **nie ohne** Orchestrator-Freigabe; vorher ein Entscheidungseintrag (`docs/decisions/NNNN-titel.md`: Kontext, Entscheidung, Folgen, Alternativen, Status).

## Review-Matrix (Autor ≠ Prüfer)
| Änderung | Pflichtreview |
|---|---|
| Backend mit Auswirkung auf Finanzdaten | Domain & Finance Engineer + QA |
| Datenbankmigration | Database Architect + QA |
| Sicherheit/Datenschutz/Backup | Security & Privacy Engineer |
| Frontend | Frontend & UI/UX Engineer (anderer als Autor) + QA (Prüfung durch `independent-reviewer`) |
| Windows-Build/Desktop | Windows & Release Engineer |
| Kritisch (Finanzlogik, Datenmodell, Sicherheit, Release) | zusätzlich Orchestrator |
Prüfer arbeiten **nur lesend** (Befunde melden); Korrekturen führt der Autor/Besitzer aus. Technisch erzwungen (nicht nur angewiesen):
- `security-privacy-engineer`: Werkzeuge nur `Read, Grep, Glob` (kein Bash, kein Edit/Write); Testausgaben/Diffs bekommt er als Nachweisdateien vom Orchestrator.
- `independent-reviewer` (QA-/Fach-/DB-Prüfung): kein Edit/Write; Bash nur über `scripts/ro_run.sh` (Read-only-Mounts, unprivilegierter Benutzer, kein Netz), durchgesetzt per PreToolUse-Hook `.claude/hooks/ro_guard.py`. Der Hook wirkt nur in einem **vertrauten Workspace**; ohne Trust sind Bash-Aufrufe in diesem Profil gesperrt (fail closed), aber nicht über den Hook geprüft.
- Alle Nicht-Orchestratoren: `disallowedTools: Agent` (keine Verschachtelung). Skills stehen im Frontmatter (`skills:`) und werden vorgeladen.
- Dateimengen: Claude Code hat keine Schreibsperre; Einhaltung wird nachträglich mit `scripts/check_file_set.py` (snapshot/check/overlap) geprüft. Konflikte zwischen Agenten entscheidet der Orchestrator; bei fachlich/rechtlich offenen Fragen entscheidet der Mensch.

## Übergabeformat (jeder Agent, jedes Mal)
1. **Aufgabe** 2. **Ausgangslage** (gelesene Dateien, Stand) 3. **Geänderte Dateien** 4. **Technische Entscheidungen** 5. **Implementierungsstatus** (Statusstufe) 6. **Ausgeführte Tests** (Befehl) 7. **Testergebnisse** (Zahlen) 8. **Offene Fehler** 9. **Risiken** 10. **Nächste Schritte** (inkl. benötigter Reviews).
Vorlage: `docs/AGENT_WORKFLOWS.md`.

## Eskalation an den Menschen
Rechtliche/steuerliche Bewertung; neue fachliche Annahmen mit Geldwirkung; Löschen von Daten/Dokumenten; Schreiben ins Lexono-Repo; Push/PR; Aufheben eines Sicherheits-Vetos; Abschwächen einer Finanz-Invariante; Windows-Aussagen ohne Windows-Lauf.
