"""Zentrale Vorgangshistorie: Audit-Ereignisse + Kommunikation + Reparaturverlauf, chronologisch."""
from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from leventum.models import AppUser, AuditEvent, Communication, Deposit, Document, DunningNotice, Lease, LeaseParty, Repair, RepairEvent, Task
from leventum.security.finance_access import FINANCE_AUDIT_ENTITY_TYPES, FINANCE_DOC_TYPES, FINANCE_REPAIR_EVENT_KINDS, is_finance_audit


def _actor_names(db: Session, ids: set) -> dict:
    ids = {i for i in ids if i}
    return {u.id: u.display_name for u in db.scalars(select(AppUser).where(AppUser.id.in_(ids)))} if ids else {}


def _doc_id(e) -> int | None:
    d = e.details if e.action.startswith("document.") and isinstance(e.details, dict) else None
    return int(d["document_id"]) if d and str(d.get("document_id", "")).isdigit() else None


def filter_audit(db: Session, rows: list, include_finance: bool) -> list:
    """Audit-Ereignisse ohne Finanzbezug (Ereignisart/Entitätstyp, Dokumente mit Finanztyp); mit finance:read unverändert."""
    if include_finance:
        return rows
    ids = {i for i in map(_doc_id, rows) if i is not None}
    hidden = {i for (i,) in db.execute(select(Document.id).where(Document.id.in_(ids), Document.doc_type.in_(sorted(FINANCE_DOC_TYPES))))} if ids else set()
    return [e for e in rows if not is_finance_audit(e.action, e.entity_type) and _doc_id(e) not in hidden]


def timeline(db: Session, *, audit_refs: list[tuple[str, int]], comm_filter=None, repair_ids: list[int] | None = None, limit: int = 200,
             include_finance: bool = True) -> list[dict]:
    """include_finance=False (finance:read fehlt): Audit-Ereignisse mit Finanzbezug (Kaution, Mahnung, Rechnung, Zahlung; Dokumente mit Finanztyp) und
    Reparaturereignisse mit Rechnungsbetrag entfallen. Gefiltert wird nach Ereignisart/Quelle (nicht per Textsuche), VOR der Begrenzung."""
    items: list[dict] = []
    if not include_finance:
        audit_refs = [(t, i) for t, i in audit_refs if t not in FINANCE_AUDIT_ENTITY_TYPES]
    if audit_refs:
        cond = or_(*[and_(AuditEvent.entity_type == t, AuditEvent.entity_id == str(i)) for t, i in audit_refs])
        rows = list(db.scalars(select(AuditEvent).where(cond).order_by(AuditEvent.occurred_at.desc()).limit(limit * 2)))
        for e in filter_audit(db, rows, include_finance):
            items.append({"at": e.occurred_at, "source": "audit", "action": e.action, "summary": e.summary, "actor_user_id": e.actor_user_id,
                          "entity_type": e.entity_type, "entity_id": e.entity_id})
    if comm_filter is not None:
        for c in db.scalars(select(Communication).where(comm_filter).order_by(Communication.occurred_at.desc()).limit(limit)):
            items.append({"at": c.occurred_at, "source": "communication", "action": f"communication.{c.channel}.{c.direction}", "summary": f"{'Eingang' if c.direction == 'in' else 'Ausgang'} ({c.channel}): {c.subject}",
                          "actor_user_id": c.created_by_user_id, "entity_type": "communication", "entity_id": str(c.id)})
    for rid in repair_ids or []:
        for ev in db.scalars(select(RepairEvent).where(RepairEvent.repair_id == rid)):
            if not include_finance and ev.kind in FINANCE_REPAIR_EVENT_KINDS:
                continue
            items.append({"at": ev.occurred_at, "source": "repair", "action": f"repair.{ev.kind}", "summary": f"Reparatur #{rid}: {ev.text}", "actor_user_id": ev.created_by_user_id,
                          "entity_type": "repair", "entity_id": str(rid)})
    names = _actor_names(db, {i["actor_user_id"] for i in items})
    for i in items:
        i["actor"] = names.get(i["actor_user_id"])
    # naive Zeitstempel aus SQLite vereinheitlichen
    from leventum.db.engine import aware
    for i in items:
        i["at"] = aware(i["at"])
    items.sort(key=lambda i: i["at"], reverse=True)
    return items[:limit]


def party_timeline(db: Session, party_id: int, limit: int = 200, include_finance: bool = True) -> list[dict]:
    """Mieterakte: Partei + deren Verträge (+ Kautionen, Mahnungen) + Kommunikation + Reparaturen + Aufgaben. include_finance=False: ohne Kaution-/Mahnung-/Rechnungs-/Zahlungsereignisse."""
    lease_ids = [x for (x,) in db.execute(select(LeaseParty.lease_id).where(LeaseParty.party_id == party_id))]
    refs: list[tuple[str, int]] = [("party", party_id)] + [("lease", i) for i in lease_ids]
    refs += [("deposit", d) for (d,) in db.execute(select(Deposit.id).where(Deposit.lease_id.in_(lease_ids)))] if lease_ids else []
    refs += [("dunning_notice", n) for (n,) in db.execute(select(DunningNotice.id).where(DunningNotice.lease_id.in_(lease_ids)))] if lease_ids else []
    repair_ids = [r for (r,) in db.execute(select(Repair.id).where(or_(Repair.reported_by_party_id == party_id, Repair.lease_id.in_(lease_ids or [-1]))))]
    refs += [("repair", r) for r in repair_ids]
    task_ids = [t for (t,) in db.execute(select(Task.id).where(or_(Task.party_id == party_id, Task.lease_id.in_(lease_ids or [-1]))))]
    refs += [("task", t) for t in task_ids]
    comm = or_(Communication.party_id == party_id, Communication.lease_id.in_(lease_ids or [-1]))
    return timeline(db, audit_refs=refs, comm_filter=comm, repair_ids=repair_ids, limit=limit, include_finance=include_finance)


def entity_timeline(db: Session, entity_type: str, entity_id: int, limit: int = 200, include_finance: bool = True) -> list[dict]:
    if entity_type == "party":
        return party_timeline(db, entity_id, limit, include_finance)
    comm = {"lease": Communication.lease_id, "property": Communication.property_id, "unit": Communication.unit_id, "repair": Communication.repair_id}.get(entity_type)
    return timeline(db, audit_refs=[(entity_type, entity_id)], comm_filter=(comm == entity_id) if comm is not None else None,
                    repair_ids=[entity_id] if entity_type == "repair" else None, limit=limit, include_finance=include_finance)
