---
name: data-integrity-review
description: "Datenintegritätsprüfung: Waisen, Duplikate, Überlappungen, Überbelegung, Summenproben, Unveränderlichkeit. Verwenden nach Migrationen, Importen und größeren Änderungen an Verträgen/Finanzen."
---

# Skill: data-integrity-review

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Konsistenz der Daten und Unveränderlichkeitsregeln belegen.

## 2. Einsatzbedingungen
- Nach Migration/Import/Restore; vor Releases; bei Zahlen-Inkonsistenzen.

## 3. Fachliche Grundlagen
`services/integrity.py` (`check(db)`: Waisen, falsche Elternketten, `space_key`, Duplikate, überlappende Untermietverträge, Überbelegung), `GET /system/integrity`, `documents.verify_all`. Append-only: Zahlungen, Zuordnungen, Kautionsbuchungen, Audit.

## 4. Arbeitsanweisungen
1. Prüfung ausführen (API/Test). 2. Summenproben: Zuordnungen ≤ Zahlungsbetrag; Offen ≥ 0; Verteilsummen. 3. Stichproben per SQL (read-only). 4. Befunde mit Beispielzeilen melden. 5. Neue Invariante → in `integrity.py` + Test aufnehmen.

## 5. Verbindliche Regeln
- Prüfer ändert keine Daten.
- Keine Bereinigung echter Daten ohne menschliche Freigabe.

## 6. Typische Fehler
Prüfung nur auf leerer Testdatenbank; Sitzungscache verfälscht Ergebnis; Fehlalarme durch Weichlöschung.

## 7. Qualitätskriterien
Befund reproduzierbar; Zähler stimmen mit SQL überein.

## 8. Erforderliche Tests
`test_h_integrity_documents.py`, `test_d_charges_payments.py`, `test_money_storage.py`.

## 9. Übergabekriterien
Befundliste mit Beleg; empfohlene Korrektur (ausgeführt vom Besitzer).

## 10. Grenzen und Eskalationsfälle
Eskalation: echte Datenabweichungen in Produktivdaten, mögliche Manipulation.
