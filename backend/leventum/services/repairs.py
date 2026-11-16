from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from leventum import domain
from leventum.models import Invoice, Lease, Party, Property, Repair, RepairEvent, Task, Unit
from leventum.security.finance_access import FINANCE_REPAIR_EVENT_KINDS
from leventum.services import audit, payments as pay
from leventum.services.errors import ServiceError
from leventum.services.master import get_or_404
from leventum.services.dunning import eur
from leventum.services.utility import q


def _event(db: Session, repair_id: int, kind: str, text: str, actor_id: int | None):
    db.add(RepairEvent(repair_id=repair_id, kind=kind, text=text, created_by_user_id=actor_id))


def _validate(db: Session, d: dict, prop_id: int | None = None):
    if d.get("category") is not None and d["category"] not in domain.REPAIR_CATEGORIES:
        raise ServiceError("invalid", "Ungültige Kategorie.")
    if d.get("priority") is not None and d["priority"] not in domain.PRIORITIES:
        raise ServiceError("invalid", "Ungültige Priorität.")
    prop_id = d.get("property_id", prop_id)
    if d.get("unit_id") is not None and get_or_404(db, Unit, d["unit_id"], "Wohneinheit").property_id != prop_id:
        raise ServiceError("invalid", "Wohneinheit gehört nicht zum Objekt.")
    for k, m, lbl in (("lease_id", Lease, "Vertrag"), ("reported_by_party_id", Party, "Melder"), ("contractor_party_id", Party, "Dienstleister")):
        if d.get(k) is not None:
            get_or_404(db, m, d[k], lbl)
    if d.get("cost_estimate") is not None and d["cost_estimate"] < 0:
        raise ServiceError("invalid", "Kostenschätzung darf nicht negativ sein.")


def create_repair(db: Session, actor_id: int | None, *, property_id: int, title: str, reported_on: date, **d) -> Repair:
    get_or_404(db, Property, property_id, "Objekt")
    if not title.strip():
        raise ServiceError("invalid", "Titel fehlt.")
    _validate(db, d, property_id)
    r = Repair(property_id=property_id, title=title.strip(), reported_on=reported_on, status="reported", created_by_user_id=actor_id, **d)
    db.add(r)
    db.flush()
    _event(db, r.id, "reported", f"Gemeldet: {r.title}", actor_id)
    audit.record(db, "repair.created", actor_user_id=actor_id, entity_type="repair", entity_id=r.id, summary=f"Reparatur gemeldet: {r.title}")
    return r


def update_repair(db: Session, actor_id: int | None, repair_id: int, data: dict) -> Repair:
    r = get_or_404(db, Repair, repair_id, "Reparatur")
    if "status" in data or "property_id" in data:
        raise ServiceError("invalid", "Status nur über den Statuswechsel ändern; das Objekt ist nicht änderbar.")
    _validate(db, data, r.property_id)
    for k, v in data.items():
        old = getattr(r, k)
        if old == v:
            continue
        setattr(r, k, v)
        if k == "cost_estimate":
            _event(db, r.id, "estimate", f"Kostenschätzung: {eur(old) if old is not None else '–'} → {eur(v) if v is not None else '–'}", actor_id)
        elif k == "contractor_party_id":
            _event(db, r.id, "contractor", "Dienstleister zugeordnet" if v else "Dienstleister entfernt", actor_id)
        elif k == "scheduled_for":
            _event(db, r.id, "scheduled", f"Termin: {v or 'entfernt'}", actor_id)
    audit.record(db, "repair.updated", actor_user_id=actor_id, entity_type="repair", entity_id=r.id, summary="Reparatur geändert", details={"fields": sorted(data)})
    db.flush()
    return r


