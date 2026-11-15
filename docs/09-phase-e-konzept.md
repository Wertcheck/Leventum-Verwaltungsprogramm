# 09 – Phase E: Konzept, Methoden und Annahmen (operative Verwaltung)

Status: **implementiert und automatisiert getestet** (siehe `ABSCHLUSSBERICHT_PHASE_E.md`). Nicht unabhängig geprüft, nicht freigegeben.

## 1. Migration `0004_operations_tasks_repairs_communication`
Neu: `task`, `repair`, `repair_event`, `communication`, `handover_protocol`; Spalten `invoice.repair_id` (Verknüpfung Reparatur ↔ Ausgabe), `document.deleted_at/deleted_by_user_id/delete_reason` (Weichlöschung). Hin- und Rückweg per Test geprüft; PostgreSQL weiterhin nicht getestet.

## 2. Aufgaben
Verknüpfbar (mehrfach möglich) mit Partei, Objekt, Wohneinheit, Vertrag, Rechnung, Reparatur. Felder: Titel, Beschreibung, Priorität (niedrig/normal/hoch/dringend), Status (offen, in Bearbeitung, wartet auf Rückmeldung, erledigt, abgebrochen), Fälligkeit, Verantwortlicher, Erstellt/Erledigt. Status nur über den Statuswechsel (auditiert); **Abbrechen verlangt Begründung**; Wiedereröffnen löscht `completed_at`. „Überfällig“ gilt nur für offene Status. Filter: Status, Priorität, Verantwortlicher, überfällig, Bezug, Textsuche. Sortierung nach Fälligkeit (ohne Datum zuletzt).

## 3. Reparaturen
Meldung mit Objekt, optional Wohneinheit/Vertrag/Melder/Dienstleister, Kategorie, Priorität, Beschreibung, Kostenschätzung, Termin. Status: gemeldet → terminiert → in Arbeit → wartet → erledigt/abgebrochen (Wechsel in beide Richtungen, **jeder Wechsel im Verlauf**, Abbrechen mit Begründung). Der **Verlauf** (`repair_event`) ist append-only und enthält Status, Notizen, Schätzung, Dienstleister, Termin, verknüpfte Rechnungen.
* **Tatsächliche Kosten = Summe der verknüpften, nicht stornierten Rechnungen** (Ausgaben) – nicht von Hand änderbar. Weiter: bezahlt/offen (aus Zahlungszuordnungen), Abweichung zur Schätzung. Dieselben Rechnungen fließen als Objektkosten in die Wirtschaftlichkeit (Test: genau einmal).
* Verknüpfung nur innerhalb desselben Objekts; eine Rechnung gehört zu höchstens einer Reparatur.
* Aufgaben zur Reparatur über `task.repair_id`; Fotos/Belege über Dokumente.

## 3a. Kommunikation und Übergabeprotokolle
Kommunikationsprotokoll (E-Mail, Telefon, Brief, persönlich, Messenger, sonstige; Eingang/Ausgang; Betreff, Inhalt; Bezug zu Partei/Vertrag/Objekt/Wohneinheit/Reparatur, mindestens einer). **Unveränderlich** (nur GET/POST, per Test), **kein Versand** (kein Sendecode). Optionale Folgeaufgabe erbt die Bezüge. Übergabeprotokolle (Einzug/Auszug) je Vertrag: Datum, Schlüssel, Zählerstände, Zustand, Teilnehmer, Unterschrift ja/nein; Dokumente (z. B. Scan) hängen als Anhang an.

## 4. Dokumentenverwaltung
Zuordnung zu Partei, Objekt, Wohneinheit, Vertrag, Rechnung, Kaution, Zahlung, Reparatur, Aufgabe, Kommunikation, Übergabeprotokoll (mehrfach möglich, nachträglich ergänzbar). Suche nach Dateiname, Typ, Bezug. **Löschen = Weichlöschung mit Begründung**: ausgeblendet und nicht mehr abrufbar, die Datei bleibt im Speicher und im Backup (Aufbewahrungsfristen sind fachlich offen), Audit enthält Grund und Prüfsumme. Download weiterhin nur angemeldet, `attachment` + `nosniff`.
* **Pflichtliste (organisatorische Annahme, keine Rechtsaussage):** Haupt- und Untermietvertrag → Dokumenttyp „Mietvertrag“; Untermietvertrag zusätzlich „Übergabeprotokoll“ (auch erfüllt durch einen erfassten Einzug-Protokolleintrag). Gelöschte Dokumente zählen nicht.

