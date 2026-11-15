# 01 – Architekturübersicht (Phase A)

Stand: Phase A/B. Status-Legende: **[geplant]**, **[implementiert]**, **[getestet]** – siehe `ABSCHLUSSBERICHT_PHASE_A_B.md`.

## 1. Technische Ausgangslage

| Punkt | Befund |
|---|---|
| Repository | Leer (keine Commits, keine Dateien). Es gibt keinen Bestand, der weiterverwendet oder erhalten werden müsste. |
| Referenz-UI | Dashboard-Abbildung (Screenshot). Kein Logo als Vektordatei vorhanden → Platzhalter-Logo, siehe Offene Entscheidungen. |
| Entwicklungsumgebung | Linux-Container, Python 3.13, Node 22. **Kein Windows, kein WebView2, keine GUI.** Der Desktop-Wrapper und der Windows-Build sind hier nicht testbar. |
| Zielumgebung | Windows-PC, Einzelplatz, lokal. |

Konsequenz: Der Tech-Stack aus dem Masterprompt wird unverändert übernommen (kein Grund zur Abweichung):
FastAPI · SQLAlchemy 2 · Alembic · SQLite → PostgreSQL · React + TypeScript (Vite) · pywebview/WebView2 · pytest.

## 2. Schichtenmodell

```
┌──────────────────────────────────────────────────────────────┐
│ Desktop-Hülle (pywebview + WebView2)   – optional, austauschbar │
│   startet Server auf 127.0.0.1:<freier Port>, öffnet Fenster     │
├──────────────────────────────────────────────────────────────┤
│ Frontend (React/TS, Vite)  – reine Darstellung, keine Fachlogik   │
├───────────────────────── REST /api/v1 ───────────────────────┤
│ API-Schicht (FastAPI-Router, Pydantic-Schemas, Auth/Permissions) │
├──────────────────────────────────────────────────────────────┤
│ Services (Fachlogik: Verträge, Forderungen, Wirtschaftlichkeit…) │
├──────────────────────────────────────────────────────────────┤
│ Datenzugriff (SQLAlchemy-Modelle, Session, Alembic)             │
│ Dateispeicher (FileStore-Interface → LocalFileStore)             │
├──────────────────────────────────────────────────────────────┤
│ SQLite (heute)  ──────────────►  PostgreSQL (später)            │
└──────────────────────────────────────────────────────────────┘
```

Regeln:
1. **Fachlogik nur im Backend** (`leventum/services`). Das Frontend rendert Ergebnisse und validiert nur zur Bedienkomfort-Zwecken; maßgeblich ist immer das Backend.
2. **Router enthalten keine Geschäftslogik**, sie rufen Services auf.
3. **Services kennen kein SQLite.** Keine `PRAGMA`s, kein `rowid`, keine SQLite-Funktionen außerhalb von `leventum/db/engine.py`.
4. **Geldbeträge sind niemals `float`.** Typ `Money` (Decimal in Python, skaliertes `BIGINT` in der DB, Cent-genau, auf SQLite und PostgreSQL identisch).
5. **Zeitstempel in UTC**, Datumsfelder (Vertragsbeginn, Fälligkeit) als `DATE` ohne Zeitzone.
6. **Dateien nur über `FileStore`** mit relativen, nicht erratbaren Schlüsseln. Kein absoluter Pfad in der Datenbank.
7. **Konfiguration zentral** (`leventum/config.py`, Präfix `LEVENTUM_`). Speicherorte sind konfigurierbar.
8. **Löschen ist die Ausnahme**: Finanzdaten werden storniert/korrigiert, nicht überschrieben (siehe Datenmodell).

## 3. Verzeichnisstruktur

```
backend/
  leventum/
    config.py            zentrale Konfiguration
    db/                  Engine, Session, Basisklasse, Money-Typ
    models/              SQLAlchemy-Modelle
    services/            Fachlogik (Auth, Audit, Dashboard, Backup …)
    security/            Passwort-Hashing, Sessions, Berechtigungen
    storage/             FileStore (lokal)
    api/                 Router, Abhängigkeiten, Schemas
    main.py              App-Fabrik (create_app)
    desktop.py           pywebview-Starter
  alembic/               Migrationen
  tests/
frontend/                React/TS (Designsystem + Seiten)
docs/                    Phase-A-Dokumente
```

## 4. Eignung für PostgreSQL und Mehrbenutzerbetrieb – Bewertung

