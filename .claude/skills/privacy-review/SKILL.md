---
name: privacy-review
description: "Datenschutzprüfung: Datensparsamkeit, lokale Datenhaltung, Maskierung, Löschkonzept/Aufbewahrung, keine Übertragung. Verwenden bei neuen personenbezogenen Feldern, Exporten, Logs, Dokumenten und Tests mit Daten."
---

# Skill: privacy-review

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Personenbezogene Daten schützen und Datenabfluss verhindern.

## 2. Einsatzbedingungen
- Neue Felder zu Personen/IBAN/Geburtsdatum; Exporte/Backups; Logging; Testdaten.

## 3. Fachliche Grundlagen
Lokale Datenhaltung, keine ausgehenden Verbindungen; Audit maskiert IBAN/Geburtsdatum; Aufbewahrung `document_retention_days` (Annahme 3650); `purge` nur Admin; DB/Dokumente unverschlüsselt, Backups optional verschlüsselt.

## 4. Arbeitsanweisungen
1. Neue Datenfelder: Notwendigkeit, Pflicht/optional, Maskierung im Audit. 2. Logs/Fehler/Berichte auf personenbezogene Daten prüfen. 3. Testdaten: erfunden. 4. Exporte/Backups: Inhalt und Verschlüsselungsstatus ehrlich nennen. 5. Löschpfade: Weichlöschung mit Begründung, `purge` Regeln.

## 5. Verbindliche Regeln
- Keine echten Personendaten in Repo/Tests/Berichten.
- Keine rechtliche DSGVO-Bewertung; Verantwortlicher entscheidet.

## 6. Typische Fehler
Personendaten in Audit-Details/Logs; Beispiel-IBAN echt; Backup als ‚verschlüsselt‘ bezeichnet, ohne Passphrase erstellt.

## 7. Qualitätskriterien
Datenfluss dokumentiert; keine Daten verlassen die Maschine.

## 8. Erforderliche Tests
Audit-Maskierungstests (`test_j_editing_history.py`), Backup-Tests (`test_l_security_backup.py`).

## 9. Übergabekriterien
Befundliste; Empfehlungen für Dokumentation (`04-sicherheit-backup.md`).

## 10. Grenzen und Eskalationsfälle
Eskalation: Aufbewahrungsfristen, Auskunfts-/Löschansprüche, Auftragsverarbeitung → Mensch/Rechtsberatung.
