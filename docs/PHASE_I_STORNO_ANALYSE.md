# Phase I – Analyse der Stornierungs-/Gegenbuchungslogik (Befund F1)

Status: **Analyse, nicht implementiert.** Keine Logikänderung, keine Tests geändert, keine Klemmung offener Forderungen (Vorgabe). Grundlage für eine spätere Eigentümerentscheidung. Keine rechtliche/steuerliche Bewertung. Alle Optionen sind Optionen mit Pro/Contra, keine Entscheidungen. Nicht unabhängig geprüft (Autor: Domain & Finance Engineer; Review steht aus).
Stand der Messung: Code im Arbeitsverzeichnis, Skriptlauf am 2026-11-16 (Systemdatum, `date.today()`). Belegskript (nur Scratchpad, nicht im Repo): `/tmp/claude-0/-home-user/8a1483e5-401e-5ab8-b82a-ee2ec461b96c/scratchpad/domain_storno/run.py`.

## 1. Datenmodell und Ist-Verhalten

### 1.1 Modell (`models/finance.py`)
* `Payment`: `amount > 0` (CHECK), `booking_date` (frei, Index), `is_reversal`, `reverses_payment_id` (UNIQUE → je Zahlung höchstens eine Gegenbuchung). Keine Prüfung `booking_date` gegen heute oder gegen ein anderes Datum (weder DB noch Service noch Schema).
* `PaymentAllocation`: vorzeichenbehaftet (`amount <> 0`), append-only; kein eigenes Datum, **wirkt immer mit dem `booking_date` der zugehörigen Zahlung** (Join in `allocated`/`receivable_position`).
* `signed(p)` = −amount bei Gegenbuchung.

### 1.2 `reverse_payment` (`services/payments.py:140`)
* Sperren: Storno einer Stornobuchung (`invalid_state`), zweiter Storno (`already_reversed`), fehlende Begründung.
* `booking_date` der Gegenbuchung = übergebener Wert, sonst `date.today()` (Zeile 149). **Keine Validierung**: weder ≥ Originaldatum noch ≤ heute.
* Zuordnungen: je (Sollstellung|Rechnung) Summe aller Zuordnungen des Originals (inkl. früherer Rücknahmen) → eine negative Zuordnung gleicher Höhe an der Gegenbuchung. Das Original bleibt unverändert.
* Gegenbuchung ist nicht zuordenbar (`allocate` sperrt `is_reversal` und bereits stornierte Originale).

### 1.3 `deallocate` (Zeile 120)
* Negative Zuordnung **an der Originalzahlung**; Begründung Pflicht; Zahlung wird nicht storniert, bleibt als „nicht zugeordnet“ bestehen (Umbuchung auf andere Sollstellung danach möglich). Die negative Zuordnung erbt das **alte** `booking_date` der Zahlung (kein eigenes Datum) → wirkt auch für zurückliegende Stichtage (ADR 0002 A6a, bekannt, nicht behoben).

### 1.4 Wege zu `booking_date` der Gegenbuchung (geprüft)
| Weg | Datum der Gegenbuchung |
|---|---|
| UI `Finance.tsx` „Stornieren“ | sendet nur `reason` → **heute** (Standard) |
| API `POST /payments/{id}/reverse` (`ReverseIn`: `reason`, `booking_date: date \| None`) | **frei wählbar**, ohne Validierung; Beleg: Datum vor Original, 2031 und 1900 → jeweils 200 |
| Bank `reopen` (`bank.py:273`) | `reverse_payment(..., reason=…)` → **heute** |
| `POST /payments` (`PaymentIn.booking_date: date`) | **frei**, auch Zukunft (Beleg: 2031-01-01 → 201) |

Konsequenz: Die Gegenbuchung liegt per Standard **heute**. Damit liegt sie vor dem Originaldatum, sobald die Originalzahlung ein **Zukunfts-Buchungsdatum** hat (Szenario 3). Außerdem per API mit explizitem Datum.

### 1.5 Wirkung je Stichtag S (`charges.allocated/open_amount`, `receivable_position`)
Mit Originalzahlung P (Buchungsdatum d_P, Betrag B) und Gegenbuchung R (d_R):
allocated(S) = B·[S ≥ d_P] − B·[S ≥ d_R]; offen(S) = Forderung − allocated(S).
Ist d_R < d_P, gilt für d_R ≤ S < d_P: allocated = −B, offen = Forderung + B (= **2 × B** bei Volldeckung). `receivable_position` summiert nur `rest > 0`, begrenzt also nach unten (A7), aber **nicht nach oben**.
Ohne Stichtag (`open_amount(db, c)`, Forderungsliste, Mahnwesen, Bankimport, `arrears`) werden alle Zuordnungen summiert: Nach Original + Storno immer Endstand = Forderungsbetrag, unabhängig von den Daten.
Auch `allocate` prüft `amount > charge_open(db, c)` ohne Stichtag.

