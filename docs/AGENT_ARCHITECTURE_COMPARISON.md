# Vergleichsanalyse: Lexono (Referenz) → Leventum Agent Engineering System

**Quellen und Zugriff.** Lexono wurde ausschließlich lesend betrachtet (flacher Klon, Commit `5735e5b`, ohne Registrierung der Lexono-`CLAUDE.md`/Skills in dieser Sitzung; Zugriff über `add_repo` mit `access: read`). Es wurde nichts in Lexono geändert (nach der Analyse: `git status` leer, HEAD unverändert). Es wurden keine Inhalte aus `.env*`, Mandanten-/Pilotunterlagen oder Fachlogik übernommen. Alle Aussagen unten beziehen sich auf tatsächlich gelesene Dateien: `CLAUDE.md`, `agents/*/AGENT.md` (13), `skills/*/SKILL.md` (14), `.agentic/*` (Auszüge), `agents/lead`, `agents/security`, `agents/qa`, `agents/release`, `agents/documentation`, `skills/security|testing|visual_qa`. **Nicht gelesen:** der Großteil von `ARCHITECTURE.md`, `PROJECT_STATE.md`, `OPEN_ISSUES.md`, `DECISIONS.md` (zusammen > 20.000 Zeilen), der App-Code, die Tests.

## 1. Was Lexono tatsächlich hat
| Element | Befund |
|---|---|
| Struktur | `agents/<rolle>/AGENT.md` (13 Rollen: lead, architecture, backend, frontend, ux, visual_qa, qa, security, release, documentation, chat, local_ai, ai_quality), `skills/<thema>/SKILL.md` (14), `.agentic/` (Arbeitsgedächtnis: PROJECT_STATE, DECISIONS, OPEN_ISSUES, AGENT_HANDOFFS, TEST_STATE, SESSION_LOG, TASK_MAP, VISUAL_QA, MODEL_EVALUATION) |
| Claude-Code-Integration | **Keine.** Es gibt kein `.claude/`-Verzeichnis; die Dateien haben kein Frontmatter und werden von Claude Code nicht als Subagenten/Skills geladen. Die Lead-Akte stellt ausdrücklich klar (Audit 01.09.): Die Dateien sind „rollenbasierte Kontext-/Checklisten-Dateien“, **kein** Multi-Agenten-Laufzeitsystem; „Agent B → Agent I“ im Handoff-Log bedeutet denselben ausführenden Strang. Einziger echter Delegationsmechanismus ist das `Agent`-Tool. |
| Projektregeln | `CLAUDE.md` (95 Zeilen): Rolle, iteratives Vorgehen (9 Schritte), nicht verhandelbare Grundregeln, „Evidence before Done“, „Keine Fake-Vollständigkeit“, Modelleskalation, Referenzdokumente |
| Orchestrierung | Lead akzeptiert keine Änderung ohne grüne Suite; Security-Agent hat **Vetorecht**; Architekturänderungen nur mit Eintrag in `DECISIONS.md`; kein `git push` ohne Nutzeranweisung |
| QA | Volle Suite nach jeder Änderung (ordnungsabhängige Fehler); Tests nie deaktivieren, um grün zu werden; dokumentierte Baseline (`TEST_STATE.md`); Benchmark-Korpus mit „kritisch blockiert Abschluss“; „Nicht-Gemessenes als NICHT VERIFIZIERT kennzeichnen“ |
| Skills | kurze Checklisten (≈25–70 Zeilen): Zweck, Checkliste/Vorgehen, typische Fehler, relevante Dateien; viele Skills sind Ein-Rollen-Skills (`skills/backend` ↔ `agents/backend`) |
| Release/Windows | `agents/release` enthält „harte Lektionen“ (PyInstaller/Inno Setup, WebView2-Bootstrapper, Installer-Hänger), `skills/visual_qa` beschreibt Fenster-Screenshots/Bedienung via PowerShell/P-Invoke auf echtem Windows |
| Dokumentation | genau **eine** kanonische `ARCHITECTURE.md`; `.agentic/` ergänzt, dupliziert nicht |

