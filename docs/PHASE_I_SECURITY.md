# Phase I – Sicherheit und Datenschutz (Finanzberechtigungen, Agentensicherheit)
Stand: Branch `claude/leventum-property-management-phase-a-f5kfyx`, HEAD 052b758. Statusstufen: Geplant · Implementiert · Automatisiert getestet · Manuell getestet · Unabhängig geprüft · Unter Windows getestet · Freigegeben.

## 1. Ausgangszustand
Finanzwerte tauchten auch in Routen ohne Recht `finance:read` auf (Dashboard-KPIs, Hinweise, Mieterliste/-akte, Reparaturen, Historie, Dokumente, `as_of`-Abfragen). Agentenprofile enthielten Sicherheitsanweisungen ohne technische Durchsetzung; Lexono-`CLAUDE.md` war im Kontext sichtbar.

## 2. Maßnahmen (Implementiert + Automatisiert getestet)
- Zentral `backend/leventum/security/finance_access.py`: `require_finance_read`, Allow-Listen `NON_FINANCE_KPI_KEYS`, `NON_FINANCE_REMINDER_TYPES`, `NON_FINANCE_AUDIT_ACTIONS` (neue/unklassifizierte Einträge sind standardmäßig verborgen; Test `test_i7_audit_action_classification.py`), `FINANCE_DOC_TYPES`, `mask_iban`.
- Serverseitig durchgesetzt in `api/finance.py`, `api/master.py`, `api/operations.py`, `services/{dashboard,reminders,history,repairs,documents,tenant_overview}.py`. Rollen mit `finance:read`: admin, buchhaltung, lesend; ohne: verwaltung, objektbetreuung. 403 enthält keine Beträge (`{"code":"forbidden"}`). Historisches Dashboard (`as_of`) ohne `finance:read` → 403.
- Aufgabentitel ohne Beträge (`reminders.task_title`).
- Agentenprofile: Security-Agent nur `Read, Grep, Glob`; `independent-reviewer` ohne Edit/Write, Bash nur über `scripts/ro_run.sh` (Mount-Namespace, ro, uid 65534, keine Capabilities, no_new_privs, kein Netz) + Hook als Backstop; `claudeMdExcludes` für Lexono; `Edit`-Deny-Regel für Lexono. Details: `docs/PHASE_I_AGENT_ARCHITECTURE.md`.
- R4 (Windows-Agent-Verdacht, verifiziert): Download mit Nicht-Latin-1-Dateinamen (€, –, Kyrillisch) löste `UnicodeEncodeError` aus → `_content_disposition` (RFC 5987), Test `test_i4_document_download_filename.py`.

## 3. Sicherheitsbefunde
| ID | Befund | Quelle | Status |
|---|---|---|---|
| B1–B6 | Finanzlecks in Dashboard/Hinweise/Mieter/Reparaturen/Historie/Dokumente | Security-Agent (Read/Grep/Glob) | behoben, `test_i2_finance_permissions.py` (81), `test_i5_finance_leaks.py` (134) |
| M1 | Audit-Aktionen als Deny-Liste klassifiziert | Review | behoben (Allow-Liste, 39f24ee/2f88be4) |
| H1 (Security-Re-Review) | Hook fail-open bei fehlendem python3 (Exit 127) | Security-Re-Review | behoben (`|| exit 2`, Validator-Regel, Tests) |
| H1 (Independent-Reviewer) | Hook-Bypass über `#` | Independent-Reviewer | behoben, 61 Tests |
| M2 | `/dunning/prepare` akzeptierte Zukunfts-`as_of` | Independent-Reviewer | behoben, 2 Tests; alter Test mit festem Datum 2027-06-01 auf `date.today()` geändert |
| M3 | Flaky Teststring `"476" not in r.text` | Independent-Reviewer | behoben (Regex auf eigenständigen Betrag; 3 Wiederholungen grün) |
| M4 | `ro_run.sh` remountete nur feste Mountliste | Independent-Reviewer | behoben, manuell geprüft |
| M5 | Status „beendet“ in historischen Dashboards fehlt | Independent-Reviewer | als Einschränkung dokumentiert (`DASHBOARD_LIMITATIONS`), Verhalten unverändert |
| M6, R1, N1 (Aufgabentitel zeigt „Verzug“), F-2 (Rechnungsliste ohne `as_of`), F-3 (`close_expired` nie aufgerufen) | | Reviews | **Entscheidung des Eigentümers offen** |
| Altdaten | Bestehende Aufgaben können Beträge im Titel tragen; nicht migrierbar ohne Datenänderung | | offen |

## 4. Ehrliche Grenzen
- Datenbank und Dokumente sind **unverschlüsselt** (BitLocker nötig); nur Backups optional AES-256-GCM/scrypt.
- Python-Abhängigkeitsaudit **nicht eingerichtet**; `npm audit`: 2 moderate Produktionsbefunde (react-router) – nicht behoben.
- Hook wirkt nur im vertrauten Workspace; Frontmatter-Hook im vertrauten Workspace nicht getestet (nur per `--settings`).
- `ro_run.sh` Linux-only/root; unter Windows nicht anwendbar.
- Unabhängig geprüft wurde: Finanzrechte (Security-Re-Review, Agent mit Read/Grep/Glob), Domain-Review (F-1), Independent-Reviewer-Lauf auf 5bc2f62..ca27c33. Die Fixes nach dem Review (H1, M2–M5) sind **nicht** erneut unabhängig geprüft.
- **Nicht freigegeben, nicht produktionsreif** (Windows/WebView2, Verschlüsselung, Backup/Restore unter Windows, Python-Audit offen).
