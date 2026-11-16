# Phase I – Abschlussbericht (Finalisierung)
Ausgangsstand dieses Nachtrags: HEAD 3e79b0c (Phase-I-Abschluss; der Inhalt bis dahin: Commits ca27c33 … 052b758 + Doku). Nachhärtung siehe Abschnitt „Nachhärtung nach Nachreview“. Details: `PHASE_I_SECURITY.md`, `PHASE_I_QA.md`, `PHASE_I_AGENT_ARCHITECTURE.md`, `PHASE_I_STORNO_ANALYSE.md`, `decisions/0002-dashboard-kpi-definitions.md`.

## Ausgangslage
Offene Punkte aus `PHASE_AGENT_VALIDATION.md`/`PHASE_KPI_FIXES.md`: schreibfähige Prüf-Agenten, fehlende Finanzrechte in Nicht-Finanzrouten, uneinheitliche Stichtage, N+1 in `Engine._open`, kein unabhängiges Review.

## Umsetzung der Eigentümerentscheidungen (Implementiert + Automatisiert getestet)
- 2.1 `open_receivables` = alle offenen unabhängig von Fälligkeit; neu `overdue_receivables` (EUR) separat; nicht fällige gelten als offen, nicht überfällig.
- 2.2 Vertragsenden getrennt (`upcoming_main_lease_ends`, `upcoming_sublease_ends`) plus Summe; nur begonnene/aktive Verträge im Vorschaufenster (`contract_end_preview_days`).
- 2.3 Zahlungen wirken erst ab Buchungsdatum – historisch **und** aktuell (`charges.receivable_position`, `arrears`, Mahnentwurf, Bank, Mieterübersicht nach F-1-Fix); `payments.allocate` unverändert.
- 2.4 Storno-/Gegenbuchungslogik **unverändert**, keine Kappung; nur Tests (`test_i2_storno.py`) und Dokumentation (`PHASE_I_STORNO_ANALYSE.md`).
- Zentrale Stichtagslogik `services/stichtag.py`; Zukunft → 422 `as_of_in_future`; `historical_supported`/`limitations` je Ansicht; Frontend bietet Historie nur wo unterstützt.

## Prozess
Delegiert: Security (Read/Grep/Glob), Domain & Finance (Storno-Analyse, F-1), Database Architect (Messung, `_open`), Windows (Bestandsaufnahme), Independent-Reviewer (headless). Dateimengen mit `check_file_set.py` kontrolliert (Grenzen N1/N2). Autor ≠ Prüfer eingehalten; Nach-Review-Fixes (H1, M2–M5) vom Orchestrator selbst, **nicht** erneut unabhängig geprüft.

## Statusübersicht
| Bereich | Stufe |
|---|---|
| KPI-/Stichtag-/Rechte-Änderungen | Implementiert · Automatisiert getestet · Unabhängig geprüft (Stand ca27c33) |
| Fixes nach Review (H1, M2–M5) | Implementiert · Automatisiert getestet (gezielt) |
| Vollständiger Backend-Lauf nach letzter Änderung | Automatisiert getestet: 846 bestanden, 3 xfailed (vorher 845/1/3 vor Testkorrektur) |
| Browser-E2E, Frontend-Tests | Automatisiert getestet (22/22, 33) |
| Windows/WebView2 | **Nicht getestet** |
| Freigabe | **Nicht freigegeben** |

## Offene Risiken / Entscheidungen
F1/A6a/A6b (xfail), A6c, M6, R1, Aufgabentitel mit Verzug (N1), F-2, F-3, Altdaten-Aufgaben mit Beträgen; Windows R1–R7; unverschlüsselte DB/Dokumente; kein Python-Audit; npm audit 2 moderate. **Leventum ist nicht produktionsreif**, solange Windows/WebView2, Verschlüsselung, Backup/Restore und die Sicherheitsprüfungen nicht nachgewiesen sind.

