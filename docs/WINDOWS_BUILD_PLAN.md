# Windows-Build- und Installer-Plan (PLAN – NICHT UMGESETZT)

**Status: Geplant (Entwurf), nicht implementiert, nicht getestet, nicht unter Windows getestet, nicht unabhängig geprüft.**
Ein Installer, ein PyInstaller-Spec oder ein Build-Skript **existiert nicht**. Dieses Dokument sammelt Entscheidungsgrundlagen für die nächste Phase.
Alle Aussagen über Windows-, PyInstaller-, Inno-Setup-, MSIX- oder WebView2-Verhalten sind **Annahmen / zu prüfen**; sie stammen aus allgemeinem
Wissen und Quellcode-Lektüre unter Linux, nicht aus einem Lauf. Es wurde kein Installer-Code aus dem Lexono-Repository gelesen oder übernommen
(Lexono ist nur Lesereferenz). Änderungen an Installer/Build verlangen ein Release-Review durch den Windows & Release Engineer (Autor ≠ Prüfer) und die
Orchestrator-Freigabe (`.claude/rules/60-collaboration.md`).

## 1. Ausgangslage (aus dem Quellcode gelesen)
| Aspekt | Stand im Code | Folge für den Build |
|---|---|---|
| Starter | `backend/leventum/desktop.py`: uvicorn auf `127.0.0.1` (freier Port) im Thread + `pywebview`-Fenster; `--browser`, `--port` | Einstiegspunkt für den Build; `webview` wird erst im Fenstermodus importiert |
| Datenpfad | `config.py`: Windows-Standard `%LOCALAPPDATA%\Leventum` (Unterordner `db`, `documents`, `backups`); überschreibbar per `LEVENTUM_DATA_DIR`, `LEVENTUM_DOCUMENTS_DIR`, `LEVENTUM_BACKUP_DIR` | Daten liegen bereits **außerhalb** eines Programmordners – beibehalten |
| Migrationen | `main.py`: `BACKEND_DIR = Path(__file__).resolve().parent.parent`; `alembic.ini` und `alembic/` werden dort gesucht; Migration läuft bei **jedem** Start (`run_migrations` → `upgrade head`) | **Risiko:** `pyproject.toml` packt nur `leventum*`, nicht `alembic/` und `alembic.ini` → normale `pip install .` vermutlich nicht lauffähig; PyInstaller muss beides als Daten bündeln **und** `BACKEND_DIR` im gefrorenen Zustand korrekt auflösen (Codeänderung nötig, siehe 3.4) |
| Frontend | `main.py`: `settings.frontend_dist` oder `<repo>/frontend/dist`; Mount `/assets`, SPA-Fallback | `dist` muss mitgeliefert und per `LEVENTUM_FRONTEND_DIST`/Code gefunden werden |
| Backup | `services/backup.py`, `backup_crypto.py` (AES-256-GCM, scrypt via `cryptography`) | `cryptography` hat native Bibliotheken → versteckte Importe/Hooks prüfen |
| Version | `backend/leventum/__init__.py` `__version__ = "0.1.0"`; `backend/pyproject.toml` `version = "0.1.0"`; `frontend/package.json` `0.1.0`; `main.py` setzt `version="0.1.0"` fest | Drei bis vier Versionsstellen – Release-Prozess muss sie abgleichen (Einzelquelle fehlt) |
| Abhängigkeiten | siehe 2 | Python-Audit-Werkzeug nicht eingerichtet |

## 2. Abhängigkeitsliste (Plan)
**Laufzeit (aus `backend/pyproject.toml`, gelesen):** fastapi ≥ 0.115, uvicorn ≥ 0.30, sqlalchemy ≥ 2.0, alembic ≥ 1.13, argon2-cffi ≥ 23.1, pydantic ≥ 2.7,
pydantic-settings ≥ 2.3, python-multipart ≥ 0.0.9, cryptography ≥ 42. **Desktop-Extra:** pywebview ≥ 5.0.

