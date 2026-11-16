# Phase I – QA, Tests, Performance
## 1. Testläufe (Linux, Python 3.13, SQLite 3.53; Windows nicht getestet)
| Suite | Befehl | Ergebnis |
|---|---|---|
| Backend gesamt (Stand 052b758, vor Anpassung eines Tests) | `cd backend && python -m pytest -q` | **845 bestanden, 1 fehlgeschlagen, 3 xfailed** (517 s, parallel zu E2E) |
| Fehlgeschlagener Test | `test_d_dunning.py::test_regression_approved_but_unsent_notice_never_escalates` | Ursache: festes Datum 2027-06-01 liegt seit M2 in der Zukunft (422). Test auf `date.today()` geändert (Absicht unverändert). |
| Nach Korrektur gezielt | `pytest tests/test_d_dunning.py tests/test_i3_stichtag_kpis.py tests/test_agent_guard.py` | 210 bestanden |
| Frontend | `npm test` | 33 bestanden |
| Build | `npm run build` | erfolgreich |
| Browser-E2E | `npm run e2e` | 22/22 Abläufe |
| Agentensystem | `python scripts/validate_agent_system.py` | „OK – keine Fehler“ |
**Vollständiger Backend-Lauf nach der Testkorrektur (Stand 052b758 + Docs): `cd backend && python -m pytest -q` → 846 bestanden, 3 xfailed, 0 fehlgeschlagen (459 s).** Automatisiert getestet, nur Linux.

## 2. xfailed (nicht als bestanden gezählt)
`backend/tests/test_k2_dashboard_kpis.py` Zeilen ~440, 763, 775: **F1** (Storno vor Originalzahlung → offen > Betrag; strict; unverändert per Entscheidung 2.4), **A6a** (Rücknahme einer Zuordnung ändert Historie), **A6b** (stornierte Forderung fehlt in historischem Stand). Zusätzlich A6c (Status „beendet“) dokumentiert, kein xfail.

## 3. Neue Tests Phase I
`test_agent_guard.py` 61 · `test_file_set_guard.py` 3 · `test_i2_finance_permissions.py` 81 · `test_i2_storno.py` 39 · `test_i2_perf_equivalence.py` 16 · `test_i3_stichtag_kpis.py` (137 + 2 für M2) · `test_i4_document_download_filename.py` 9 · `test_i5_finance_leaks.py` 134 · `test_i6_overview_stichtag.py` 1 (Mutation geprüft: 1100 vs. 1200) · `test_i7_audit_action_classification.py` 4 · Frontend `phaseI.test.tsx` 14 · E2E-Flow 21 (Dashboard-Stichtag).

## 4. Performance (database-architect; `scripts/bench_open_items.py`; Linux/SQLite; Vorher → Nachher, 500 Forderungen)
| Pfad | Statements | Median ms |
|---|---|---|
| engine_portfolio | 1232 → 368 | 450 → 149 |
| engine_open_only (`Engine._open`) | 435 → 3 | 163 → 28 |
| current_month_figures | 1335 → 471 | 486 → 182 |
| build_dashboard | 1995 → 1131 | 586 → 294 |
| reminders_compute | 547 → 547 (unverändert) | 211 → 109 (Messrauschen) |
Änderung: `Engine._open` N+1 → eine gruppierte Abfrage (`services/economics.py`). Bit-identisch zum Original in 128 Vergleichen (`test_i2_perf_equivalence.py`). Laufzeit wird von Python/SQLAlchemy-Overhead dominiert (SQL-Anteil 3–5 %), nicht von SQL. Keine Migration. Offen: lazy loads je Vertrag/Einheit, `Engine._ist` je Zahlung. Windows-Laufzeiten nicht gemessen.

## 5. Unabhängige Prüfungen
Independent-Reviewer (Lauf auf 5bc2f62..ca27c33, nur lesend über `ro_run.sh`) bestätigte die KPI-Entscheidungen 2.1–2.4, Finanzrechte und Performance-Äquivalenz; Befunde H1, M1–M6, N1–N6 siehe `PHASE_I_SECURITY.md`. Domain-Review fand F-1 (behoben). Korrekturen danach sind nicht erneut unabhängig geprüft.

## 6. Windows/WebView2
**Nicht getestet.** Vorbereitet: `docs/WINDOWS_TESTPLAN.md`, `docs/WINDOWS_BUILD_PLAN.md`, `scripts/windows_smoke_test.ps1` (nie ausgeführt, Syntax ungeprüft). Windows-Agent-Befunde R1–R7 (u. a. `pip install .[desktop]` vermutlich nicht nutzbar, kein Backup vor Migration, Restore unter Datei-Sperren, keine Einzelinstanz-Sperre) offen. Weiterhin Release-Blocker.

