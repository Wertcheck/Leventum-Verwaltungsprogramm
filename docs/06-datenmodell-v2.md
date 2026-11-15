# 06 – Datenmodell v2 (Phase C): Ergebnis der Modellüberprüfung

## 1. Prüfung des Modells aus Phase A
| Anforderung | Phase-A-Modell | Befund |
|---|---|---|
| Wohnung ganz, Haus ganz, Zimmer, Bett | Untermietvertrag ↔ genau **1 Einheit** | **nicht tragfähig** (Zimmer/Betten fehlten, „Einheit“ war fix) |
| Mehrere Mieter/Parteien je Vertrag, Firma mietet für Bewohner | `lessor_party_id` / `lessee_party_id` je 1 Partei | **nicht tragfähig** |
| Nebenkosten je Vertrag konfigurierbar (Pauschale / Vorauszahlung / individuell / enthalten) | 1 Betrag `service_charge_prepayment` im Vertrag | **nicht tragfähig** (Pauschale wäre als Vorauszahlung missverstanden worden) |
| Rechtliche Einordnung nur dokumentieren | nur Freitext `notice_note` | unzureichend |
| Eingehende NK-Abrechnung → Objekt/Einheiten, Nachzahlung/Guthaben | nur skizziert | vor Phase D vorgezogen |

Daher wurde das Modell **vor** der Implementierung überarbeitet (Migration `0002`). Die Phase-A-Tabellen waren nie angelegt, es gab keine Datenmigration.

## 2. Getrennte Ebenen
```
Immobilie (property)
 └─ Wohneinheit (unit)
     └─ Zimmer (room)
         └─ Bett / Schlafplatz (bed)

Vermietungseinheit (rentable_unit)  = genau EINE Ebene der Hierarchie (property|unit|room|bed), Vorfahren mitgesetzt
Vertrag (lease, kind = main | sub)  ──lease_item──► 1..n Vermietungseinheiten
                                    ──lease_party──► n Parteien mit Rolle (lessor, lessee, co_lessee, occupant, guarantor)
                                    ──lease_term──► versionierte Miete (Kaltmiete, Zuschläge)
                                    ──utility_agreement──► versionierte Nebenkostenvereinbarung
                                    ──lease_note──► Hinweise / Prüfvermerke (append-only)
Nebenkostenabrechnung (utility_statement, level upstream) ─► Positionen (tatsächliche Kosten) ─► Verteilung auf Wohneinheiten
Zahlung / Forderung: Phase D (bewusst nicht vorweggenommen)
```
**Räumliche Überschneidung:** Der Pfad (Objekt→WE→Zimmer→Bett) einer Vermietungseinheit wird als Tupel verglichen; zwei Einheiten kollidieren, wenn der Pfad der einen ein Präfix der anderen ist. Damit sind „ganze Wohnung“ und „Zimmer darin“ nie gleichzeitig im selben Zeitraum vermietbar, zwei verschiedene Betten aber sehr wohl.

## 3. Tabellen (Migration 0002)
`party`, `party_role`, `property`, `unit`, `room`, `bed`, `rentable_unit` (CHECK `level_consistent`), `lease_type`, `lease`, `lease_party`, `lease_item`, `lease_term`, `utility_agreement`, `lease_note`, `cost_type`, `utility_statement`, `utility_statement_unit`, `utility_statement_line`, `utility_line_weight`.
Geld und Flächen: BIGINT (×100), Datumsfelder `DATE`, keine DB-spezifischen Typen → PostgreSQL-fähig (nicht getestet).

## 4. Vertragsarten, rechtliche Einordnung
* `lease_type` ist **konfigurierbar** (Seeds: Hauptmiete, Wohnraum unbefristet/befristet, Zimmer, Bett, Monteurwohnung, Boardinghouse, Gewerbe, Sonstige). Der Typ ist ein **Ordnungsmerkmal, keine Rechtsaussage** und löst keine Rechtsfolge aus.
* Felder: `is_fixed_term`, `fixed_term_reason` (Befristungsgrund), `intended_use` (vereinbarte Nutzung), `legal_basis_ref` (z. B. „§ 549 BGB“, Freitext mit Vorschlagsliste), `legal_basis_note`, `legal_review_status` (`not_reviewed` | `in_review` | `reviewed`), Prüfer/Zeitpunkt, `internal_notes`, `lease_note` (Hinweis/Prüfvermerk).
* **Kein automatisches Setzen**: weder Befristung, Monteur noch Boardinghouse setzen `legal_basis_ref` oder den Prüfstatus (Test `test_no_automatic_legal_classification…`). `legal_review_status` ist nur über den expliziten Endpunkt `legal-review` änderbar (wird auditiert), nicht über PATCH.
* Hinweise (`hints`) wie „Rechtliche Einordnung nicht als geprüft dokumentiert“ sind rein informativ.

