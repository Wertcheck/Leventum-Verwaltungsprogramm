# Abschlussbericht Master-Review (CTO-Review, fachliche Korrekturen, Funktionsvervollständigung, UI/UX, QA)

**Statuslegende (strikt getrennt):** Geplant · Implementiert · Automatisiert getestet · Manuell getestet · Unter Windows getestet · Unabhängig geprüft · Freigegeben.
**Unter Windows getestet: nichts. Unabhängig geprüft: nichts. Freigegeben: nichts.**
**Die Anwendung wird ausdrücklich NICHT als produktionsreif bezeichnet.** Grüne Tests belegen weder Datensicherheit im Betrieb, noch Finanzkorrektheit nach fachlicher/steuerlicher Prüfung, noch Windows-Kompatibilität (siehe Abschnitte 9–11, 13). Ausgangsanalyse: `MASTER_REVIEW.md`, Plan: `IMPLEMENTIERUNGSPLAN.md`.

## 1. Ausgangszustand
Backend (FastAPI/SQLAlchemy/Alembic/SQLite) mit Stammdaten, Verträgen, Finanzen, Kautionen, Mahnwesen, Bankimport, Dokumenten, Aufgaben/Reparaturen; Frontend (React/TS) für Phasen A–E; 210 Backend-/16 Frontend-Tests; drei manuelle Playwright-Skripte (Chromium). Nie ausgeführt: Windows/pywebview/WebView2, PostgreSQL. Details: `MASTER_REVIEW.md` §1.

## 2. Gefundene Fehler und Lücken
| Nr. | Befund | Ergebnis der Prüfung |
|---|---|---|
| B1 | KPI-Beträge brechen/werden abgeschnitten | teilweise bestätigt; bei 1366 px weiterhin Abschneiden (durch eigene Messung gefunden, siehe 3) |
| B2 | 7 aktive Untermietverträge/Mieter vs. 8 Personen in Liste | kein Rechenfehler; Definition fehlte/uneinheitlich |
| B3 | „Entwurf vorhanden“ vs. „Entwürfe vorbereiten (0)“ | Oberfläche irreführend; **zusätzlich Backend-Fehler:** Eskalation (Stufe 2) auch ohne dokumentierten Versand der Vorstufe |
| B4 | Mieterliste ohne Detailpanel | bestätigt |
| B5 | Objektstruktur | Daten konsistent; Zusammenfassung „angelegt X von Y“ fehlte; DB ließ doppelte Vermietungseinheiten zu |
| B6 | Dokumente „0 KB“ | kein Speicherfehler (17-Byte-Demodateien); es fehlten Integritätsprüfung beim Download und eine definierte endgültige Löschung |
| B7 | „Offen zum 30.11.“ bei Systemdatum 15.11. | **fachlicher Fehler** (Stichtag in der Zukunft) |
| B8 | Reparaturkosten | korrekt |
| Weitere | `window.prompt/confirm/alert` (16 Stellen); keine Sicherheitsheader; Stammdatenänderungen ohne Vorher/Nachher; Verteilung geprüfter NK-Abrechnungen änderte sich nachträglich mit Flächenänderung; Dashboard-Antwort >1 s (5× Engine); keine Rückwirkungs-Warnung bei Sollstellungen/Vertragsdatum |
| Beim Test gefunden (während dieser Arbeit) | weiße Seite in `PropertyDetail` (Hook hinter frühem `return`) – durch E2E-Suite entdeckt und behoben; Modal-Layout schnitt Formularspalten ab; Tabellen erzeugten bei 1024 px horizontalen Seitenüberlauf |

