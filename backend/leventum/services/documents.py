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
        from leventum.models import Deposit, DepositTransaction, Invoice, Lease, Party, Payment, Property, Unit
        _ENTITY_MODELS.update(party=Party, property=Property, unit=Unit, lease=Lease, invoice=Invoice, deposit=Deposit,
                              deposit_transaction=DepositTransaction, payment=Payment)
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


def for_entity(db: Session, entity_type: str, entity_id: int) -> list[Document]:
    return list(db.scalars(select(Document).join(DocumentLink).where(DocumentLink.entity_type == entity_type, DocumentLink.entity_id == entity_id)
                           .order_by(Document.id)))