**Zusätzlich für den Build (noch nicht in `pyproject.toml`, Aufnahme als eigenes Extra, z. B. `build`, zu entscheiden):**
| Komponente | Zweck | Anmerkung / Prüfpunkt |
|---|---|---|
| PyInstaller | Python-Anwendung zu EXE bündeln | Version fixieren; Kompatibilität mit Python-Version prüfen; pywebview/uvicorn-Hooks prüfen |
| pywebview (Windows) | Fensterhülle; zieht auf Windows laut Dokumentation u. a. `pythonnet`/`clr`-Abhängigkeiten (Annahme, zu prüfen) | Backend-Wahl (Edge/WebView2) beim Build bestätigen; DLL-Einbindung prüfen |
| WebView2 Runtime / Bootstrapper | Rendering-Engine; **nicht** Teil der Python-Pakete | Evergreen-Bootstrapper (`MicrosoftEdgeWebview2Setup.exe`) von Microsoft; Lizenz/Weitergabebedingungen und Offline-Variante prüfen; Download durch den **Installer** (ausgehende Verbindung bei der Installation – bewusst entscheiden, Alternative: Offline-Installer mitliefern) |
| Node.js/npm | nur zum Bau des Frontends (`npm ci && npm run build`) | Kein Bestandteil der Auslieferung |
| Installer-Werkzeug | siehe 4 | Entscheidung offen |
| Signierwerkzeug (`signtool`) | siehe 5 | Zertifikat nicht vorhanden |
| (Optional) `pip-audit` | Python-Schwachstellenprüfung | Bisher **nicht installiert/ausgeführt** → „nicht geprüft“ (`dependency-audit`-Skill) |

Neue Abhängigkeiten nur mit Lizenz-/Telemetrie-/Netzwerkprüfung (`.claude/skills/dependency-audit/SKILL.md`); keine Abhängigkeit mit ausgehender Verbindung.

## 3. Struktur eines PyInstaller-Builds (Entwurf)
### 3.1 Modus
`--onedir` empfohlen (Annahme: schnellerer Start, weniger Antiviren-Fehlalarme als `--onefile`, einfachere Fehlersuche); `--onefile` entpackt bei jedem Start in einen Temp-Ordner
(Defender-/Startzeit-Risiko, zu prüfen). Fenster-Variante ohne Konsole (`--windowed`) erst, wenn Logging in Datei geklärt ist (Fehler sonst unsichtbar).

### 3.2 Datenverzeichnis außerhalb des Programmordners
- Programmordner (z. B. `%LOCALAPPDATA%\Programs\Leventum` oder `C:\Program Files\Leventum`) ist **schreibgeschützt/austauschbar** gedacht; Benutzerdaten bleiben in `%LOCALAPPDATA%\Leventum` (Standard aus `config.py`).
- Datenordner **nie** vom Installer/Updater/Deinstaller überschrieben oder gelöscht. Keine Daten relativ zur EXE.
- `.env` wird von `pydantic-settings` relativ zum **Arbeitsordner** gelesen (`env_file=".env"`): Arbeitsordner der gestarteten Anwendung festlegen (z. B. Datenordner), damit keine fremde `.env` aufgenommen wird (zu prüfen).

### 3.3 Einzubettende Ressourcen (`datas`)
| Ressource | Quelle | Zielort im Bundle | Hinweis |
|---|---|---|---|
| Frontend | `frontend/dist/` (Ergebnis von `npm run build`) | `frontend/dist` | `frontend_dist` per Standardsuche oder Umgebungsvariable setzen |
| Alembic | `backend/alembic/` (inkl. `versions/`, `env.py`, `script.py.mako`), `backend/alembic.ini` | wie im Quellbaum relativ zu `BACKEND_DIR` | Siehe 3.4; Migrationsdateien sind Python-Module, die von Alembic per Pfad geladen werden (Annahme: werden von der Importanalyse **nicht** erfasst) |
| Weitere Ressourcen | falls Vorlagen/Texte im Paket (`leventum/...`) als Nicht-Python-Dateien existieren: vor dem Build per Suche ermitteln | – | Nicht geprüft |

