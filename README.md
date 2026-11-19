# Leventum Verwaltung (Rent-to-Rent)

Lokale Windows-Desktop-Anwendung (FastAPI + React/TypeScript + SQLite, später PostgreSQL) zur Verwaltung von Hauptmiet- und Untermietverhältnissen.
Dokumentation: [`docs/`](docs/) · Berichte: [`Phase A+B`](docs/ABSCHLUSSBERICHT_PHASE_A_B.md) · [`Phase C`](docs/ABSCHLUSSBERICHT_PHASE_C.md) · [`Phase D`](docs/ABSCHLUSSBERICHT_PHASE_D.md) · [`Phase E`](docs/ABSCHLUSSBERICHT_PHASE_E.md) · [`Master-Review`](docs/ABSCHLUSSBERICHT_MASTER_REVIEW.md) · [`UI-Prüfung mit Screenshots`](docs/UI_PRUEFBERICHT_SCREENSHOTS.md)

## Entwicklung
```bash
python -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e "backend[dev]"
(cd frontend && npm install && npm run build)          # Frontend bauen
python -m pytest backend                               # Backend-Tests
(cd frontend && npm test)                              # Frontend-Tests
python -m leventum.desktop --browser                   # Server starten, URL wird ausgegeben
pip install -e "backend[desktop]" && python -m leventum.desktop   # Fenster via pywebview/WebView2 (nur Windows getestet werden – bisher NICHT geprüft)
```
Frontend-Entwicklung mit Hot-Reload: Backend auf Port 8000 starten, `npm run dev` (Proxy auf `/api`).

## Demo starten (erfundene Daten)
```bash
. .venv/bin/activate && python -m leventum.demo --open     # legt Demo-Daten an (eigenes Verzeichnis neben dem echten), startet den Server, gibt Benutzer/Passwort aus
python -m leventum.demo --reset                            # Demo-Daten neu anlegen (löscht nur Verzeichnisse mit Markierung .leventum-demo)
```
Die Demo schreibt nie in das echte Datenverzeichnis, legt alle Daten über die REST-API an (Termine relativ zu heute) und blendet im Programm einen Demo-Hinweis ein.
Ablauf-Prüfung der Oberfläche gegen den laufenden Demo-Server: `DEMO_URL=… DEMO_PASSWORD=… NODE_PATH=$(npm root -g) node frontend/e2e/demo-flow.cjs`.

## Windows-Installer
Vorbereitet (`packaging/`, `docs/WINDOWS_INSTALLER.md`), aber **nicht gebaut und nicht unter Windows getestet**.

## Datenspeicher
Standard: `%LOCALAPPDATA%\Leventum` (Windows) bzw. `~/.local/share/leventum`. Überschreibbar über `LEVENTUM_DATA_DIR`, `LEVENTUM_DATABASE_URL`, `LEVENTUM_DOCUMENTS_DIR`, `LEVENTUM_BACKUP_DIR`.
Schema-Änderungen ausschließlich über Alembic (`backend/alembic`); Migrationen laufen beim Start automatisch.
Die SQLite-Datenbank ist nur für den Einzelplatzbetrieb gedacht. Für mehrere gleichzeitige Nutzer ist PostgreSQL vorgesehen (nicht getestet, siehe `docs/01-architektur.md`).

## Automatisierte Browser-Tests (Playwright/Chromium)
```bash
(cd frontend && npm run build)
(cd frontend && NODE_PATH=$(npm root -g) npm run e2e)    # startet eigenen Server mit temporärer Datenbank, 21 Abläufe, Exit-Code 0/1
NODE_PATH=$(npm root -g) node frontend/e2e/responsive.cjs <URL> <Ausgabeordner>   # Überlauf-Prüfung 4 Viewports (Instanz mit Demodaten)
```
Die Suite läuft in **Chromium**, nicht im pywebview/WebView2-Fenster. Windows-Prüfung: [`docs/WINDOWS_TESTPLAN.md`](docs/WINDOWS_TESTPLAN.md) (**nicht durchgeführt**).

## Manuelle Browser-Durchläufe (Playwright, optional)
`frontend/e2e/phase-c.cjs`, `phase-d.cjs` und `phase-e.cjs` – Anleitung im Kopf der Dateien (frische Datenbank, laufender Server).

`frontend/e2e/seed-and-shoot.cjs` befüllt eine **frische** Instanz mit erfundenen Demodaten und erzeugt die Screenshots in `docs/screenshots/` (nur für Abnahme/Doku, nie gegen echte Daten).
