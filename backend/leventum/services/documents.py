"""Minimaler Dokumentenspeicher (Metadaten in der DB, Dateien im FileStore). Kein Zugriff ohne Authentifizierung."""
from __future__ import annotations

from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from leventum import domain
from leventum.models import Document, DocumentLink
from leventum.services import audit
from leventum.services.errors import NotFound, ServiceError
from leventum.storage import FileStore, FileValidationError

_ENTITY_MODELS: dict = {}


def _model(entity_type: str):
    if not _ENTITY_MODELS:
        from leventum.models import (Communication, Deposit, DepositTransaction, HandoverProtocol, Invoice, Lease, Party, Payment, Property, Repair, Task, Unit)
        _ENTITY_MODELS.update(party=Party, property=Property, unit=Unit, lease=Lease, invoice=Invoice, deposit=Deposit,
                              deposit_transaction=DepositTransaction, payment=Payment, repair=Repair, task=Task, communication=Communication,
                              handover_protocol=HandoverProtocol)
    return _ENTITY_MODELS[entity_type]


def upload(db: Session, store: FileStore, actor_id: int | None, *, stream: BinaryIO, filename: str, doc_type: str,
           entity_type: str, entity_id: int) -> Document:
    if entity_type not in domain.DOC_ENTITIES or doc_type not in domain.DOC_TYPES:
        raise ServiceError("invalid", "Ungültiger Dokumenttyp oder Zuordnungstyp.")
    if db.get(_model(entity_type), entity_id) is None:
        raise NotFound("Zuordnungsziel")
    try:
        f = store.save(stream, filename)
    except FileValidationError as e:
        raise ServiceError("invalid_file", str(e), 422)
    doc = Document(storage_key=f.key, original_name=f.original_name, mime=f.mime, size=f.size, sha256=f.sha256, doc_type=doc_type,
                   uploaded_by_user_id=actor_id)
    doc.links.append(DocumentLink(entity_type=entity_type, entity_id=entity_id))
    db.add(doc)
    db.flush()
    audit.record(db, "document.uploaded", actor_user_id=actor_id, entity_type=entity_type, entity_id=entity_id, summary=f"Dokument hochgeladen: {f.original_name}",
                 details={"document_id": doc.id, "sha256": f.sha256})
    return doc


def for_entity(db: Session, entity_type: str, entity_id: int, include_deleted: bool = False) -> list[Document]:
    stmt = select(Document).join(DocumentLink).where(DocumentLink.entity_type == entity_type, DocumentLink.entity_id == entity_id).order_by(Document.id)
    if not include_deleted:
        stmt = stmt.where(Document.deleted_at.is_(None))
    return list(db.scalars(stmt))


def query(db: Session, *, q: str | None = None, doc_type: str | None = None, entity_type: str | None = None, entity_id: int | None = None,
          include_deleted: bool = False, limit: int = 500) -> list[Document]:
    stmt = select(Document).order_by(Document.id.desc())
    if entity_type:
        stmt = stmt.join(DocumentLink).where(DocumentLink.entity_type == entity_type)
        if entity_id is not None:
            stmt = stmt.where(DocumentLink.entity_id == entity_id)
    if q:
        stmt = stmt.where(Document.original_name.ilike(f"%{q}%"))
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    if not include_deleted:
        stmt = stmt.where(Document.deleted_at.is_(None))
    return list(db.scalars(stmt.limit(limit)).unique())


def add_link(db: Session, actor_id: int | None, document_id: int, entity_type: str, entity_id: int) -> Document:
    doc = db.get(Document, document_id)
    if doc is None or doc.deleted_at:
        raise NotFound("Dokument")
    if entity_type not in domain.DOC_ENTITIES:
        raise ServiceError("invalid", "Ungültiger Zuordnungstyp.")
    if db.get(_model(entity_type), entity_id) is None:
        raise NotFound("Zuordnungsziel")
    if not any(l.entity_type == entity_type and l.entity_id == entity_id for l in doc.links):
        doc.links.append(DocumentLink(entity_type=entity_type, entity_id=entity_id))
        audit.record(db, "document.linked", actor_user_id=actor_id, entity_type=entity_type, entity_id=entity_id, summary="Dokument zugeordnet", details={"document_id": doc.id})
    db.flush()
    return doc