### 3.4 Notwendige Codeprüfungen/-änderungen (NICHT durchgeführt; Entscheidung des Orchestrators, `main.py` ist zentrale Datei)
`BACKEND_DIR` basiert auf `__file__`. Im PyInstaller-Bundle liegt `__file__` im Entpackordner (`sys._MEIPASS`); ob `alembic.ini`/`alembic/` dort an der erwarteten relativen Position liegen, hängt von den `datas`-Zielpfaden ab (zu prüfen). Optionen: (a) `datas` so platzieren, dass die Relativpfade stimmen; (b) Pfadauflösung in `main.py` um `sys.frozen`/`sys._MEIPASS` erweitern; (c) Alembic-Skriptort über Konfiguration/Umgebungsvariable. Jede Variante ist eine Änderung an einer zentralen Datei → Review und Entscheidungsdokument (`docs/decisions/NNNN-…`).

### 3.5 Versteckte Importe (Prüfliste, zu verifizieren – nicht raten)
Kandidaten, die PyInstaller-Analyse evtl. nicht findet (Annahme): `uvicorn` Protokoll-/Loop-Module (`uvicorn.logging`, `uvicorn.loops.*`, `uvicorn.protocols.*`, `uvicorn.lifespan.*`), SQLAlchemy-SQLite-Dialekt (`sqlalchemy.dialects.sqlite`), `alembic`-Templates/-DDL-Implementierung (`alembic.ddl.sqlite`), `argon2` (cffi-Backend), `cryptography`-Backends, `pydantic`/`pydantic_settings`, `multipart` (`python_multipart`), pywebview-Plattformmodul (`webview.platforms.edgechromium` / `winforms`, abhängig von der pywebview-Version), `leventum.models`-Untermodule (dynamische Importe in `services/documents.py::_model` – dort lazy Import). Vorgehen: Build, Start mit Konsole, alle Importfehler sammeln, Hooks/`--hidden-import` ergänzen; **jede Ergänzung durch einen Lauf belegen**.

### 3.6 Ablauf (Entwurf)
1. Sauberer Checkout, Git-Status sauber, Version erhöht und abgeglichen.
2. Backend-Tests, Frontend-Tests/Build, E2E (Linux) – Nachweis speichern.
3. `npm ci && npm run build` → `frontend/dist`.
4. PyInstaller-Build in frischer venv mit fixierter Abhängigkeitsliste (Lock-/Constraints-Datei zu erstellen, noch nicht vorhanden).
5. Smoke-Test des gebündelten Programms (analog `scripts/windows_smoke_test.ps1`, dann Testplan-Matrix) **auf einer sauberen Windows-VM ohne Python**.
6. Installer bauen (4), signieren (5), Hashwerte (SHA-256) der Artefakte dokumentieren.
7. Release-Checkliste (8) abarbeiten.

## 4. Installer-Optionen (nur Vor-/Nachteile; Entscheidung offen, Aussagen = Annahmen)
| Option | Mögliche Vorteile | Mögliche Nachteile / offene Fragen |
|---|---|---|
| **Inno Setup** (klassischer EXE-Installer) | Verbreitet, skriptbar, Pro-Benutzer-Installation ohne Admin möglich; flexible Pre-/Post-Install-Logik (WebView2-Prüfung, Prozessprüfung); Deinstaller lässt sich so konfigurieren, dass Datenordner unangetastet bleibt | Signierung separat; Update-Logik selbst zu bauen; SmartScreen-Reputation hängt von Signatur ab; Werkzeug zusätzlich zu beschaffen |
| **MSIX** | Saubere Installation/Deinstallation, Containerisierung, Update-Mechanismen im Paketformat | Signierung (vertrauenswürdiges Zertifikat) praktisch Pflicht; **Virtualisierung von Dateisystem/Registry kann `%LOCALAPPDATA%`-Zugriffe umleiten** (Datenort/Backup-Pfade müssten geprüft werden – hohes Risiko für diese App); Verteilung außerhalb des Stores/Sideloading-Voraussetzungen; Python/pywebview-Kompatibilität ungeprüft |
| MSI (z. B. WiX) | Unternehmens-/GPO-Verteilung | Höherer Aufwand; WebView2-Prüfung/Datenordner-Regeln aufwendiger |
| Portable ZIP (`--onedir`, kein Installer) | Einfachster Start, kein Installer-Risiko, Update = Ordner ersetzen (Daten bleiben extern) | Keine Startmenü-Verknüpfung/Deinstallation; WebView2-Prüfung manuell; Anwenderfehler (Daten im Programmordner ablegen) |
Empfehlung für den ersten Pilot (Vorschlag, keine Behauptung): zunächst **portables `--onedir`-ZIP** zur Risikominimierung, danach Inno Setup bewerten; MSIX wegen der Dateisystem-Virtualisierung zurückstellen. Entscheidung trifft der Mensch; Entscheidungsdokument anlegen.

