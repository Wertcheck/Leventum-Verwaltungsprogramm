# Phase: Dashboard-KPI-Fehler

Stand 2026-11-15. Entscheidungsgrundlage: `docs/decisions/0002-dashboard-kpi-definitions.md`. **Status: Implementiert, automatisiert getestet, von anderen Agenten begutachtet; nicht freigegeben; Windows nicht getestet. Mehrere Annahmen (A1, A2, A8, F1, F-Sec1) warten auf die Bestätigung des Eigentümers.**

## 1. Fachliche Definitionen (Eigentümer) und Umsetzung
| KPI | Definition | Umsetzung |
|---|---|---|
| `upcoming_contract_ends` | nur aktive Verträge (Mietbeginn erreicht), Ende steht bevor und liegt im konfigurierten Vorschauzeitraum; nicht begonnene ausgeschlossen | zentral `leases.contract_end_due/upcoming_ends` (`is_running(lease, Stichtag)`, `Stichtag ≤ Ende ≤ Stichtag+N`, inklusiv); Dashboard **und** Hinweise (`reminders`) nutzen sie; N aus `Settings.contract_end_preview_days` (Standard 90, 1–730, Env `LEVENTUM_CONTRACT_END_PREVIEW_DAYS`); hartcodierte 90 und `CONTRACT_END_DAYS` entfernt |
| `units` | nur aktive WE in aktiven Objekten | Join auf `Property.is_active` (wie `economics.Structure`) |
| `open_receivables` (+ `overdue_payments`, Hinweise) | stichtagsbezogen; Zahlungen mit Buchungsdatum nach dem Stichtag mindern nicht; historische Stichtage | zentral `charges.receivable_position(db, as_of)` (eine gruppierte Abfrage; `Payment.booking_date ≤ as_of`); `economics.current_month_figures`, Dashboard und `reminders` nutzen sie; `GET /dashboard?as_of=` (ohne Parameter wie bisher, Zukunft → 422), Antwort mit `as_of` und `historical_supported` je KPI |
Beispiel des Eigentümers (600/500/100 → 100) ist als Test belegt.

## 2. Entscheidungen und Annahmen (ADR 0002)
Eigentümerdefinitionen wörtlich umgesetzt; **zur Bestätigung offen:** A1 (Forderungen unabhängig von der Fälligkeit – wie bisher; Empfehlung des Reviewers wäre „nur fällig“ wie die Wirtschaftlichkeit), A2 (Haupt- **und** Untermietverträge zählen bei den Vertragsenden), A5 (Zahlungswirkung nach Buchungsdatum), A8 (Dashboard weicht von Forderungsliste/Mahnwesen/Bankimport ab, die weiter ohne Stichtag rechnen).

## 3. Geänderte Dateien (`git diff ee00e7c..HEAD`)
Produktiv: `backend/leventum/config.py`, `services/leases.py`, `services/charges.py`, `services/economics.py` (nur Lesepfad `current_month_figures`), `services/reminders.py`, `services/dashboard.py`, `api/routers.py`, `api/operations.py`. Tests: `backend/tests/test_k2_dashboard_kpis.py` (neu). Doku: `docs/03-api-module.md`, `docs/decisions/0002-…`, diese Datei, `PHASE_AGENT_VALIDATION.md`. **Nicht geändert:** Modelle, Migrationen, Zahlungs-/Buchungsdaten, Finanz-Schreibpfade, Frontend. Keine neue Abhängigkeit.

## 4. Messungen (Review des `database-architect`, SQLite, Linux)
`receivable_position` = `open_amount(as_of)` je Forderung an 5 Stichtagen (identisch). SQL-Statements bei 30/60 Forderungen: `reminders.compute` **73→44 / 103→44**; `build_dashboard` **201→150 / 321→210**. Kein Schema-/Migrationsbedarf.

