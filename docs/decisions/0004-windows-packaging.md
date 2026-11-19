# 0004 – Windows-Paketierung (PyInstaller onedir + Inno Setup, pro Benutzer)

Status: **Vorgeschlagen, nicht freigegeben** (Orchestrator-Freigabe und Release-Review durch einen unabhängigen Prüfer stehen aus).

## Kontext
Ziel ist ein auf Windows ohne Entwicklungsumgebung installierbares Programm. Bestehende Architektur: FastAPI-Server auf 127.0.0.1 + pywebview/WebView2 (`desktop.py`), Daten unter `%LOCALAPPDATA%\Leventum`.
`main.py` löste `alembic/`, `alembic.ini` und das Frontend relativ zu `__file__` auf; das funktioniert in einem gebündelten Programm nicht.

## Entscheidung
- **PyInstaller `--onedir`** (zwei Programme: `Leventum.exe` ohne Konsole, `LeventumServer.exe` mit Konsole als Diagnose-/Browser-Fallback), Spec: `packaging/leventum.spec`.
- **Inno Setup 6**, Installation **pro Benutzer** (`{localappdata}\Programs\Leventum`, kein Administrator), Desktop-/Startmenü-Verknüpfungen, Deinstaller löscht **keine** Benutzerdaten: `packaging/leventum.iss`.
- **Codeänderung (zentrale Datei `main.py`)**: `RESOURCE_DIR`/`DEFAULT_FRONTEND_DIST` lösen im gebündelten Betrieb (`sys.frozen`, `sys._MEIPASS`) auf; im Quellbaum unverändert. Variante (b) aus `docs/WINDOWS_BUILD_PLAN.md` §3.4.
- **`desktop.py`**: Logdatei im Datenordner, wenn keine Konsole existiert (sonst Absturz beim Logging); `--demo` startet eine **frische**, getrennte Demo-Datenbank (Reset nur mit Markierung `.leventum-demo`), Zufallspasswort wird im Fenster/auf der Konsole gezeigt, nie gespeichert/eingebettet.
- Demo-Starter-Härtung nach unabhängigem Review: Abbruch bei gesetzten `LEVENTUM_DATABASE_URL/DOCUMENTS_DIR/BACKUP_DIR`; kein Ziel gleich/über/in dem echten Datenverzeichnis, Home, Arbeitsordner oder Wurzel; Markierung mit Kennung; Aufräumen bei Fehlschlag.
- `httpx` wandert ins Extra `desktop` (die Demo seedet über `fastapi.testclient`).

## Folgen
- Benutzerdaten bleiben bei Update/Deinstallation erhalten. Demo und Produktivdaten liegen in getrennten Ordnern (`Leventum` vs. `leventum-demo`).
- Ohne Codesignatur sind SmartScreen-/Defender-Warnungen zu erwarten (Annahme). Kein Icon, keine Versionsinfo, kein Auto-Update.
- WebView2-Runtime ist keine Paketabhängigkeit; der Installer prüft die Registry und weist hin (Annahme zu den Registry-Schlüsseln, ungetestet).

## Alternativen
MSIX (Dateisystem-Virtualisierung kann `%LOCALAPPDATA%`-Zugriffe umleiten, Signierung nötig), `--onefile` (Entpacken bei jedem Start, Defender), MSI/WiX (höherer Aufwand), portables ZIP (kein Deinstaller).