## 5. Signierung (Plan)
- Ohne Codesignatur ist mit SmartScreen-/Defender-Warnungen zu rechnen (Annahme). Zertifikat (Code-Signing, ggf. EV) ist **nicht vorhanden**; Beschaffung, Verwahrung des Schlüssels (HSM/Token), Verantwortlichkeit und Kosten sind eine Entscheidung des Menschen.
- Zu signieren: EXE(s), Installer, ggf. DLLs im Bundle; Zeitstempel-Server verwenden (**ausgehende Verbindung beim Signieren – nur auf der Build-Maschine, nicht in der App**).
- Signaturschlüssel/Passwörter nie im Repository/in Logs.
- Prüfpunkte: Signatur gültig (`signtool verify`), SmartScreen-Verhalten auf frischer VM, Defender-Verhalten bei `--onefile` vs. `--onedir`.

## 6. WebView2-Runtime-Prüfung und -Installation (Plan)
1. Installer/Starter prüft, ob eine WebView2-Runtime vorhanden ist (typisch über Registry-Eintrag der Runtime unter EdgeUpdate-Clients; **genauer Pfad/Schlüssel noch zu verifizieren**; `scripts/windows_smoke_test.ps1` nutzt dafür einen ungeprüften Pfad).
2. Fehlt sie: (a) Bootstrapper vom Installer starten (benötigt Internet), oder (b) Offline-Runtime mitliefern (größere Artefakte, Pflege), oder (c) klare Fehlermeldung mit Anleitung. Entscheidung offen. Windows 11 enthält die Runtime laut Microsoft-Dokumentation vorinstalliert (Annahme, zu prüfen); Windows 10 nicht zwingend.
3. Start der Anwendung bei fehlender Runtime: Verhalten von pywebview ungeprüft (Testfall WIN-ST-05); `desktop.py` hat derzeit **keine** eigene verständliche Fehlermeldung bei fehlendem pywebview (`import webview` ungeschützt) – Anpassung wäre eine Codeänderung außerhalb dieses Auftrags.
4. Keine automatische Installation ohne Wissen der Nutzerin; Installer weist auf den Download hin (Datenschutz: nur Microsoft-Download, keine Übertragung von Anwendungsdaten).

## 7. Update- und Deinstallationsregeln (Plan)
1. **Daten nie überschreiben:** Installer/Updater schreibt ausschließlich in den Programmordner; `%LOCALAPPDATA%\Leventum` (und konfigurierte Daten-/Dokument-/Backupordner) werden nie angelegt-überschrieben, geleert oder gelöscht.
2. **Backup vor Migration:** Vor dem Start einer neuen Version mit höherem Schema (Migrationen laufen automatisch in `create_app`) muss ein Backup entstehen. Aktuell **nicht** implementiert: `run_migrations` läuft ohne vorheriges Backup. Optionen: Installer/Starter erzeugt vor dem ersten Start der neuen Version ein Backup (setzt laufende/ältere Version voraus) oder Start der neuen Version prüft die Schema-Revision und erstellt vorher ein Backup (Codeänderung in zentraler Datei → Orchestrator, Database Architect, QA). Bis dahin im Update-Verfahren als **manueller Pflichtschritt** („Backup prüfen“) dokumentieren.
3. **Keine Downgrades:** Ältere Programmversion auf neuerem Schema nicht starten (Schema-Revision im Manifest; Downgrade-Migrationen sind Testfälle, kein Betriebsweg). Installer verhindert/warnt vor Versionsrückgang (Annahme zu klären).
4. **Laufende Instanz:** Installer/Updater erkennt laufende App (Prozess/Port) und fordert Schließen; keine Dateiersetzung unter laufendem Prozess.
5. **Deinstallation:** Entfernt Programmdateien/Verknüpfungen; Datenordner bleibt standardmäßig **unangetastet**; ein „Daten löschen“-Angebot (falls überhaupt) nur als ausdrücklich bestätigte, getrennte Aktion mit Warnung – Löschen von Daten ist eine Eskalation an den Menschen.
6. **Fehlschlag/Rollback:** Schlägt eine Migration fehl, bleibt der alte Stand (Backup) erhalten; Rückweg über Restore dokumentieren und testen (WIN-UPD-03).
7. Tests: Matrix K in `docs/WINDOWS_TESTPLAN.md`.

