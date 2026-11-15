# Abschlussbericht Phase C (Modellüberarbeitung + Stammdaten/Verträge)

Statuslegende wie in `ABSCHLUSSBERICHT_PHASE_A_B.md`. **Unabhängig geprüft: nichts. Freigegeben: nichts.**

## 1. Modellüberprüfung (vor der Implementierung)
Das Phase-A-Modell trug die neuen Anforderungen **nicht** (1 Einheit je Untermiete, je 1 Partei, 1 NK-Betrag im Vertrag). Es wurde überarbeitet: `docs/06-datenmodell-v2.md`. Annahmen/Rechtsfragen: `docs/07-annahmen-und-rechtsfragen.md`.

## 2. Implementiert
- **Raumhierarchie** Objekt → Wohneinheit → Zimmer → Bett und **Vermietungseinheit** (eine Ebene, DB-CHECK auf Konsistenz).
- **Parteien** (Person/Firma, Rollen, eigene Organisation), **Objekte**, **Wohneinheiten** (Belegung berechnet aus Untermietverträgen, auch über Zimmer/Betten).
- **Verträge** (Haupt/Unter) mit konfigurierbarer Vertragsart, mehreren Parteien (Mitmieter, Bewohner, Bürge), mehreren Mietgegenständen, versionierten Mietkonditionen und **getrennter, versionierter Nebenkostenvereinbarung** (Pauschale / Vorauszahlung / individuell / enthalten / keine).
- **Konsistenzprüfung beim Aktivieren:** räumlich-zeitliche Überschneidung (Fehler), Deckung durch Hauptmietvertrag inkl. Untervermietungserlaubnis (Fehler, Ausnahme nur mit Begründung + Audit), Überschneidung Hauptverträge (Warnung), fehlende Konditionen (Warnung), rechtliche Hinweise (nur Information).
- **Rechtliche Dokumentation** (Grundlage z. B. „§ 549 BGB“, Prüfstatus, Vermerke) – ausschließlich manuell, nie automatisch.
- **Eingehende Nebenkostenabrechnung (Ebene A):** Positionen, Vorauszahlungen, Nachzahlung/Guthaben, Abweichung zur Vermieter-Angabe, Verteilung auf Wohneinheiten, Sperre nach Prüfung; **Vergleich** mit Untermieter-Vereinbarungen ohne Erzeugung von Forderungen.
- API (siehe `03-api-module.md`), globale Suche, Mieterübersicht, Dashboard-Zähler (6 echte Kennzahlen).
- UI: Mieter, Eigentümer, Objekte (Baum + Vermietungseinheiten), Wohneinheiten, Verträge (Anlage als Entwurf, Prüfung/Aktivierung, Rechtsdokumentation), Suche, Eigene Organisation.

## 3. Datenbank
Migration `0002_master_data_leases_utility` (19 Tabellen, siehe v2-Doku). Modelle und Migration sind per Test synchron.

## 4. Tests (tatsächlich ausgeführt)
| Suite | Ergebnis |
|---|---|
| Backend `pytest` | **80 bestanden**, 0 fehlgeschlagen |
| Frontend `vitest` | 2 bestanden; Build erfolgreich |
| Manueller Browser-Durchlauf `frontend/e2e/phase-c.cjs` (Chromium, echter Server, frische DB) | alle Schritte OK: Organisation → Eigentümer → Objekt → WE/Zimmer/Bett → Vermietungseinheiten → Hauptvertrag aktiviert → Mieter → Untermiete Bett aktiviert → Zimmer-Konflikt blockiert → Suche |

Fachtests decken ab: ganze Wohnung; zwei Zimmer in einer Wohnung; bettenweise (zwei Betten, gleiches Bett, Zimmer vs. Betten); mehrere Untermietverträge je Wohneinheit (parallel an verschiedenen Räumen, nacheinander); Firma als Mieter mit Bewohnern; Hauptmietvertrag auf Objekt- und Wohneinheitsebene (Deckung, Lücken, Erlaubnis ungeklärt/verboten, Override); Beispiel 850/180 ↔ 1.150/220 getrennt; alle fünf NK-Modi; Eingangsabrechnung (Nachzahlung, Guthaben, fehlende Vorauszahlung, unterjährige Änderung, Pauschale ≠ Vorauszahlung, Sperre); Verteilung (Fläche, gleich, Gewichte, fehlende Daten, Cent-Summe exakt); Vergleich (Pauschale/Vorauszahlung/enthalten/individuell, Teilzeiträume, Zimmerebene, objektweite Untermiete); keine automatische rechtliche Einordnung; Rechte (lesende Rolle) und Audit.

## 5. Offene Fehler / Einschränkungen
- **Der Browser-Durchlauf ist ein manuelles Skript**, kein automatisierter CI-Test. Frontend hat nur 2 Komponententests.
- **Nebenkosten haben keine Oberfläche** (nur API, getestet). Ebenso: Bearbeiten/Deaktivieren von Stammdaten, Mietkonditionen/NK-Vereinbarungen nach Anlage ändern, Vertragsparteien nachträglich ändern (API für Terms/Agreements vorhanden, UI nicht).
- Zahlungen, Forderungen, Hauptmietverteilung, Wirtschaftlichkeit und Gesamt-Deckungsbeitrag: **Phase D**, nicht implementiert. Der Zahlungsstatus der Mieter ist daher `null`.
- Keine Kapazitätsprüfung für Zimmer/Betten; NK-Verteilung nur bis Wohneinheit; tagesbasierte Mieten nicht umgerechnet; keine optimistische Sperre bei gleichzeitiger Bearbeitung.
- Heuristik „Leventum“ = erste aktive eigene Organisation (mehrere Gesellschaften nicht sauber unterstützt).
- Auslaufende Verträge werden nicht automatisch auf „beendet“ gesetzt (`close_expired` existiert, ist aber nirgends ausgelöst).
- Nicht getestet: PostgreSQL, Windows, Last.
- Rechtliche Fragen sind **offen und ungeprüft** (`07-annahmen-und-rechtsfragen.md`).

## 6. Nächster Schritt
Phase D auf Basis v2: Sollstellungen (Forderung/Verbindlichkeit), Zahlungen mit Zuordnung/Storno, Hauptmiete-Verteilung, Wirtschaftlichkeit inkl. NK-Betrachtung, Rechnungen/Belege, UI für Nebenkosten. Vorher entscheiden: Kaution, Mahnwesen, Bankimport, Leerstandsdefinition.