## 3. Tatsächlich behobene Fehler (Implementiert; jeweils automatisiert getestet, soweit unter 8 genannt)
* Mahn-Eskalation nur nach **dokumentiertem Versand** (`approved_not_sent`), Mindestabstand 7 Tage (Annahme).
* Datenstand statt Periodenende als Stichtag; Prognose getrennt und gekennzeichnet; Warnung bei Zeitraum über Datenstand.
* Zentrale Definitionen: `is_running`, `phase` (draft/cancelled/upcoming/active/notice/ended), „aktiver Mieter“; Dashboard-KPIs mit Definition/Hinweis (Info-Symbol).
* Eindeutigkeit von Vermietungseinheiten über `space_key` (Migration mit Backfill für Altdubletten).
* Dokumentintegrität (SHA-256-Prüfung beim Download, `verify`, `verify-all`), kontrollierte endgültige Entfernung (nur Admin, nach Aufbewahrungsfrist).
* Audit mit Vorher/Nachher (sensible Felder maskiert); eingefrorene NK-Verteilung bei Status „geprüft“.
* Sicherheitsheader; Dashboard-Performance (Engine einmal je Sitzung).
* Native Browser-Dialoge vollständig ersetzt (`DialogProvider`; Test stellt sicher, dass kein `window.prompt/confirm/alert` zurückkehrt).
* KPI-Karten (clamp/nowrap/kleinere Icons), Modal-Formulare, Tabellen scrollen in der Karte statt die Seite zu verbreitern.

## 4. Implementierte Funktionen
| Bereich | Stand |
|---|---|
| Sollstellungsrhythmen monatlich/vierteljährlich/halbjährlich/jährlich/auf Abruf; kalenderbasiert, tagesanteilig; Vorschau (Dry-Run); Konflikt-/Überlappungsschutz; Rückwirkung nur nach Bestätigung | implementiert, automatisiert getestet, im Browser getestet (E2E 05) |
| Mahnwesen: konsistente Zähler je Zustand, Art/Zeitraum/Sollstellungs-Nr., kein Versandcode, Platzhalter blockiert Freigabe | implementiert, automatisiert getestet (E2E 07) |
| Wirtschaftlichkeit: Datenstand-Banner, getrennter Prognoseblock | implementiert, Backend automatisiert getestet; UI nur durch E2E 10 (Banner/Soll sichtbar) |
| Mieterliste mit Phasen/Filtern und **rechtem Detailpanel** (Drawer unter 1280 px) über einen gebündelten Endpunkt | implementiert, Komponententest + E2E 08; Drawer-Darstellung nur per CSS, nicht separat per Screenshot belegt |
| Objektstruktur: Zusammenfassung „angelegt X von Y“ | implementiert |
| Bearbeiten **mit Historie**: Partei, Objekt, Wohneinheit, Zimmer, Bett, Vertragsfelder, Mietkonditionen als **neue Version** (Hinweis auf nicht veränderte Sollstellungen) | implementiert; automatisiert (Backend) + E2E 18–20 |
| Betriebskosten über die Oberfläche (`/betriebskosten`): Abrechnung Ebene A anlegen, Positionen, Schlüssel (Fläche/gleich/Personen/Verbrauch/kein), Umlagefähigkeit, Vorauszahlungen, Ergebnis, Verteilung inkl. „nicht zuordenbar“, Vergleich Ebene B, Prüfung sperrt/friert ein | implementiert; E2E 09 |
| Backup: optional verschlüsselt (AES-256-GCM, Passphrase ≥ 12), Prüfen, Wiederherstellen (inkl. Passphrase), Datenprüfung in Einstellungen | implementiert; Backend-Tests + E2E 12–15 |
| Windows: `ALLOW_DOWNLOADS`-Einstellung im Starter (Fehler werden abgefangen) | **implementiert, ungetestet** |

## 5. Geänderte Datenbankmodelle und Migrationen
Neue Revision `0005_space_key_document_purge_statement_`: `rentable_unit.space_key` (nullable → Backfill inkl. `#dup{id}` für Altdubletten → NOT NULL + unique), `document.purged_at/purged_by_user_id/purge_reason`, `utility_statement.allocation_snapshot` (JSON). Hin- und Rückweg sowie Migration mit Altdaten automatisiert getestet (`tests/test_backup_migrations.py`). Keine Migration gegen PostgreSQL ausgeführt.

## 6. Neue und geänderte API-Endpunkte
Vollständig in `03-api-module.md` (Ergänzung Master-Review): `/charges/preview`, `/charges/generate` (`allow_backdated`), `/tenants` (paginiert), `/tenants/{id}/overview`, PATCH für Raum/Bett/WE/Vertrag/Partei/Objekt, `/documents/{id}/verify|purge`, `/documents/verify-all`, `/system/integrity`, verschlüsselte Backups, erweiterte `/dunning/overdue`, `/economics`, `/dashboard`.