## 5. Tests
`test_k2_dashboard_kpis.py`: 89 passed, 3 xfailed (A6a, A6b, F1 – alle bekannte Einschränkungen, nicht als bestanden zu werten). Abgedeckt u. a.: zukünftiger Beginn, begonnener Vertrag mit künftigem Ende, abgelaufen (Grenzen 0/+N/+N+1/−1), gekündigt, offenes Ende, Haupt+Sub, aktives/inaktives Objekt und WE, volle Zahlung, Teilzahlung, Zukunftszahlung, historische Stichtage, mehrere Zahlungen/Verträge, Storno, Überzahlung, Rechte/401/403/422, konfigurierter Vorschauzeitraum in Dashboard und Hinweisen, `/reminders/task`. **Volle Backend-Suite 361 passed, 3 xfailed; Frontend 19 passed; E2E 21/21.**

## 6. Unabhängiges Review (andere Agenten, keine Freigabe)
* `domain-finance-engineer`: Berechnung korrekt (Handrechnung = Code = `open_amount`), keine neuen Schreibzugriffe; Befunde F1, F2, Testlücken (später geschlossen). Zweitreview der neuen Tests: Handrechnung stimmt, nur Test-Hygiene offen.
* `database-architect`: SQL-Semantik korrekt, Abfragezahl gemessen, keine Migration nötig; Hinweise A, B, C, D, E (siehe unten).
* `security-privacy-engineer`: kein Veto; Befund F-Sec1 (Finanzaggregate über `as_of` für Rollen ohne `finance:read`).
Der implementierende Agent (`backend-engineer`) hat seine Arbeit **nicht** als unabhängig geprüft deklariert.

## 7. Offene Probleme (nicht behoben)
| Nr. | Problem | Entscheidung/Owner |
|---|---|---|
| F1 | Storno mit Buchungsdatum **vor** der Originalzahlung → Stichtag dazwischen „offen > Forderungsbetrag“ (vorbestehend, auch in `open_amount`); Test `xfail(strict)` | Eigentümer/Domain; berührt Zahlungslogik |
| A1/A2/A8 | siehe Abschnitt 2 | Eigentümer |
| A6 | Historische Stichtage: später zurückgenommene Zuordnungen und heute stornierte Sollstellungen wirken rückwirkend; Stammdaten, Vertragsstatus `ended`, Aufgaben, Reparaturen, Leerstand/Monats-KPIs zeigen den heutigen Stand (`historical_supported` weist es aus; für Vertrags-KPIs gilt A6c) | dokumentiert |
| F-Sec1 | `as_of` ermöglicht Zeitreihen von Finanzaggregaten für `dashboard:read`-Rollen ohne `finance:read` | Eigentümer: Beschränkung oder Risikoakzeptanz |
| B | `economics.Engine._open` hat weiterhin N+1 (eigenes Paket, zentrale Finanzdatei) | Orchestrator-Freigabe nötig |
| C | `receivable_position` läuft je Dashboard-Aufruf 3× (ohne gemeinsamen Cache) | niedrig |
| Index | kein Index auf `charge.direction`/`voided_at`; bei Zehntausenden Zeilen beobachten | niedrig |
| E7 | Objekt-Deaktivierung ist bei laufenden Verträgen nicht gesperrt (inaktives Objekt mit Verträgen → inkonsistente Zähler) | Eigentümer |
| F2 | Settings-Fallback `Settings()` in `dashboard.py`/`reminders.py` ohne durchgereichten Wert (API reicht ihn durch) | niedrig |
| Tests | Füller-Assert, A6c-Kommentar, Hint-Zweig mit Mehrfachverträgen, `historical_supported` für alle KPIs, F1-Test für Fix-Variante „Storno ablehnen“, `TODAY` beim Import | QA, niedrig |
| Frontend | neue Felder `as_of`, `historical_supported` und die 422-Formate werden in der Oberfläche **nicht** genutzt/behandelt; kein UI-Stichtagswähler | offen |
| Plattform | Windows/WebView2 und PostgreSQL **nicht getestet** | — |
