# Abschlussbericht Phase E (operative Verwaltung)

Statuslegende: **Geplant · Implementiert · Getestet** (automatisiert ausgeführt) **· Unabhängig geprüft · Freigegeben**.
**Unabhängig geprüft: nichts. Freigegeben: nichts.** Methoden und Annahmen: `09-phase-e-konzept.md`.

## 1. Implementiert und getestet
| Bereich | Stand |
|---|---|
| Aufgaben (6 Bezüge, Status, Priorität, Fälligkeit, Filter, Überfälligkeit, Abbruch-Begründung) | implementiert, getestet |
| Reparaturen (Verlauf, Status, Schätzung/tatsächliche Kosten aus verknüpften Rechnungen, Aufgaben, Fotos/Belege) | implementiert, getestet |
| Kommunikationsprotokoll (unveränderlich, kein Versand, Folgeaufgabe) und Übergabeprotokolle | implementiert, getestet |
| Dokumentenverwaltung (alle Bezüge, Suche, Mehrfachzuordnung, Weichlöschung mit Grund, Pflichtliste) | implementiert, getestet |
| Erinnerungen (7 Typen, berechnet, Aufgabe daraus mit Duplikatschutz) | implementiert, getestet |
| Historie / Mieterakte (Audit + Kommunikation + Reparaturen + Aufgaben) | implementiert, getestet |
| Dashboard (alle Kennzahlen echt; Hinweise und Aufgaben) | implementiert, getestet |
| UI: Aufgaben, Reparaturen (+Detail), Kommunikation, Dokumente, Vertrags-Dokumente/-Protokolle, Dashboard-Hinweise, Mieterakte-Historie | implementiert, getestet (Komponententests + Browserlauf) |
| Rechte (`document:*`, `repair:*` neu aufgeteilt) | implementiert, getestet |

## 2. Datenbank
Migration `0004_operations_tasks_repairs_communication` (5 neue Tabellen, 4 neue Spalten). Modelle ↔ Migration synchron; Hin-/Rückweg per Test.

## 3. Testergebnisse (tatsächlich ausgeführt)
| Suite | Ergebnis |
|---|---|
| Backend `pytest` | **210 bestanden**, 0 fehlgeschlagen (175 aus Phase A–D + 35 neu; 1 bestehender Test fachlich angepasst: alle Dashboard-Kennzahlen sind jetzt verfügbar) |
| Frontend `vitest` | **16 bestanden** (6 neu), Build erfolgreich |
| Browserlauf Phase E (`frontend/e2e/phase-e.cjs`) | alle Schritte OK, keine JS-Fehler |
| Browserläufe Phase C und D (Regression, erneut ausgeführt) | alle Schritte OK, keine JS-Fehler |

Neue Backend-Tests u. a.: Aufgaben zu jedem Bezug, Statusfolge samt Audit, Filter/Überfälligkeit/Sortierung; Reparaturverlauf, Kosten nur aus nicht stornierten verknüpften Rechnungen (Schätzung/Abweichung/bezahlt/offen), Verknüpfungsregeln, Kosten genau einmal in der Wirtschaftlichkeit; Kommunikation (Pflichtbezug, Filter, Folgeaufgabe, nicht änderbar, kein Versand), Übergabeprotokolle; Dokumente (alle Bezugstypen, Suche, Weichlöschung bleibt auf Datenträger, Pflichtliste inkl. gelöschter Dokumente); Erinnerungen (Fristfenster, Monatsende-Korrektur, Teilzahlung, Entwürfe/Storno ohne Erinnerung, Abrechnung nur bei Vorauszahlung, Stabilität/Eindeutigkeit der Schlüssel, Erinnerung→Aufgabe idempotent); Historie ohne Daten fremder Mieter; Rollenrechte.

### Bei der Entwicklung gefundene und behobene Punkte
Nur Testfehler (falsche Erwartungen, Mock ohne Dokumentenliste, geschütztes Leerzeichen in der Euro-Formatierung); keine Fehler im Anwendungscode. Zwei zu weich formulierte Testprüfungen (`or`-Verknüpfung, toter `if False`-Hack) wurden verschärft bzw. entfernt.

## 4. Bekannte Einschränkungen (offen)
* **Nicht getestet:** Windows, WebView2, Installer, PostgreSQL, große Datenmengen (Erinnerungen werden bei jedem Dashboard-Aufruf neu berechnet).
* Kündigungsstichtage sind nur **rechnerische Hinweise**, keine Rechtsprüfung; Schwellenwerte (90/60/7 Tage) und Pflichtdokumentenliste sind feste Annahmen, nicht konfigurierbar.
* Dokumente: nur Weichlöschung, keine Versionen/Vorschau/OCR, keine Verschlüsselung; keine Löschung der Datei (Aufbewahrungsfristen offen).
* Kommunikation: reine Protokollierung (kein E-Mail-/Briefversand, kein Mail-Import); Einträge nicht korrigierbar (nur Ergänzung).
* Aufgaben: Verantwortlicher im UI noch nicht wählbar; keine Wiederholungsaufgaben, keine Benachrichtigungen außerhalb der Oberfläche.
* Reparaturen: keine Angebote/Aufträge, keine Zeiterfassung; Kosten ausschließlich über Rechnungen.
* Weiter offen aus früheren Phasen: UI für Betriebskostenabrechnung (nur API), Bearbeiten von Stammdaten/Konditionen, Quartals-/Jahresrhythmen, automatisches Beenden ausgelaufener Verträge, Verschlüsselung der Daten/Backups.
* Browserläufe sind manuelle Skripte, keine CI-Tests.

## 5. Sicherheit
Neue Endpunkte hinter Authentifizierung (automatischer Routentest deckt sie ab); Rechte getrennt je Bereich; Dokumente nur angemeldet abrufbar; keine externen Verbindungen. Restrisiken wie in Phase B/D.

## 6. Nächster Schritt
Phase F (Qualitätssicherung und Windows-Build) – dafür ist ein Windows-Rechner nötig: Installer, WebView2-Fenster, PostgreSQL-Lauf, Backup/Restore-Test, Sicherheits- und UI-Prüfung. Vorher sinnvoll: die offenen Lücken (Betriebskosten-UI, Bearbeiten von Stammdaten/Konditionen, Rhythmen) und die fachlichen Fragen aus `07`, `08`, `09` klären.
