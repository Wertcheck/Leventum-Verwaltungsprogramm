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
