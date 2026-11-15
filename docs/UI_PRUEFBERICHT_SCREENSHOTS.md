# UI-Prüfbericht mit Screenshots

Vorgehen: Eine frische Instanz wurde mit realistischen **Demodaten** befüllt (2 Objekte, 5 Wohneinheiten, WG-Wohnung mit Zimmern und Betten, 2 Hauptmiet- und 7 Untermietverträge, Sollstellungen Januar–November, Zahlungen, Rückstände, Kautionen, Rechnung, Reparatur, Aufgaben, Kommunikation, Bankimport, Dokumente). Von allen Bereichen wurden Screenshots erzeugt (`frontend/e2e/seed-and-shoot.cjs`, Ergebnis in `docs/screenshots/`), kritisch mit der Referenz verglichen und Mängel behoben. **Die Demodaten sind frei erfunden und nur für diese Prüfung gedacht.**

## Gefundene Mängel und Korrekturen
| # | Befund (nur im Bild sichtbar) | Korrektur | Absicherung |
|---|---|---|---|
| 1 | Doppelte Bezeichnungen „WE WE 03 · Zimmer Zimmer 1 · Bett Bett A“ | Präfix nur setzen, wenn die Bezeichnung es nicht schon enthält (Backend, Auswertungen, Oberfläche) | Backend-Tests |
| 2 | Dashboard lud über 1 s: Die aufwendige Monatsauswertung lief je Kennzahl neu (5×) | einmal je Aufruf berechnet | Test „nur einmal“ |
| 3 | Dashboard-Karte „Wirtschaftlicher Überblick“ mit Platzhaltertext „Wird in Phase D berechnet“ | zeigt echte Zahlen des laufenden Monats (Soll, Ist, Rückstand, Leerstand) | Frontend-Test |
| 4 | Mieterliste: Spalte „Zahlungsstatus“ zeigte „ab Phase D“ | echter Status „Ausgeglichen“ / „Rückstand 1.570,00 €“, Filter „Zahlungsrückstand“ | Backend-Tests |
| 5 | Verträge nur als „#4“ (Sollstellungen, Mahnwesen, Bankvorschläge, Aufgaben, Hinweise) | sprechende Bezeichnung „Sandra Klein · Haus Bergmann · WE 02“ | Backend-Tests |
| 6 | Auswahllisten und Dateifelder wie unformatierte Browser-Standardfelder | einheitlich im Designsystem gestaltet | Sichtprüfung |
| 7 | Geldbeträge in Dashboard-Kacheln brachen um („5.670,0 / 0 €“), lange Wörter wurden zerrissen | kleinere Schrift, kein Umbruch, Silbentrennung | Sichtprüfung |
| 8 | Reparaturverlauf mit englischen Statuscodes („reported → scheduled“) und Punktzahlen („476.00 €“) | deutsche Bezeichnungen und Zahlenformat (auch im Protokoll) | Backend-Tests |
| 9 | Aufgabenliste: Status doppelt (Abzeichen + Auswahlfeld), Bezüge kryptisch („Vertrag #3 Reparatur #1 Partei #4“) | nur Auswahlfeld; Bezüge mit Namen | Frontend-/Browsertest |
| 10 | Hauptmietkaution zeigte als Gegenpartei Leventum statt des Vermieters | Vermieter wird angezeigt | Sichtprüfung |
| 11 | Wirtschaftlichkeit/Leerstand: Filterfelder unausgewogen; ISO-Datum „2026-11-15“ | Raster; deutsches Datum | Sichtprüfung |
| 12 | Sollstellungsliste ohne Monatsfilter (alle Monate untereinander) | Monatsfilter, Standard laufender Monat | Browsertest |

## Bildübersicht (`docs/screenshots/`)
`00-einrichtung` · `01-dashboard` · `02-mieter` · `03-eigentuemer` · `04-objekte` · `05-objekt-detail` · `06-wohneinheiten` · `07-vertraege` · `08-vertrag-detail` · `09-sollstellungen-zahlungen` · `10-kautionen` · `11-mahnwesen` · `12-bankimport` · `13-rechnungen` · `14-wirtschaftlichkeit` · `15-leerstand` · `16-aufgaben` · `17-reparaturen` · `18-reparatur-detail` · `19-kommunikation` · `20-dokumente` · `21-einstellungen` · `22-mieterakte`

## Abgleich mit der Referenz
Übereinstimmend: linke feste Seitenleiste mit Logo, Aktiv-Markierung, Topbar mit Suche/Benachrichtigung/Benutzer, weißer Hauptbereich, dunkelblaue Schrift, blaue Akzente, Kartenraster, feine Rahmen, Status-Abzeichen (grün/orange/rot).
**Abweichungen:** Die Referenz zeigt ein Mieter-Detailpanel rechts neben der Liste und eine Fotovorschau des Objekts – beides ist nicht umgesetzt (Detailansicht öffnet als eigene Seite, keine Objektfotos). Die Navigation ist gegenüber der Referenz um die 16 Bereiche mit Untermenüs erweitert. Farbwerte sind geschätzt und nicht pixelgenau abgeglichen.

## Nicht geprüft
Nur Chromium in 1536 × 1024 px. Keine Prüfung auf Windows/WebView2, kleinen Bildschirmen, Dunkelmodus, Barrierefreiheit (Kontrast, Tastaturbedienung) oder Druck.
