# Windows-Installer und Demo-Version – Stand

**Kurzfassung:** Ein Installer (`Leventum_Setup.exe`) wurde **nicht gebaut**, weil in dieser Umgebung (Linux, kein Windows, kein Wine, kein Inno Setup) weder PyInstaller für Windows noch Inno Setup ausführbar sind. Vorbereitet und unter Linux belegt ist die Bündelung; alles Windows-Spezifische ist **implementiert, aber nicht getestet**.

## Statusstufen
| Baustein | Stufe | Beleg |
|---|---|---|
| Pfadauflösung im gebündelten Betrieb (`main.py`) | Quellbaum: automatisiert getestet (`test_desktop_launcher.py`); gebündelt: **manuell getestet (Linux, einmaliger Lauf, nicht im CI reproduzierbar)** | Linux-Build von `packaging/leventum.spec` lief mit leerer Umgebung: Migrationen, Frontend, Anmeldung, Backup (verschlüsselt), Neustart-Persistenz, Demo (Ergebnisse im Abschlussbericht des Auftrags, nicht als Datei im Repository) |
| `LeventumServer`/`Leventum` (PyInstaller, Linux) | **Manuell getestet (Linux, einmaliger Lauf)** | 12-Schritte-Demoablauf (`frontend/e2e/demo-flow.cjs`) gegen das gebündelte Programm: 12/12 |
| `desktop.py --demo`, Logdatei ohne Konsole | Hilfsfunktionen automatisiert getestet (Linux); `desktop.main()` selbst und der Fenstermodus **nicht** getestet; Browser-Modus manuell | `tests/test_desktop_launcher.py`, Lauf von `--browser --demo` |
| Fenstermodus (pywebview/WebView2), `--demo` im Fenster | Implementiert, **nicht getestet** | – |
| `packaging/build_windows.ps1`, `installer_smoke.ps1`, `leventum.iss`, `.github/workflows/windows-installer.yml` | Implementiert, **nie ausgeführt**, PowerShell-/Inno-Syntax **nicht geprüft** | – |
| Installer gebaut / auf sauberem Windows getestet | **Nicht erfolgt** | – |

## Installer bauen (auf Windows)
Voraussetzungen: Python 3.12/3.13 (64 Bit), Node.js 20+, Inno Setup 6.
```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
# -> build\installer\Leventum_Setup.exe, build\installer\SHA256.txt
powershell -File packaging\installer_smoke.ps1 -Setup build\installer\Leventum_Setup.exe   # stiller Server-Smoke-Test
```
Alternativ im Repository: GitHub-Aktion „windows-installer“ (manuell auslösbar; baut auf `windows-latest`, führt den Smoke-Test aus, lädt den Installer als Artefakt hoch). Noch nie gelaufen.

## Verhalten (Soll)
- Installation pro Benutzer nach `%LOCALAPPDATA%\Programs\Leventum`; Daten unter `%LOCALAPPDATA%\Leventum` (nicht im Programmordner, bei Deinstallation unangetastet).
- Startmenü: „Leventum“, „Leventum Demo (erfundene Daten)“ (frische Demo bei jedem Start, Passwort wird zufällig erzeugt und im Fenster gezeigt, Daten in `%LOCALAPPDATA%\leventum-demo`), „Leventum Browser-Modus (Diagnose)“.
- Logdatei (nur bei fehlender Konsole): normaler Betrieb `%LOCALAPPDATA%\Leventum\logs\leventum.log`; Demo-Betrieb im Geschwisterordner `%LOCALAPPDATA%\leventum-demo-logs\leventum.log` (bewusst NICHT im Demo-Datenverzeichnis). Das Demo-Passwort wird nie in eine Logdatei geschrieben (nur im Fenster oder auf einer echten Konsole).

