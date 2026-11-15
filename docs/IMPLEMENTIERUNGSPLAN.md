# Implementierungsplan (priorisiert)

Reihenfolge entspricht dem verbindlichen Arbeitsablauf. Nach jedem Paket: Tests, Dokumentation, Git-Status, Commit.

| Nr. | Paket | Kern | Abnahmekriterium |
|---|---|---|---|
| **P1** | **Fachliche Korrekturen** | (a) Mahn-Eskalation nur nach *versandter* Vorstufe; (b) Mahnwesen-UI: Art, Zeitraum, Sollstellungs-Nr., getrennte Zähler „neu vorbereitbar / Entwurf vorhanden / wartet / freigegeben“; (c) Wirtschaftlichkeit: **Datenstand** = min(Periodenende, heute), Prognose separat und gekennzeichnet; (d) zentrale Definitionen „laufender Vertrag“, „aktiver Mieter“, Vertragsphase (`upcoming/active/notice/ended`); Dashboard und Mieterliste nutzen dieselbe Funktion, KPI mit Definitionstext; (e) Vermietungseinheiten: eindeutiger `space_key` + Integritätsprüfung + klare Zusammenfassung; (f) Dokumente: Integritätsprüfung beim Download, `verify`, geregelte endgültige Löschung (Aufbewahrungsfrist, nur Admin, Grund, Audit) | Tests je Punkt; Regressionstests für alle bestätigten Befunde; keine bestehenden Tests rot |
| **P2** | **Rhythmen (C3)** | monatlich/vierteljährlich/halbjährlich/jährlich, kalenderbasierte Perioden mit Zeitanteil, Überlappungsschutz gegen bestehende Sollstellungen, Vorschau (Dry-Run), Bestätigung für rückwirkende Erzeugung, nachvollziehbare Fehler bei unvollständigen Vertragsdaten | Tests: Summen identisch zu monatlicher Erzeugung, keine Doppelbuchung bei Rhythmuswechsel, Teilperioden centgenau |
| **P3** | **Stammdaten bearbeiten (C1)** | API für Zimmer/Betten (Umbenennen, Fläche, Deaktivieren mit Belegungsprüfung); Vorher/Nachher-Audit; Snapshot der Verteilung bei geprüfter Nebenkostenabrechnung; Hinweis auf Sollstellungen außerhalb geänderter Vertragszeiträume; UI-Bearbeitung für Partei, Objekt, WE, Zimmer, Bett, Vertragskonditionen (neue Version) | Änderung der Fläche ändert eine geprüfte Abrechnung nicht; Sollstellungen/Zahlungen unverändert |
| **P4** | **Betriebskosten-UI (C2)** | Seite Betriebskosten: Abrechnungen Ebene A erfassen, Positionen, Umlageschlüssel/Gewichte, Vorauszahlungen, Ergebnis, Verteilung inkl. nicht zuordenbarer Beträge, Vergleich Ebene B, Prüfung/Sperre; Vereinbarung je Untermietvertrag in der Vertragsansicht pflegbar | vollständiger Ablauf über die Oberfläche im E2E-Test |
| **P5** | **Mieter-Detailpanel (B4)** | Liste links, Detailpanel rechts (Drawer bei geringer Breite), ein aggregierter Endpunkt statt vieler Abfragen | Antwortzeit-Test, Komponententest, E2E |
| **P6** | **Dialoge/UX-Basis** | eigene Bestätigungs-/Eingabedialoge statt `window.prompt/confirm/alert`, Ladezustände, Fehlerzustände | keine Browser-Dialoge mehr im Code (Test) |
| **P7** | **Responsive/KPI (B1)** | KPI-Raster, nowrap für Beträge, Breakpoints; Prüfung bei 1536×1024, 1366×768, 1280×800, 1024×768 inkl. automatischer Überlauf-Prüfung | Screenshots + automatisierte Prüfung ohne Überlauf/Abschneiden |
| **P8** | **Sicherheit (Phase F)** | Sicherheitsheader inkl. CSP; verschlüsselte Backups (AES-GCM, Passphrase) optional; Backup-Restore-Drill mit Dokumenten und Neustart; `npm audit`/Abhängigkeitsprüfung; Berechtigungs-Matrixtest | Tests; Verschlüsselung nur dort behauptet, wo implementiert |
| **P9** | **Automatisierte E2E-Suite (Phase G)** | 18 Abläufe als wiederholbare Suite (startet eigenen Server mit temporärer Datenbank) | Suite grün, in `npm run e2e` |
| **P10** | **Windows/WebView2** | Build-/Testanleitung und Smoke-Test-Skript; `ALLOW_DOWNLOADS`; **praktische Prüfung nur auf Windows möglich** | Status ehrlich: „nicht getestet“, solange kein Windows-Lauf vorliegt |
| **P11** | **Abschlussbericht** | `docs/ABSCHLUSSBERICHT_MASTER_REVIEW.md` | alle Aussagen belegt, Statusstufen getrennt |

## Nicht Teil dieses Plans (bewusst)
Mieterportal; automatisierter Versand von Mahnungen/E-Mails; Open Banking/CAMT.053; PostgreSQL-Betrieb (weiterhin vorbereitet, nicht getestet).

## Fachliche Annahmen für die Umsetzung (zur späteren Korrektur)
1. Zahlungsperioden sind **kalenderbasiert** (Quartal ab Jan/Apr/Jul/Okt, Halbjahr ab Jan/Jul, Jahr ab Jan), Fälligkeit **vorschüssig** am Fälligkeitstag des ersten Monats der Periode; unterjährige Verträge zeitanteilig.
2. Dokumente: Aufbewahrung standardmäßig 10 Jahre (Annahme, nicht rechtlich geprüft); endgültige Löschung erst danach, nur Administrator.
3. Ein Vertrag gilt als „aktiv“ ab Beginn bis zum wirksamen Ende; „Kündigung“ ist ein Zusatzmerkmal eines weiterlaufenden Vertrags.