## Nachhärtung nach Nachreview (Auftrag „Security & QA Hardening“)
Ausgangsstand: Branch `claude/leventum-property-management-phase-a-f5kfyx`, HEAD 3e79b0c, Arbeitsbaum sauber, Lexono HEAD 5735e5b ohne Änderungen.
| Befund (Nachreview) | Maßnahme | Stufe |
|---|---|---|
| Runner reicht komplette Umgebung (Tokens) durch | `scripts/ro_run.sh`: `env -i`-Allowlist (zweistufig), fester PATH, `PYTEST_ADDOPTS` fest, `GIT_CONFIG_NOSYSTEM/GLOBAL`; Test mit Dummy-Secrets | Implementiert · Automatisiert getestet |
| `RO_RUN_UID` unvalidiert | numerisch 1..65534, nie 0, sonst Exit 3; wird nicht in Shell-Text eingesetzt | Implementiert · Automatisiert getestet |
| Option-Einschleusung (`--reuid=0`), geerbte FDs, fehlende PID/IPC/UTS-Isolation, `\|\| true` bei Remount | Erstes Argument ≠ Option (Exit 2); `--` vor Befehl; FDs > 2 geschlossen; `--pid --fork --mount-proc --ipc --uts`; Verifikation, dass kein oberster Mount rw bleibt (Exit 3); `/tmp` `nosuid,nodev` | Implementiert · Automatisiert getestet (rw-Mount-Abbruchzweig nur per Code-Lektüre) |
| MCP-Werkzeuge im Reviewer-Profil | Hook sperrt `mcp__*`, Frontmatter-Matcher erweitert, Validator-Regel; Werkzeug-Probe des Profils (Selbstauskunft: nur Read, Grep, Glob, Bash) | Implementiert · Automatisiert getestet (Hook); Wirkung der `tools`-Allowlist auf MCP nur per Selbstauskunft, **nicht** technisch belegt |
| `check_file_set.py` Schwächen | neu: HEAD im Snapshot, committete Änderungen, Renames (beide Pfade), Symlinks, Modi, ignorierte Dateien (Rauschliste), `*` nicht über `/`, Exit 0/1/2 getrennt | Implementiert · Automatisiert getestet (35 Tests) |
| M2 Test ohne Forderungen | neuer Test mit überfälligen Forderungen, Zustandsvergleich vorher/nachher (DunningNotice/Line, AuditEvent, Charge, Payment, Allocation), Kontrollaufruf; `candidates()` lehnt Zukunft ab (Service-Änderung `dunning.py`, ein Aufruf `stichtag.resolve`) | Implementiert · Automatisiert getestet |
| Zeitabhängige Tests | `stichtag.date` per monkeypatch eingefroren (2027-06-01) in den neuen/angepassten Tests; bestehende Altbestands-Tests in test_i3 unverändert (nutzen `TODAY` beim Import) | Implementiert |
| A6c ohne Test | Charakterisierungstest (dokumentierte Einschränkung, kein Sollverhalten) + Gegenfall + `receivable_position` identisch für `active`/`ended` | Automatisiert getestet |
| F-3 Docstring | `close_expired`: nur Docstring korrigiert (wird von keinem Code im Repo aufgerufen); Verhalten unverändert, Eigentümerentscheidung offen | Implementiert |
| Regex M3 | Helfer `has_standalone_476`; Buchstaben-Nachbarn werden nicht mehr als Betrag gewertet; Centwerte und „4 76“ bewusst nicht erkannt (getestet) | Automatisiert getestet |

### Unabhängiger Review der Nachhärtung
`independent-reviewer` (Lesen + `ro_run.sh`; ändert nichts) prüfte den uncommitteten Diff gegen 3e79b0c: `ro_run.sh` (Allowlist, UID-Validierung, Optionen, FD-Schließung, Mount-Verifikation, PID-Namespace), `ro_guard.py`/Matcher, `check_file_set.py` + Tests (inkl. Ad-hoc-Läufe mit Sonderzeichen, Rename, `--amend`), `dunning.py::candidates`, M2-/A6c-Tests (Zustandsvergleich, Zeit-Einfrieren), Regex, `close_expired`, Docs. **Bestätigt:** Allowlist wirkt (gemessen), Arithmetik-/FD-Injektion nicht erreichbar, Diff gegen `backend/leventum/` = nur `candidates` (4 Zeilen) + Docstring, `receivable_position` unverändert, 318 Tests in 3 Dateien im Runner grün, 35 file-set-Tests grün. **Befunde:** siehe `PHASE_I_SECURITY.md` §6 (Pfad-Sockets → `/run` verdeckt; weitere niedrig/offen). **Nicht bestätigt vom Reviewer:** volle Suiten, Runner-Tests als root, MCP-Hook im echten Trust-Ablauf, Mutation der neuen Tests (nur gedanklich). Der Pflichtreview von `candidates()` durch Domain & Finance ist erfolgt (siehe unten). Keine Freigabe.

### Fachreview `candidates()` (Domain & Finance, Autor ≠ Prüfer)
`domain-finance-engineer` (nur Lesen/Testlauf) prüfte `dunning.py::candidates` (Zukunft → 422 `as_of_in_future`): **keine Invariante berührt** (Punkt 8 gestärkt, Punkt 9 unverändert, kein Schreibpfad); alle produktiven Aufrufer (`prepare_notices`, `/dunning/overdue`) lösten den Stichtag schon vorher auf → API-Verhalten unverändert; kein Frontend-/Prognose-Aufrufer mit Zukunftsdatum (`Dunning.tsx` sendet kein `as_of`). Er führte 158 Tests (`test_d_dunning.py` + `test_i3_stichtag_kpis.py`) aus: bestanden. Hinweise (niedrig, nicht behoben): zweite „heute“-Quelle `dunning.py:154`; `sent_on > as_of` bei historischem Stichtag nicht getestet; Mitternachtsfall. Nicht geprüft: `Economics.tsx`-Prognose, `bank.py`, `reminders.py` im Detail. Das ist ein Fachreview, **keine Freigabe**; QA-Review durch den `independent-reviewer` deckte denselben Diff ab (siehe oben).