## 5. Nebenkostenvereinbarung (je Vertrag, versioniert)
| Modus | Betrag | Abrechnung vereinbart | Bedeutung in der Software |
|---|---|---|---|
| `prepayment` | ja | **ja** (automatisch) | Vorauszahlung, Abrechnung möglich (nach manueller Prüfung) |
| `flat_rate` | ja | **nein** (Setzen von „ja“ wird abgelehnt) | Pauschale, **keine** Abrechnung, keine Nachforderung |
| `included` | nein | nein | in der Gesamtmiete enthalten, addiert keinen NK-Soll |
| `individual` | nein | **ungeklärt (NULL)** bis manuell gesetzt | Beschreibung Pflicht, nie als abrechenbar angenommen |
| `none` | nein | nein | keine Nebenkosten vereinbart |

## 6. Nebenkosten – Ebene A und Vergleich mit Ebene B
* **Ebene A (Vermieter → Leventum):** `utility_statement` (level `upstream`) je Hauptmietvertrag und Zeitraum, Geltungsbereich = Wohneinheiten, Positionen (`cost_type`, Betrag, Verteilungsschlüssel, `allocable_status` unreviewed/allocable/not_allocable). Ergebnis = Σ Kosten − Vorauszahlungen (+ Nachzahlung / − Guthaben). Vorauszahlungen werden **nicht still als 0 angenommen**: fehlen sie, gibt es kein Ergebnis; Vorschlag aus Vereinbarung (Soll, tagesgenau) oder manuelle/abrechnungsseitige Erfassung (`prepayments_source`). Abweichung zum vom Vermieter ausgewiesenen Ergebnis wird gemeldet. Status `draft → captured → reviewed`; geprüfte Abrechnungen sind gesperrt (historischer Stand).
* **Verteilung:** Wohnfläche (aus Stammdaten), gleichmäßig, Personen/Verbrauch/individuell (Gewichte je Wohneinheit erforderlich). Fehlende Daten → Position bleibt **unverteilt** mit Warnung, nichts wird geraten. Largest-Remainder: Summe der Anteile = Betrag exakt.
* **Vergleich (Ebene B, nur Auswertung):** je Wohneinheit verteilte tatsächliche Kosten vs. vereinbarte Untermieter-Nebenkosten (Vorauszahlungen und Pauschalen **getrennt**, tagesgenau anteilig). `claim_status` je Vereinbarung: `settlement_agreed_review_required`, `no_claim_flat_rate`, `no_claim_included_in_rent`, `no_claim_no_utility_agreement`, `undetermined_manual_review`. **Es werden keine Forderungen erzeugt.** Untermietverträge über mehrere Wohneinheiten/das ganze Objekt werden als „nicht zuordenbar“ markiert.
* **Auswirkung auf den vorläufigen Deckungsbeitrag:** `NK-Ergebnis = Σ (Untermieter-NK-Soll aus Vorauszahlung + Pauschale) − verteilte tatsächliche Kosten`, ausdrücklich ohne mögliche Nachforderungen und mit separat ausgewiesenen unverteilten Kosten. Die Einbindung in die Gesamt-Wirtschaftlichkeit (inkl. Kaltmiete-Marge, Zahlungen) folgt in Phase D.

## 7. Bekannte Grenzen des Modells
* Räume/Betten werden **nicht** auf Kapazität (max. Personen) geprüft; ein Bett = eine Vermietung.
* Die Hauptmiete wird nicht auf Wohneinheiten verteilt (Phase D, `allocation_rule`).
* Verteilung der NK nur bis Wohneinheit, nicht bis Zimmer/Bett.
* Eine Abrechnung gehört zu **einem** Objekt und **einem** Hauptmietvertrag.
* Tagesbasierte Mieten (`rent_period = day`) werden gespeichert, aber nicht auf Monate hochgerechnet.
