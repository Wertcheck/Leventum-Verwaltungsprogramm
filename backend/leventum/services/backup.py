"""Backup = ZIP aus konsistentem DB-Snapshot + Dokumenten + Manifest (SHA-256).
Nur SQLite wird unterstützt; für PostgreSQL ist pg_dump-Integration offen (siehe Dokumentation)."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import Engine

from leventum import __version__
from leventum.config import Settings

FORMAT = 1
DB_NAME = "database.sqlite3"


class BackupError(Exception):
    pass


@dataclass
class VerifyResult:
    ok: bool
    problems: list[str]
    manifest: dict | None = None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _db_path(engine: Engine) -> Path:
    if engine.dialect.name != "sqlite":
        raise BackupError("Backup ist derzeit nur für SQLite implementiert.")
    return Path(engine.url.database)


def _schema_revision(db_file: Path) -> str | None:
    con = sqlite3.connect(db_file)
    try:
        row = con.execute("SELECT version_num FROM alembic_version").fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def create_backup(engine: Engine, settings: Settings, label: str = "manual") -> Path:
    src = _db_path(engine)
    settings.backups_path.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    target = settings.backups_path / f"leventum-backup-{stamp}-{label}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / DB_NAME
        s = sqlite3.connect(src)
        d = sqlite3.connect(snap)
        try:
            s.backup(d)  # SQLite-Backup-API: konsistent auch bei laufender Datenbank
        finally:
            d.close()
            s.close()
        files: list[dict] = [{"path": DB_NAME, "sha256": _sha256(snap), "size": snap.stat().st_size}]
        doc_root = settings.documents_path
        doc_files = sorted(p for p in doc_root.rglob("*") if p.is_file()) if doc_root.exists() else []
        part = target.with_suffix(".part")
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snap, DB_NAME)
            for p in doc_files:
                rel = "documents/" + p.relative_to(doc_root).as_posix()
                files.append({"path": rel, "sha256": _sha256(p), "size": p.stat().st_size})
                z.write(p, rel)
            manifest = {"format": FORMAT, "app_version": __version__,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "schema_revision": _schema_revision(snap), "files": files}
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
        part.replace(target)
    return target


def verify_backup(path: Path) -> VerifyResult:
    problems: list[str] = []
    try:
        with zipfile.ZipFile(path) as z:
            if z.testzip() is not None:
                return VerifyResult(False, ["ZIP-Archiv ist beschädigt."])
            if "manifest.json" not in z.namelist():
                return VerifyResult(False, ["manifest.json fehlt."])
            manifest = json.loads(z.read("manifest.json"))
            if manifest.get("format") != FORMAT:
                return VerifyResult(False, [f"Unbekanntes Backup-Format: {manifest.get('format')}"], manifest)
            names = set(z.namelist())
            for f in manifest["files"]:
                if f["path"] not in names:
                    problems.append(f"Datei fehlt im Archiv: {f['path']}")
                    continue
                h = hashlib.sha256()
                with z.open(f["path"]) as fh:
                    while chunk := fh.read(1024 * 1024):
                        h.update(chunk)
                if h.hexdigest() != f["sha256"]:
                    problems.append(f"Prüfsumme stimmt nicht: {f['path']}")
            if not problems:
                with tempfile.TemporaryDirectory() as tmp:
                    z.extract(DB_NAME, tmp)
                    con = sqlite3.connect(Path(tmp) / DB_NAME)
                    try:
                        res = con.execute("PRAGMA integrity_check").fetchone()[0]
                    finally:
                        con.close()
                    if res != "ok":
                        problems.append(f"Datenbank-Integritätsprüfung fehlgeschlagen: {res}")
            return VerifyResult(not problems, problems, manifest)
    except (zipfile.BadZipFile, OSError, json.JSONDecodeError, KeyError) as e:
        return VerifyResult(False, [f"Backup nicht lesbar: {e}"])


def list_backups(settings: Settings) -> list[dict]:
    out = []
    if settings.backups_path.exists():
        for p in sorted(settings.backups_path.glob("leventum-backup-*.zip"), reverse=True):
            out.append({"id": p.name, "size": p.stat().st_size,
                        "created_at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()})
    return out


def resolve_backup(settings: Settings, backup_id: str) -> Path:
    p = (settings.backups_path / backup_id).resolve()
    if p.parent != settings.backups_path.resolve() or not p.is_file():
        raise BackupError("Backup nicht gefunden.")
    return p


def restore_backup(engine: Engine, settings: Settings, backup: Path) -> Path:
    """Stellt DB + Dokumente wieder her. Legt vorher ein Sicherheits-Backup des Ist-Zustands an.
    Gibt den Pfad des Sicherheits-Backups zurück. Der alte Stand bleibt bei jedem Fehler vor dem Austausch erhalten."""
    res = verify_backup(backup)
    if not res.ok:
        raise BackupError("Backup ist nicht intakt: " + "; ".join(res.problems))
    db_file = _db_path(engine)
    safety = create_backup(engine, settings, label="pre-restore")
    with tempfile.TemporaryDirectory(dir=settings.data_dir) as tmp:
        tmp_p = Path(tmp)
        with zipfile.ZipFile(backup) as z:
            z.extractall(tmp_p)
        new_db = tmp_p / DB_NAME
        new_docs = tmp_p / "documents"
        engine.dispose()
        for suffix in ("-wal", "-shm"):
            Path(str(db_file) + suffix).unlink(missing_ok=True)
        shutil.copy2(new_db, db_file)
        docs = settings.documents_path
        old_docs = docs.with_name(docs.name + ".old")
        if old_docs.exists():
            shutil.rmtree(old_docs)
        if docs.exists():
            docs.rename(old_docs)
        if new_docs.exists():
            shutil.copytree(new_docs, docs)
        else:
            docs.mkdir(parents=True)
        shutil.rmtree(old_docs, ignore_errors=True)
    engine.dispose()
    return safety


def latest_backup_info(settings: Settings) -> dict:
    items = list_backups(settings)
    items = [i for i in items if not i["id"].endswith("-pre-restore.zip")] or items
    if not items:
        return {"last_backup_at": None, "age_hours": None, "stale": True}
    last = max(items, key=lambda i: i["created_at"])
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(last["created_at"])).total_seconds() / 3600
    return {"last_backup_at": last["created_at"], "age_hours": round(age, 1), "stale": age > settings.backup_max_age_hours}
