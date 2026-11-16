---
name: operating-cost-accounting
description: "Betriebskostenabrechnung Ebene A (Vermieter→Leventum) und Vergleich Ebene B (Untermieter): Positionen, Umlageschlüssel, Vorauszahlungen, Verteilung, Einfrieren, Nicht-Zuordenbares. Verwenden bei Änderungen an `utility.py` und der Betriebskosten-UI."
---

# Skill: operating-cost-accounting

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Betriebskostenlogik korrekt, ohne Schätzwerte und ohne automatische Nachforderungen umsetzen.

## 2. Einsatzbedingungen
- Änderungen an `services/utility.py`, `/utility-statements*`, `frontend/src/pages/Utility.tsx`.

## 3. Fachliche Grundlagen
Statements mit Positionen (Kostenart, Betrag, Schlüssel none|area|equal|persons|consumption|custom, Umlagefähigkeit), Gewichte je Wohneinheit, Vorauszahlungen (Quelle agreed_calculated|statement|manual), Ergebnis (nachzahlung/guthaben/ausgeglichen), Status draft→captured→reviewed. Bei reviewed: `allocation_snapshot` eingefroren. Ebene B: Vergleich nur als Prüfgrundlage, `claim_possible` bedeutet ‚Prüfung nötig‘.

## 4. Arbeitsanweisungen
1. Positionssumme und Verteilsumme prüfen (Largest-Remainder). 2. Nicht umlagefähige/ohne Schlüssel → ‚nicht zuordenbar‘, nicht verteilen. 3. Fehlende Flächen/Gewichte → Warnung, keine Schätzung. 4. Prüfstatus setzen nur mit Vorauszahlungen; danach Sperre. 5. Vergleich Ebene B: Pauschale/Inklusivmiete/keine Vereinbarung → kein Anspruch; Vorauszahlung → Abrechnung vereinbart? → Prüfung.

## 5. Verbindliche Regeln
- Keine geschätzten Umlagewerte; keine automatische Nachforderung; Ebenen nie vermischen.
- Geprüfte Abrechnung unveränderlich (Snapshot).

## 6. Typische Fehler
Rundungsrest unverteilt lassen; Flächenänderung wirkt auf geprüfte Abrechnung; Mehrfach-WE-Untermietvertrag automatisch zugeordnet.

## 7. Qualitätskriterien
Summe Verteilung + Nicht-Zuordenbares = Gesamtkosten; Snapshot stabil bei Flächenänderung.

## 8. Erforderliche Tests
`test_phase_c_utility.py`, `test_j_editing_history.py` (Snapshot), E2E 09.

## 9. Übergabekriterien
Übergabe mit Rechenbeispiel; Review Domain & Finance + QA.

## 10. Grenzen und Eskalationsfälle
Eskalation: Rechtsfragen (Umlagefähigkeit, Fristen), neue Schlüsselarten, Nachforderungslogik.
