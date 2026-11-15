from __future__ import annotations

from sqlalchemy.orm import Session

from leventum.models import AuditEvent


def record(db: Session, action: str, *, actor_user_id: int | None = None, entity_type: str | None = None,
           entity_id: str | int | None = None, summary: str = "", details: dict | None = None) -> AuditEvent:
    ev = AuditEvent(action=action, actor_user_id=actor_user_id, entity_type=entity_type,
                    entity_id=None if entity_id is None else str(entity_id), summary=summary, details=details)
    db.add(ev)
    db.flush()
    return ev
