# 08 – Phase D: Konzept, Methoden und Annahmen

Status: **implementiert und automatisiert getestet** (siehe `ABSCHLUSSBERICHT_PHASE_D.md`). Nicht unabhängig geprüft, nicht freigegeben.

## 1. Analyse der Phase-C-Basis
| Befund | Konsequenz |
|---|---|
| Vermietungseinheiten decken Objekt/Wohneinheit/Zimmer/Bett ab; räumliche Überschneidung per Pfad-Präfix | Alle Rechnungen nutzen dasselbe Modell (kleinste Einheit „Blatt“) |
| Mietkonditionen und Nebenkostenvereinbarung sind versioniert, getrennt | Soll wird aus ihnen berechnet; Sollstellung und Wirtschaftlichkeit nutzen **dieselbe Funktion** (`monthly_components`) |
| Kein Dokumentenmodul | Minimaler, geschützter Dokumentenspeicher ergänzt (Belege, Rechnungen, Kautionen) |
| Phase-A-Formel „− Leerstandskosten“ | **Doppelzählung**, korrigiert (Leerstand ist Teil der Hauptmiete) |
| `payment_rhythm` nur gespeichert | Sollstellungen sind in Phase D **monatlich** (Einschränkung) |
| Hauptmiete nicht verteilbar | Neue Spalte `lease.allocation_method` + `lease_allocation_weight` |

## 2. Migration `0003_finance_deposits_dunning_bank_documents`
Neue Tabellen: `charge`, `invoice`, `payment`, `payment_allocation`, `deposit`, `deposit_transaction`, `document`, `document_link`, `dunning_notice`, `dunning_line`, `bank_account`, `bank_import`, `bank_transaction`, `lease_allocation_weight`; Spalte `lease.allocation_method`. Geld = BIGINT (×100). Datenbank-Absicherungen: CHECK (Beträge > 0, genau ein Zuordnungsziel, Perioden), UNIQUE `charge.dedupe_key` (Duplikatschutz), UNIQUE `bank_transaction(account_id, fingerprint)`, UNIQUE `payment.reverses_payment_id`, UNIQUE `bank_transaction.payment_id`.

## 3. Kautionen
Je Vertrag genau eine Kaution (`deposit.lease_id` unique): Hauptmiete = Leventum → Vermieter, Untermiete = Mieter → Leventum. Buchungen: `paid`, `refunded`, `retained` (Begründung Pflicht), Storno mit Begründung. Offen = vereinbart − gezahlt; gehalten = gezahlt − zurückgezahlt − einbehalten. Rückzahlung/Einbehalt ≤ gehalten, Einzahlung ≤ offen. **Kein Bezug zu `charge`/`payment`**, keine Verrechnung zwischen Haupt- und Untermietkaution, nicht in Wirtschaftlichkeit/Dashboard (Tests). Belege über Dokumente.

## 4. Sollstellungen, Zahlungen
* Monatsbetrag je Art (Kaltmiete, Zuschlag, NK-Vorauszahlung, NK-Pauschale) tagesgenau anteilig (Tage/Tage des Monats), einmal je Art auf Cent gerundet (Halbaufrunden); tagesbasierte Miete = Tagessatz × Tage. „Enthalten“/„individuell“/„keine“ erzeugen keine NK-Sollstellung.
* Idempotent (`dedupe_key`); bestehende Beträge werden **nie überschrieben**, Abweichungen als Konflikt gemeldet; Korrektur = Storno + Neuerzeugung. Fälligkeit = `payment_due_day` (auf Monatsende begrenzt). Höchstens 12 Monate im Voraus.
* Zahlungen unveränderlich; Zuordnungen vorzeichenbehaftet und append-only. Zuordnung ≤ offener Betrag und ≤ nicht zugeordneter Zahlungsbetrag (Überzahlung bleibt als nicht zugeordnet sichtbar). Richtung muss passen (Forderung ↔ Eingang, Verbindlichkeit/Rechnung ↔ Ausgang). Storno = Gegenbuchung mit negativen Gegen-Zuordnungen; Offen-Stand ist auch **zu einem Stichtag** korrekt rekonstruierbar.
* Mögliche Doppelerfassung (gleiches Datum/Betrag/Partner/Zweck) wird abgelehnt, außer bewusst bestätigt.

