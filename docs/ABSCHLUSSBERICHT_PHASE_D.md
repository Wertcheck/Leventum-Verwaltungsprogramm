# Abschlussbericht Phase D

Statuslegende: **Geplant · Implementiert · Getestet** (automatisiert ausgeführt) **· Unabhängig geprüft · Freigegeben**.
**Unabhängig geprüft: nichts. Freigegeben: nichts.** Fachliche Methoden: `08-phase-d-konzept.md`.

## 1. Analyse der Phase-C-Basis (Ergebnis)
Das Vermietungseinheiten-Modell trägt Phase D ohne Umbau. Drei Punkte wurden angepasst: (a) die Phase-A-Formel „Deckungsbeitrag − Leerstandskosten“ war eine **Doppelzählung** und wurde korrigiert; (b) ein minimaler Dokumentenspeicher wurde ergänzt (Belege); (c) `lease.allocation_method` für die Verteilung der Hauptmiete. Alle 80 Phase-C-Tests blieben unverändert grün (angepasst wurden nur 3 Erwartungen, die sich fachlich zwingend änderten: Schema-Revision, Dashboard-Kennzahlen, „keine Forderungstabelle“).

## 2. Implementiert und getestet
| Bereich | Stand |
|---|---|
| Sollstellungen (idempotent, Cent-genau, tagesanteilig, Storno, Konflikt-Meldung) | implementiert, getestet |
| Zahlungen (unveränderlich, Teilzahlung, Überzahlung, Zuordnung/Rücknahme, Storno per Gegenbuchung, Duplikatwarnung) | implementiert, getestet |
| Rechnungen & Belege (Zuordnung, Zahlung, Dokumentenupload/-download geschützt) | implementiert, getestet |
| Kautionen (Haupt/Unter getrennt, Teilzahlung, Rückzahlung, Teilrückzahlung, Einbehalt mit Begründung, Storno, Belege, Historie) | implementiert, getestet |
| Mahnwesen (3 Stufen, Erkennung mit Teilzahlungen, Entwürfe, manuelle Freigabe, Versand nur dokumentiert, Protokoll) | implementiert, getestet |
| Bankimport CSV (Validierung, Duplikate, Erkennung Ein/Ausgang, Vorschläge, Prüfliste, manuelle Bestätigung, Protokoll, erweiterbare Parser) | implementiert, getestet |
| Leerstand A physisch / B wirtschaftlich (Bett/Zimmer/Wohneinheit/Objekt, zeitbezogen) | implementiert, getestet |
| Wirtschaftlichkeit Portfolio/Immobilie/Wohneinheit/Vermietungseinheit (Soll/Ist/Offen, Rückstände, NK-Abrechnungssaldo, Kautionen ausgeschlossen) | implementiert, getestet |
| UI: Sollstellungen & Zahlungen, Kautionen, Mahnwesen, Bankimport, Rechnungen, Wirtschaftlichkeit, Leerstand, Dashboard (6 weitere echte Kennzahlen) | implementiert, getestet (Komponententests + manueller Browserlauf) |
| Logo: vom Auftraggeber bereitgestellte Datei (zugeschnitten) ersetzt den Platzhalter | implementiert, im Browser gesichtet |

## 3. Datenbank
Migration `0003_finance_deposits_dunning_bank_documents` (14 neue Tabellen, 1 neue Spalte). Modelle ↔ Migration per Test synchron; Up-/Downgrade-Roundtrip getestet. PostgreSQL weiterhin **nicht** getestet.

## 4. Testergebnisse (tatsächlich ausgeführt)
| Suite | Ergebnis |
|---|---|
| Backend `pytest` | **175 bestanden**, 0 fehlgeschlagen (80 aus Phase A–C + 95 neu) |
| Frontend `vitest` | **10 bestanden** (8 neu), Build erfolgreich |
| Manueller Browserlauf Phase C (`frontend/e2e/phase-c.cjs`, erneut ausgeführt, jetzt mit allen Schritten inkl. WE-Status) | alle Schritte OK, keine JS-Fehler |
| Manueller Browserlauf Phase D (`frontend/e2e/phase-d.cjs`) | alle Schritte OK, keine JS-Fehler |

