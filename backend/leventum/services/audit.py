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


SENSITIVE = {"iban", "birth_date", "notes", "email", "phone"}


def diff(obj, data: dict) -> dict:
    """Vorher/Nachher der tatsächlich geänderten Felder. Sensible personenbezogene Felder werden nur als „geändert“ vermerkt (kein Klartext im Protokoll)."""
    out = {}
    for k, new in data.items():
        old = getattr(obj, k, None)
        if old == new:
            continue
        if k in SENSITIVE:
            out[k] = ["(geändert)", "(geändert)"]
        else:
            fmt = lambda v: None if v is None else str(v)[:200]
            out[k] = [fmt(old), fmt(new)]
    return out
