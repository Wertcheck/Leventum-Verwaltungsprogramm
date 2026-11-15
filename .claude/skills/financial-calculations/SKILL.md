---
name: financial-calculations
description: Prüfung und Umsetzung von Geldberechnungen: Beträge, Rundung, Tagesanteile, Perioden, Verteilung, offene Posten, Datenstand/Prognose. Verwenden bei jeder Änderung an Sollstellungen, Zahlungen, Betriebskosten, Wirtschaftlichkeit, Dashboard-Geldkennzahlen.
---

# Skill: financial-calculations

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Rechenlogik korrekt, nachvollziehbar und mit Handrechnung belegt halten.

## 2. Einsatzbedingungen
- Änderung/Prüfung in `charges.py`, `payments.py`, `deposits.py`, `utility.py`, `economics.py`, `dashboard.py`, `dunning.py`.

## 3. Fachliche Grundlagen
`10-finance-invariants.md` ist maßgeblich. Betrag = Decimal (2 Nachkommastellen, ROUND_HALF_UP). Monatsanteile tagesanteilig, je Monat gerundet (`monthly_components`). Perioden kalenderbasiert (Quartal/Halbjahr/Jahr), vorschüssig am Fälligkeitstag des Periodenbeginns, geklemmt auf Vertragsbeginn; `dedupe_key`. Offen = Soll − zugeordnete Zahlungen; Datenstand `min(Periodenende, heute)`; Prognose getrennt.

## 4. Arbeitsanweisungen
1. Bestehende Tests der Funktion lesen. 2. Handrechnung mit konkreten Beispielzahlen (inkl. Teilmonat, Rundungsrest) aufschreiben. 3. Code gegen Handrechnung prüfen. 4. Randfälle: Vertragsbeginn mitten im Monat, Vertragsende, Teilzahlung, Storno, Überzahlung, leere Konditionen. 5. Summenprobe: Verteilung = Gesamtbetrag. 6. Änderung nur mit Tests, die die Invariante **beweisen**.

## 5. Verbindliche Regeln
- Keine Rückwirkung, kein Überschreiben, keine Rundungsdifferenzen verschweigen.
- Keine Annahmen mit Geldwirkung ohne Kennzeichnung und menschliche Freigabe.
- Soll und Ist nie addieren.

## 6. Typische Fehler
`float`; Rundung erst am Ende statt je Monat/Position; Summe der Anteile ≠ Gesamtbetrag; zukünftiger Stichtag als ‚überfällig‘; Erwartungswerte aus dem Code abgeleitet statt von Hand.

## 7. Qualitätskriterien
Handrechnung reproduziert Codeergebnis exakt; Summenprobe; Idempotenztest (zweiter Lauf ändert nichts).

## 8. Erforderliche Tests
Backend-Tests `test_d_charges_payments.py`, `test_i_rhythms.py`, `test_d_economics.py`, `test_phase_c_utility.py`, `test_dashboard.py` + volle Suite.

## 9. Übergabekriterien
Übergabe mit Rechenbeispielen, betroffenen Invarianten, Testergebnissen; Pflichtreview Domain & Finance + QA.

## 10. Grenzen und Eskalationsfälle
Eskalation: neue Rundungs-/Periodenregel, Steuer-/Rechtsfragen, Änderung bestehender Sollstellungen.