## 2. Szenariotabelle (Handrechnung = Skriptbeleg, identisch)
Forderung 600,00 fällig 2026-09-01, Stichtage in Spalte „Stichtag“. Werte = `receivable_position.open_total` (= `open_amount(as_of)`, da eine Forderung je Szenario). „Ohne Stichtag“ = `open_amount` ohne `as_of`.

| # | Szenario | Stichtag → offen (Handrechnung = Skript) | Ohne Stichtag |
|---|---|---|---|
| S1 | Original vor Gegenbuchung: Zahlung 600 am 10-10, Storno 10-20 | 10-09: 600 · 10-10: 0 · 10-19: 0 · 10-20: 600 · heute: 600 | 600 |
| S2 (F1) | Gegenbuchung vor Original: Zahlung 10-20, Storno 10-10 (nur per API) | 10-09: 600 · **10-10: 1200** · **10-19: 1200** · 10-20: 600 · heute: 600 | 600 |
| S3 | Zukunftszahlung: Buchungsdatum 12-16 (heute + 30), zugeordnet; Storno **ohne** Datum (= heute 11-16) | vor Storno: ohne Stichtag **0**, heute **600**, am Zahltag 0 · nach Storno: 11-15: 600 · **11-16 (heute): 1200** · **12-15: 1200** · 12-16: 600 | 600 |
| S3b | wie S3, Storno mit Datum = Originaldatum (nur Beleg der Variante) | heute: 600 · 12-15: 600 · 12-16: 600 | 600 |
| S4 | Mehrere Gegenbuchungen: A 600 (10-10) storno 10-20; B 600 (10-25) storno 11-02. 2. Storno auf A → `already_reversed` 409; Storno des Storno → `invalid_state` 409 | 10-09: 600 · 10-10: 0 · 10-20: 600 · 10-25: 0 · 11-01: 0 · 11-02: 600 | 600 |
| S4b | Zwei Stornos je vor ihrem Original: A (10-20) storno 10-05; B (10-30) storno 10-12 | 10-04: 600 · 10-05: 1200 · **10-12: 1800** · 10-20: 1200 · 10-30: 600 | 600 |
| S5 | Teilzahlungen 400 (10-10) + 200 (10-15); Storno der 400 am 10-20; Storno der 200 am 10-12 (vor Original) | 10-09: 600 · 10-10: 200 · 10-12: 400 · 10-15: 200 · 10-20: 600 | 600 |
| S6 | Rücknahme statt Storno: Zahlung 600 (10-10) zugeordnet, heute `deallocate` 600 | vor Rücknahme: 10-12 → 0 · nach Rücknahme: 10-09: 600 · **10-10: 600 · 10-12: 600** · heute: 600; Zahlung bleibt, `unallocated` 600, Umbuchung auf andere Forderung möglich | 600 |
| S7 | Teil-Rücknahme 200, danach Storno 10-20 | 10-09: 600 · 10-10: 200 · 10-20: 600; Storno bucht −400 (nur den Restbestand) | 600 |

Handrechnung Beispiel S2: Zuordnung +600 wirkt ab 10-20, −600 ab 10-10. Am 10-15: allocated = −600 → offen 600 − (−600) = 1200. Am 10-20: +600 −600 = 0 → offen 600. S4b am 10-12: A −600 (ab 10-05), B −600 (ab 10-12), beide Originale noch nicht wirksam → allocated −1200 → offen 1800. S5 am 10-12: +400 −200 (Storno der 200er vor ihrem Original) = 200 → offen 400 (real wurden 400 gezahlt: Zuordnung am Stichtag um 200 zu niedrig; kein „offen > Forderung“, aber ebenfalls verzerrt).

Ausgeführt: Skript oben gegen den Code, Ausgabe in Abschnitt 2 übernommen. Nicht ausgeführt: automatisierte Suite (nicht Teil dieser Aufgabe); vorhandener Test `test_f1_reversal_booked_before_original_payment_never_exceeds_charge` (xfail strict) bleibt unberührt.

