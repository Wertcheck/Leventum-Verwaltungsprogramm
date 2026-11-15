# Leventum Agent Engineering System

Stand: erstellt, mit Selbstprüfung (`python scripts/validate_agent_system.py`) und einem Testlauf (siehe `AGENT_SYSTEM_IMPLEMENTATION_REPORT.md`). **Unabhängig geprüft: nichts. Freigegeben: nichts.** Herleitung und Abgrenzung zu Lexono: `AGENT_ARCHITECTURE_COMPARISON.md`. Ablauf und Vorlagen: `AGENT_WORKFLOWS.md`.

## Bausteine
| Baustein | Ort | Zweck |
|---|---|---|
| Projektregeln (immer geladen) | `CLAUDE.md` | 9 Grundsätze, Orchestrierung in Kurzform, Befehle |
| Regeln (modular) | `.claude/rules/00…60-*.md` | Domäne, Finanz-Invarianten, Daten/Migrationen, Sicherheit/Datenschutz, Git/Repos, Evidenz/Status, Zusammenarbeit |
| Agenten (Subagenten) | `.claude/agents/*.md` | 9 Rollen mit Frontmatter `name`, `description`, `tools` |
| Skills (Arbeitsanweisungen) | `.claude/skills/<name>/SKILL.md` | 20 Skills, je 10 Pflichtabschnitte |
| Schutz Lexono | `.claude/settings.json` | verweigert Schreibwerkzeuge auf das Lexono-Referenzverzeichnis (best effort, siehe unten) |
| Selbstprüfung | `scripts/validate_agent_system.py` | Struktur, Pflichtabschnitte, Verweise, Werkzeugzuordnung, Secret-Muster |
| Entscheidungen | `docs/decisions/NNNN-titel.md` | ADRs |

## Agenten und Werkzeuge
| Agent | Werkzeuge | Skills |
|---|---|---|
| `lead-architect` (Orchestrator, Hauptsitzung) | Read, Grep, Glob, Bash, Edit, Write, **Agent** | architecture-review, orchestration-workflow, technical-documentation |
| `backend-engineer` | Read, Grep, Glob, Bash, Edit, Write | backend-development, api-testing, data-integrity-review |
| `frontend-ui-engineer` | wie oben | frontend-development, ui-ux-review, e2e-testing |
| `domain-finance-engineer` | wie oben | financial-calculations, rental-contract-domain, operating-cost-accounting, data-integrity-review |
| `security-privacy-engineer` | Read, Grep, Glob, Bash (**ohne Schreibwerkzeuge**) | security-review, privacy-review, backup-restore, dependency-audit |
| `qa-test-engineer` | Read, Grep, Glob, Bash, Edit, Write (nur Testcode per Regel) | api-testing, e2e-testing, regression-testing, data-integrity-review |
| `database-architect` | Read, Grep, Glob, Bash, Edit, Write | database-migrations, data-integrity-review, backup-restore |
| `windows-release-engineer` | wie oben | windows-desktop-qa, release-management, dependency-audit |
| `documentation-engineer` | Read, Grep, Glob, Edit, Write | technical-documentation, architecture-review |
Mehrfachnutzung von Skills vermeidet Duplikate (z. B. `data-integrity-review` in 4 Rollen, `backup-restore` in 2).

## Orchestrierung
1. Die **Hauptsitzung** ist der Orchestrator. Claude-Code-Subagenten können keine weiteren Subagenten starten; deshalb liegt Delegation immer beim Orchestrator. Aufruf entweder durch normales Arbeiten gemäß `CLAUDE.md` oder – sofern die eingesetzte Claude-Code-Version es unterstützt (**nicht geprüft**) – mit dem Hauptagenten `lead-architect`.
2. Pakete mit **disjunkten Dateimengen**; Parallelität nur dann; zentrale Dateien nur eine Instanz zur Zeit.
3. Review-Matrix und „Autor ≠ Prüfer“ (`.claude/rules/60-collaboration.md`); Veto der Sicherheitsrolle; Eskalationsliste an den Menschen.
4. Übergabeformat mit 10 Feldern (Vorlage in `AGENT_WORKFLOWS.md`).

## Wichtige Einschränkungen (ehrlich)
- Neu angelegte `.claude/agents/*.md` werden von Claude Code **beim Sitzungsstart** geladen. In der Sitzung, in der sie erstellt wurden, waren sie nicht als Agententypen verfügbar; der Testlauf nutzte daher allgemeine Subagenten, die ihre Rollenprofile **gelesen und befolgt** haben (siehe Bericht). Der Start über die echten Agententypen (`subagent_type: "backend-engineer"` etc.) ist **nicht getestet**.
- `.claude/rules/` wird nach Claude-Code-Konvention geladen; die kritischsten Grundsätze stehen deshalb zusätzlich in `CLAUDE.md`.
- `.claude/settings.json` (Schreibschutz für Lexono) ist eine zusätzliche Schutzschicht; ihre Syntaxwirkung wurde in dieser Sitzung **nicht** durch einen Verbotsversuch geprüft (kein Schreibversuch auf Lexono gewollt). Hauptschutz ist die Regel selbst und der lesend angebundene Klon.
- Agentenprofile sind Anweisungen an ein Sprachmodell, keine durchsetzbaren Garantien; Prüfungen (Tests, Validierungsskript, Git-Diff) belegen das Verhalten.
- Parallelität wurde **nicht** praktisch erprobt; die Dateimengen-Regel ist ein Verfahren, kein technischer Lock.

## Erweiterung
Neuer Agent: Datei `.claude/agents/<name>.md` (Frontmatter + Pflichtabschnitte), Skills referenzieren, Tabelle oben und Review-Matrix ergänzen, `REQUIRED_AGENTS` im Skript erweitern, Skript ausführen. Neuer Skill: Verzeichnis + `SKILL.md` mit 10 Abschnitten, mindestens einem Agenten zuordnen. Regeländerungen nur bewusst und mit Eintrag in `docs/decisions/`.
