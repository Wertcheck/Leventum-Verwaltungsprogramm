# Phase: Validierung der echten Agententypen

Stand 2026-11-15 (Start-Commit `ee00e7c`). Statusstufen: Geplant · Erstellt · Automatisiert getestet · Unabhängig geprüft. **Freigegeben: nichts.** Alle „Belege“ unten sind **Selbstauskünfte der Subagenten** (Antworten auf eine Sonde) oder von mir beobachtete Werkzeugaufrufe; ein unabhängiger Blick in die Laufzeitkonfiguration von Claude Code war nicht möglich.

## 1. Tatsächlich geladene Agenten (Prüfpunkte 1–3)
Nach dem Sitzungsneustart standen alle 9 Typen in der Agentenliste der Sitzung (`backend-engineer, database-architect, documentation-engineer, domain-finance-engineer, frontend-ui-engineer, lead-architect, qa-test-engineer, security-privacy-engineer, windows-release-engineer`) und alle 20 Skills in der Skill-Liste. Jeder Typ wurde **einzeln** per `subagent_type` mit einer Sonde aufgerufen (9 Aufrufe, alle erfolgreich).
| Prüfpunkt | Ergebnis (Beleg: Sondenantworten) |
|---|---|
| 1. Alle 9 Typen erkannt | **Ja** |
| 2. Einzeln aufrufbar | **Ja** (9/9 haben geantwortet, Rolle korrekt benannt) |
| 3a. Rollenprofil geladen | **Ja** – jeder Agent nannte Überschriften seines Profils |
| 3b. `CLAUDE.md` und alle 7 Regeln im Kontext | **Ja** – jeder Agent nannte je Datei einen Satzanfang |
| 3c. **Skills geladen** | **Nein, nicht automatisch.** Kein Subagent hat ein Skill-Werkzeug; die Profile nennen nur Pfade, die der Agent per `Read` selbst lesen muss. Die Skills wirken also nur, weil das Briefing „lies zuerst deine Skills“ verlangt hat. Ein Frontmatter-Feld zum Vorladen (`skills:`) wurde **nicht** eingesetzt/geprüft. |
| Zusatzbefund | In **allen** Agentenkontexten war auch die `CLAUDE.md` von **Lexono** sichtbar (die Lexono-Regeln stehen damit neben denen von Leventum). Ursache vermutlich das Arbeitsverzeichnis/der angebundene Klon unter `/home/user`; nicht abschließend geklärt. Mitigation offen: Lexono-Klon aus dem Sitzungsbereich entfernen oder Sitzung im Leventum-Verzeichnis starten. |

## 2. Werkzeugberechtigungen (Prüfpunkte 4–6)
| Agent | Gemeldete Werkzeuge | Agent-/Delegationswerkzeug |
|---|---|---|
| lead-architect | Read, Grep, Glob, Bash, Edit, Write, SubagentHandback | **nein** |
| backend-engineer, frontend-ui-engineer, domain-finance-engineer, qa-test-engineer, database-architect, windows-release-engineer | Read, Grep, Glob, Bash, Edit, Write, SubagentHandback | nein |
| documentation-engineer | Read, Grep, Glob, Edit, Write, SubagentHandback (kein Bash) | nein |
| security-privacy-engineer | **Read, Grep, Glob, Bash, SubagentHandback** (kein Edit/Write) | nein |
* **Prüfpunkt 4 (Werkzeuge korrekt):** entspricht den Frontmatter-Listen (`tools:`); `SubagentHandback` ist ein Laufzeitzusatz für die Berichtsübergabe.
* **Prüfpunkt 5 (nur Orchestrator delegiert):** Bestätigt im Sinn von „**kein** Subagent kann delegieren – auch `lead-architect` nicht, obwohl seine Datei `Agent` auflistet“. Delegiert hat ausschließlich die **Hauptsitzung**. Wichtig: Die Hauptsitzung war **nicht** als `lead-architect`-Typ gestartet (`--agent` nicht geprüft); sie handelte nach `CLAUDE.md` als Orchestrator. Der Typ `lead-architect` wurde nur als Sonde aufgerufen, nicht als Orchestrator eingesetzt.
* **Prüfpunkt 6 (Security ohne Schreibwerkzeuge):** Edit/Write fehlen – **aber Bash ist vorhanden**, und der Agent bestätigte selbst, dass er damit Dateien indirekt ändern könnte. Das ist **tatsächlich passiert**: Der Security-Reviewer legte während des Reviews kurz eine temporäre Testdatei in `backend/tests/` an (über Bash), löschte sie wieder und hat das gemeldet; ich habe danach `git status` geprüft (sauber). Das Briefing hatte ausdrücklich verboten, im Repo zu schreiben. **Ergebnis: Die Werkzeugliste verhindert Schreiben nicht; „ohne Schreibwerkzeuge“ ist nur eine Teil-Absicherung.** Gegenmaßnahmen sind Regeln, Briefing und nachträgliche Git-Kontrolle – keine technische Sperre.