## 7. Nachhärtung nach Nachreview – Testzahlen (getrennt nach selbst ausgeführt / übersprungen / nur dokumentiert)
**Selbst ausgeführt (Orchestrator, Linux, root, Stand Arbeitsbaum nach Nachhärtung, vor Commit):**
| Lauf | Ergebnis |
|---|---|
| Backend gesamt `cd backend && python -m pytest -q -rs` (465 s) | **957 bestanden, 0 fehlgeschlagen, 0 übersprungen, 3 xfailed** (zweiter Gesamtlauf nach den Review-Folgemaßnahmen; erster Lauf vorher: 951) |
| Frontend `npm test` | 33 bestanden |
| `npm run build` | erfolgreich |
| Browser-E2E | 22/22 |
| `python scripts/validate_agent_system.py` | „OK – keine Fehler“ |
| Runner im echten isolierten Runner (`scripts/ro_run.sh`, als root) | in `test_agent_guard.py` (als root **außerhalb** des Runners ausgeführt: 0 übersprungen; der Reviewer konnte das im Runner als Nicht-root nicht reproduzieren: dort 36 übersprungen – Selbstauskunft des Orchestrators/QA-Agenten, nicht unabhängig bestätigt); zusätzlich manuell: uid 65534, Caps 0, NoNewPrivs 1, Repo read-only, `gh` nicht angemeldet |
**Von Agenten gemeldet (Teilläufe, Selbstauskunft, nicht erneut einzeln vom Orchestrator wiederholt, aber im Gesamtlauf enthalten):** `test_file_set_guard.py` 35; `test_file_set_guard.py`+`test_i5_finance_leaks.py` 195; `test_i3_stichtag_kpis.py`+`test_d_dunning.py` 158; `test_agent_guard.py` 99.
**Übersprungen:** keine im Gesamtlauf. Nicht ausgeführt: der Test „unlesbare Datei → Exit 2“ in `test_file_set_guard.py` läuft nur ohne root (Zweig als root nicht geprüft); der Abbruchzweig „oberster Mount bleibt rw → Exit 3“ in `ro_run.sh` ist nur per Code-Lektüre geprüft.
**xfailed (separat, nicht als bestanden gezählt):** unverändert F1, A6a, A6b (`test_k2_dashboard_kpis.py`).
**Nur dokumentiert / nicht belegt:** Windows/WebView2; Mutationsnachweis der neuen Tests nur gedanklich, nicht real mutiert.

## 8. P0/P1-Remediation – Testergebnisse (Linux, root; vor Commit; getrennt nach selbst ausgeführt / von Agenten gemeldet / nicht ausgeführt)
**Vom Orchestrator selbst ausgeführt:**
| Lauf | Ergebnis |
|---|---|
| `cd backend && python -m pytest -q -rs` (gesamt; letzter Lauf auf dem endgültigen Stand vor dem Commit, 527 s; frühere Läufe 1456) | **1466 bestanden, 0 fehlgeschlagen, 0 übersprungen, 3 xfailed** (F1, A6a, A6b unverändert) |
| `npm test` (Frontend) | 33 bestanden (Frontend unverändert seit dem letzten Lauf) |
| `python scripts/validate_agent_system.py` | OK – keine Fehler (11 Agenten, 20 Skills, 7 Regeln) |
| Hook-FIFO-Mutationsprobe (Kopie ohne `O_NONBLOCK`) | hängt → Timeout (rc 124); aktueller Hook rc 0 |
| `review_preflight.py check` gegen das echte Repo (vor Nachhärtung) | BLOCKED, erwartet: Änderungen ungepinnt/ungecommittet, kein Trust-Eintrag (`f-trust`) |
**Von Agenten gemeldet (im Gesamtlauf enthalten, Selbstauskunft):** `test_agent_guard.py` 369 · `test_file_set_guard.py` 126 · `test_review_preflight.py` 144. **Nicht erneut ausgeführt:** Browser-E2E und Build (keine Frontend-Änderung), Mutationsproben der meisten neuen Tests (nur FIFO belegt), Windows.
**Experimente im echten Claude-Code-Ablauf (`claude -p` 2.1.325, Linux):** Nonce-Protokoll im Subagent-Betrieb: vertraut → Hook feuert, `verify` Exit 0, Canary blockiert (2/2); unvertraut → Hook inaktiv, Canary ausgeführt, `verify` Exit 1 (2/2). Statisches Profil (Haupt-Prozess): `init`-Liste `Read, Grep, Glob`, Dummy-MCP verbunden aber nicht angeboten, keine Datei verändert (4 Läufe); als Subagent nur Selbstauskunft. Standard-Permission-Modus, Bash-fähiger Reviewer: vertraut wie oben; unvertraut → direkter `echo` läuft, Runner-Aufruf „requires approval“. Roh-Streams: `scratchpad/probe2`, `scratchpad/probe3` (ohne Konfig-Kopien).
