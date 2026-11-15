# 05 – Entwicklungsreihenfolge und offene fachliche Entscheidungen

## Entwicklungsreihenfolge

| Phase | Inhalt | Abnahmekriterium (überprüfbar) |
|---|---|---|
| A | Analyse, Konzept (diese Dokumente) | Dokumente vorhanden, Annahmen und offene Fragen benannt |
| **B** | Backend-Gerüst, DB+Alembic, Auth/Sessions, Audit, FileStore, Backup, Dashboard-Struktur, UI-Shell, Desktop-Starter | pytest grün; Migration läuft auf leerer DB; Frontend baut; Screenshot-Vergleich mit Referenz |
| C | Parteien, Objekte, Einheiten, Haupt-/Untermietverträge, Konsistenzregeln, Mieterliste/-akte, globale Suche | Tests für Überschneidung, Deckung, Mehr-Einheiten-Objekt |
| D | Sollstellungen, Zahlungen, Zuordnung, Storno, Wirtschaftlichkeit, Betriebskosten (2 Ebenen), Rechnungen | Rechentests mit Beispielen (850/180 → 1150/220), Teilzahlung, Rückstand, Leerstand |
| E | Aufgaben, Reparaturen, Dokumente, Kommunikation, Historie, Erinnerungen, Dashboard vollständig | Upload-/Download-Tests, Verknüpfungstests |
| F | E2E-Tests, Sicherheitsprüfung, PostgreSQL-Lauf, Backup/Restore-Test, Windows-Build/Installer | Läuft auf Windows (nur dort prüfbar) |

## Offene fachliche Entscheidungen (blockieren die genannten Phasen **nicht**, dürfen aber nicht stillschweigend angenommen werden)

| # | Frage | Betrifft | Vorläufiges Vorgehen |
|---|---|---|---|
| 1 | Wird **zimmer-/bettenweise** untervermietet (WG-Modell)? Dann reicht „1 Untermiete = 1 Einheit“ nicht. | Datenmodell C | Annahme *nicht* getroffen; Entscheidung vor Phase C nötig |
| 2 | Untermiete: Nebenkosten als **Vorauszahlung mit Abrechnung** oder als **Pauschale/Inklusivmiete** (oder möblierte Warmmiete)? | Betriebskosten D | Beides modellierbar vorgesehen (`other_charges`/Pauschale-Flag); Klärung vor D |
| 3 | Rechtliche Besonderheiten der **gewerblichen Zwischenvermietung** (z. B. Eintritt des Eigentümers bei Ende des Hauptmietvertrags, Zulässigkeit der Vertragsgestaltung) | Vertragsüberwachung | Software gibt **keine** Rechtsauskunft; Hinweis auf Rechtsberatung |
| 4 | **Umsatzsteuer** / steuerlicher Status (Wohnraum, Gewerbe, Option), Buchführungsart; DATEV-Export gewünscht? | Finanzen D | Beträge zunächst brutto/ohne USt-Logik; Entscheidung vor D |
| 5 | **Kautionen** beidseitig (Hinterlegung, getrennte Anlage, Verzinsung) | Verträge/Finanzen | Nur Erfassung des Betrags/Status, keine Verzinsungslogik |
| 6 | **Mietanpassungen** (Staffel/Index) | `lease_term` | Manuell als neue Konditionszeile |
| 7 | **Teil-Monate**: Berechnung tagesgenau (Ist-Tage/Monatstage) oder 30-Tage-Konvention? Definition Leerstandstag | Soll-Erzeugung, Leerstand | Konfigurierbar; Standard-Vorschlag: tagesgenau |
| 8 | Standard-Verteilung der **Hauptmiete** auf Einheiten (Fläche/gleichmäßig) | Wirtschaftlichkeit | Konfigurierbar je Vertrag, Standard Fläche |
| 9 | **Bankimport** (CSV/CAMT/MT940) für Zahlungseingänge gewünscht? | Zahlungen D | Zunächst manuell; Import als Erweiterung |
| 10 | **Mahnwesen**: Stufen, Fristen, Gebühren | Erinnerungen E | Nur Vorbereitung von Entwürfen, kein Versand |
| 11 | **Heizkosten**/Messdienstleister: Eingabe fertiger Aufteilung oder Berechnung nach HeizkostenV? | Betriebskosten D | Erst Übernahme extern berechneter Werte |
| 12 | **Aufbewahrung/Löschung** (GoBD, DSGVO) | Dokumente/Daten | Kein automatisches Löschen |
| 13 | Backup-Ziel (externes Laufwerk/NAS), **Verschlüsselung** der Backups | Backup | Standardziel lokal; empfohlen BitLocker + externes Ziel |
| 14 | Mehrere **Gesellschaften** (Leventum GmbH u. a.)? | `party.is_own_organization` | Modell erlaubt mehrere |
| 15 | Zeitpunkt Mehrbenutzer/Server (Hosting, Betrieb) | Architektur | PostgreSQL-Umstellung vorher zwingend |
| 16 | **Logo** (Vektor) und Schriftart | UI | Platzhalter-Logo, Systemschrift |
