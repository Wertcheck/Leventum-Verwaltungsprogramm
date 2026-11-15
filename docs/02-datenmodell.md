# 02 – Fachliches Datenmodell und Datenbankstruktur (Phase A)

> **Überarbeitet in Phase C:** Die Abschnitte 3 und 4 (Stammdaten, Verträge) sind durch [`06-datenmodell-v2.md`](06-datenmodell-v2.md) ersetzt (Raumhierarchie, Vermietungseinheit, mehrere Vertragsparteien, getrennte Nebenkostenvereinbarung). Abschnitt 5 (Finanzen) bleibt Entwurf für Phase D und wird dort an v2 angepasst.

**Status: Entwurf [geplant].** In Phase B ist nur der Abschnitt „Fundament“ als Migration umgesetzt (Benutzer, Rollen, Sitzungen, Audit, Einstellungen). Alle übrigen Tabellen folgen in den Phasen C–E und werden dort per Alembic angelegt.

## 1. Fachliche Grundidee Rent-to-Rent

```
Eigentümer (Party) ──besitzt──► Objekt ──enthält──► Wohneinheit(en)
        │                                              ▲   ▲
Hauptmietvertrag  (Vermieter ──► Leventum)  ───deckt───┘   │
        │ parent                                           │
Untermietvertrag  (Leventum ──► Mieter)  ──── genau 1 Einheit
```

Zwei **getrennte Zahlungsströme** auf **getrennten Verträgen**:
- *Verbindlichkeit* (payable): Leventum schuldet dem Vermieter Hauptmiete + NK-Vorauszahlung.
- *Forderung* (receivable): Leventum fordert vom Untermieter Untermiete + NK-Vorauszahlung.

Es gibt **vier** Wertebenen, die nie vermischt werden dürfen:
1. **Soll** (vereinbart/gestellt) – `charge`
2. **Ist** (tatsächlicher Zahlungsfluss) – `payment`
3. **Offen** (Soll − zugeordnete Ist) – berechnet
4. **Abgegrenzte Kosten** (Rechnungen, die noch nicht bezahlt sind) – `invoice`

### Wirtschaftlichkeit (berechnet, nicht gespeichert)
Zwei Rechnungen, strikt getrennt dargestellt:

* **Mietmarge (Kaltmiete):** Σ Unter-Kaltmiete (Soll) − Σ Haupt-Kaltmiete (Soll, auf Einheiten verteilt).
* **Nebenkosten-Durchlauf:** Σ NK-Vorauszahlungen Unter − Σ NK-Vorauszahlungen Haupt. Das ist **keine** Marge, sondern ein offener Saldo bis zur Abrechnung beider Ebenen.
* **Vorläufiger Deckungsbeitrag (Soll-Basis)** = Mietmarge + NK-Durchlauf-Saldo − objektbezogene Kosten (Rechnungen). *(Korrektur in Phase D: Der frühere Zusatz „− Leerstandskosten“ war eine Doppelzählung, weil das Hauptmiete-Soll die Leerstandszeiten bereits enthält. Leerstandskosten sind nur eine Teilmenge der Hauptmietkosten.)*
* **Zahlungsbasierter Deckungsbeitrag (Ist-Basis)** = Zahlungseingänge − Zahlungsausgänge im Zeitraum.
* **Leerstandskosten** (Ausweisung, kein weiterer Abzug) = anteilige Haupt-Gesamtmiete (Kalt + NK) der kleinsten Einheit für Tage ohne laufenden Untermietvertrag *innerhalb* eines Hauptmietvertrags (tagesgenau). Details: `08-phase-d-konzept.md`.
* Die Ausweisung heißt **„vorläufiger Deckungsbeitrag“**, nie „Gewinn“.

Hauptmiete auf Objektebene → Einheiten: `allocation_rule` (Methode: Wohnfläche / gleichmäßig / individuelle Gewichte). Rundung per **Largest-Remainder-Verfahren**, sodass die Summe der Teilbeträge exakt der Gesamtmiete entspricht. Regel ist versioniert (gültig ab), die Methode steht im Bericht.

