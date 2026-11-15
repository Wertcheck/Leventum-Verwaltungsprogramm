# Daten und Migrationen

- Schemaänderungen **ausschließlich über Alembic** (`backend/alembic/versions`, aktuell bis `0005`). Keine Auto-Generierung ungeprüft übernehmen: NOT-NULL/Unique auf Bestandsdaten erst nach Backfill (Muster: `0005`, Altdubletten-Test in `tests/test_backup_migrations.py`).
- Jede Migration: Upgrade **und** Downgrade getestet, auch mit Altdaten. Revisions-Assertion in `test_backup_migrations.py` mitpflegen.
- Keine Löschung/Änderung historischer Finanzdaten; Dokumente nur weich löschen (mit Begründung); endgültig nur `purge` durch Admin nach Aufbewahrungsfrist.
- Modelle ↔ Migration synchron (Test vorhanden). SQLite ist Standard; PostgreSQL ist **vorbereitet, nie getestet** – so berichten.
- Integritätsregeln zentral in `services/integrity.py`; neue Invarianten dort ergänzen und testen.
- Transaktionen: Services committen nicht selbst (außer `services/auth.py`); die API-Schicht ruft `db.commit()`; mehrstufige Änderungen atomar.
