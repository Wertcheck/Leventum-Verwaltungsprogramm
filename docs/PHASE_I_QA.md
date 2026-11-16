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