## 7. Neue und geänderte Frontend-Komponenten
Neu: `components/Dialogs.tsx` (ask/confirmBox/notify), `components/EditDialog.tsx`, `components/TenantPanel.tsx`, `pages/Utility.tsx`. Geändert: Finance (Vorschau-Dialog), Dunning, Economics, Parties (Master-Detail, Bearbeiten), Properties (Bearbeiten, Zusammenfassung), Leases (Bearbeiten, Konditionsversion), Settings (verschlüsselte Backups, Datenprüfung), Dashboard/`KpiCard` (Definition/Hinweis), Bank, Tasks, Repairs, DocPanel, `styles.css`, `main.tsx`, `nav.ts`.

## 8. Durchgeführte Tests mit konkreten Ergebnissen (tatsächlich ausgeführt, Linux)
| Suite | Ergebnis |
|---|---|
| Backend `pytest` (Gesamtlauf) | **272 bestanden**, 0 fehlgeschlagen, 1 Warnung (126 s) |
| Frontend `vitest` | **19 bestanden** (inkl. Mieterpanel, Dialoge, „keine nativen Dialoge“); `npm run build` erfolgreich |
| **E2E-Suite** `npm run e2e` (`frontend/e2e/suite.cjs`, Chromium, eigener Server + temporäre DB) | **21/21 Abläufe bestanden** (Letzter Lauf; ein Zwischenlauf deckte den `PropertyDetail`-Absturz auf, der danach behoben wurde) |
| Responsive-Prüfung (`e2e/responsive.cjs`, 15 Seiten × 4 Viewports 1536×1024, 1366×768, 1280×800, 1024×768, mit Demodaten) | zunächst 1 + 7 Befunde, nach Korrektur **keine Überläufe/abgeschnittenen KPI-Werte** (gemessen per `scrollWidth`); Screenshots: Dashboard 1366×768 manuell angesehen |
| Skripte `phase-c`, `phase-d`, `phase-e` (Regression, an neue Dialoge/Vorschau angepasst) | alle Schritte OK, keine JS-Fehler |
Hinweis zur Suite: Sie enthält **21** Abläufe (Anforderung nannte 18). Sie deckt Einrichtung, Objektstruktur, Dialoge, Verträge/Überschneidung, Sollstellungen, Zahlung/Storno, Mahnwesen, Mieterpanel, Betriebskosten, Wirtschaftlichkeit, Dokument, Backup (auch verschlüsselt), Datenprüfung, Restore, Responsive, KPI-Definitionen, Bearbeiten, Konditionsversion, Vertragsende ab. Nicht jeder einzeln im Prompt genannte Ablauf ist enthalten (z. B. Bankimport und Kautionen nur in `phase-d.cjs`, nicht in `suite.cjs`).
Manuell getestet im Sinn der Legende: nur Betrachtung einzelner Screenshots durch den Entwickler (keine Abnahme durch Fachanwender).

## 9. Nicht getestete Bereiche
* **Windows, pywebview/WebView2, Installer, Downloads im Fenster, DPI-Skalierung** (Testplan: `WINDOWS_TESTPLAN.md`, alle Punkte „offen“).
* PostgreSQL (nur vorbereitet), Mehrbenutzerbetrieb, Last/Dauerbetrieb, große Datenmengen jenseits des 60-Mieter-Performance-Tests.
* Browser außer Chromium; Tastatur-/Screenreader-Barrierefreiheit nur oberflächlich (Fokus auf Dialoge, `aria`-Labels).
* Drawer-Darstellung des Mieterpanels unter 1280 px nicht per eigenem Screenshot nachgewiesen; Mahnwesen-/Wirtschaftlichkeits-Seiten nur per Überlaufmessung, nicht visuell geprüft.
* Systematische Ladezustände/Skeletons: nur punktuell („Lade …“ im Panel); keine durchgängige Prüfung.
* Python-Abhängigkeitsprüfung (`pip-audit`) nicht ausgeführt.