## 3. Fachliche Bewertung je Szenario
Bewertungsmaßstab: Ist-Sicht (Zahlung zählt ab Buchungsdatum, Storno ab eigenem Buchungsdatum; ADR 0002 A5) und Invariante 8 (Datenstand).

| # | Plausibel? | Eingebaute Annahmen |
|---|---|---|
| S1 | Ja. Zahlung war zwischen 10-10 und 10-19 eingegangen, am 10-20 zurückgebucht (z. B. Rücklastschrift). Historie korrekt. | Gegenbuchung bildet realen Rückfluss am Rückbuchungstag ab. |
| S2 | **Nein** für Stichtage 10-10…10-19 (offen 1200 > Forderung 600, weil eine Rückbuchung ohne vorherigen Eingang gezählt wird). Endstand korrekt. | Annahme: Storno-Datum ≥ Original-Datum; wird nirgends erzwungen. |
| S3 | **Nein** im Gegenwartswert: Ein heute ausgeführtes Storno einer Zukunftszahlung erzeugt für heute (Dashboard `open_receivables`) 1200. Praktisch der wahrscheinlichste Weg zu F1, da ohne ein bewusst gewähltes Datum (UI-Standard). Vor dem Storno zeigen Forderungsliste/Mahnwesen 0 (Zahlung zählt sofort, A8), Dashboard 600 – Seiten weichen schon vorher ab. | Annahme: Zukunftsdaten bei Zahlungen sind legitim (nicht validiert); Storno „heute“ ist für Zukunftszahlung sinnvoll (sie wurde nie ausgeführt). Fachlich ist unklar, ob eine Zukunftszahlung überhaupt „Ist“ sein darf. |
| S3b | Ja (rechnerisch), aber die Zahlung gilt zu keinem Zeitpunkt als geleistet; die Gegenbuchung trägt ein Datum in der Zukunft. | Gegenbuchung und Original am selben Tag heben sich auf. |
| S4 | Ja. Zweite Zahlung nach Storno möglich (Forderung wieder offen), Mehrfach-Storno desselben Originals technisch blockiert. | Annahme: höchstens eine Gegenbuchung je Original (UNIQUE). |
| S4b | **Nein**: 1800 = 3 × Forderung. Mehrere F1-Effekte addieren sich. Kein Datenfehler, nur Stichtagsansicht. | wie S2. |
| S5 | Teilweise: Werte bleiben ≤ Forderung, aber die Stichtagszahlung ist verzerrt (400 statt 200 offen bei Zahlung 400 und noch nicht gezahlten 200). | wie S2. |
| S6 | Zwei Lesarten. Für Umbuchung/Fehlzuordnung gewollt (Zahlung war bar da, Zuordnung falsch). Aber: historische Stichtage ändern sich (ADR 0002 A6a); 10-12 zeigt nach Rücknahme 600 offen statt 0, obwohl die Zahlung am 10-10 existierte. | Annahme: Rücknahme korrigiert den Zuordnungsirrtum rückwirkend (anders als Storno, das Ist-Fluss abbildet). Mit Invariante 5 vereinbar (append-only), mit Invariante 6/„keine stille Rückwirkung“ nur eingeschränkt, da die Wirkung auf Stichtagsberechnungen rückwirkend ist. |
| S7 | Ja; Storno rechnet auf den Restbestand der Zuordnung (−400), Endstand 600. | Summe der Zuordnungen (inkl. Rücknahmen) je Ziel. |

Querbefund: Mit der aktuellen Semantik ist jede Datenkonstellation im **Endstand** (ohne Stichtag) richtig (600). Fehlerbild betrifft nur **Stichtagsansichten zwischen d_R und d_P**.

## 4. Lösungsvarianten (nicht umgesetzt, nicht empfohlen im Sinne einer Entscheidung)
Ausgeschlossen durch Vorgabe: Klemmung von offen auf den Forderungsbetrag.