## 5. Erinnerungen und Hinweise (berechnet, nicht gespeichert)
Bei jedem Aufruf aus den Daten berechnet (Stichtag injizierbar → deterministisch getestet). Jede Erinnerung hat einen **stabilen Schlüssel**; daraus lässt sich genau **eine** Aufgabe erzeugen (Duplikatschutz per `task.dedupe_key`, zweiter Versuch → 409).
| Typ | Regel | Stufe |
|---|---|---|
| Vertragsende | wirksames Ende ≤ 90 Tage (≤ 30 Tage: Hinweis, sonst Info) | info/warning |
| Kündigungsstichtag | **rechnerisch** = Vertragsende − Kündigungsfrist (Monate, Monatsende-korrigiert), nur aktive Verträge mit Enddatum+Frist, Hinweis ab 60 Tage vorher und nach Verstreichen. Ausdrücklich **keine Rechtsprüfung** (Zugang, Werktage, Form unberücksichtigt) | warning |
| Überfällige Zahlung | Forderungen nach Teilzahlungen offen > 0 und fällig vor heute, je Vertrag | critical |
| Kaution überfällig | offen > 0 und Fälligkeit verstrichen | warning |
| Fehlendes Dokument | Pflichtliste (s. o.) | warning/info |
| Reparatur | Termin ≤ 7 Tage (info); Termin verstrichen & offen (critical); dringend & noch „gemeldet“ (critical) | – |
| Betriebskostenabrechnung | Hauptvertrag mit NK-Vorauszahlung, im Vorjahr aktiv, **keine** erfasste Abrechnung für das Vorjahr (nur Ebene A; Fristen rechtlich zu prüfen) | info |
Entwürfe, stornierte und beendete Verträge lösen nichts aus. Sortierung: Schwere, Datum, Schlüssel.

## 6. Historie
`GET /history` führt je Bezug chronologisch zusammen: Audit-Ereignisse (wer/was/wann), Kommunikation und Reparaturverlauf. **Mieterakte** = Partei + deren Verträge + Kautionen + Mahnungen + Reparaturen + Aufgaben + Kommunikation (Fremddaten anderer Mieter ausgeschlossen, per Test).

## 7. Dashboard
Alle Kennzahlen haben jetzt eine echte Datenquelle (neu: Offene/Überfällige Aufgaben, Offene Reparaturen). „Aufgaben & Hinweise“ zeigt die 8 wichtigsten Erinnerungen (mit „Aufgabe erstellen“) und die nächsten 5 Aufgaben.

## 8. Rechte
`task:*` (Aufgaben, Kommunikation), `repair:*`, `document:*` (neu getrennt von `finance:*`), `master:*` (Übergabeprotokolle, Historie). Objektbetreuung: Aufgaben/Reparaturen/Dokumente, keine Stammdaten/Finanzen; Buchhaltung: Dokumente schreiben, keine Reparaturen; Lesend: nur lesen (alle per Test).

## 9. Offene fachliche Fragen / Annahmen (Phase E)
1. Aufbewahrung/Löschen von Dokumenten (GoBD/DSGVO): derzeit nur Weichlöschung, keine endgültige Löschung.
2. Pflichtliste je Vertragsart und Vertragstyp (z. B. Monteurwohnung, Gewerbe) – derzeit eine feste, organisatorische Annahme.
3. Kündigungsfristen: nur rechnerischer Stichtag; Behandlung von Verlängerungsoptionen, Sonderkündigungsrechten, Zugangsfristen offen und rechtlich zu klären.
4. Schwellenwerte der Erinnerungen (90/60/7 Tage) – Vorschläge, noch nicht konfigurierbar.
5. Betriebskostenabrechnung Ebene B (gegenüber Untermietern) hat weiter keinen Datensatz, daher keine Erinnerung.
6. Mehrbenutzer: Verantwortliche/Zuweisung ist modelliert, aber in der Oberfläche noch nicht auswählbar (nur ein Administrator).
7. Zeiterfassung/Arbeitsaufwand zu Reparaturen, Dienstleisterbewertung, Angebotsvergleich: nicht umgesetzt.
