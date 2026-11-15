---
name: rental-contract-domain
description: Fachmodell Rent-to-Rent: Haupt-/Untermietverträge, Phasen, Raumhierarchie, Überlappungsregeln, Konditionsversionen, Kündigung, Vertragslaufzeit. Verwenden bei Änderungen an Verträgen, Vermietungseinheiten, Mieterlisten, Dashboard-Definitionen.
---

# Skill: rental-contract-domain

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Vertrags- und Raumlogik fachlich korrekt und konsistent halten.

## 2. Einsatzbedingungen
- Änderungen in `leases.py`, `master.py`, `tenant_overview.py`, `integrity.py`, Vertrags-/Objekt-Seiten.

## 3. Fachliche Grundlagen
`00-domain-rent-to-rent.md`. Phasen: draft|cancelled|upcoming|active|notice|ended (`leases.phase`). `space_key` eindeutig; Pfad-Präfix-Überschneidung blockiert; Untermietvertrag nur auf Vermietungseinheit im Rahmen eines laufenden Hauptmietvertrags; Kündigung = Zusatzmerkmal, Vertrag läuft bis wirksames Ende.

## 4. Arbeitsanweisungen
1. Betroffene Zustände und Übergänge aufzeichnen. 2. Überschneidungs-/Aktivierungsregeln lesen (`validate_*`, `activate`). 3. Neue Regel nur ergänzen, nie aufweichen. 4. Datumsänderung: Folgen für Sollstellungen als Hinweis (`impact`), nicht still ändern. 5. Testfälle für Grenzdaten (Beginn/Ende am selben Tag, Anschlussvertrag).

## 5. Verbindliche Regeln
- Überlappungsregeln nicht aufweichen.
- Keine automatische rechtliche Einordnung (§ 549 BGB nur Prüfvermerk).
- Keine stillen Änderungen von Vertragsbedingungen; neue Version ab Datum.

## 6. Typische Fehler
- Phase mit Rohstatus verwechseln (`lease_status` vs. `lease_raw_status`).
- Eigene ‚aktiv‘-Definition im Frontend.
- Anschlussverträge am Stichtag als Überlappung/Lücke falsch bewerten.

## 7. Qualitätskriterien
Jede Regel durch Test mit Grenzdatum belegt; Definitionen aus `leases.py` genutzt.

## 8. Erforderliche Tests
`test_phase_c_spaces_leases.py`, `test_j_editing_history.py`, `test_k_tenant_panel.py`, `test_h_integrity_documents.py` + E2E 04/08/19/20.

## 9. Übergabekriterien
Übergabe mit Zustandsdiagramm/Tabelle der Änderung; Review Domain & Finance + QA.

## 10. Grenzen und Eskalationsfälle
Eskalation: neue Vertragsarten, rechtliche Bewertung, Änderung der Aktiv-/Überlappungsdefinition.