## 2. Fundament (Phase B – umgesetzt)

| Tabelle | Zweck | Wichtige Spalten |
|---|---|---|
| `role` | Rollen | `code` (admin, verwaltung, buchhaltung, objektbetreuung, lesend), `name` |
| `app_user` | Benutzer | `username` (unique), `display_name`, `password_hash` (Argon2id), `role_id`, `is_active`, `failed_login_count`, `locked_until`, `created_at` |
| `user_session` | Serverseitige Sitzungen | `token_hash` (SHA-256, unique), `user_id`, `created_at`, `expires_at`, `last_seen_at`, `revoked_at` |
| `audit_event` | Append-only-Protokoll | `occurred_at` (UTC), `actor_user_id` (nullable bei System), `action`, `entity_type`, `entity_id`, `summary`, `details` (JSON) |
| `app_setting` | Schlüssel/Wert | `key` (PK), `value` (JSON) |

Berechtigungen (Rolle → Rechte) liegen im Code (`security/permissions.py`), nicht in der DB; so sind Rechte versioniert und testbar. Aktuell wird nur `admin` ausgeliefert; die anderen Rollen sind angelegt, aber noch nicht zuweisbar über die UI.

## 3. Stammdaten (Phase C – Entwurf)

| Tabelle | Wichtige Spalten / Regeln |
|---|---|
| `party` | `kind` (person/company), `display_name`, `first_name`, `last_name`, `company_name`, `birth_date` (optional, nur wenn erforderlich), Adresse, `email`, `phone`, `iban` (nur für Zahlungspartner), `notes`, `is_own_organization` (Leventum selbst; mehrere Gesellschaften möglich) |
| `party_role` | (`party_id`, `role`): owner, landlord, tenant, service_provider – eine Party kann mehrere Rollen haben |
| `property` | `name`, Adresse, `property_type` (mfh, wohnung, efh, gewerbe, sonstige), `owner_party_id`, `year_built`, `total_area`, `heating_type`, Ausstattung, Notizen. *Vertraglicher Vermieter* wird aus dem aktiven Hauptmietvertrag abgeleitet, nicht doppelt gespeichert. |
| `unit` | `property_id`, `unit_number` (unique je Objekt), `floor`, `living_area` (Skal. ×100), `rooms`, Ausstattung, `manual_status` (reserviert/Renovierung/nicht verfügbar, sonst NULL). **Belegung vermietet/leer wird aus Untermietverträgen berechnet**, nicht von Hand gepflegt. |

## 4. Verträge (Phase C – Entwurf)

| Tabelle | Wichtige Spalten / Regeln |
|---|---|
| `lease` | `kind` (`main`/`sub`), `lessor_party_id`, `lessee_party_id`, `parent_lease_id` (Pflicht bei `sub`, zeigt auf `main`), `start_date`, `end_date` (NULL = unbefristet), `notice_period_months`, `notice_note` (Freitext, keine Rechtsauskunft), `status` (draft/active/terminated/ended), `deposit_amount`, `payment_rhythm`, `payment_due_day`, `subletting_permitted` (nur `main`), `terminated_on`, `termination_effective_on` |
| `lease_unit` | (`lease_id`, `unit_id`): Hauptvertrag deckt 1..n Einheiten (ganzes Objekt = alle Einheiten); Untermietvertrag genau 1 Einheit |
| `lease_term` | versionierte Konditionen: `lease_id`, `valid_from`, `valid_to`, `base_rent`, `service_charge_prepayment`, `other_charges`. Mieterhöhungen = neue Zeile, keine Überschreibung |
| `allocation_rule` / `allocation_weight` | Verteilung der Hauptmiete (Objekt → Einheiten), versioniert |

