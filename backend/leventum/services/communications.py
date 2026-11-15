"""Kommunikationsprotokoll und Übergabeprotokolle. Nur Erfassung – die Software versendet keine Nachrichten."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from leventum import domain
from leventum.models import Communication, HandoverProtocol, Lease, Party, Property, Repair, Unit
from leventum.services import audit, tasks as T
from leventum.services.errors import ServiceError
from leventum.services.master import get_or_404

REFS = {"party_id": (Party, "Partei"), "lease_id": (Lease, "Vertrag"), "property_id": (Property, "Objekt"), "unit_id": (Unit, "Wohneinheit"), "repair_id": (Repair, "Reparatur")}


def create(db: Session, actor_id: int | None, *, channel: str, direction: str, subject: str, occurred_at: datetime | None = None, body: str | None = None,
           follow_up: dict | None = None, **refs) -> Communication:
    if channel not in domain.COMM_CHANNELS or direction not in domain.COMM_DIRECTIONS:
        raise ServiceError("invalid", "Ungültiger Kanal oder ungültige Richtung.")
    if not subject.strip():
        raise ServiceError("invalid", "Betreff fehlt.")
    refs = {k: v for k, v in refs.items() if v is not None}
    if not refs:
        raise ServiceError("invalid", "Mindestens eine Zuordnung (Partei, Vertrag, Objekt, Wohneinheit oder Reparatur) ist erforderlich.")
    for k, v in refs.items():
        get_or_404(db, REFS[k][0], v, REFS[k][1])
    c = Communication(channel=channel, direction=direction, subject=subject.strip(), body=body, created_by_user_id=actor_id,
                      occurred_at=occurred_at or datetime.now(timezone.utc), **refs)
    db.add(c)
    db.flush()
    audit.record(db, "communication.created", actor_user_id=actor_id, entity_type="communication", entity_id=c.id, summary=f"Kommunikation erfasst: {c.subject}",
                 details={"channel": channel, "direction": direction, **refs})
    if follow_up:
        T.create_task(db, actor_id, **{**{k: v for k, v in refs.items() if k in T.LINKS}, **follow_up})
    return c


def query(db: Session, **flt) -> list[Communication]:
    stmt = select(Communication).order_by(Communication.occurred_at.desc(), Communication.id.desc())
    for k, v in flt.items():
        if v is not None:
            stmt = stmt.where(getattr(Communication, k) == v)
    return list(db.scalars(stmt))


def create_handover(db: Session, actor_id: int | None, *, lease_id: int, kind: str, protocol_date: date, **d) -> HandoverProtocol:
    lease = get_or_404(db, Lease, lease_id, "Vertrag")
    if lease.status in ("cancelled",):
        raise ServiceError("invalid_state", "Für stornierte Verträge kein Übergabeprotokoll.", 409)
    if kind not in domain.HANDOVER_KINDS:
        raise ServiceError("invalid", "Ungültige Art (Einzug/Auszug).")
    if d.get("unit_id") is not None:
        u = get_or_404(db, Unit, d["unit_id"], "Wohneinheit")
        if u.id not in {i.rentable_unit.unit_id for i in lease.items if i.rentable_unit.unit_id} and u.property_id not in {i.rentable_unit.property_id for i in lease.items}:
            raise ServiceError("invalid", "Die Wohneinheit gehört nicht zum Mietgegenstand des Vertrags.")
    h = HandoverProtocol(lease_id=lease.id, kind=kind, protocol_date=protocol_date, created_by_user_id=actor_id, **d)
    db.add(h)
    db.flush()
    audit.record(db, "handover.created", actor_user_id=actor_id, entity_type="lease", entity_id=lease.id, summary=f"Übergabeprotokoll ({kind}) erfasst",
                 details={"handover_id": h.id, "signed": h.signed})
    return h
