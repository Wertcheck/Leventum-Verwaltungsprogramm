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