def soft_delete(db: Session, actor_id: int | None, document_id: int, reason: str) -> Document:
    """Blendet das Dokument aus. Die Datei bleibt im Speicher (Aufbewahrungsfristen sind fachlich offen) und im Backup."""
    from datetime import datetime, timezone
    doc = db.get(Document, document_id)
    if doc is None:
        raise NotFound("Dokument")
    if doc.deleted_at:
        raise ServiceError("already_deleted", "Das Dokument ist bereits gelöscht.", 409)
    if not reason.strip():
        raise ServiceError("invalid", "Begründung erforderlich.")
    doc.deleted_at, doc.deleted_by_user_id, doc.delete_reason = datetime.now(timezone.utc), actor_id, reason.strip()
    audit.record(db, "document.deleted", actor_user_id=actor_id, entity_type="document", entity_id=doc.id, summary=f"Dokument gelöscht: {doc.original_name}", details={"reason": reason, "sha256": doc.sha256})
    db.flush()
    return doc


def missing_for_lease(db: Session, lease) -> list[str]:
    """Fehlende Pflichtdokumente laut Annahme `REQUIRED_DOCS`. Ein Übergabeprotokoll gilt auch durch einen erfassten Einzug-Protokolleintrag als vorhanden."""
    from leventum.models import HandoverProtocol
    have = {d.doc_type for d in for_entity(db, "lease", lease.id)}
    if db.scalar(select(HandoverProtocol.id).where(HandoverProtocol.lease_id == lease.id, HandoverProtocol.kind == "move_in")) is not None:
        have.add("uebergabeprotokoll")
    return [t for t in domain.REQUIRED_DOCS.get(lease.kind, ()) if t not in have]


def verify(store: FileStore, doc: Document) -> dict:
    """Prüft, ob die Datei tatsächlich vorhanden, lesbar und unverändert ist (Größe + SHA-256)."""
    import hashlib
    if doc.purged_at:
        return {"ok": False, "problem": "purged", "message": "Die Datei wurde endgültig entfernt."}
    if not store.exists(doc.storage_key):
        return {"ok": False, "problem": "missing", "message": "Die Datei fehlt im Dokumentenspeicher."}
    h, size = hashlib.sha256(), 0
    try:
        with store.open(doc.storage_key) as fh:
            while chunk := fh.read(1024 * 256):
                h.update(chunk)
                size += len(chunk)
    except OSError as e:
        return {"ok": False, "problem": "unreadable", "message": f"Die Datei ist nicht lesbar: {e}"}
    if size != doc.size:
        return {"ok": False, "problem": "size_mismatch", "message": f"Dateigröße weicht ab (gespeichert {doc.size}, tatsächlich {size})."}
    if h.hexdigest() != doc.sha256:
        return {"ok": False, "problem": "hash_mismatch", "message": "Die Prüfsumme stimmt nicht – die Datei wurde verändert oder ist beschädigt."}
    return {"ok": True, "problem": None, "message": "Datei vorhanden und unverändert."}


def verify_all(db: Session, store: FileStore) -> list[dict]:
    """Alle nicht gelöschten Dokumente prüfen; liefert nur die Auffälligkeiten."""
    out = []
    for d in db.scalars(select(Document).where(Document.deleted_at.is_(None))):
        r = verify(store, d)
        if not r["ok"]:
            out.append({"document_id": d.id, "original_name": d.original_name, **r})
    return out


def purge(db: Session, store: FileStore, actor_id: int | None, document_id: int, reason: str, retention_days: int, today=None) -> Document:
    """Endgültige Entfernung der Datei. Nur für bereits (weich) gelöschte Dokumente, nur nach Ablauf der Aufbewahrungsfrist (ab Upload),
    mit Begründung. Metadaten und Prüfsumme bleiben zum Nachweis erhalten."""
    from datetime import date, datetime, timezone
    doc = db.get(Document, document_id)
    if doc is None:
        raise NotFound("Dokument")
    if doc.purged_at:
        raise ServiceError("already_purged", "Die Datei wurde bereits endgültig entfernt.", 409)
    if not doc.deleted_at:
        raise ServiceError("not_deleted", "Nur bereits gelöschte Dokumente können endgültig entfernt werden (zuerst löschen).", 409)
    if not reason.strip():
        raise ServiceError("invalid", "Begründung erforderlich.")
    today = today or date.today()
    from leventum.db.engine import aware
    due = aware(doc.uploaded_at).date().toordinal() + retention_days
    if today.toordinal() < due:
        raise ServiceError("retention_period", f"Aufbewahrungsfrist ({retention_days} Tage ab Upload) noch nicht abgelaufen; frühestens am {date.fromordinal(due):%d.%m.%Y} möglich.", 409)
    store.delete(doc.storage_key)
    doc.purged_at, doc.purged_by_user_id, doc.purge_reason = datetime.now(timezone.utc), actor_id, reason.strip()
    audit.record(db, "document.purged", actor_user_id=actor_id, entity_type="document", entity_id=doc.id, summary=f"Datei endgültig entfernt: {doc.original_name}",
                 details={"reason": reason, "sha256": doc.sha256, "retention_days": retention_days})
    db.flush()
    return doc
