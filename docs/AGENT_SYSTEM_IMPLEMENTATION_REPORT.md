# Abschlussbericht: Leventum Agent Engineering System

Stand 2026-11-15, Leventum-Branch `claude/leventum-property-management-phase-a-f5kfyx`. Statusstufen: **Geplant · Erstellt · Getestet · Unabhängig geprüft**. **Unabhängig geprüft: nichts. Freigegeben: nichts.** „Getestet“ bedeutet hier nur: Selbstprüfungsskript und ein einziger kontrollierter Testlauf (siehe Abschnitt 7).

## 1. Repository-Zugriff und Berechtigungen
| Punkt | Befund |
|---|---|
| Leventum | Zugriff vorhanden (Schreibrechte, Entwicklungsbranch laut Sitzungsvorgabe) |
| Lexono | In der Kontoliste sichtbar (`Wertcheck/Lexono`, privat). Angebunden mit `add_repo(access: "read")`, flach geklont nach `/home/user/lexono`, Commit `5735e5b`. Die Lexono-`CLAUDE.md`/Skills wurden **nicht** in die Sitzung registriert (`register_repo_root` nicht aufgerufen), damit keine Lexono-Regeln in die Leventum-Arbeit laufen. |
| Wichtige Einschränkung | Die Kontoliste weist für **alle** Repositories `can_push: true` aus, auch für Lexono. Die GitHub-Verbindung des Kontos ist also breiter als „read-only auf Lexono“. Die Read-only-Garantie in dieser Sitzung beruht auf (a) der lesend ausgestellten Sitzungsanbindung, (b) den Regeln, (c) `.claude/settings.json` (nicht durch Schreibversuch geprüft). **Auf GitHub-Seite ist sie nicht erzwungen.** Empfehlung: In den GitHub-App-Einstellungen („Installed GitHub Apps → Claude → Configure → Repository access“) nur gewünschte Repositories auswählen und die Berechtigung „Contents“ für Lexono auf *Read-only* setzen, soweit GitHub das je Repository erlaubt (Fine-grained Token/App-Installation). **Das wurde nicht durchgeführt oder geprüft.** |
| Lexono unverändert | Kontrolliert: `git status` leer, HEAD vor und nach der Arbeit `5735e5b`. Keine Schreiboperation wurde versucht. |

## 2. Lexono-Analyse
Detail: `AGENT_ARCHITECTURE_COMPARISON.md`. Gelesen: `CLAUDE.md`, 13 Agentenakten, 14 Skills, Auszüge aus `.agentic/*`. Nicht gelesen: Großteil von `ARCHITECTURE.md`, `PROJECT_STATE/OPEN_ISSUES/DECISIONS` (> 20.000 Zeilen), App-Code, Tests. Kernbefund: Lexonos Agenten-/Skill-Dateien sind **Konventionen ohne Claude-Code-Format** (kein `.claude/`, kein Frontmatter), Delegation nur über das `Agent`-Tool; Logs wachsen unbegrenzt.

## 3. Wiederverwendete Konzepte (angepasst)
Vetorecht der Sicherheitsrolle; „Evidence before Done“/keine Fake-Vollständigkeit; volle Suite nach Änderung, Tests nie abschalten; kein Push ohne Auftrag; eine kanonische Dokumentation; Delegation nur für unabhängig prüfbare Aufgaben; stoppen bei offener Fachentscheidung. **Nicht übernommen:** jegliche Lexono-Fachlogik (Mandanten, Privacy Gateway, lokale KI, Chat, Rechtsquellen, Installer-Details) und die unbegrenzten Freitext-Logs.

## 4. Angelegt (Status: erstellt)
* **Agenten (9)** in `.claude/agents/`: lead-architect, backend-engineer, frontend-ui-engineer, domain-finance-engineer, security-privacy-engineer, qa-test-engineer, database-architect, windows-release-engineer, documentation-engineer. Sicherheitsrolle ohne Schreibwerkzeuge; nur der Orchestrator hat das `Agent`-Werkzeug.
* **Skills (20)** in `.claude/skills/<name>/SKILL.md`: alle 19 geforderten plus `orchestration-workflow`; je 10 Pflichtabschnitte (maschinell geprüft). 7 Skills werden von mehreren Agenten genutzt.
* **Regeln (7)** in `.claude/rules/`: Domäne, Finanz-Invarianten, Daten/Migrationen, Sicherheit/Datenschutz, Git/Repos, Evidenz/Status, Zusammenarbeit.
* `CLAUDE.md` (kurz; Kerngrundsätze zusätzlich dort, falls Regeldateien nicht geladen werden), `.claude/settings.json` (Schreibverbot-Regeln für das Lexono-Verzeichnis), `scripts/validate_agent_system.py`, `docs/AGENT_SYSTEM.md`, `docs/AGENT_WORKFLOWS.md`, `docs/AGENT_ARCHITECTURE_COMPARISON.md`, ADR `docs/decisions/0001-agent-engineering-system.md`.
* Eingeführte Verfahren: Dateimengen-Zuweisung, Review-Matrix, „Autor ≠ Prüfer“, 10-Punkte-Übergabeformat, Eskalationsliste, Briefing-Vorlage.

