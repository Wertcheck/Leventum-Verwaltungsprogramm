# Finanz-Invarianten (nicht verhandelbar; Änderungen nur mit Orchestrator + Domain & Finance + QA + Entscheidungsdokument)

1. **Beträge** sind `Decimal` mit 2 Stellen (DB: BIGINT × 100, `Money`), Rundung ROUND_HALF_UP, Währung EUR. Nie `float`.
2. **Verteilungen** (Betriebskosten, Rundungsreste) per Largest-Remainder: Summe der Anteile = Gesamtbetrag, deterministisch (Gleichstand → kleinerer Schlüssel).
3. **Sollstellungen werden nie überschrieben.** Erzeugung ist idempotent über `dedupe_key`; abweichender Betrag oder andere Periodenlänge → **Konflikt melden**, nicht ändern. Korrektur nur per Storno (`voided_at`) + neue Sollstellung.
4. **Rückwirkung nur mit ausdrücklicher Bestätigung** (`allow_backdated`); Vorschau (Dry-Run) schreibt nichts.
5. **Zahlungen sind unveränderlich** (append-only); Korrektur per **Gegenbuchung** mit Begründung. Zuordnungen ebenso.
6. **Konditionen/Vertragsbedingungen:** Änderung = neue Version ab Datum; Historie bleibt; keine stille Rückwirkung auf erzeugte Sollstellungen (Hinweis statt Änderung).
7. **Geprüfte Betriebskostenabrechnung:** Verteilung wird eingefroren (`allocation_snapshot`); danach keine Änderung durch Stammdaten.
8. **Offen zum Datenstand** = `min(Periodenende, heute)`; Prognose nur separat und als Prognose gekennzeichnet; nie Soll und Ist addieren.
9. **Mahnwesen:** nur Entwürfe; Freigabe manuell; keine Freigabe bei Platzhalter oder veraltetem Entwurf; Eskalation nur nach **dokumentiertem** Versand der Vorstufe; kein Versandcode; keine Gebühren/Zinsen.
10. **Bankimport:** Vorschlag → Prüfliste → ausdrückliche Bestätigung (`confirm: true`); Architektur nicht vereinfachen; Duplikaterkennung erhalten.
11. **Kautionen:** eigene Buchungen (gezahlt/zurückgezahlt/einbehalten), nie in Rentabilität oder Mietforderungen.
Jede Änderung an diesen Punkten verlangt Tests, die das Verhalten **beweisen** (vorhandene Tests: `backend/tests/test_d_*.py`, `test_i_rhythms.py`, `test_phase_c_utility.py`).