def set_status(db: Session, actor_id: int | None, repair_id: int, status: str, note: str | None = None, on: date | None = None) -> Repair:
    r = get_or_404(db, Repair, repair_id, "Reparatur")
    if status not in domain.REPAIR_STATUS:
        raise ServiceError("invalid", "Ungültiger Status.")
    if status == r.status:
        return r
    if status == "cancelled" and not (note or "").strip():
        raise ServiceError("reason_required", "Für das Abbrechen ist eine Begründung erforderlich.")
    old = r.status
    r.status = status
    r.completed_on = (on or date.today()) if status == "done" else None
    _event(db, r.id, "status", f"Status: {domain.REPAIR_LABEL[old]} → {domain.REPAIR_LABEL[status]}" + (f" ({note})" if note else ""), actor_id)
    audit.record(db, "repair.status", actor_user_id=actor_id, entity_type="repair", entity_id=r.id, summary=f"Reparaturstatus: {domain.REPAIR_LABEL[old]} → {domain.REPAIR_LABEL[status]}", details={"note": note})
    db.flush()
    return r


def add_note(db: Session, actor_id: int | None, repair_id: int, text: str) -> RepairEvent:
    get_or_404(db, Repair, repair_id, "Reparatur")
    if not text.strip():
        raise ServiceError("invalid", "Text fehlt.")
    _event(db, repair_id, "note", text.strip(), actor_id)
    db.flush()
    audit.record(db, "repair.note", actor_user_id=actor_id, entity_type="repair", entity_id=repair_id, summary="Notiz zur Reparatur")
    return db.scalars(select(RepairEvent).where(RepairEvent.repair_id == repair_id).order_by(RepairEvent.id.desc())).first()


def link_invoice(db: Session, actor_id: int | None, repair_id: int, invoice_id: int) -> Invoice:
    r = get_or_404(db, Repair, repair_id, "Reparatur")
    inv = get_or_404(db, Invoice, invoice_id, "Rechnung")
    if inv.property_id != r.property_id:
        raise ServiceError("invalid", "Die Rechnung gehört zu einem anderen Objekt.")
    if inv.repair_id not in (None, r.id):
        raise ServiceError("conflict", f"Die Rechnung ist bereits Reparatur {inv.repair_id} zugeordnet.", 409)
    inv.repair_id = r.id
    _event(db, r.id, "invoice", f"Rechnung {inv.invoice_number or inv.id} ({eur(inv.amount)}) verknüpft", actor_id)
    audit.record(db, "repair.invoice_linked", actor_user_id=actor_id, entity_type="repair", entity_id=r.id, summary="Rechnung verknüpft", details={"invoice_id": inv.id})
    db.flush()
    return inv


def costs(db: Session, r: Repair) -> dict:
    """Tatsächliche Kosten = Summe der verknüpften, nicht stornierten Rechnungen (Ausgaben). Nicht von Hand überschreibbar."""
    invs = [i for i in db.scalars(select(Invoice).where(Invoice.repair_id == r.id)) if not i.voided_at]
    actual = q(sum((i.amount for i in invs), Decimal(0)))
    paid = q(sum((i.amount - pay.invoice_open(db, i) for i in invs), Decimal(0)))
    return {"estimate": r.cost_estimate, "actual": actual, "paid": paid, "open": q(actual - paid), "invoice_ids": [i.id for i in invs],
            "deviation_from_estimate": q(actual - r.cost_estimate) if r.cost_estimate is not None else None}


def view(db: Session, r: Repair, include_finance: bool = True) -> dict:
    """include_finance=False (finance:read fehlt): keine Kosten, Ereignisse der Art FINANCE_REPAIR_EVENT_KINDS (Rechnung mit Betrag) entfallen (Filter nach Ereignisart)."""
    ev = db.scalars(select(RepairEvent).where(RepairEvent.repair_id == r.id).order_by(RepairEvent.id)).all()
    tasks = db.scalars(select(Task).where(Task.repair_id == r.id).order_by(Task.id)).all()
    if not include_finance:
        return {"costs": None, "events": [e for e in ev if e.kind not in FINANCE_REPAIR_EVENT_KINDS], "tasks": tasks}
    return {"costs": costs(db, r), "events": ev, "tasks": tasks}


def is_open(r: Repair) -> bool:
    return r.status in domain.REPAIR_OPEN
