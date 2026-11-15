# Leventum Verwaltung (Rent-to-Rent)

Lokale Windows-Desktop-Anwendung (FastAPI + React/TypeScript + SQLite, später PostgreSQL) zur Verwaltung von Hauptmiet- und Untermietverhältnissen.
Dokumentation: [`docs/`](docs/) · Berichte: [`Phase A+B`](docs/ABSCHLUSSBERICHT_PHASE_A_B.md) · [`Phase C`](docs/ABSCHLUSSBERICHT_PHASE_C.md) · [`Phase D`](docs/ABSCHLUSSBERICHT_PHASE_D.md)

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

## Datenspeicher
Standard: `%LOCALAPPDATA%\Leventum` (Windows) bzw. `~/.local/share/leventum`. Überschreibbar über `LEVENTUM_DATA_DIR`, `LEVENTUM_DATABASE_URL`, `LEVENTUM_DOCUMENTS_DIR`, `LEVENTUM_BACKUP_DIR`.
Schema-Änderungen ausschließlich über Alembic (`backend/alembic`); Migrationen laufen beim Start automatisch.
Die SQLite-Datenbank ist nur für den Einzelplatzbetrieb gedacht. Für mehrere gleichzeitige Nutzer ist PostgreSQL vorgesehen (nicht getestet, siehe `docs/01-architektur.md`).

## Manuelle Browser-Durchläufe (Playwright, optional)
`frontend/e2e/phase-c.cjs` und `frontend/e2e/phase-d.cjs` – Anleitung im Kopf der Dateien (frische Datenbank, laufender Server).