## 3. Delegationsablauf (Prüfpunkt 7) – echter Testlauf mit den echten Typen
Aufgabe: Prüfung/Behebung der drei Dashboard-KPI-Fehler. Reihenfolge (Orchestrator = Hauptsitzung):
1. Sonden an alle 9 Typen (parallel, nur Selbstauskunft).
2. Analyse (nur lesend, parallel, disjunkt): `backend-engineer` (Änderungspunkte), `domain-finance-engineer` (fachliche Abstimmung, Handrechnungen).
3. Orchestrator: ADR 0002 (Entscheidungen/Annahmen), Freigabe der zentralen Dateien nur für Lesepfade.
4. `qa-test-engineer`: Tests zuerst (Datei `test_k2_dashboard_kpis.py`). Orchestrator reproduzierte den roten Stand (46 failed / 28 passed / 2 xfailed).
5. `backend-engineer`: Implementierung innerhalb einer **vorgegebenen Dateimenge**; er stieß auf `api/operations.py` (außerhalb der Menge), **änderte sie nicht** und meldete die nötige Änderung – der Orchestrator führte sie aus. (Beleg, dass die Dateimengen-Regel hier gegriffen hat.)
6. Unabhängiges Review, parallel, nur lesend: `domain-finance-engineer`, `database-architect`, `security-privacy-engineer`.
7. `qa-test-engineer`: Testlücken schließen (+3 Mutationstests im Scratchpad).
8. Zweitreview der neuen Tests durch `domain-finance-engineer`.
9. Orchestrator: Volltests Backend/Frontend/E2E, Dokumentation, Commits.
Einhaltung der Regeln: Alle Agenten antworteten im 10-Punkte-Übergabeformat und kennzeichneten ihre Arbeit nicht als „unabhängig geprüft/freigegeben“. **Abweichungen:** (a) der oben beschriebene Schreibzugriff des Security-Reviewers; (b) die Reviews wurden zum Teil von demselben **Agententyp** durchgeführt wie die vorangehende Analyse (`domain-finance-engineer`), aber in jeweils frischem Kontext und nicht als Autor der Implementierung; (c) ein separates **QA-Review der Implementierung** gab es nicht (QA schrieb Tests und lief Suiten; die Implementierung wurde vom Domain-, DB- und Security-Reviewer geprüft, die Volltests liefen unter Orchestrator-Kontrolle); (d) der „zusätzliche Orchestrator-Review“ bestand aus der Prüfung der Berichte, der Diffstatistik, dem Nachvollzug der Testläufe und eigenen Eingriffen – **nicht** aus einer vollständigen eigenen Code-Durchsicht des Diffs.

## 4. Welche Skills tatsächlich verwendet wurden (Selbstauskunft der Agenten)
| Aufruf | Skills laut Bericht gelesen |
|---|---|
| backend-engineer (Analyse, Implementierung) | backend-development, api-testing, data-integrity-review |
| domain-finance-engineer (Analyse) | financial-calculations, rental-contract-domain, operating-cost-accounting (überflogen), data-integrity-review (überflogen) |
| qa-test-engineer (Tests zuerst) | api-testing, regression-testing, data-integrity-review + ADR |
| qa-test-engineer (Härtung) | api-testing, regression-testing + ADR |
| domain-finance-engineer (Reviews 1 und 2) | financial-calculations, rental-contract-domain |
| database-architect (Review) | database-migrations, data-integrity-review, backup-restore |
| security-privacy-engineer (Review) | security-review, privacy-review (backup-restore, dependency-audit nicht gelesen) |
Nicht verwendet: frontend-development, ui-ux-review, e2e-testing (Frontend nicht geändert), orchestration-workflow/architecture-review (vom Orchestrator nicht per Skill-Werkzeug geladen; Ablauf folgt `CLAUDE.md`/`60-collaboration.md`), windows-desktop-qa, release-management, technical-documentation, dependency-audit, operating-cost-accounting (nur überflogen).

## 5. Testresultate dieser Phase
| Prüfung | Ergebnis |
|---|---|
| Sonden | 9/9 beantwortet |
| `test_k2` vor Implementierung (3 Dateien) | 46 failed, 28 passed, 2 xfailed (reproduziert) |
| Zielsuite nach Implementierung | 119 passed, 2 xfailed (5–6 Dateien, Agent + Orchestrator) |
| `test_k2` nach Härtung | 89 passed, 3 xfailed |
| **Backend vollständig (Endstand `c89c56f`)** | **361 passed, 3 xfailed, 0 failed** (186 s) |
| Frontend vitest | 19 passed; `npm run build` ok |
| Browser-E2E-Suite (`npm run e2e`) | 21/21 Abläufe bestanden |
| Validator `scripts/validate_agent_system.py` | OK, keine Fehler (nach dieser Phase unverändert gültig) |
| Mutationstests (Scratchpad, 3) | alle erkannt (8 / 2 / 2 Tests schlugen an) |
| Windows/WebView2 | **nicht getestet** |

## 6. Bewertung und Einschränkungen
* **Bestätigt:** Die 9 Typen laden, sind einzeln aufrufbar, sehen Profil, `CLAUDE.md` und Regeln; Delegation läuft nur über die Hauptsitzung; Dateimengen-Regel und Übergabeformat funktionierten im Lauf.
* **Nicht bestätigt/Schwächen:** Skills werden nicht geladen (nur per Briefing); Bash umgeht die Schreibbeschränkung (real aufgetreten); Lexono-`CLAUDE.md` im Agentenkontext; Hauptsitzung nicht als `lead-architect` gestartet; Parallelität nur mit **nicht schreibenden** Agenten oder disjunkten Aufgaben erprobt (die Implementierung lief bewusst allein).
* **Empfehlungen (nicht umgesetzt):** `skills:`-Frontmatter prüfen; Bash für Prüfer entfernen oder Schreibschutz per Hook/Berechtigung erzwingen; Lexono-Klon aus dem Sitzungsbereich nehmen; Sitzung mit `--agent lead-architect` testen.
* Es gibt **keine unabhängige Freigabe**; die Reviews sind Befunde anderer Agenten.
