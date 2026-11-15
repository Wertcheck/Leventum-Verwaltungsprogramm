# MASTER REVIEW – Bestandsaufnahme (Phase A)

Stand: Branch `claude/leventum-property-management-phase-a-f5kfyx`, HEAD `681b1e2`, Arbeitsbaum sauber. Alle Aussagen unten wurden gegen Code und Daten geprüft; „bestätigt“ heißt reproduziert (Test, Abfrage oder Code-Nachweis).

## 1. Tatsächlicher Implementierungsstand
| Messgröße | Wert (gemessen) |
|---|---|
| API-Operationen / Pfade | 114 / 91 (OpenAPI des laufenden Servers) |
| Datenbanktabellen | 43, Migrationen `0001`–`0004` (Hin-/Rückweg getestet) |
| Backend-Code (services/api/models) | ca. 5.900 Zeilen, 18 Testdateien |
| Backend-Tests | **217 bestanden** (Baseline-Lauf dieser Phase) |
| Frontend-Tests | **16 bestanden** (3 Dateien) |
| Browser-Tests | 3 manuelle Skripte (`frontend/e2e/phase-c|d|e.cjs`) + Screenshot-Skript; **keine** automatisierte E2E-Suite |
| Frontend-Routen | 21 Navigationsziele, 24 Routen |
| Windows/WebView2 | **nie getestet** (Entwicklungsumgebung ist Linux) |

**Vorhanden:** Authentifizierung/Sitzungen/Rechte, Audit, Stammdaten, Raumhierarchie, Haupt-/Untermietverträge, versionierte Konditionen und Nebenkostenvereinbarung, Sollstellungen (nur monatlich), Zahlungen/Zuordnung/Storno, Rechnungen, Kautionen, Mahnwesen, CSV-Bankimport, Leerstand/Wirtschaftlichkeit, Nebenkosten Ebene A (nur API), Aufgaben, Reparaturen, Kommunikation, Dokumente, Erinnerungen, Historie, Backup/Restore (unverschlüsselt).
**Teilweise:** Bearbeiten (nur API für Partei/Objekt/Wohneinheit/Vertrag; keine UI; keine API für Zimmer/Betten), Backup (kein Test mit Dokumenten + Neustart, keine Verschlüsselung).
**Fehlt:** Betriebskosten-Oberfläche, Rhythmen quartal/halbjahr/jahr (Feld existiert, Erzeugung nur monatlich), Mieter-Detailpanel, Stammdaten-Bearbeitung in der UI, endgültige Löschregelung für Dokumente, Integritätsprüfung beim Dokument-Download, Sicherheitsheader, Backup-Verschlüsselung, automatisierte E2E-Tests, Windows-Test, responsive Prüfung < 1536 px.

