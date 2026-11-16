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

## 5. Nachhärtung nach Nachreview (Stand Arbeitsbaum vor Commit)
- **Runner-Umgebung:** `scripts/ro_run.sh` verwirft die Aufruferumgebung (zweistufiges `env -i`, fester PATH). Test mit Dummy-Secrets (GITHUB_TOKEN, GH_TOKEN, CLAUDE_CODE_MESSAGING_TOKEN, CLOUDSDK_AUTH_ACCESS_TOKEN, SESSION_INGRESS_URL, PYTHONPATH, BASH_ENV …): keines erscheint im Prüfprozess. **Rest-Grenze:** Ein vom Aufrufer gesetztes `LD_PRELOAD` wirkt in den root-Prozessen des Skripts selbst, bevor die Allowlist greift; im Skript nicht behebbar, nur durch den Aufrufer/Hook (VAR=-Präfix verboten) – **nicht getestet**.
- **`RO_RUN_UID`:** validiert (1..65534, Dezimalzahl, nie 0), Injektionsvarianten (`;`, `$()`, Backtick, `&&`, Zeilenumbruch) legen keine Datei an (Test).
- **Weitere Härtung:** Options-Argumente als erstes Argument → Exit 2; FDs > 2 geschlossen; PID-/IPC-/UTS-Namespace; Mount-Verifikation (Exit 3); `/tmp` nosuid/nodev; git ohne System-/Nutzerkonfiguration.
- **MCP/GitHub im Reviewer-Profil:** Werkzeug-Probe (Selbstauskunft des Subagenten): nur `Read, Grep, Glob, Bash`, keine MCP-/GitHub-Werkzeuge, vorgeladene Skills = die 4 im Profil. Der Security-Agent (nur Read/Grep/Glob) sah in seinem Kontext **Instruktionstexte** von MCP-Servern (github, PDF_net, Claude_Docs), aber keine Werkzeuge – ein Hinweis auf Kontextlecks, kein Beleg für aufrufbare Tools. Zusätzlich sperrt der Hook jetzt `mcp__*` (Test). **Nicht technisch belegt:** dass eine `tools`-Allowlist MCP-Werkzeuge in Claude Code zuverlässig ausschließt und dass der Hook bei MCP-Aufrufen überhaupt ausgelöst wird; `disallowedTools` mit `mcp__*` wurde bewusst nicht eingeführt (Syntax nicht belegt, Validator kennt es nicht). Die `gh`-CLI im Runner: ohne Token, ohne Netz („not logged in“, gemessen).
- **Offen:** Seccomp nicht gesetzt; Kernel-Exploits nicht abgedeckt; Hook im echten Frontmatter-Trust-Ablauf nicht getestet; ob Tokens früher in Transkripten gelandet sind, ist nicht geprüft (Rotation = Entscheidung des Menschen).
- Security-Agent (Read/Grep/Glob, kein Autor der Änderungen) hat das Design geprüft und die Befunde geliefert; er hat die umgesetzte Fassung **nicht** erneut geprüft.

## 6. Ergebnis des unabhängigen Reviews der Nachhärtung und Folgemaßnahmen
Reviewer: `independent-reviewer` (nur Read/Grep/Glob/Bash über `ro_run.sh`; änderte nichts: `git status` vor/nach identisch). Befunde und Umgang:
- **Mittel – Pfad-Unix-Sockets nicht netzisoliert** (belegt: `/run/sandbox-telemetry/ingest.sock`, world-writable, im Runner sichtbar; nicht verbunden): „kein Netz“ gilt für TCP/IP/abstrakte Sockets, nicht für Pfad-Sockets. **Maßnahme:** `/run` wird im Runner durch ein leeres tmpfs verdeckt (Test `test_runner_hides_host_run_directory_and_unix_sockets`: 0 Einträge, 0 Sockets mit `find / -xdev`). Andere Mounts mit Sockets in anderen Umgebungen: nicht geprüft.
- **Niedrig – fd 1/2** zeigen auf eine Host-Datei (Ausgabe des aufrufenden Prozesses); beabsichtigt, aber ein beschreibbares Handle außerhalb des Runner-tmpfs. Offen/akzeptiert.
- **Beobachtung:** Der Zielprozess darf `unshare -Ur` ausführen; ein `mount -o remount,rw,bind /` darin wurde verweigert (vom Reviewer gemessen). Weitere Ausbruchsversuche nicht unternommen. Bekannte Grenze, kein Seccomp.
- **Niedrig – UID-Tests** ergänzt: „00000“, „0000“, „065534“, Tab, Unicode-Ziffern → Exit 3.
- **Niedrig – check_file_set:** Grenzen (Submodule, `docs/*/`, `overlap` bei künftigen Dateien, `--out` im Repo) im Docstring ergänzt, nicht behoben.
- **Regex M3:** Die Verbesserung hat eine Kehrseite (Abschwächung): Buchstaben unmittelbar vor/nach der Zahl (außer „EUR“) gelten nicht mehr als Betrag; „476m²“ oder „Betrag476“ würden nicht mehr erkannt. Bewusst akzeptiert; die übrigen Leak-Prüfungen sind unverändert.
- **Nicht reproduzierbar im Runner:** Der Reviewer lief nicht als root; 36 Runner-Tests wurden dort übersprungen (98 bestanden/36 übersprungen). Die Runner-Tests wurden nur vom Orchestrator und vom QA-Agenten als root außerhalb des Runners ausgeführt (siehe PHASE_I_QA.md).
- Pflichtreview der `candidates()`-Änderung durch Domain & Finance ist erfolgt (keine Blocker, siehe `PHASE_I_REVIEW.md`). **Mittel – offen:** Wirkung der MCP-Hook-Sperre im echten Trust-Ablauf nicht gemessen.
