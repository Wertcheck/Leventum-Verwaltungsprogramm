# 07 – Fachliche Annahmen und offene Rechtsfragen (Phase C)

**Die Software erteilt keine Rechtsauskunft. Nichts hier wurde juristisch geprüft.**

## A. Getroffene Annahmen (technisch, jederzeit änderbar)
| # | Annahme | Wo |
|---|---|---|
| A1 | Laufend = Status `active` oder `terminated`; wirksames Ende = `termination_effective_on` sonst `end_date`. Entwürfe blockieren keine Flächen, die Prüfung erfolgt beim Aktivieren. | Überschneidung |
| A2 | Direkt anschließende Verträge (Ende 31.3., Beginn 1.4.) sind zulässig; ein Tag Überlappung ist ein Fehler. | Überschneidung |
| A3 | Hauptmiete deckt eine Untervermietung nur, wenn `subletting_permitted = true`. `NULL` (ungeklärt) gilt als **nicht erlaubt**. Ausnahme nur mit dokumentierter Begründung (`coverage_override_reason`, wird auditiert). | Deckung |
| A4 | Deckung muss den **gesamten** Untermietzeitraum lückenlos abdecken (mehrere aufeinanderfolgende Hauptverträge sind zulässig). Unbefristete Untermiete braucht unbefristeten Hauptvertrag. | Deckung |
| A5 | Teilmonate werden **tagesgenau** (Tage/Tage des Monats) gerechnet. Rundung auf Cent, kaufmännisch. | NK-Vorauszahlung, Vergleich |
| A6 | Pauschale und „enthalten“ führen nie zu einer Abrechnungs-/Nachforderungsfähigkeit; `individual` bleibt „ungeklärt“, bis manuell gesetzt. | Nebenkostenvereinbarung |
| A7 | Vorauszahlungen (Soll) laut Vereinbarung ≠ tatsächlich gezahlte Beträge; Zahlungen werden erst in Phase D erfasst. Bis dahin ist das Ergebnis eine **Soll-Betrachtung**. | Ebene A |
| A8 | Gewichte für Personen/Verbrauch/individuell werden je Wohneinheit manuell erfasst (2 Nachkommastellen). | Verteilung |
| A9 | Die eigene Organisation (Leventum) ist eine Partei mit `is_own_organization`; beim Hauptvertrag muss sie Mieter, beim Untervertrag Vermieter sein. | Vertragsprüfung |
| A10 | Verträge werden nicht gelöscht; Entwürfe können (mit Begründung) storniert werden. Stammdaten werden deaktiviert statt gelöscht (UI dafür noch nicht umgesetzt). | Datenhaltung |
| A11 | Tie-Break bei der Cent-Verteilung: kleinerer Schlüssel (kleinere ID) erhält den Rest-Cent zuerst. | Verteilung |

## B. Offene Rechtsfragen (vor produktiver Nutzung mit Fachberatung klären)
1. **Einordnung je Vertrag:** Wann gilt ein befristeter Vertrag, eine Monteurwohnung oder ein Boardinghouse-Vertrag als Wohnraummietverhältnis, und welche Vorschriften (u. a. § 549 BGB und die dort geregelten Ausnahmen) sind im Einzelfall anwendbar? → Die Software dokumentiert Grundlage, Prüfstatus und Vermerk, entscheidet nichts.
2. **Befristungsgrund:** Welche Befristungen sind zulässig und wie ist der Grund zu dokumentieren? Das Feld ist Freitext; kein Abgleich mit Rechtsvorschriften.
3. **Gewerbliche Zwischenvermietung:** Rechtsfolgen für Untermieter bei Beendigung des Hauptmietvertrags und Anforderungen an die Vertragsgestaltung.
4. **Nebenkostenabrechnung gegenüber Untermietern:** Voraussetzungen (Vereinbarung, Umlagefähigkeit der Kostenarten, Abrechnungsfrist, Formerfordernisse, Heizkostenabrechnung). `cost_type` und `allocable_status` sind neutral vorbelegt (`unreviewed`); es gibt **keine** hinterlegte Liste umlagefähiger Kosten.
5. **Pauschale vs. Vorauszahlung:** Bei Mischformen (`individual`) ist die vertragliche Auslegung manuell zu klären, bevor eine Abrechnung erfolgt.
6. **Zimmer-/Bettenvermietung:** Mietrechtliche Einordnung (z. B. Gemeinschaftsflächen, Mitnutzung), Haftungs-/Kautionsfragen.
7. **Eingehende Abrechnungen (Ebene A):** Fristen und Einwendungsmöglichkeiten gegenüber dem Vermieter; die Software berechnet lediglich Differenzen und weist Abweichungen aus.
8. **Datenschutz:** Erfassung von Bewohnern (Rolle `occupant`), Geburtsdaten, Aufbewahrung/Löschung.
9. **Steuern/Umsatzsteuer** der verschiedenen Vermietungsformen.

## C. Weiterhin offene fachliche Entscheidungen
Kaution (beidseitig), Mietanpassungen (Staffel/Index), Standard-Verteilung der Hauptmiete auf Einheiten, Leerstandsdefinition, Bankimport, Mahnwesen, Messdienst/Heizkosten, Backup-Ziel/-Verschlüsselung, Logo (Vektor). Siehe `05-entwicklungsplan-und-offene-fragen.md`.