## 10. Bekannte Einschränkungen
* Betriebskosten-UI: **keine** Bearbeitung/Löschung einzelner Positionen, **keine** eigenen Gewichte (`custom`) in der Oberfläche (API unterstützt `weights`), keine Verknüpfung zu Dokumenten in der Seite, keine Pflege der Nebenkostenvereinbarungen-Historie per Dialog (nur Anzeige).
* Bearbeiten: Zimmer/Bett nur Umbenennen/Fläche; Deaktivieren/Reaktivieren mit Belegungsprüfung ist im Backend vorhanden, in der Oberfläche **nicht** angebunden. Keine Anzeige des Versionsverlaufs von Stammdaten (nur Audit-Historie in der Mieterakte).
* Wirtschaftlichkeits-Prognose gilt nur unter der Annahme „keine weiteren Zahlungen“.
* Fachliche **Annahmen** (nicht rechtlich geprüft): kalenderbasierte Perioden, vorschüssige Fälligkeit, Mindestabstand Mahnstufen 7 Tage, Aufbewahrung 10 Jahre, „gekündigter, laufender Vertrag = aktiver Mieter“.
* Keine Gebühren-/Zinsberechnung im Mahnwesen, kein Versand (bewusst); Nebenkosten-Nachforderungen werden nie automatisch erzeugt.

## 11. Offene Risiken
* **Datensicherheit:** Datenbank und Dokumente sind **unverschlüsselt**; nur Backups sind (optional) verschlüsselt. Schutz hängt an BitLocker/Windows-Konto. Ein unverschlüsseltes Backup ist möglich (Standard).
* **Wiederherstellbarkeit:** Restore ist automatisiert und per UI auf **Linux** nachgewiesen; unter Windows (Dateisperren, Neustart des Prozesses) ungeprüft. Eine vergessene Backup-Passphrase ist nicht wiederherstellbar.
* **Finanzkorrektheit:** durch Tests abgesichert (Rundung ROUND_HALF_UP, Largest-Remainder, Idempotenz, Storno), aber keine unabhängige fachliche/steuerliche Prüfung; Rechtsfragen (Mahnwesen, Nebenkosten, Fristen) offen.
* **Abhängigkeiten:** `npm audit`: Produktivabhängigkeiten 2 Meldungen (mittel, react-router), 6 weitere nur Entwicklungswerkzeuge; kein `--force`-Upgrade durchgeführt.
* Schutz der Finanzdaten (Append-only) gilt auf Anwendungs-, nicht auf Datenbankebene.

## 12. Git-Commit- und Push-Status
Branch `claude/leventum-property-management-phase-a-f5kfyx`. Seit `681b1e2` entstanden Commits für Phase A, fachliche Korrekturen, Rhythmen, Bearbeiten/Historisierung, Detailpanel, Sicherheit, Dialoge/Vorschau, UI-Anpassungen, Betriebskosten/E2E-Suite, Stammdaten-Bearbeiten (siehe `git log 681b1e2..HEAD`). Alle Commits bis zum Bearbeiten-Dialog sind gepusht; der Stand dieses Berichts wird mit dem nachfolgenden Commit gepusht (Status im Antworttext). Kein Pull Request erstellt.

## 13. Status der Windows-Testinstallation
**Nicht durchgeführt / nicht getestet.** Es gab in dieser Umgebung keinen Windows-Rechner. Vorhanden: `ALLOW_DOWNLOADS`-Anpassung (ungetestet), `WINDOWS_TESTPLAN.md` (Checkliste W1–W9, alle offen). Kein Installer, kein Build-Skript für Windows. Die Aussage „läuft unter Windows“ ist **nicht belegt**.

## Nächste sinnvolle Schritte
1. Windows-Testplan auf einem echten Windows-10/11-Rechner mit WebView2 abarbeiten (inkl. Downloads, Backup/Restore, DPI 125/150 %).
2. Fachliche/rechtliche Prüfung der Annahmen (Mahnfristen, Nebenkosten, Aufbewahrung) und unabhängige Prüfung der Finanzlogik.
3. Betriebskosten-UI vervollständigen (Positionen bearbeiten/löschen, eigene Gewichte), Deaktivieren von Zimmern/Betten anbinden, Ladezustände durchgängig.
4. Bankimport und Kautionen in die automatisierte Suite aufnehmen; Python-Abhängigkeitsaudit.
