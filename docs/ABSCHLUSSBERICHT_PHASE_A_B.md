# Abschlussbericht Phase A + B

Statuslegende: **Geplant** · **Implementiert** · **Getestet** (automatisiert ausgeführt, Ergebnis unten) · **Unabhängig geprüft** · **Freigegeben**.
Es gibt derzeit **keine** unabhängig geprüften und **keine** freigegebenen Bestandteile.

## 1. Was wurde implementiert?
**Phase A (Dokumentation, geplant → Entwurf vorhanden):** `docs/01…05` – Architektur, fachliches Datenmodell Rent-to-Rent, DB-Struktur, API-Module, Sicherheits-/Backupkonzept, Entwicklungsplan, 16 offene fachliche Fragen.

**Phase B (Fundament, implementiert):**
- Backend: Konfiguration, SQLAlchemy-Basis mit `Money`-Typ (Cent-exakt), Engine (einziger SQLite-spezifischer Ort), Alembic-Migration `0001`.
- Auth: Ersteinrichtung ohne Standardpasswort, Argon2id, serverseitige Sessions (Token nur als Hash), Sperre nach Fehlversuchen, CSRF-Header, Host-Prüfung, Audit-Ereignisse.
- Rollen/Rechte-Grundlage (5 Rollen; nur `admin` nutzbar).
- `FileStore` (lokal) mit Typ-/Magic-Byte-/Größenprüfung und Traversal-Schutz.
- Backup/Restore (DB-Snapshot + Dokumente + SHA-256-Manifest, Verifikation, Sicherheits-Backup vor Restore) samt API und UI.
- Dashboard-API: 12 Kennzahlen, ausnahmslos `available:false`/`value:null`, da noch keine Datenquelle existiert (keine Demo-Zahlen).
- Frontend: Designsystem-Grundlage, Shell (Sidebar/Topbar), Login/Einrichtung, Dashboard, Einstellungen (Backup), Platzhalterseiten für alle übrigen Bereiche (ausdrücklich als „nicht implementiert“ gekennzeichnet).
- Desktop-Starter `leventum.desktop`.

## 2. Dateien
`docs/*`, `README.md`, `.gitignore`, `backend/**` (pyproject, alembic, `leventum/**`, `tests/**`), `frontend/**`.

## 3. Datenbankmodelle / Migrationen
Migration `0001_foundation`: `role`, `app_user`, `user_session`, `audit_event`, `app_setting`. Alle Fachtabellen (Parteien, Objekte, Verträge, Finanzen …) sind **nur entworfen**, nicht angelegt.

## 4. Tatsächlich nutzbar
Einrichtung, Anmeldung/Abmeldung, Backup erstellen/prüfen/wiederherstellen, Navigation, Dashboard-Gerüst. **Keine fachliche Verwaltung** (keine Mieter, Objekte, Verträge, Zahlungen) – das ist Phase C/D.

## 5./6. Ausgeführte Tests und Ergebnisse
| Suite | Befehl | Ergebnis |
|---|---|---|
| Backend (pytest) | `python -m pytest backend` | **30 bestanden, 0 fehlgeschlagen** |
| Frontend (vitest) | `npm test` | **2 bestanden** |
| Frontend-Build | `npm run build` (tsc + vite) | erfolgreich |
| Manueller E2E-Lauf (Playwright/Chromium gegen echten Server) | Einrichtung → schwaches Passwort abgelehnt → Dashboard → Backup erstellen → prüfen → Reload (Session bleibt) → Logout | erfolgreich, keine JS-Fehler außer dem absichtlich provozierten 400 |

Abgedeckt u. a.: jede registrierte API-Route (außer Whitelist) verlangt Auth; Passwort nie im Klartext; Session-Token nur gehasht; Sperre/Audit; CSRF- und Host-Schutz; Geld-Rundung ohne float-Fehler; Upload-Ablehnung (Typ, Magic-Bytes, Größe, leer, Traversal); Backup enthält DB+Dokumente; Manipulationserkennung; Restore stellt DB **und** Dokumente zurück; Migrationen = Modelle (Autogenerate ohne Differenz), Up-/Downgrade.

**Nicht getestet / nicht möglich in dieser Umgebung:** Windows, WebView2/pywebview-Fenster, Installer, PostgreSQL, Last/Mehrbenutzer, automatisierte Frontend-E2E-Tests im Repo (der Playwright-Lauf war manuell, nicht eingecheckt), Barrierefreiheit.

## 7. Offene Fehler / Einschränkungen
- Logo ist ein **Platzhalter**; Farben/Abstände sind aus dem Screenshot geschätzt, kein pixelgenauer Abgleich.
- Globale Suche und Benachrichtigungen sind bewusst deaktiviert (keine Daten).
- Backup: keine Verschlüsselung, keine Rotation, nur SQLite, kein Zeitplan (nur Altersanzeige/Warnung). Restore setzt voraus, dass keine parallelen Schreibzugriffe laufen (Einzelplatz).
- Audit ist nur auf Anwendungsebene append-only (kein DB-Schutz gegen direkten Zugriff).
- Rate-Limiting ist pro Benutzerkonto, nicht pro Quelle.
- Frontend: nur 2 Komponententests; Login-Zustand ohne Session-Ablauf-Erkennung während der Nutzung (401 führt nicht automatisch zur Anmeldeseite).
- `npm audit` meldet Hinweise zu Entwicklungsabhängigkeiten (nicht bewertet).

## 8. Sicherheitsrisiken
Siehe `docs/04-sicherheit-backup.md`. Wesentlich: unverschlüsselte lokale DB/Dokumente (BitLocker/Windows-Konto erforderlich), kein Schutz gegen Malware im Benutzerkonto, keine unabhängige Sicherheitsprüfung.

## 9. Nächster Schritt
Vor Phase C die offenen Fragen **#1 (Zimmer-/Bettenvermietung)** und **#2 (NK-Modell der Untermieten)** klären, danach Phase C (Parteien, Objekte, Einheiten, Haupt-/Untermietverträge mit Überschneidungs- und Deckungsprüfung, Mieterliste/-akte, globale Suche). Die Rechenlogik (Phase D) wird mit den Beispielwerten 850/180 → 1.150/220 testgetrieben aufgebaut.