## 5. Mahnwesen
* Überfällig: Forderung (nur Untermieter), nicht storniert, `Fälligkeit < Stichtag − Karenz`, **offener Betrag nach Teilzahlungen > 0**.
* Stufen: 1 Zahlungserinnerung → 2 Erste Mahnung → 3 Zweite Mahnung; nächste Stufe erst, wenn die vorherige **als versandt dokumentiert** ist und `MIN_DAYS_BETWEEN_LEVELS = 7` Tage vergangen sind (**Annahme, nicht rechtlich geprüft**). Keine 4. Stufe.
* Ablauf: Entwurf (Vorbereitung, je Vertrag und Stufe, idempotent) → manuelle Prüfung/Bearbeitung → Freigabe → manuelle Dokumentation des Versands. Freigabe wird blockiert bei offenem Platzhalter (Frist) oder **veraltetem Entwurf** (inzwischen gezahlt/storniert). **Es gibt keinen Versandcode.** Keine Gebühren, keine Verzugszinsen. Jeder Schritt im Audit-Protokoll.

## 6. Bankimport
* Format-unabhängige Architektur: `StatementParser` → `ParseResult`; heute `csv`. CAMT.053/Open Banking = neuer Parser, keine Änderung am Import-Service (Test mit Fake-Parser).
* CSV: UTF-8/CP1252, Trennzeichen automatisch, Spalten per Aliasliste oder expliziter Zuordnung, deutsche/englische Zahlen, Soll/Haben-Spalten, TT.MM.JJJJ/ISO-Datum, nur EUR, IBAN-Prüfung. **Alles-oder-nichts** bei Fehlern (Zeilennummern). Vorschau ohne Speicherung.
* Duplikate: Fingerabdruck (Konto, Datum, Betrag, Name, IBAN, Zweck, Referenz, **laufende Nummer gleicher Zeilen in der Datei**) → erneuter Import und überlappende Auszüge erzeugen keine Duplikate; echte Mehrfachbuchungen bleiben erhalten.
* Vorschläge (nur beratend, Punkte + Gründe): IBAN (50), Name (30), Vertragsnummer im Zweck (40), Betrag deckt offene Sollstellungen exakt (+20)/entspricht einem Monatssoll (+10); Verteilung **älteste Fälligkeit zuerst**; ausgehend: Verbindlichkeiten Hauptmiete, Rechnungen (Nummer/Lieferant), Kautionen („Kaution“ im Zweck). Mindestpunktzahl 30; ohne Vorschlag → Prüfliste „nicht zuordenbar“.
* Bestätigung: nur explizit (`confirm: true`), Zuordnung ≤ Buchungsbetrag, ≤ offene Beträge, Richtung geprüft, mögliches Duplikat einer manuellen Zahlung blockiert, einmalig (Status). „Ohne Zuordnung“ nur mit Begründung. Rückgängig = Gegenbuchung/Storno + Wiederöffnen. Ausblenden mit Begründung.

## 7. Leerstand
Kleinste Einheit („Blatt“): Bett → sonst Zimmer ohne Betten → sonst Wohneinheit ohne Zimmer. Gewichte: Betten teilen sich das Gewicht des Zimmers; Zimmer nach Fläche (nur wenn **alle** Zimmer der Wohneinheit eine Fläche haben, sonst gleich).
* **A Physisch:** Blatt-Tage ohne laufenden Untermietvertrag ÷ alle Blatt-Tage (nach Anzahl und nach Gewicht). 3 Betten, 2 belegt → 33,33 %.
* **B Wirtschaftlich:** Hauptmiete-Soll (Kalt+NK) des Blatts an Tagen **mit** Mietverpflichtung (laufender Hauptvertrag) **ohne** laufenden Untermietvertrag; je Hauptvertrag, Blatt und Monat: `Kosten × Leerstandstage / Deckungstage`, gerundet. Ohne Hauptvertrag kein wirtschaftlicher Leerstand (nur physischer).
* Zeitbezogen tagesgenau (Vertragsbeginn/-ende, Kündigung, Lücken zwischen Mietern, Hauptmietänderungen). Offene Vertragsenden werden korrekt behandelt.
* Keine Doppelzählung: Verträge auf Objekt/Wohneinheit/Zimmer/Bett belegen jeweils alle darunter liegenden Blätter; Auswertungsebenen summieren Blätter.

