---
name: database-migrations
description: Alembic-Migrationen und Modelländerungen: Up/Down, Backfill, Constraints, Altdatentest. Verwenden bei jeder Schemaänderung.
---

# Skill: database-migrations

Gemeinsame Regeln: `CLAUDE.md`, `.claude/rules/`. Dieser Skill ergänzt sie, ersetzt sie nicht.

## 1. Zweck
Schema kontrolliert, rückführbar und mit Bestandsdaten sicher ändern.

## 2. Einsatzbedingungen
- Jede Änderung in `backend/leventum/models/*` oder `backend/alembic/versions/*`.

## 3. Fachliche Grundlagen
Revisionen 0001–0005; `0005` zeigt Muster (nullable → Backfill → NOT NULL + unique, `#dup{id}` für Altdubletten). Test `tests/test_backup_migrations.py` (Up/Down, Altdaten, Revision-Assert). Geld/Fläche als BIGINT×100 (`Decimal2`).

## 4. Arbeitsanweisungen
1. Änderung mit Database Architect abstimmen (ADR bei Hochrisiko). 2. Migration manuell schreiben/prüfen, nie blind autogenerierte übernehmen. 3. Altdaten-Szenario bauen (Duplikate, NULLs). 4. Up, Down, erneut Up testen. 5. Modelle ↔ Migration synchron (Test). 6. Backup-/Restore-Kompatibilität prüfen (Schema-Revision im Manifest). 7. Volle Suite.

## 5. Verbindliche Regeln
- Keine Löschung/Änderung historischer Finanzdaten per Migration ohne menschliche Freigabe.
- Constraints erst nach Backfill.
- Downgrade vorhanden oder Begründung dokumentiert.

## 6. Typische Fehler
NOT NULL ohne Default auf Bestandsdaten; Unique ohne Duplikatbereinigung; Modell ändern ohne Migration; SQLite-spezifisches Verhalten als PostgreSQL-tauglich ausgeben.

## 7. Qualitätskriterien
Migration läuft auf leerer und auf Altdaten-DB; Down/Up verlustfrei soweit vorgesehen; Integritätsprüfung (`/system/integrity`) sauber.

## 8. Erforderliche Tests
`pytest tests/test_backup_migrations.py` + volle Suite; neuer Altdatentest je Migration.

## 9. Übergabekriterien
Migration, Test, Risikoanalyse, Rollback-Hinweis; Review Database Architect + QA.

## 10. Grenzen und Eskalationsfälle
Eskalation: Datenverlustrisiko, Änderung an Finanztabellen, PostgreSQL-Umzug (nie getestet).