Konsistenzregeln (Service-Ebene, mit Tests):
1. Keine zwei aktiven Untermietverträge auf derselben Einheit mit überlappendem Zeitraum (**harter Fehler**).
2. Untermietvertrag muss vollständig von einem aktiven Hauptmietvertrag mit `subletting_permitted` abgedeckt sein (**Fehler**; Ausnahme nur per ausdrücklicher Bestätigung, wird im Audit protokolliert).
3. Überlappende Hauptmietverträge derselben Einheit → Warnung.
4. Zeiträume ohne Untermietvertrag innerhalb eines Hauptvertrags = Leerstand.
5. Beendete/stornierte Verträge werden nicht gelöscht.

## 5. Finanzen (Phase D – Entwurf)

| Tabelle | Wichtige Spalten / Regeln |
|---|---|
| `charge` (Sollstellung) | `lease_id`, `direction` (receivable/payable), `charge_type` (base_rent, service_prepayment, settlement, deposit, other), `period_start/end`, `due_date`, `amount`, `voided_at/by/reason`, `corrects_charge_id`. Nie löschen; Korrektur = Storno + Neubuchung |
| `payment` | `direction` (in/out), `booking_date`, `amount`, `counterparty_party_id`, `method`, `reference`, `property_id`, `document_id`, `reverses_payment_id`. **Unveränderlich** (Triggerloser Schutz: Service erlaubt kein UPDATE auf Betrag/Datum; Korrektur = Gegenbuchung) |
| `payment_allocation` | `payment_id`, **entweder** `charge_id` **oder** `invoice_id` (CHECK: genau eines), `amount`. Teilzahlung = Zuordnung < Soll; Überzahlung = Zahlung − Σ Zuordnungen > 0 |
| `invoice` | `supplier_party_id`, `property_id`, `unit_id`, `cost_type_id`, `invoice_date`, `due_date`, `gross_amount`, `document_id`, `status`; Entwürfe aus OCR/KI bleiben `suggested` bis zur menschlichen Bestätigung |
| `cost_type` | `code`, `name`, Kategorie, `allocable_default`, Standard-Schlüssel (Umlagefähigkeit **konfigurierbar**, nie pauschal) |
| `settlement` | Betriebskostenabrechnung: `level` (`upstream` = Vermieter→Leventum, `downstream` = Leventum→Mieter), `lease_id`, Zeitraum, `status` (draft/reviewed/final), `upstream_settlement_id` (Verknüpfung der Ebenen), Ergebnis |
| `settlement_line` | `cost_type_id`, Gesamtkosten, `allocable` (Ja/Nein, begründet), Verteilungsschlüssel, Anteil, Vorauszahlung, Ergebnis |
| `consumption_reading` | Verbrauchswerte für Schlüssel „Verbrauch“ |

Rundung: alle Geldbeträge auf 2 Nachkommastellen, `ROUND_HALF_UP`, Verteilungen per Largest-Remainder.

## 6. Operative Verwaltung (Phase E – Entwurf)

`task` (explizite FKs auf party/property/unit/lease/invoice/repair), `repair` + `repair_event` (Verlauf), `document` (Metadaten: `storage_key`, `sha256`, `mime`, `size`, `doc_type`, `original_name`) + `document_link` (Typ/ID-Zuordnung, validiert über Allowlist), `communication` (Kanal, Richtung, Betreff, Text), `payment_reminder` (Stufe, `charge_id`), `handover_protocol`, `note`.

Polymorphe Verknüpfungen (`document_link`, `communication`, `audit_event`) haben keine DB-seitigen Fremdschlüssel; die Integrität stellen Services über eine Allowlist der Entitätstypen sicher. Bewusster Kompromiss gegenüber 20 Nullable-FK-Spalten.

## 7. Querschnitt

* `created_at/updated_at/created_by/updated_by` auf allen Fachtabellen.
* Jede schreibende Service-Operation erzeugt ein `audit_event` (Wer, Wann, Was, Vorher/Nachher bei Finanzdaten).
* Soft-Cancel statt Delete für Verträge, Sollstellungen, Zahlungen, Rechnungen.