## 5. Selbstprüfung (Status: getestet, nur strukturell)
`python scripts/validate_agent_system.py` → **OK, keine Fehler** (9 Agenten, 20 Skills, 7 Regeln, 108 Pfadverweise geprüft). Geprüft werden: Frontmatter, Pflichtabschnitte, Skill-Verweise, Werkzeugzuordnung (z. B. Sicherheitsrolle ohne Edit/Write), Pfadverweise, Secret-Muster, keine doppelten Konfigurationsdateien. Wirksamkeit belegt durch zwei absichtliche Defekte (toter Skill-Verweis, gelöschter Skill-Abschnitt) – beide wurden gemeldet, danach zurückgesetzt. **Die inhaltliche Qualität der Anweisungen prüft das Skript nicht.**

## 6. Orchestrierung
Orchestrator = Hauptsitzung (Subagenten können keine Subagenten starten). Ablauf und Vorlagen: `AGENT_WORKFLOWS.md`. Zentrale Dateien nur eine Instanz zur Zeit; Parallelität nur bei disjunkten Dateimengen – im Testlauf **nur lesend** erprobt, nicht bei schreibenden Agenten.

## 7. Testlauf „Prüfe die KPI-Berechnung des Leventum-Dashboards“ (nur lesend)
Durchführung: Orchestrator-Analyse (Dateimenge `services/dashboard.py`, `leases.py`, `tests/test_dashboard.py`; Risiko mittel; keine Schreibaktion) → **parallel** Backend- und Domain-&-Finance-Agent (beide nur lesend, disjunkte Arbeit, keine Schreibkonflikte) → danach **QA** (abhängig von deren Befunden) → Zusammenführung. **Abweichung vom Zielbild, offen genannt:** Die Rollen-Agententypen waren in dieser Sitzung nicht ladbar; es liefen allgemeine Subagenten, die ihre Rollenprofile, Regeln und Skills **per Briefing lesen und befolgen** sollten. Ob die echten Agententypen funktionieren, ist **nicht getestet**. Es wurden keine Repo-Dateien, Daten oder Geschäftslogik verändert (`git status` danach nur die neuen Agentendateien; Hilfsskripte lagen im Scratchpad).

**Vom Orchestrator selbst gegengeprüft (Code gelesen):** B1 (`_upcoming_ends` ohne `start_date`/`is_running`) und der unbenutzte `phase`-Import sind **bestätigt**.
**Von QA unabhängig reproduziert (Ausführung):** (a) `upcoming_contract_ends` zählt einen noch nicht begonnenen Vertrag (Start +10, Ende +60 Tage → `active_subleases=0`, `upcoming_contract_ends=1`); (b) inaktives Objekt → `properties=0`, `units=2`; (c) Zahlung mit Buchungsdatum +60 Tage senkt `open_receivables` sofort (600,00 → 100,00).
**Von Domain-Agent von Hand nachgerechnet (erfundenes Beispiel):** `sublease_receivables` 1.105,00, `main_rent_obligations` 1.030,00, `monthly_utility_costs` 180,00, `open_receivables` 1.615,00, `overdue_payments` 6, `economic_vacancy_cost` 366,87, `active_tenants` 4, `physical_vacancy` 1, `upcoming_contract_ends` 1 – jeweils **gleich** dem Code. Die Rechnung selbst habe ich nicht erneut nachvollzogen; sie ist ein Agentenergebnis.
**Tests (QA, ausgeführt):** `test_dashboard.py`, `test_d_economics.py`, `test_g_screenshot_findings.py`, `test_h_integrity_documents.py` → 42 bestanden. Die volle Suite lief in diesem Testlauf **nicht**.