## 8. Release-Checkliste (Entwurf; jede Zeile mit Beleg, Statusstufen getrennt)
| # | Punkt | Beleg/Nachweis | Status |
|---|---|---|---|
| 1 | Versionsstand abgeglichen (`__init__.py`, `pyproject.toml`, `package.json`, `main.py`-Titelversion) und erhöht | Diff | offen |
| 2 | Git-Status sauber, richtiger Branch, Commit-Hash dokumentiert | `git status`, Hash | offen |
| 3 | Backend-Suite, Frontend-Tests/Build, Browser-E2E, Responsive – Ergebnis mit Zahlen/Datum | Ausgabe | offen |
| 4 | Migrationen: Upgrade/Downgrade, Altdatentest, Revisions-Assertion aktuell (`test_backup_migrations.py`) | Testausgabe | offen |
| 5 | Backup vor Update/Migration vorgesehen und **getestet** (siehe 7.2) | Restore-Drill, WIN-UPD-01 | offen |
| 6 | Dependency-Audit: `npm audit` (voll und `--omit=dev`); Python-Audit-Werkzeug eingerichtet oder „nicht geprüft“ berichtet | Ausgabe/Vermerk | offen |
| 7 | Build reproduzierbar aus sauberem Checkout; Abhängigkeiten fixiert | Build-Log, Hashwerte | offen |
| 8 | Windows-Testplan: alle Freigabeblocker B1–B12 bestanden mit Ergebnisprotokoll | `docs/WINDOWS_TESTPLAN.md` + Protokolle | offen (alle Fälle offen) |
| 9 | Smoke-Test auf sauberer VM ohne Python/Node | Ergebnisdatei | offen |
| 10 | Signatur gültig (falls vorgesehen); SmartScreen-Verhalten dokumentiert | `signtool verify`, Screenshot | offen |
| 11 | Sicherheitsreview (Security & Privacy Engineer): Bindung, Header, keine ausgehenden Verbindungen, keine Secrets in Logs | Review-Bericht | offen |
| 12 | Release-Review durch Windows & Release Engineer (≠ Autor des Builds) + Orchestrator-Freigabe | Review-Bericht | offen |
| 13 | Bekannte Einschränkungen im Release-Bericht (siehe 9 und `docs/ABSCHLUSSBERICHT_MASTER_REVIEW.md`), Verschlüsselung ehrlich (nur Backups optional; DB/Dokumente unverschlüsselt, BitLocker) | Bericht | offen |
| 14 | Anwenderhinweise: Backup-Routine, Datenordner, BitLocker, WebView2 | Doku | offen |
| 15 | Freigabe/Go-Live: **menschliche Entscheidung** | Dokumentierte Entscheidung | offen |