## 2. Screenshot-Befunde gegen Code und Daten
| Befund | Ergebnis | Nachweis / Ursache |
|---|---|---|
| **B1** KPI-Karten brechen Beträge um | **Teilweise bestätigt, bereits behoben (Commit 681b1e2)**. Ursache war reines Frontend-Layout. Nicht geprüft bei 1366/1280/1024 px. KPI-Berechnung ist **nicht vollständig zentral**: Zähler (`dashboard.py`-Lambdas) und Beträge (`economics.current_month_figures`) nutzen getrennte Definitionen von „laufend“ (`_running` dupliziert die Logik aus `leases`). | Code-Review |
| **B2** 7 aktive Untermietverträge / 7 aktive Mieter vs. Liste mit 8 Personen | **Kein Rechenfehler, aber Definition nicht dokumentiert und missverständlich.** Gezählt werden Verträge mit Status `active`/`terminated` im Zeitraum Beginn…wirksames Ende → 6 aktive + 1 gekündigter (Keller, läuft bis 31.12.) = 7. Lisa Schneider hat keinen Vertrag und wird nicht gezählt. **Bestätigter Fehler:** Die Mieterliste zeigt für Verträge, die noch nicht begonnen haben, den Status „Aktiv“ (`lease.status` statt zeitbezogener Phase). | API-Abfrage (`/dashboard`, `/tenants`), Code |
| **B3** „Entwurf vorhanden“ vs. „Entwürfe vorbereiten (0)“ | **Backend ist konsistent, Oberfläche irreführend.** Alle 9 Kandidaten haben Zustand `draft_exists`; die Zahl zählt nur Zustand `due` (= 0). Die Tabelle zeigt weder Forderungsart noch Zeitraum noch Sollstellungs-Nr., obwohl die API `charge_type` liefert → Positionen mit gleichem Fälligkeitstag (Kaltmiete + NK) sind nicht unterscheidbar (bestätigt: 2 Positionen je Vertrag/Datum). | API-Abfrage |
| **B3+** (neu gefunden) Eskalation ohne Versand | **Bestätigter Backend-Fehler.** Eine nur *freigegebene*, nie als versandt dokumentierte Stufe-1-Erinnerung erzeugt 7 Tage nach Freigabe einen Stufe-2-Entwurf. | reproduziert mit Skript: `('due', 2)` |
| **B4** Mieterliste ohne Detailpanel | **Bestätigt (fehlt).** | UI |
| **B5** Objektstruktur / Vermietungseinheiten | **Daten konsistent.** 3 WE, 3 Zimmer, 2 Betten; Vermietungseinheiten 1 Objekt + 2 WE + 1 Zimmer + 2 Betten; keine Duplikate, keine Waisen, keine falsche Eltern-Kette (SQL-Prüfung). **Irreführend ist die Zusammenfassung** („1× Zimmer“ meint *angelegte Vermietungseinheiten*, nicht vorhandene Zimmer). **Strukturelle Lücke:** Eindeutigkeit je Raum wird nur im Service erzwungen (SQL-`UNIQUE` über NULL-Spalten wirkt nicht). | SQL, Code |
| **B6** Dokumente „0 KB“ / „< 1 KB“ | **Kein Speicherfehler.** Die Demo-Dateien sind 17 Byte groß; Speicherung/Größe/SHA-256 sind getestet. **Lücken:** keine Prüfung der Dateiintegrität beim Download, keine definierte endgültige Löschung (nur Weichlöschung), Verhalten bei beschädigter Datei ungetestet. | Daten, Code |
| **B7** Stand 30.11. bei Systemdatum 15.11. | **Bestätigt (fachlicher Fehler).** `offen_zum_stichtag` nutzt das Periodenende (zukünftig) als Stichtag; Forderungen, die zwischen heute und Monatsende fällig werden, würden als „überfällig“ erscheinen. Prognose und Datenstand sind nicht getrennt/gekennzeichnet. | API-Abfrage, Code |
| **B8** Reparaturkosten | **Korrekt.** 476,00 € stammen aus der verknüpften Rechnung, bezahlt 0,00 € aus Zahlungszuordnungen (keine manuelle Pflege möglich). | API-Abfrage, Tests |

## 3. Weitere gefundene Risiken
1. **Browser-Dialoge** (`window.prompt/confirm/alert`, 16 Stellen): in pywebview/WebView2 nicht verlässlich nutzbar → Desktop-Risiko; zudem schwache UX. Ersatz durch eigene Dialoge nötig.
2. **Downloads im pywebview-Fenster** können ohne `ALLOW_DOWNLOADS` scheitern (unter Windows zu prüfen).
3. **Keine Sicherheitsheader** (CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`) – gemessen leer.
4. **Keine Verschlüsselung** von Datenbank, Dokumenten und Backups (nur Zugriffsschutz in der Anwendung). Das wurde in der Dokumentation bisher korrekt als Lücke geführt.
5. **Stammdatenänderungen** werden nur als Feldnamen protokolliert (kein Vorher/Nachher); Fläche einer Wohneinheit beeinflusst nachträglich die Verteilung bereits **geprüfter** Nebenkostenabrechnungen (kein Snapshot).
6. **Lebensdauer von Verträgen:** Beginn/Ende eines Vertrags lassen sich ändern, ohne dass auf bereits erzeugte Sollstellungen außerhalb des neuen Zeitraums hingewiesen wird.
7. **Windows:** keinerlei praktischer Nachweis; hier nicht testbar (siehe Plan).

## 4. Abhängigkeiten
Windows-Rechner mit WebView2 für Desktop-QA; Rechtsberatung für Fristen/Mahnwesen/Nebenkosten (unverändert offen); fachliche Entscheidungen zu Rhythmus-Ankerung (kalendarisch vs. vertragsbezogen), Aufbewahrungsfrist von Dokumenten, Standard-Umlageschlüsseln.