Neue Backend-Tests (Auswahl): Sollstellung 850/180 ↔ 1150/220; Teilmonate, Mieterhöhung mitten im Monat, Kündigung, tagesbasierte Miete; keine doppelten Sollstellungen (auch DB-Constraint); Konflikt statt Überschreiben; Teilzahlung exakt auf den Cent; Überzahlung; Storno stellt Offen-Betrag her und bleibt zum Stichtag nachvollziehbar; Kautionen unabhängig/ausgeschlossen; Mahnstufen, Wartefristen, veralteter Entwurf, Platzhalterschutz; CSV-Formate, Fehlerzeilen, Alles-oder-nichts, Duplikate (Wiederimport, Überlappung, Mehrfachzeilen, anderes Konto); Vorschläge (IBAN/Name/Betrag/Rechnungsnummer/Kaution); Bestätigung nur explizit, kein Doppelbuchen, Rollback bei Fehler, Wiedereröffnen; Leerstand Bett/Zimmer/Wohneinheit, Zeitbezug, Mieterwechsel, Lücken, offene Vertragsenden; Summenkonsistenz aller Auswertungsebenen; Rundung 100 € auf 3 Betten; fehlende Fläche wird nicht geraten; Rechte (lesende Rolle) und Auth auf allen neuen Routen.

### Bei der Entwicklung gefundene und behoben Fehler
1. Überlauf (`date.max + 1 Tag`) bei unbefristeten Verträgen in der Leerstandsrechnung.
2. UI: Ergebnismeldung der Sollstellungs-Erzeugung wurde sofort überschrieben.
3. UI: Bank-Bestätigung sendete Zusatzfelder der Vorschläge und wurde vom Server abgelehnt (der Komponententest nutzte zu saubere Mock-Daten; Test ist jetzt realistisch).
4. Mehrere falsch von Hand gerechnete Erwartungswerte in Tests (Code war richtig, Tests korrigiert) – jeweils nachgerechnet.

## 5. Bekannte Einschränkungen (offen)
* **Nicht getestet:** Windows, pywebview/WebView2, Installer, PostgreSQL, Last/große Datenmengen (Wirtschaftlichkeit wird je Anfrage vollständig neu berechnet; für kleine/mittlere Bestände ausgelegt).
* Sollstellungen nur **monatlich** (Quartal/Jahr nicht). Keine Mahngebühren/Verzugszinsen (Vorgabe). Mahn-Wartefrist 7 Tage und Wortlaute sind **ungeprüfte Annahmen**.
* Bankimport: nur CSV, ein Währungskonto (EUR), keine CAMT.053/Open Banking (architektonisch vorbereitet, nicht implementiert); Vorschläge sind heuristisch; Sammelüberweisungen nicht aufgeteilt.
* Wirtschaftlichkeit: Zeitraum nur ganze Monate; keine Umsatzsteuerlogik; Renovierung/„nicht verfügbar“ mindert Leerstand nicht; Objektkosten nach Rechnungsdatum (keine Leistungszeitraum-Abgrenzung); nicht verteilte Hauptmiete/Objektkosten erscheinen nur auf Objekt-/Portfolioebene.
* Dokumente: minimaler Speicher (kein Löschen/Versionieren, keine Vorschau, kein OCR). Keine Verschlüsselung der Dokumente/Backups.
* Unveränderlichkeit von Zahlungen/Audit nur auf Anwendungsebene (kein Datenbankschutz).
* Keine UI für Betriebskostenabrechnung (Ebene A nur per API), keine UI zum Ändern von Stammdaten/Konditionen; `close_expired` (Vertrag „beendet“) wird noch nicht automatisch ausgelöst; Dashboard „Offene Aufgaben“ folgt mit Phase E.
* Browser-Läufe sind manuelle Skripte, keine CI-Tests.

## 6. Sicherheit
Siehe `04-sicherheit-backup.md` (Ergänzung Phase D). Keine Zugangsdaten, keine externen Verbindungen; Bankbuchungen nur nach expliziter Bestätigung; Dokumente nur authentifiziert. Restrisiken wie in Phase B (unverschlüsselte lokale Daten, BitLocker nötig).

## 7. Offene fachliche Fragen
`08-phase-d-konzept.md`, Abschnitt 9 (u. a. Mahnwesen-Regeln, Rhythmen, Standard-Verteilung der Hauptmiete, Kautionsverzinsung, Umsatzsteuer, Leerstandsdefinition bei Renovierung, Bankformate).

## 8. Nächster Schritt
Phase E (Aufgaben, Reparaturen, vollständiges Dokumentenmanagement, Kommunikation/Historie, Erinnerungen) oder – abhängig von Ihrer Priorität – vorab: Oberfläche für die Betriebskostenabrechnung, Bearbeiten von Stammdaten/Konditionen und Quartals-/Jahres-Rhythmen.