**Bewertung (Orchestrator):** Die Geldwerte sind in den geprüften Szenarien rechnerisch korrekt; die Fehler liegen in Definitionen/Konsistenz, nicht in der Arithmetik:
| Nr. | Befund | Schwere (Einschätzung) | Status |
|---|---|---|---|
| F1 | `upcoming_contract_ends` ignoriert `is_running`: zählt noch nicht begonnene Verträge, widerspricht der eigenen Definition; 90-Tage-Konstante dupliziert `reminders.CONTRACT_END_DAYS` | mittel | bestätigt (Orchestrator + QA) |
| F2 | `units` = `Unit.is_active` ohne Objektstatus, Definition sagt „aktiver Objekte“; Wirtschaftlichkeit (nur aktive Objekte) weicht ab | niedrig–mittel | bestätigt (QA, Domain) |
| F3 | `open_receivables`/`overdue_payments` ohne Datenstand (`as_of`): Zukunfts-Zahlung wirkt sofort; Dashboard ≠ Wirtschaftlichkeit (datenstandbezogen) | mittel, **Fachentscheidung nötig** | bestätigt (QA, Domain) |
| F4 | Testlücken auf KPI-Ebene: `open_receivables`, `overdue_payments ≠ 0`, `monthly_utility_costs`, `economic_vacancy_cost`, Grenzdaten, Teilzahlung | mittel | bestätigt (QA); manche Fälle in anderen Testdateien abgedeckt (gekündigt/Hint, Task-/Repair-Zähler, Rechte-Matrix – dort nur gelesen) |
| F5 | Label „Überfällige Zahlungen“ zählt Sollstellungs-Positionen; „Monatliche Betriebskosten“ nur Soll der Hauptmiet-NK; `physical_vacancy` nimmt Renovierung/„nicht verfügbar“ nicht aus | niedrig (Darstellung/Annahmen, teils in `docs/08` als offen vermerkt) | Domain-Befund, nicht reproduziert |
| F6 | Dashboard liefert Finanz-/Aufgabenzahlen an Rollen ohne `finance:read`/`task:read` | niedrig–mittel, **Fachentscheidung** | nur Codelesung (Backend-Agent) |
| F7 | Mögliche N+1-Abfragen (`open_amount` je Forderung); mehrfache Vertrags-Scans | niedrig | nur gelesen, **nicht gemessen** |
| F8 | Hygiene: ungenutzter Import, toter `available=False`-Zweig | niedrig | Orchestrator (Import) bestätigt |
**Nicht entschieden/geändert:** Nichts davon wurde im Produktivcode behoben (Testlauf war ausdrücklich nur lesend). F1–F3 und F6 sind Fach-/Produktentscheidungen für den Menschen. Vorgeschlagene Beweistests T1–T10 (QA) sind **nicht** ins Repo geschrieben.

## 8. Einschränkungen
* Das System besteht aus Anweisungen für ein Sprachmodell; kein technischer Zwang außer den Werkzeuglisten der Agenten und der Deny-Regel.
* Echte Agententypen (`subagent_type`) und der Start mit `--agent lead-architect` sind **nicht getestet**; Parallelität bei schreibenden Agenten **nicht erprobt**.
* `.claude/rules/`-Laden und die Syntax der Deny-Regeln in `.claude/settings.json` wurden **nicht** verifiziert.
* Nur ein Testlauf, nur lesend, mit allgemeinen Subagenten; die Subagentenberichte sind ungeprüfte Agentenaussagen, außer wo oben als reproduziert/gegengeprüft vermerkt.
* Skill-Inhalte beruhen auf dem Leventum-Stand (Master-Review); Testzahlen darin (272/19/21) sind Momentaufnahmen und vor Nutzung neu zu messen.
* Die Windows-Rolle kann ohne Windows-Rechner nichts belegen (weiterhin „nicht getestet“).

## 9. Offene Punkte
1. GitHub-seitig echte Read-only-Beschränkung für Lexono einrichten (Abschnitt 1) – Entscheidung/Handlung beim Eigentümer.
2. Sitzung neu starten und prüfen, ob die 9 Agententypen und die Regeln geladen werden; dann Testlauf wiederholen, diesmal mit echten Typen.
3. Fachentscheidungen F1–F3, F6; danach Backend-Fix-Paket mit Domain-&-Finance- und QA-Review und Tests T1–T10.
4. Python-Dependency-Audit-Werkzeug einrichten (`dependency-audit` nennt die Lücke).
5. Entscheidungen künftig als ADRs ablegen; Pflege der Agentendateien nur über den Orchestrator.

## 10. Git-Änderungen
Nur im Leventum-Repository, nur neue Dateien: `CLAUDE.md`, `.claude/**` (9 Agenten, 20 Skills, 7 Regeln, `settings.json`), `scripts/validate_agent_system.py`, `docs/AGENT_SYSTEM.md`, `AGENT_WORKFLOWS.md`, `AGENT_ARCHITECTURE_COMPARISON.md`, `AGENT_SYSTEM_IMPLEMENTATION_REPORT.md`, `docs/decisions/0001-…`. Kein Produktivcode, keine Tests, keine Daten geändert. Lexono: keine Änderung. Commit/Push siehe Antwort der Sitzung.
