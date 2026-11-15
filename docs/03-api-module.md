# 03 – API-Module (REST, Präfix `/api/v1`)

Alle Endpunkte außer `GET /health` und den Setup-/Login-Endpunkten verlangen eine gültige Sitzung und das passende Recht.

| Modul | Phase | Wichtige Ressourcen | Status |
|---|---|---|---|
| `health` | B | `GET /health` (ohne Auth, ohne Daten) | **implementiert** |
| `auth` | B | `GET /auth/status`, `POST /auth/setup` (nur solange kein Benutzer existiert), `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | **implementiert** |
| `dashboard` | B (Struktur) / C–E (Inhalte) | `GET /dashboard` – nur real berechnete Werte; nicht verfügbare Kennzahlen werden als `available: false` markiert | **implementiert** (Struktur) |
| `system/backup` | B | `GET /system/backups`, `POST /system/backups`, `POST /system/backups/{id}/verify`, `POST /system/backups/{id}/restore` | **implementiert** (siehe Bericht für Testumfang) |
| `parties` (Eigentümer, Vermieter, Mieter, Dienstleister) | C | CRUD, Rollen, Mieterakte-Aggregat | geplant |
| `properties`, `units` | C | CRUD, Belegungsstatus (berechnet) | geplant |
| `leases` (main/sub), `lease-terms` | C | CRUD, Validierung, Überschneidungs-/Deckungsprüfung | geplant |
| `charges`, `payments`, `allocations` | D | Sollstellung erzeugen, Zahlung buchen, Zuordnung, Storno | geplant |
| `finance/economics` | D | Wirtschaftlichkeit je Objekt/Einheit/Zeitraum | geplant |
| `utility-costs` (`cost-types`, `settlements`) | D | Betriebskostenabrechnung beider Ebenen | geplant |
| `invoices` | D | Erfassen, Upload, Zuordnung, Bestätigung von Vorschlägen | geplant |
| `tasks`, `repairs` | E | CRUD, Filter | geplant |
| `documents` | E | Upload (Typ-/Größenprüfung), Download nur authentifiziert | geplant |
| `communications`, `reminders`, `history` | E | Vorgangshistorie | geplant |
| `search` | C–E | `GET /search?q=` über alle Entitäten → Deep-Link | geplant |
| `reports` | E/F | Auswertungen/Export | geplant |
| `users`, `roles` | später | Benutzerverwaltung (Modell bereits vorhanden) | geplant |

Konventionen: JSON, ISO-8601, Geld als String-Dezimal (`"1150.00"`), Fehler als `{ "detail": ..., "code": ... }`, Paginierung `limit/offset`, Optimistic Locking per `version`-Feld auf Finanz- und Vertragsdaten (Phase C/D).


## Ergänzung Phase C (implementiert und getestet)
| Ressource | Endpunkte |
|---|---|
| Parteien | `GET/POST /parties`, `GET/PATCH /parties/{id}` (Filter `role`, `q`, `active`) |
| Objekte & Raumhierarchie | `GET/POST /properties`, `GET/PATCH /properties/{id}` (Baum Objekt→WE→Zimmer→Bett), `POST /properties/{id}/units`, `GET /units`, `PATCH /units/{id}`, `POST /units/{id}/rooms`, `POST /rooms/{id}/beds` |
| Vermietungseinheiten | `GET/POST /rentable-units` (Ebene Objekt/Wohneinheit/Zimmer/Bett, idempotent) |
| Verträge | `GET/POST /leases`, `GET/PATCH /leases/{id}`, `GET /leases/{id}/validation`, `POST …/terms`, `…/utility-agreements`, `…/notes`, `…/legal-review`, `…/activate`, `…/terminate`, `…/cancel`; `GET /lease-types` |
| Mieterübersicht | `GET /tenants` (Zahlungsstatus bis Phase D immer `null`) |
| Nebenkosten (Ebene A + Vergleich) | `GET/POST /utility-statements`, `GET /utility-statements/{id}` (inkl. berechnetem Ergebnis), `POST …/lines`, `PUT …/prepayments`, `POST …/status`, `GET …/allocation`, `GET …/comparison`; `GET /cost-types` |
| Suche | `GET /search?q=` (Parteien, Objekte, Wohneinheiten, Verträge) |

Geldbeträge und Flächen sind JSON-Strings mit 2 Nachkommastellen. Validierungsfehler beim Aktivieren: HTTP 422 mit `detail.details.{errors,warnings,hints}`. Rechte: `master:read/write` (Stammdaten/Verträge), `finance:read/write` (Nebenkosten).


## Ergänzung Phase D (implementiert und getestet)
| Ressource | Endpunkte |
|---|---|
| Sollstellungen | `GET /charges`, `POST /charges/generate` (idempotent), `POST /charges` (manuell, Begründung), `POST /charges/{id}/void` |
| Zahlungen | `GET/POST /payments`, `POST /payments/{id}/allocations`, `/deallocate`, `/reverse` (Storno per Gegenbuchung) |
| Rechnungen | `GET/POST /invoices`, `POST /invoices/{id}/void` |
| Dokumente | `POST /documents` (multipart), `GET /documents?entity_type&entity_id`, `GET /documents/{id}/download` (nur angemeldet) |
| Kautionen | `GET/POST /deposits`, `GET /deposits/{id}`, `POST /deposits/{id}/transactions`, `POST /deposit-transactions/{id}/void` |
| Mahnwesen | `GET /dunning/overdue`, `POST /dunning/prepare`, `GET /dunning/notices[/{id}]`, `PATCH …`, `POST …/approve`, `…/mark-sent`, `…/cancel` |
| Bankimport | `GET/POST /bank/accounts`, `POST /bank/imports/preview`, `POST /bank/imports`, `GET /bank/imports`, `GET /bank/transactions` (`suggestions`, `only_unmatched`), `POST …/{id}/confirm` (Pflichtfeld `confirm: true`), `…/ignore`, `…/reopen` |
| Auswertungen | `GET /economics?scope=portfolio|property|unit|rentable_unit&id&start&end`, `GET /vacancy?start&end&property_id` |
| Hauptmiete | `PUT /leases/{id}/allocation` (Methode area/equal/custom + Gewichte) |


## Ergänzung Phase E (implementiert und getestet)
| Ressource | Endpunkte |
|---|---|
| Aufgaben | `GET/POST /tasks` (Filter: `status`, `priority`, `overdue`, `open_only`, `q`, Bezüge), `GET/PATCH /tasks/{id}`, `POST /tasks/{id}/status` |
| Erinnerungen | `GET /reminders`, `POST /reminders/task` (genau eine Aufgabe je Erinnerung); Vertragsende-Hinweise nutzen dieselbe Definition und denselben Vorschauzeitraum (`contract_end_preview_days`) wie das Dashboard; überfällige Forderungen nutzen `charges.receivable_position` (Stichtag heute) |
| Reparaturen | `GET/POST /repairs`, `GET/PATCH /repairs/{id}`, `POST …/status`, `…/notes`, `…/invoices` |
| Kommunikation | `GET/POST /communications` (kein Ändern/Löschen, kein Versand) |
| Übergabeprotokolle | `GET/POST /handover-protocols` |
| Historie | `GET /history?entity_type&entity_id` |
| Dokumente | `GET /documents/search`, `POST /documents/{id}/links`, `POST /documents/{id}/delete` (Weichlöschung), `GET /leases/{id}/missing-documents` |

## Ergänzung Master-Review (neue/geänderte Endpunkte)
| Endpunkt | Zweck |
|---|---|
| `POST /charges/preview` | Vorschau (Dry-Run) der Sollstellungs-Erzeugung: `would_create`, `skipped_existing`, `conflicts` (`amount_differs`, `period_overlap`), `errors`, `notes`, `backdated_count`; schreibt nichts |
| `POST /charges/generate` | Erzeugt Sollstellungen; rückwirkende Perioden nur mit `allow_backdated: true`, sonst 409 `backdated_confirmation_required`; Rhythmen `monthly/quarterly/half_yearly/yearly`, `on_demand` erzeugt nichts |
| `GET /tenants` | gebündelt, paginiert (`items,total,limit,offset`); `lease_status` = Phase `upcoming/active/notice/ended/draft/no_lease`, `lease_raw_status` = gespeicherter Status |
| `GET /tenants/{id}/overview` | eine Abfrage für das Detailpanel (Verträge, Soll/Offen, Zahlungen, Kaution, Dokumente, Aufgaben, Reparaturen, Aktivität) |
| `PATCH /rooms/{id}`, `/beds/{id}`, `/units/{id}`, `/leases/{id}`, `/parties/{id}`, `/properties/{id}` | Bearbeiten mit Audit Vorher/Nachher (IBAN/Geburtsdatum maskiert); `warnings`/`impact` bei Folgen (Fläche, Vertragsende) |
| `POST /leases/{id}/terms` | neue Konditionsversion (Historie bleibt, keine stille Rückwirkung) |
| `GET /dunning/overdue` | zusätzlich `summary.by_state` (due, draft_exists, approved_not_sent, waiting, max_level_reached), `charge_label`, `period_start/end` |
| `GET /economics` | zusätzlich `datenstand`, `offen_zum_stichtag.{as_of,is_forecast}`, `prognose_periodenende` (nur gekennzeichnete Prognose) |
| `GET /dashboard` | KPI-Felder `definition` und `hint`; „aktiver Mieter“ = Partei mit mind. einem laufenden Untermietvertrag als Mieter/Mitmieter (gekündigte, noch laufende Verträge zählen) |
| `GET /dashboard?as_of=YYYY-MM-DD` | Entscheidung `docs/decisions/0002-dashboard-kpi-definitions.md`. `as_of` optional (ohne = heute, abwärtskompatibel); Zukunft → 422 `as_of_in_future`, ungültiges Format → 422. Antwort enthält `as_of` und je KPI `historical_supported`. Stichtagsfähig (`true`): aktive Haupt-/Untermietverträge, aktive Mieter, offene Forderungen, überfällige Zahlungen, anstehende Vertragsenden. Nicht stichtagsfähig (`false`, zeigen immer den heutigen Stand/Monat; keine erfundene Historie): Immobilien, Wohneinheiten, Aufgaben, Reparaturen, Leerstand, Monats-Soll/Betriebskosten. Offene Forderungen: Forderungen (`receivable`, nicht storniert) abzüglich Zahlungen mit `booking_date <= as_of`, unabhängig von der Fälligkeit (Annahme A1); überfällig = Rest > 0 und Fälligkeit < Stichtag. `units` = aktive Einheiten in aktiven Objekten. `upcoming_contract_ends` = zum Stichtag laufende Haupt- und Untermietverträge mit wirksamem Ende in `[as_of, as_of + contract_end_preview_days]`; der Zeitraum kommt aus der Einstellung `contract_end_preview_days` (Env `LEVENTUM_CONTRACT_END_PREVIEW_DAYS`, Standard 90, 1–730) und gilt identisch für `GET /reminders`. Bekannte Einschränkungen historischer Stichtage: ADR 0002 A6 (zurückgenommene Zuordnungen, heute stornierte Forderungen, heutige Stammdaten/Vertragsstatus). Recht `dashboard:read` unverändert |
| `POST /documents/{id}/verify`, `/documents/verify-all`, `POST /documents/{id}/purge` | Integritätsprüfung; endgültige Entfernung nur Admin nach Aufbewahrungsfrist |
| `GET /system/integrity` | Datenprüfung (siehe 04) |
| `POST /system/backups` `{passphrase?}`, `…/verify`, `…/restore` `{confirm, passphrase?}` | optional verschlüsselte Backups (AES-256-GCM) |
| `GET/POST /utility-statements…` | Betriebskosten Ebene A inkl. `allocation` (bei Status „geprüft“ eingefroren) und `comparison` (Ebene B) – jetzt auch über die Oberfläche (`/betriebskosten`) |
