# 0002 – Dashboard-KPI-Definitionen und Stichtagslogik
Status: akzeptiert als **Arbeitsstand der Orchestrierung auf Basis der vom Eigentümer vorgegebenen Definitionen**; die unten markierten Annahmen sind **nicht** vom Eigentümer bestätigt und stehen zur Bestätigung aus · Datum: 2026-11-15
Betroffen: zentrale Finanzdateien `services/charges.py`, `services/economics.py` (Orchestrator-Freigabe hiermit erteilt, nur für Lesepfade).

## Vorgaben des Eigentümers (wörtlich übernommen)
1. `upcoming_contract_ends`: nur aktive Verträge mit erreichtem Mietbeginn, Ende steht noch bevor und liegt im **konfigurierten** Vorschauzeitraum; nicht begonnene Verträge ausgeschlossen.
2. `units`: nur aktive Wohneinheiten in aktiven Objekten.
3. `open_receivables`: stichtagsbezogen; Zahlungen mit Buchungsdatum nach dem Stichtag reduzieren die offene Forderung zum Stichtag nicht (600/500/100 → 100); historische Stichtage unterstützen.

## Entscheidungen / Umsetzungsform
* Eine zentrale Funktion je Größe; Dashboard, Hinweise (`reminders`) und Wirtschaftlichkeits-Momentaufnahme (`current_month_figures`) nutzen dieselbe: `leases.contract_end_due/upcoming_ends`, `charges.receivable_position(db, as_of)`; `units` wie `economics.Structure` (Objekt **und** Einheit aktiv).
* Vorschauzeitraum: neue Einstellung `contract_end_preview_days` (Standard 90, Env `LEVENTUM_CONTRACT_END_PREVIEW_DAYS`), eine Quelle für Dashboard und Hinweise. Keine Oberflächen-Einstellung, keine Schemaänderung.
* Stichtag: optionaler Query-Parameter `as_of` an `GET /dashboard` (ohne Parameter unverändert „heute“). Zukunftsdatum → Fehler 422 (keine Prognose im Dashboard). Antwort ergänzt um `as_of` und je KPI `historical_supported`.
* Keine Änderung an Buchungen, Zahlungen, Zuordnungen oder Schema.

## Annahmen (zur Bestätigung durch den Eigentümer)
* **A1 Fälligkeit (E1):** „Offene Forderungen“ bleibt **unabhängig von der Fälligkeit** (wie bisher, Lesart A); das weicht von `offen_zum_stichtag` der Wirtschaftlichkeit ab (nur fällig bis Stichtag). Entscheidung bewusst nicht geändert, weil der Eigentümertext keine Fälligkeitsregel nennt. Empfehlung des Domain-Agenten wäre Lesart B.
* **A2 Vertragsarten (E2):** `upcoming_contract_ends` zählt Haupt- **und** Untermietverträge (wie bisher und wie `reminders`).
* **A3 Gekündigte Verträge:** Ein gekündigter, noch laufender Vertrag (phase `notice`) zählt mit seinem wirksamen Ende.
* **A4 Grenzen:** `heute ≤ Ende ≤ heute + N`, beide inklusiv.
* **A5 Zahlungswirkung (E3):** Zahlungen wirken nach `Payment.booking_date`, nicht nach dem Zuordnungszeitpunkt; Stornobuchungen wirken ab ihrem eigenen Buchungsdatum.
* **A6 Bekannte Einschränkungen historischer Stichtage (E4, E5, E7), NICHT behoben:** (a) eine später zurückgenommene Zuordnung (`deallocate`) verändert historische Stichtage rückwirkend; (b) heute stornierte Sollstellungen fehlen in historischen Stichtagen; (c) Stammdaten (`is_active`, Struktur), Vertragsstatus (ended/cancelled), Aufgaben und Reparaturen zeigen immer den heutigen Stand; (d) Objekt-Deaktivierung ist bei laufenden Verträgen nicht gesperrt. Diese Punkte werden in der API als `historical_supported: false` bzw. in der Dokumentation ausgewiesen.
* **A7** Keine Verrechnung von Überzahlungen über Forderungen hinweg (nur `offen > 0` wird summiert).
