import io
import sqlite3
import zipfile
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, select

from leventum.db.base import Base
from leventum.models import AuditEvent, Role
from leventum.services import backup as b
import leventum.models  # noqa: F401


def _doc(settings, name="a.pdf", data=b"%PDF-1 original"):
    p = settings.documents_path / "ab" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_migration_creates_schema_and_matches_models(settings, app):
    """Modelle und Migrationen sind synchron: Autogenerate findet keine Differenzen."""
    e = create_engine(settings.db_url)
    with e.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diffs == []
    with app.state.session_factory() as db:
        assert {r.code for r in db.scalars(select(Role))} >= {"admin", "lesend"}


def test_migration_downgrade_and_upgrade_roundtrip(tmp_path):
    from alembic import command
    from alembic.config import Config
    from leventum.main import BACKEND_DIR
    url = f"sqlite:///{tmp_path/'m.db'}"
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    assert sqlite3.connect(tmp_path / "m.db").execute("select count(*) from sqlite_master where name='app_user'").fetchone()[0] == 0
    command.upgrade(cfg, "head")


def test_backup_contains_db_docs_manifest_and_verifies(app, settings):
    _doc(settings)
    path = b.create_backup(app.state.engine, settings)
    names = zipfile.ZipFile(path).namelist()
    assert {"database.sqlite3", "manifest.json", "documents/ab/a.pdf"} <= set(names)
    res = b.verify_backup(path)
    assert res.ok and res.manifest["schema_revision"] == "0002"


def test_verify_detects_tampering(app, settings, tmp_path):
    _doc(settings)
    path = b.create_backup(app.state.engine, settings)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(bad, "w") as zout:
        for n in zin.namelist():
            data = zin.read(n)
            if n.startswith("documents/"):
                data = b"manipuliert"
            zout.writestr(n, data)
    res = b.verify_backup(bad)
    assert not res.ok and any("Prüfsumme" in p for p in res.problems)
    garbage = tmp_path / "g.zip"
    garbage.write_bytes(b"kein zip")
    assert not b.verify_backup(garbage).ok


def test_restore_roundtrip_db_and_documents_together(auth_client, app, settings):
    doc = _doc(settings)
    r = auth_client.post("/api/v1/system/backups")
    assert r.status_code == 200 and r.json()["verified"] is True
    bid = r.json()["id"]
    # Zustand NACH dem Backup verändern: Dokument ändern, neues Dokument, Audit-Eintrag
    doc.write_bytes(b"%PDF-1 VERAENDERT")
    _doc(settings, "neu.pdf")
    with app.state.session_factory() as db:
        db.add(AuditEvent(action="nach.backup", summary="x"))
        db.commit()
    r = auth_client.post(f"/api/v1/system/backups/{bid}/restore", json={"confirm": True})
    assert r.status_code == 200, r.text
    assert doc.read_bytes() == b"%PDF-1 original"
    assert not (settings.documents_path / "ab" / "neu.pdf").exists()
    with app.state.session_factory() as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "nach.backup")) is None
    # Sicherheits-Backup des Zustands vor der Wiederherstellung existiert und enthält die Änderungen
    safety = settings.backups_path / r.json()["safety_backup"]
    z = zipfile.ZipFile(safety)
    assert z.read("documents/ab/a.pdf") == b"%PDF-1 VERAENDERT"


def test_restore_requires_confirmation_and_rejects_corrupt_backup(auth_client, settings):
    bid = auth_client.post("/api/v1/system/backups").json()["id"]
    assert auth_client.post(f"/api/v1/system/backups/{bid}/restore", json={}).status_code == 400
    (settings.backups_path / "leventum-backup-corrupt.zip").write_bytes(b"x")
    r = auth_client.post("/api/v1/system/backups/leventum-backup-corrupt.zip/restore", json={"confirm": True})
    assert r.status_code == 400


def test_backup_id_cannot_escape_directory(auth_client):
    r = auth_client.post("/api/v1/system/backups/..%2F..%2Fetc%2Fpasswd/verify")
    assert r.status_code == 404


def test_backup_status_reports_stale_without_backup(auth_client):
    j = auth_client.get("/api/v1/system/backups").json()
    assert j["last_backup_at"] is None and j["stale"] is True
    auth_client.post("/api/v1/system/backups")
    j = auth_client.get("/api/v1/system/backups").json()
    assert j["stale"] is False and len(j["items"]) == 1