### V1 – Storno-Datum ≥ Originaldatum verlangen (Validierung in `reverse_payment`)
* Pro: Verhindert S2/S4b/S5-Verzerrung künftig an der Quelle; keine Änderung der Leselogik; Invarianten 5/6 unberührt (keine Änderung bestehender Daten).
* Contra: S3 (UI-Standard „heute“ < Originaldatum) würde dann ablehnen oder ein Standard-Datum (z. B. max(heute, Originaldatum)) nötig machen; Bestandsdaten bleiben unverändert (keine Korrektur historischer Stichtagswerte); Änderung von Standardverhalten und API-Vertrag (neuer Fehlercode); Gegenbuchung mit Zukunftsdatum.
* Testbedarf: Service- und API-Test (Ablehnung/Annahme am Gleichtag, nach Original), Bank-`reopen` mit Zukunftsdatum, Altdaten-Test mit vorhandenen F1-Konstellationen (Lesen), xfail aus F1 anpassen, UI-/E2E-Fall.
* Risiko: Blockiert legitime Rückbuchung, falls Bank das Rückbuchungsdatum vor dem Originaldatum meldet (Wertstellung vs. Buchung, nicht geprüft).

### V2 – Gegenbuchung wirkt rechnerisch immer ab Originaldatum (Leselogik: Wirkdatum = max(eigenes Datum, Originaldatum))
* Pro: Kein F1 mehr, auch für Bestandsdaten; keine neue Eingabepflicht.
* Contra: Ändert ADR 0002 A5 („Stornobuchungen wirken ab eigenem Buchungsdatum“); Join in `allocated`/`receivable_position`/Wirtschaftlichkeit komplexer (Abfrage über `reverses_payment_id`); S1 würde sich nicht ändern, aber das *Gegenbuchungsdatum* hätte in der Stichtagsrechnung keine Wirkung mehr für Rückbuchungen nach Originaldatum, falls als „max“ definiert (dann identisch zu heute für S1; Unterschied nur im F1-Fall). Variante „Wirkdatum = Originaldatum“ (Storno löscht die Zahlung historisch) wäre eine **stille Rückwirkung** (Invariante 6 / A6a-Prinzip) und würde S1 ändern → nicht kompatibel mit Ist-Sicht; hier nur als zu verwerfende Unter-Option genannt.
* Testbedarf: Tests für alle Stichtagsfunktionen (Dashboard, Wirtschaftlichkeit, Bank), Konsistenz zwischen Seiten, Regressionstest ADR 0002, Beweis, dass bestehende Zahlungen/Zuordnungen unverändert bleiben.
* Risiko: Zentrale Finanzlogik; Pflichtreview Domain & Finance + QA + Orchestrator; mehrere Lesepfade müssen identisch bleiben (Doppeldefinition vermeiden).

### V3 – Nur Anzeige-Warnung/Integritätshinweis, keine Logikänderung
* Pro: Kein Risiko für Berechnungen; „Hinweis statt Änderung“ entspricht dem Muster von Invariante 6; schnell umsetzbar (z. B. Regel in `services/integrity.py`: Gegenbuchung mit `booking_date` < Originaldatum; Hinweis am Dashboard-Stichtag).
* Contra: Zahlenwerte bleiben fachlich irritierend (1200, 1800); nur sichtbar, nicht behoben; Hinweislogik muss Stichtagsfenster kennen.
* Testbedarf: Integritätstest (Erkennung S2/S3/S4b), Anzeige-Test, kein Einfluss auf Summen (Regressionsbeweis).

### V4 – Standarddatum anpassen (Default = max(heute, Originaldatum)), explizite Datumsangabe weiterhin frei
* Pro: Entschärft S3 ohne neue Fehlerfälle; UI/Bank-`reopen` profitieren automatisch.
* Contra: Explizites API-Datum bleibt riskant (S2); Gegenbuchung mit Zukunftsdatum bei Zukunftszahlung; Änderung des Standardverhaltens auch ohne Eigentümerwissen.
* Testbedarf: Default-Test (Vergangenheits- und Zukunftsoriginal), API mit/ohne Datum.

### V5 – Zukunfts-Buchungsdatum bei Zahlungen verbieten (Eingabevalidierung `create_payment`, ggf. mit Toleranz)
* Pro: Entfernt den praktisch wahrscheinlichsten Auslöser (S3) und die Abweichung Forderungsliste (zählt sofort) vs. Dashboard (zählt ab Datum) bei Zukunftszahlungen.
* Contra: Verbietet ggf. gewollte Vorab-Erfassung (z. B. terminierter Dauerauftrag); Bankimport/Duplikatlogik betroffen; löst Fall „Storno-Datum vor Original per API“ nicht. Eigene Fachentscheidung, möglicherweise Geldwirkung.
* Testbedarf: Service/API/Bankimport, vorhandene Zukunftszahlungen (Altdaten) nur lesend.

