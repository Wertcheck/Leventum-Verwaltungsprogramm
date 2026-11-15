from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from leventum import domain
from leventum.models import AppUser, Invoice, Lease, Party, Property, Repair, Task, Unit
from leventum.services import audit
from leventum.services.errors import ServiceError
from leventum.services.master import get_or_404

LINKS = {"party_id": (Party, "Partei"), "property_id": (Property, "Objekt"), "unit_id": (Unit, "Wohneinheit"), "lease_id": (Lease, "Vertrag"),
         "invoice_id": (Invoice, "Rechnung"), "repair_id": (Repair, "Reparatur")}


def _validate(db: Session, data: dict):
    for k, (model, label) in LINKS.items():
        if data.get(k) is not None:
            get_or_404(db, model, data[k], label)
    if data.get("assignee_user_id") is not None and db.get(AppUser, data["assignee_user_id"]) is None:
        raise ServiceError("not_found", "Verantwortlicher nicht gefunden.", 404)
    if "priority" in data and data["priority"] not in domain.PRIORITIES:
        raise ServiceError("invalid", "Ungültige Priorität.")


def create_task(db: Session, actor_id: int | None, *, title: str, **data) -> Task:
    if not title.strip():
        raise ServiceError("invalid", "Titel fehlt.")
    _validate(db, data)
    t = Task(title=title.strip(), created_by_user_id=actor_id, **data)
    db.add(t)
    db.flush()
    audit.record(db, "task.created", actor_user_id=actor_id, entity_type="task", entity_id=t.id, summary=f"Aufgabe erstellt: {t.title}",
                 details={k: v for k, v in data.items() if k in LINKS and v is not None})
    return t


def update_task(db: Session, actor_id: int | None, task_id: int, data: dict) -> Task:
    t = get_or_404(db, Task, task_id, "Aufgabe")
    if "status" in data or "dedupe_key" in data or "source" in data:
        raise ServiceError("invalid", "Status nur über den Statuswechsel ändern.")
    if "title" in data and not data["title"].strip():
        raise ServiceError("invalid", "Titel fehlt.")
    _validate(db, data)
    for k, v in data.items():
        setattr(t, k, v)
    audit.record(db, "task.updated", actor_user_id=actor_id, entity_type="task", entity_id=t.id, summary="Aufgabe geändert", details={"fields": sorted(data)})
    db.flush()
    return t


def set_status(db: Session, actor_id: int | None, task_id: int, status: str, note: str | None = None) -> Task:
    t = get_or_404(db, Task, task_id, "Aufgabe")
    if status not in domain.TASK_STATUS:
        raise ServiceError("invalid", "Ungültiger Status.")
    if status == t.status:
        return t
    if status == "cancelled" and not (note or "").strip():
        raise ServiceError("reason_required", "Für das Abbrechen ist eine Begründung erforderlich.")
    old = t.status
    t.status = status
    t.completed_at = datetime.now(timezone.utc) if status in ("done", "cancelled") else None
    audit.record(db, "task.status", actor_user_id=actor_id, entity_type="task", entity_id=t.id, summary=f"Aufgabenstatus: {domain.TASK_LABEL[old]} → {domain.TASK_LABEL[status]}",
                 details={"from": old, "to": status, "note": note})
    db.flush()
    return t


def is_overdue(t: Task, today: date | None = None) -> bool:
    return t.status in domain.TASK_OPEN and t.due_date is not None and t.due_date < (today or date.today())


def query(db: Session, *, status: str | None = None, priority: str | None = None, assignee_user_id: int | None = None, overdue: bool = False,
          open_only: bool = False, q: str | None = None, today: date | None = None, **links) -> list[Task]:
    stmt = select(Task).order_by(Task.due_date.is_(None), Task.due_date, Task.id.desc())
    if status:
        stmt = stmt.where(Task.status == status)
    if open_only:
        stmt = stmt.where(Task.status.in_(domain.TASK_OPEN))
    if priority:
        stmt = stmt.where(Task.priority == priority)
    if assignee_user_id:
        stmt = stmt.where(Task.assignee_user_id == assignee_user_id)
    for k, v in links.items():
        if v is not None:
            stmt = stmt.where(getattr(Task, k) == v)
    if q:
        stmt = stmt.where(Task.title.ilike(f"%{q}%"))
    rows = list(db.scalars(stmt))
    return [t for t in rows if is_overdue(t, today)] if overdue else rows
