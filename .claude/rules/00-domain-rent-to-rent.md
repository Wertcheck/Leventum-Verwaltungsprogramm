# Domäne: Rent-to-Rent (Pflichtwissen für alle Agenten)

Leventum Real Estate GmbH mietet Objekte von **Eigentümern/Vermietern** (Hauptmietvertrag, `kind=main`, Leventum = Mieter) und vermietet sie an **Untermieter** (Untermietvertrag, `kind=sub`, Leventum = Vermieter). Zwei Ebenen, die nie vermischt werden:
- **Ebene A (upstream):** Leventum ↔ Vermieter (Hauptmiete, Betriebskostenabrechnung des Vermieters, Verbindlichkeiten).
- **Ebene B (downstream):** Leventum ↔ Untermieter (Untermiete, Vorauszahlungen/Pauschalen, Forderungen).

**Raumhierarchie:** Objekt → Wohneinheit → Zimmer → Bett. Vermietbar ist nur eine **Vermietungseinheit** (`RentableUnit`, eindeutig über `space_key`) auf Ebene Objekt/WE/Zimmer/Bett. Räumliche Überschneidung (Pfad-Präfix) zwischen gleichzeitig laufenden Untermietverträgen ist unzulässig und wird **nicht aufgeweicht**. „Blatt-Modell“ für Leerstand/Wirtschaftlichkeit: Bett | Zimmer ohne Betten | WE ohne Zimmer.

**Zentrale Definitionen (eine Quelle: `backend/leventum/services/leases.py`):** `is_running(lease, day)`, `phase(lease, today)` ∈ draft|cancelled|upcoming|active|notice|ended. „Aktiver Mieter“ = Partei mit ≥ 1 laufendem Untermietvertrag als Mieter/Mitmieter; ein gekündigter, noch laufender Vertrag zählt weiter. Neue Zählungen/Kennzahlen **nutzen diese Funktionen**, definieren nichts neu.

**Statusstufen von Verträgen/Sollstellungen/Zahlungen strikt trennen:** Soll (Sollstellung, vertraglicher Planwert) ≠ Ist (Zahlung, Buchungsdatum) ≠ Offen (Soll − zugeordnete Zahlungen). **Kautionen** laufen separat und **außerhalb** von Mietforderungen und Rentabilität. Leerstandskosten sind Teil der Hauptmiete (nicht zusätzlich abziehen).

**Rechtliches:** Die Software trifft **keine rechtliche Einordnung** (z. B. § 549 BGB nur als dokumentierter Prüfvermerk). Keine automatische Mahngebühr/Verzugszinsen, kein automatischer Mahnversand, keine automatischen Nebenkosten-Nachforderungen, keine geschätzten Umlagewerte. Annahmen (Mindestabstand Mahnstufen 7 Tage, Aufbewahrung 3650 Tage, kalenderbasierte Rhythmen) sind **Annahmen** und als solche zu kennzeichnen (`docs/07-annahmen-und-rechtsfragen.md`, `docs/IMPLEMENTIERUNGSPLAN.md`).