**Beobachtete Schwächen (aus den Dateigrößen und Inhalten ableitbar):** `.agentic/OPEN_ISSUES.md` ≈ 6.900, `DECISIONS.md` ≈ 5.500, `PROJECT_STATE.md` ≈ 5.500, `AGENT_HANDOFFS.md` ≈ 1.350 Zeilen – ungebremst wachsende Freitext-Logs (Lexono hat deshalb `SESSION_LOG.md` ausgelagert). Handoffs sind unstrukturierte Prosa. Skills ohne einheitliche Gliederung, Prüf-/Übergabekriterien und Eskalationsfälle. Rollenakten enthalten Zeitverlaufs-Berichte („Letzte Arbeit“, „Letzter Stand“), die veralten.

## 2. Direkt wiederverwendbare organisatorische Muster
| Muster | Übernahme in Leventum |
|---|---|
| Vetorecht der Sicherheitsrolle gegen Baseline-Verschlechterung | `security-privacy-engineer`: Veto, nur der Mensch kann es aufheben (`.claude/rules/60-collaboration.md`) |
| „Evidence before Done“ / keine Fake-Vollständigkeit / „NICHT VERIFIZIERT“ kennzeichnen | `.claude/rules/50-evidence-and-status.md` (mit den bereits im Leventum-Bericht verwendeten Statusstufen) |
| Volle Suite nach jeder relevanten Änderung; Tests nie abschalten, um grün zu werden | Regel + Skill `regression-testing` |
| Kein `git push` ohne Nutzeranweisung; keine großen Architekturänderungen ohne dokumentierte Entscheidung | `40-git-and-repos.md`, Decisions-Verzeichnis |
| Eine kanonische Architekturdokumentation, kein Duplikat | `docs/AGENT_SYSTEM.md` verweist, dupliziert nicht (bestehende `docs/01–09` bleiben Quelle) |
| Ehrliche Klarstellung, dass Rollenakten kein Laufzeitsystem sind, und Delegation nur über das `Agent`-Tool bei klar abgegrenzten, unabhängig prüfbaren Aufgaben | Übernommen und **zur Architektur gemacht**: Leventum-Agenten sind echte Claude-Code-Subagenten (siehe unten) |
| Unbekannte Fachentscheidung → stoppen, Optionen vorlegen | Regel „Eskalation“ |
| Bekannte harte Lektionen je Rolle festhalten (Release/Windows) | `windows-release-engineer` + Skills `windows-desktop-qa`, `release-management` (nur Leventum-eigene Lektionen, keine Lexono-Installer-Details als Tatsache) |

## 3. Anpassungsbedürftige Muster
| Lexono | Problem | Leventum-Lösung |
|---|---|---|
| Rollen- und Skill-Dateien ohne Claude-Code-Format | werden nicht automatisch geladen/delegierbar | `.claude/agents/*.md` mit Frontmatter (`name`, `description`, `tools`) und `.claude/skills/<name>/SKILL.md` (`name`, `description`) |
| Ein Agent ≙ ein Skill (1:1) | Duplikation, kein Mehrfachnutzen | Skills sind fachübergreifend; Agenten referenzieren Skills; gemeinsame Invarianten stehen **einmal** in `.claude/rules/` |
| Handoff als Freitext-Log | nicht prüfbar, wächst unbegrenzt | festes Übergabeformat (10 Felder), Ablage nur für Aufgaben, die mehrere Sitzungen betreffen; Entscheidungen als einzelne ADR-Dateien `docs/decisions/NNNN-titel.md` statt Riesendatei |
| Rollenakte mit Statusverlauf („Letzte Arbeit“) | veraltet | Agentenprofile enthalten **nur** zeitlose Verantwortung/Regeln; Zustand steht in Berichten/Git |
| Orchestrator „prüft Ergebnisse“ ohne Verfahren | unklar, wer wann gegenprüft | Review-Matrix + Dateibesitz-Regel + „Autor ≠ Prüfer“ |
| Veto pauschal | Blockade ohne Eskalationsweg | Veto + dokumentierter Eskalationsweg an den Menschen |
| Visual QA über PowerShell/P-Invoke auf echtem Windows | in Leventum bisher nur Chromium/Playwright möglich | Skill `e2e-testing` (Chromium, vorhanden) getrennt von `windows-desktop-qa` (nicht getestet, Testplan) |
| Modelleskalation (Sonnet Standard) | Modellname im Projekt fest | als generische Regel „Eskalation bei Risiko“, ohne Modellnamen festzuschreiben |