## Manuelle Testfälle auf sauberem Windows (Pflicht vor jeder Aussage „unter Windows getestet“)
1 Installation ohne Entwicklungsumgebung · 2 erster Start · 3 Einrichtung/Anmeldung · 4 Dashboard · 5 Immobilien · 6 Mietverträge · 7 Zahlung · 8 Wirtschaftlichkeit · 9 Dokumente (Upload/Download im Fenster) · 10 Neustart · 11 Persistenz · 12 Deinstallation · 13 Daten noch vorhanden · zusätzlich: Demo-Verknüpfung, Fehlen von WebView2, SmartScreen-Verhalten, DPI-Skalierung. Detailplan: `docs/WINDOWS_TESTPLAN.md`.

## Offene Punkte nach der Zweitprüfung (dokumentiert, nicht behoben)
- **M-2:** Der Demo-Reset ist nicht gegen eine gleichzeitig laufende zweite Demo-Instanz abgesichert (feste Demo-Verzeichnis, Reset bei jedem Start; unter Windows kann `rmtree` an einer geöffneten SQLite-Datei scheitern). Betroffen sind nur markierte Demo-Verzeichnisse. Abhilfe später: Single-Instance-Sperre.
- **NTFS-Junctions:** Erkennung über `Path.is_junction` nur ab Python 3.12 (`pyproject` erlaubt 3.11); unter 3.11 nicht erkennbar. Relevant nur bei vorab manipuliertem Demo-Verzeichnis mit Markierung.
- **Lieferkette (L-6):** GitHub-Aktionen auf Tags statt Commit-SHA, `choco install innosetup`, `pyinstaller` und `pywebview` ungepinnt; Installer unsigniert.
- **N-1:** Ein teilweise gelöschtes Demo-Verzeichnis (z. B. gesperrte SQLite-Datei unter Windows beim Reset) kann ohne Markierung zurückbleiben; jeder weitere Demo-Start meldet dann „kein Demo-Verzeichnis“, bis der Ordner `%LOCALAPPDATA%\leventum-demo` von Hand gelöscht wird. Engines werden beim Seeding nicht geschlossen (`dispose`).
- **N-2:** `Leventum.exe --browser --demo` ohne Konsole zeigt das Demo-Passwort nirgends (Passwort wird bewusst nicht ins Log geschrieben).
- **N-3:** `_log_dir` ist nicht abgesichert; ein Fehler dort (z. B. ungültige Einstellung) tritt im Fensterbetrieb ohne Logdatei auf.
- **N-4:** `docs/decisions/0004-windows-packaging.md` und `packaging/leventum.spec` sagen „Logdatei im Datenordner“; im Demo-Betrieb liegt sie im Geschwisterordner (siehe oben). Text noch nicht angepasst.
- **N-5:** Port-Reservierung vor dem Serverstart (Zeitfenster); N-6/N-7 (Fehlertexte im Log, `German.isl`/Inno-Version) Informational.
- **Weitere Hinweise der Zweitprüfungen (nicht behoben):** `installer_smoke.ps1` setzt nur `LEVENTUM_DATA_DIR` – bei gesetzten `LEVENTUM_DATABASE_URL/DOCUMENTS_DIR/BACKUP_DIR` oder einer `.env` im Arbeitsordner könnte der Test echte Daten berühren (nur auf Entwicklerrechnern relevant; im CI-Runner nicht); Logdatei ohne Rotation, enthält ggf. personenbezogene Daten aus Tracebacks; `demo.py` nutzt für die Start-Prüfung den Systemproxy; ein Installationsverzeichnis gleich dem Datenordner ist wählbar.
- `desktop.main()` hat keinen automatisierten Test (kein gefälschtes `webview`-Modul); `frontend/e2e/demo-flow.cjs` ist nicht Teil von `npm run e2e` und nicht im CI.
- Das Inno-Skript trägt eine UTF-8-BOM (bytebasiert geprüft: `EF BB BF`); durch `tests/test_packaging_files.py` abgesichert.

## Bekannte Lücken
Keine Codesignatur, kein Icon/Versionsinfo, kein Auto-Update, WebView2-Prüfung nur per Registry (Annahme), Antiviren-Verhalten unbekannt, Python-/Abhängigkeitsaudit nicht eingerichtet (`pip-audit`), Version an vier Stellen gepflegt.