## 9. Bekannte Risiken (Stand: aus Quellcode-Lektüre; ungetestet)
| # | Risiko | Quelle | Gegenmaßnahme (Plan) |
|---|---|---|---|
| R1 | Normale `pip install .` findet `alembic.ini`/`alembic/` vermutlich nicht (`BACKEND_DIR` aus `__file__`, Paketdaten fehlen) | `main.py`, `pyproject.toml` | Pfadauflösung/Packaging klären (3.4), Test auf sauberer VM |
| R2 | Migration läuft bei jedem Start ohne Backup | `main.py::create_app` | Backup-vor-Migration-Mechanismus (7.2) |
| R3 | Restore überschreibt die DB-Datei und benennt `documents` um; unter Windows können Dateisperren (offene Handles, Defender, Explorer) zu `PermissionError` führen; nicht als `BackupError` abgefangen → möglicher Halbzustand (DB schon ersetzt, Dokumente nicht) | `services/backup.py::restore_backup`, `api/routers.py` | WIN-BR-07/-08 früh testen; ggf. Restore beim nächsten Start (vor DB-Öffnung) ausführen – Designentscheidung, zentrale Dateien |
| R4 | `Content-Disposition: filename="…"` ohne RFC-5987-Kodierung; Nicht-Latin-1-Zeichen im Dateinamen könnten Serverfehler auslösen | `api/finance.py::documents_download` | WIN-WV-11 / Linux-Test; Korrektur durch Fachagent |
| R5 | Keine Einzelinstanz-Sperre; feste/belegte Ports: Bind-Fehler im Thread und Health-Schleife könnten fehlinterpretiert werden; zwei Instanzen auf derselben SQLite-Datei | `desktop.py` | WIN-ST-06/-07; Sperrdatei/Port-Fehlermeldung als Codeänderung vorschlagen |
| R6 | `import webview` ohne Fehlerbehandlung; keine verständliche Meldung bei fehlendem pywebview/WebView2 | `desktop.py` | WIN-ST-04/-05; Meldung als Codeänderung vorschlagen |
| R7 | `ALLOW_DOWNLOADS` in `try/except`: bei fehlender Einstellung still ignoriert → Downloads evtl. nicht möglich | `desktop.py` | WIN-WV-10; pywebview-Version festlegen |
| R8 | Antivirus-/Defender-Fehlalarme bei PyInstaller-EXE (`--onefile` besonders) | Allgemeinwissen, ungeprüft | `--onedir`, Signatur, Test auf VM |
| R9 | MAX_PATH (260) bei tiefen Datenordnern | Windows allgemein, ungeprüft | WIN-FS-04 |
| R10 | SQLite/WAL auf Netzlaufwerk/Cloud-Sync-Ordnern | Allgemeinwissen | Nicht unterstützen; Hinweis in Anwenderdoku |
| R11 | DB und Dokumente unverschlüsselt (nur Backups optional verschlüsselt) | `docs/04-sicherheit-backup.md` | BitLocker-Hinweis; ehrliche Berichterstattung |
| R12 | Kein Python-Schwachstellen-Audit; `npm audit`: Produktivabhängigkeiten react-router (2 Meldungen mittlerer Schwere laut `docs/04-sicherheit-backup.md`, Stand dort) | `docs/04-sicherheit-backup.md` | Audit vor Release erneut ausführen und bewerten |
| R13 | Versionsangaben an mehreren Stellen (inkl. fest verdrahtete Version in `main.py`) | `main.py`, `pyproject.toml`, `package.json`, `__init__.py` | Release-Checkliste Punkt 1 |
| R14 | Update-Pfad (neue Version auf alte Daten) auf Windows nie getestet | – | Matrix K |
| R15 | MSIX-Dateisystem-Virtualisierung könnte Datenpfade umleiten (falls MSIX gewählt) | Allgemeinwissen, ungeprüft | MSIX zurückstellen bzw. gesondert testen |

## 10. Offene Entscheidungen (für den Menschen/Orchestrator)
1. Installer-Format (Portable ZIP / Inno Setup / MSIX / MSI) und Pilotumfang.
2. Code-Signing-Zertifikat: ja/nein, Art, Verantwortlicher.
3. WebView2: Bootstrapper (Online) vs. Offline-Runtime vs. nur Hinweis.
4. Umgang mit Backup-vor-Migration (7.2) und Restore-Design (R3) – Änderungen an zentralen Dateien (`main.py`, `services/backup.py`).
5. Python-Audit-Werkzeug einführen (Abhängigkeitsfreigabe).
6. Versions-Einzelquelle.

## 11. Statushinweis
Dieses Dokument: **Geplant/Erstellt**. Nicht getestet, nicht unter Windows getestet, nicht unabhängig geprüft, nicht freigegeben. Es existiert kein Installer und kein Build-Skript.