## 4. Nicht übertragbare Lexono-spezifische Fachlogik
Mandanten-/Aktenisolation, Pseudonymisierung/Privacy Gateway/Final Payload Gate, Anthropic-Key-Gateway, lokale KI/Ollama/Modellevaluation, Chat-Workspace, Dokument-Workspace-Highlighting, Rechtsquellen-/Fristenerkennung, Legal-Benchmark, spaCy/Presidio, Inno-Setup-/1,1-GB-Bundle-Details, Pilot-/Kanzlei-Unterlagen. Diese Rollen (`chat`, `local_ai`, `ai_quality`, `visual_qa` in der Lexono-Form) werden **nicht** angelegt. Auch Lexonos Testbaseline-Zahlen, Branch-/Datumsangaben und Entscheidungen sind für Leventum ohne Aussagekraft.

## 5. Sinnvolle neue Funktionen für Leventum (nicht in Lexono gefunden)
1. **Echte Claude-Code-Subagenten** mit eingeschränkten Werkzeugen je Rolle (Prüfer ohne Schreibrechte, wo möglich).
2. **Domänen-Rollen mit Pflichtreview für Geld und Verträge** (`domain-finance-engineer`): Sollstellungen, Zahlungen, Kautionen, Betriebskosten, Mahnwesen.
3. **Finanz-Invarianten als einzige Quelle** (`10-finance-invariants.md`) – jede Rolle verweist darauf.
4. **Review-Matrix** nach Änderungstyp (Finanzen, Migration, Sicherheit, Frontend, Windows).
5. **Datei-Besitz/Konfliktregeln für parallele Agenten** (Parallelisierung nur bei disjunkten Dateimengen; zentrale Dateien nur über den Orchestrator).
6. **Skill `data-integrity-review`** mit Bezug auf `services/integrity.py`, `space_key`, Unveränderlichkeit von Zahlungen.
7. **Ausführbare Selbstprüfung** `scripts/validate_agent_system.py` (Frontmatter, Pflichtabschnitte, Verweise, Skill-Zuordnung) – bei Lexono nicht gefunden.
8. **Eskalationsregeln für rechtliche Fragen**: keine rechtliche Bewertung, nur Dokumentation und Verweis (aus den Leventum-Annahmen).
9. **Statusstufen** inkl. „Unter Windows getestet“ als eigene Stufe.

## 6. Zielarchitektur (Leventum)
```
CLAUDE.md                      kurz: Kernregeln + Verweise (immer geladen)
.claude/
  agents/        9 Subagenten (Frontmatter: name, description, tools); lead-architect = Orchestrator-Rolle
  skills/        20 Skills (SKILL.md, je 10 Pflichtabschnitte)
  rules/         7 Regeldateien (Domäne, Finanzen, Daten, Sicherheit, Git, Evidenz, Zusammenarbeit)
  settings.json  Schutz gegen Schreibzugriff auf das Lexono-Referenzverzeichnis (best effort)
docs/AGENT_SYSTEM.md · AGENT_WORKFLOWS.md · AGENT_ARCHITECTURE_COMPARISON.md · AGENT_SYSTEM_IMPLEMENTATION_REPORT.md
scripts/validate_agent_system.py
```
**Wichtige technische Einschränkung (aus Lexonos Audit bestätigt und für Leventum übernommen):** Claude-Code-Subagenten können keine weiteren Subagenten starten. Der Orchestrator ist daher die **Hauptsitzung** (Rolle `lead-architect`, z. B. via `claude --agent lead-architect` oder durch Befolgen von `CLAUDE.md`), die Fachagenten über das `Agent`-Tool delegiert. Ob `--agent` in der konkret eingesetzten Claude-Code-Version verfügbar ist, wurde hier **nicht geprüft**.