## 8. Wirtschaftlichkeit
Bereiche: Portfolio, Immobilie, Wohneinheit, Vermietungseinheit; Zeitraum = ganze Kalendermonate (max. 60).
* **Soll** (aus Verträgen): Untermiete Kalt/NK, Hauptmiete Kalt/NK, manuelle Sollstellungen „sonstige“, Objektkosten (Rechnungen nach Rechnungsdatum).
* **Ist** (Zahlungen nach Buchungsdatum): Eingänge von Untermietern, Hauptmiete, Rechnungen, nicht zugeordnete Ein-/Ausgänge (separat; nur Objekt-/Portfolio-Ebene). Stornos wirken im Monat der Gegenbuchung.
* **Offen** zum Periodenende: Forderungen, davon überfällig (= **Zahlungsrückstände**), Verbindlichkeiten, Rechnungen.
* **Verteilung Hauptmiete:** zweistufig – Wohneinheiten (Methode je Hauptvertrag: Fläche [Standard], gleich, individuell), dann Blätter (Gewichte). Largest-Remainder → Summen exakt. Fehlen Flächen/Gewichte → **nicht verteilt**, bleibt auf Objekt-/Portfolioebene (Warnung), nichts wird geraten. Mehrere Wohneinheiten bei Untermiete analog (Fläche).
* **Ergebnis:** „Vorläufiger Deckungsbeitrag“ in zwei getrennten Basen: Soll-Basis = Untermiete − Hauptmiete − Objektkosten; Ist-Basis = Zahlungseingänge − Zahlungsausgänge. Nicht addieren. Zusätzlich Mietmarge (Kalt) und NK-Durchlauf getrennt sowie optional NK-Abrechnungssaldo (Ebene A) auf Objekt-/Portfolioebene. Kautionen ausgeschlossen. Leerstandskosten werden ausgewiesen, nicht erneut abgezogen.

## 9. Offene fachliche Fragen (Phase D)
1. Mahnwesen: Mindestabstände zwischen Stufen, Fristen, Wortlaut, ggf. Gebühren/Verzugszinsen – **rechtlich ungeprüft**.
2. Zahlungsrhythmus quartalsweise/jährlich: Sollstellungen sind bisher nur monatlich.
3. Verteilung der Hauptmiete: Standardmethode je Vertrag bestätigen (derzeit Fläche); Gewichtung von Zimmern/Betten (Fläche vs. gleich).
4. Kautionen: Verzinsung, getrennte Anlage, Verrechnung bei Vertragsende (bewusst nicht automatisiert).
5. Umsatzsteuer/steuerliche Behandlung der Erträge/Kosten (Wirtschaftlichkeit ist brutto/netto-neutral, keine USt-Logik).
6. Leerstand: Behandlung von Renovierung/„nicht verfügbar“ (derzeit nicht ausgenommen) und Karenzzeiten zwischen Mietern.
7. Bankimport: weitere Bankformate/Spaltenprofile; CAMT.053-Priorität; Umgang mit Sammelüberweisungen/Rücklastschriften.
8. Objektkosten: Zeitliche Abgrenzung (Rechnungsdatum vs. Leistungszeitraum) und Zuordnung auf Zimmer/Betten.
9. Betriebskostenabrechnung gegenüber Untermietern (Ebene B) weiterhin nicht automatisiert; Oberfläche für Ebene A fehlt (nur API).