**Ergebnis: Die Architektur unterstützt beides, mit klar benannten Voraussetzungen. Es wurde NICHT gegen PostgreSQL getestet** (in dieser Umgebung nicht verfügbar); das ist ein offener Punkt für Phase F.

Bereits berücksichtigt:
- Ausschließlich SQLAlchemy-Core/ORM, generische Typen (`JSON`, `Date`, `DateTime(timezone=True)`), kein rohes SQL in Fachmodulen.
- Alembic mit `render_as_batch=True` (nötig für SQLite-ALTER, auf PostgreSQL harmlos). Benannte Constraints per `naming_convention`, sonst sind Migrationen auf SQLite nicht änderbar.
- Server-seitige Sitzungen (keine Prozess-lokalen Zustände) → mehrere Prozesse/Nutzer möglich.
- Geld/Mengen als Integer-skaliert → keine Rundungsunterschiede zwischen Datenbanken.
- Audit-Ereignisse mit `actor_user_id` von Anfang an.
- Die Datenbank-URL ist Konfiguration (`LEVENTUM_DATABASE_URL`).

Bekannte Hürden bei der Umstellung (bewusst dokumentiert, nicht „weggeredet“):
| Hürde | Plan |
|---|---|
| SQLite erlaubt nur einen Schreiber; bei mehreren Mitarbeitern zwingend PostgreSQL | Umstellung vor Mehrbenutzerbetrieb. SQLite ist nur Einzelplatz. |
| Dokumente liegen im lokalen Dateisystem | `FileStore`-Interface; Serverbetrieb braucht Netzlaufwerk/Server-Verzeichnis oder S3-kompatiblen Store (zweite Implementierung). |
| Überschneidungsprüfung von Mietverträgen | Anwendungsebene (portabel). Auf PostgreSQL optional zusätzlich `EXCLUDE USING gist`. |
| Typ-Unterschiede (z. B. Groß-/Kleinschreibung bei Suche) | Suche über `lower(...) LIKE` bzw. SQLAlchemy `ilike`; keine FTS5-Abhängigkeit in Fachmodulen. Später PG-`tsvector` hinter derselben Service-Schnittstelle. |
| Datenübernahme | Export/Import-Werkzeug über das ORM (nicht über Datei-Kopie der DB). Geplant in Phase F. |
| Sitzungs-Cookies/TLS im Serverbetrieb | Serverbetrieb braucht HTTPS, `Secure`-Cookie, echte Benutzerverwaltung (bereits modelliert). |

## 5. Designsystem (verbindliche Referenz: Dashboard-Abbildung)

Aus dem Bild abgeleitete Tokens (Näherungswerte, per Pipette zu verfeinern):

| Token | Wert | Verwendung |
|---|---|---|
| `--color-ink` | `#0B1F4B` | Überschriften, Navigation, Tabellentext |
| `--color-ink-muted` | `#5B6B8C` | Sekundärtext |
| `--color-primary` | `#1D4ED8` | Akzent, aktive Navigation (Icon/Text) |
| `--color-primary-soft` | `#EAF1FF` | Aktiver Navigationspunkt, Hover, Icon-Kacheln |
| `--color-surface` | `#FFFFFF` | Hauptbereich, Karten |
| `--color-canvas` | `#F7F9FC` | Seitenhintergrund/Zeilenkopf |
| `--color-border` | `#E3E8F2` | Feine Rahmen |
| Status Aktiv | Text `#15803D` / BG `#DCF5E4` | Badge |
| Status Warnung | Text `#B45309` / BG `#FDEBD0` | Badge „Kündigung“ |
| Status Fehler | Text `#B91C1C` / BG `#FDE2E2` | Rückstand |

Layout: feste linke Sidebar (ca. 275 px) mit Logo und Navigation; Topbar mit globaler Suche, Benachrichtigungen, Benutzermenü; Hauptbereich mit Begrüßung, KPI-Karten (4–6 pro Zeile), Tabellenkarten, Detailkarte rechts. Radius 12–14 px, Rahmen 1 px, sehr dezente Schatten, keine Animationen außer Hover-Farbwechsel.

Wiederverwendbare Komponenten (Phase B): `AppShell`, `Sidebar`, `Topbar`, `Card`, `KpiCard`, `DataTable`, `Badge`, `Button`, `EmptyState`, `PageHeader`. Alle Farben ausschließlich über CSS-Variablen.