### V6 – Status quo dokumentieren
* Pro: Keine Änderung. Endstände korrekt.
* Contra: Stichtagswerte > Forderung sind per API/Zukunftszahlung erreichbar; Dashboard „heute“ kann 1200 statt 600 zeigen (S3).

Kombinationen sind möglich (z. B. V3 + V4). Zu allen Varianten gilt: Keine bestehenden `Payment`/`PaymentAllocation`-Zeilen ändern (Invariante 5), keine Klemmung (Vorgabe), Autor ≠ Prüfer, Entscheidungsdokument `docs/decisions/NNNN-…` vor Umsetzung (60-collaboration).

Zu Rücknahme (S6): Eine Änderung an `deallocate` (z. B. eigenes Wirkdatum der Rücknahme) würde die bekannte Einschränkung A6a beheben; das erfordert vermutlich ein neues Feld/Migration (Datenmodelländerung) oder eine Datumsregel ohne Schemaänderung (z. B. Rücknahme nur am Zahlungstag zulassen). Nicht bewertet.

## 5. Offene Entscheidungen für den Eigentümer
1. Soll eine Gegenbuchung (Storno) fachlich nie vor dem Buchungsdatum der Originalzahlung liegen dürfen (V1), oder ist ein früheres Datum in Ausnahmefällen gewollt (z. B. Rückbuchung mit Wertstellung vor Originaldatum)?
2. Sollen Zahlungen mit Buchungsdatum in der Zukunft erlaubt bleiben (V5)? Wenn ja: Zählt eine Zukunftszahlung als „Ist“ (heutiger Gegenwartswert: Forderungsliste ja, Dashboard nein, ADR 0002 A8)?
3. Welches Standard-Buchungsdatum soll ein Storno ohne Datumsangabe haben: heute (Ist), das Originaldatum, oder das spätere von beiden (V4)?
4. Soll im Fall „Storno-Datum < Originaldatum“ (nur noch Bestandsdaten oder weiterhin zulässig) das Stichtagsverhalten unverändert bleiben und nur eine Warnung erscheinen (V3), oder soll die Leselogik angepasst werden (V2)? Wenn V2: Welches Wirkdatum gilt für Stornobuchungen (max(eigenes Datum, Originaldatum) vs. Originaldatum)?
5. Wie sollen Altdaten behandelt werden, falls es sie gibt (Bestandsdaten sind in diesem Auftrag nicht ausgewertet)? Nur lesende Prüfung/Hinweis, keine Änderung?
6. Soll eine „Rücknahme der Zuordnung“ (S6) rückwirkend auf zurückliegende Stichtage wirken (heute: ja, A6a) oder ab dem Tag der Rücknahme?
7. Soll es einen Unterschied in der Oberfläche zwischen „Zahlung stornieren“ (Rückfluss) und „Zuordnung zurücknehmen“ (Fehlzuordnung) geben, und welcher Weg ist für welchen Fall vorgesehen?
8. Soll das Dashboard weiterhin Werte > Forderungsbetrag anzeigen dürfen (Bestätigung der Vorgabe „keine Klemmung“), und falls ja: reicht eine sichtbare Kennzeichnung?
9. Sollen Forderungsliste/Mahnwesen/Bankimport (ohne Stichtag) und Dashboard (mit Stichtag) vereinheitlicht werden (ADR 0002 A8)? Das beeinflusst alle obigen Szenarien.
10. Gilt die Annahme „höchstens eine Gegenbuchung je Originalzahlung“ (UNIQUE) weiterhin, auch wenn eine Gegenbuchung falsch war (Korrektur einer Gegenbuchung bisher nicht möglich)?

## 6. Statusstufen
* Dieses Dokument und alle Befunde: **Analyse, nicht implementiert.** Skriptbeleg: gegen aktuellen Code ausgeführt (Scratchpad, nicht im Repository). Keine Tests hinzugefügt oder geändert, keine Suite ausgeführt.
* Nicht unabhängig geprüft; nicht von einem Menschen freigegeben. Keine Windows-Aussage.
* Nicht geprüft: tatsächliche Bestandsdaten, Bankformate mit Zukunftsdaten (`bank.confirm_payment` übernimmt `t.booking_date` ungeprüft aus dem Import, siehe `bank.py:229`), Wirtschaftlichkeit (`economics.py`) bei F1-Konstellationen, Dunning bei Stichtagsfragen (nutzt `open_amount` ohne Stichtag, daher vom Datum der Gegenbuchung unabhängig).
