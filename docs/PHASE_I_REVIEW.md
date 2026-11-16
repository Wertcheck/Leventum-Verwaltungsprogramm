# Phase I – Abschlussbericht (Finalisierung)
Stand HEAD 052b758. Details: `PHASE_I_SECURITY.md`, `PHASE_I_QA.md`, `PHASE_I_AGENT_ARCHITECTURE.md`, `PHASE_I_STORNO_ANALYSE.md`, `decisions/0002-dashboard-kpi-definitions.md`.

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
