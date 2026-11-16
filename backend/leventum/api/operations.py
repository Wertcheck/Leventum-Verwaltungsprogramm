from __future__ import annotations

import io
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from leventum.api import schemas as S
from leventum.api.deps import current_user, get_db, get_settings, require
from leventum.api.finance import _store, doc_out
from leventum.api.master import js, ser
from leventum.config import Settings
from leventum.models import AppUser, Communication, Document, HandoverProtocol, Lease, Repair, Task
from leventum.security.finance_access import can_read_finance, is_finance_reminder_key, require_finance_read
from leventum.services import communications as COM, documents as DOC, history as H, reminders as REM, repairs as R, tasks as T
from leventum.services.errors import ServiceError
from leventum.services.master import get_or_404

router = APIRouter()
TR, TW = Depends(require("task:read")), Depends(require("task:write"))
RR, RW = Depends(require("repair:read")), Depends(require("repair:write"))
DR, DW = Depends(require("document:read")), Depends(require("document:write"))
MR = Depends(require("master:read"))


def _dump(m, **kw):
    return m.model_dump(**kw)


# --- Aufgaben ---------------------------------------------------------------------------------------------------------------------
def task_out(t: Task, db: Session | None = None) -> dict:
    o = {**ser(t), "overdue": T.is_overdue(t)}
    if db is not None:  # sprechende Bezüge statt nur IDs
        from leventum.models import Party, Property
        from leventum.services.master import lease_title
        if t.lease_id:
            o["lease_label"] = lease_title(db, db.get(Lease, t.lease_id))
        if t.party_id:
            o["party_label"] = db.get(Party, t.party_id).display_name
        if t.property_id:
            o["property_label"] = db.get(Property, t.property_id).name
        if t.repair_id:
            o["repair_label"] = db.get(Repair, t.repair_id).title
    return o


@router.get("/tasks", dependencies=[TR])
def tasks_list(status: str | None = None, priority: str | None = None, assignee_user_id: int | None = None, overdue: bool = False, open_only: bool = False,
               q: str | None = None, party_id: int | None = None, property_id: int | None = None, unit_id: int | None = None, lease_id: int | None = None,
               invoice_id: int | None = None, repair_id: int | None = None, db: Session = Depends(get_db)):
    rows = T.query(db, status=status, priority=priority, assignee_user_id=assignee_user_id, overdue=overdue, open_only=open_only, q=q, party_id=party_id,
                   property_id=property_id, unit_id=unit_id, lease_id=lease_id, invoice_id=invoice_id, repair_id=repair_id)
    return {"items": [task_out(t, db) for t in rows]}


@router.post("/tasks", dependencies=[TW], status_code=201)
def tasks_create(body: S.TaskIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    t = T.create_task(db, user.id, **_dump(body))
    db.commit()
    return task_out(t)


@router.get("/tasks/{tid}", dependencies=[TR])
def tasks_get(tid: int, db: Session = Depends(get_db)):
    return task_out(get_or_404(db, Task, tid, "Aufgabe"))


@router.patch("/tasks/{tid}", dependencies=[TW])
def tasks_patch(tid: int, body: S.TaskPatch, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    t = T.update_task(db, user.id, tid, _dump(body, exclude_unset=True))
    db.commit()
    return task_out(t)


@router.post("/tasks/{tid}/status", dependencies=[TW])
def tasks_status(tid: int, body: S.TaskStatusIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    t = T.set_status(db, user.id, tid, body.status, body.note)
    db.commit()
    return task_out(t)


# --- Erinnerungen -------------------------------------------------------------------------------------------------------------------
@router.get("/reminders", dependencies=[Depends(require("dashboard:read"))])
def reminders(db: Session = Depends(get_db), settings: Settings = Depends(get_settings), user: AppUser = Depends(current_user)):
    # Ohne finance:read entfallen die Finanz-Hinweise (FINANCE_REMINDER_TYPES); sie werden gar nicht erst berechnet.
    items = REM.compute(db, preview_days=settings.contract_end_preview_days, include_finance=can_read_finance(user))
    return {"items": js(items), "note": "Berechnet aus den aktuellen Daten. Fristen sind rechnerische Hinweise, keine Rechtsauskunft."}


@router.post("/reminders/task", dependencies=[TW], status_code=201)
def reminder_to_task(body: S.ReminderTaskIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user), settings: Settings = Depends(get_settings)):
    can_fin = can_read_finance(user)
    if not can_fin and is_finance_reminder_key(body.key):
        require_finance_read(user)  # 403 schon anhand des Schlüsselpräfixes: keine Aussage, ob die Erinnerung existiert; keine Aufgabe
    rem = next((r for r in REM.compute(db, preview_days=settings.contract_end_preview_days, include_finance=can_fin) if r["key"] == body.key), None)
    if rem is None:
        raise ServiceError("not_found", "Die Erinnerung besteht nicht mehr.", 404)
    if rem["task_id"]:
        raise ServiceError("exists", f"Zu dieser Erinnerung existiert bereits Aufgabe #{rem['task_id']}.", 409, {"task_id": rem["task_id"]})
    links = {}
    if rem["entity_type"] == "lease":
        links["lease_id"] = rem["entity_id"]
    elif rem["entity_type"] == "repair":
        links["repair_id"] = rem["entity_id"]
    elif rem["entity_type"] == "deposit":
        from leventum.models import Deposit
        links["lease_id"] = get_or_404(db, Deposit, rem["entity_id"], "Kaution").lease_id
    t = T.create_task(db, user.id, title=rem["title"][:200], description=rem["detail"], due_date=body.due_date or rem["due_date"],
                      priority="high" if rem["severity"] == "critical" else "normal", **links)
    t.source, t.dedupe_key = "reminder", rem["key"]
    db.commit()
    return task_out(t)


# --- Reparaturen -----------------------------------------------------------------------------------------------------------------------
def repair_out(db: Session, r: Repair, full: bool = False) -> dict:
    c = R.costs(db, r)
    o = {**ser(r), "costs": js(c), "is_open": R.is_open(r)}
    if full:
        v = R.view(db, r)
        o["events"] = [ser(e) for e in v["events"]]
        o["tasks"] = [task_out(t, db) for t in v["tasks"]]
        o["documents"] = [doc_out(d) for d in DOC.for_entity(db, "repair", r.id)]
    return o


@router.get("/repairs", dependencies=[RR])
def repairs_list(status: str | None = None, open_only: bool = False, property_id: int | None = None, unit_id: int | None = None, priority: str | None = None,
                 db: Session = Depends(get_db)):
    stmt = select(Repair).order_by(Repair.reported_on.desc(), Repair.id.desc())
    if status:
        stmt = stmt.where(Repair.status == status)
    if open_only:
        from leventum import domain
        stmt = stmt.where(Repair.status.in_(domain.REPAIR_OPEN))
    if property_id:
        stmt = stmt.where(Repair.property_id == property_id)
    if unit_id:
        stmt = stmt.where(Repair.unit_id == unit_id)
    if priority:
        stmt = stmt.where(Repair.priority == priority)
    return {"items": [repair_out(db, r) for r in db.scalars(stmt.limit(500))]}


@router.post("/repairs", dependencies=[RW], status_code=201)
def repairs_create(body: S.RepairIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    r = R.create_repair(db, user.id, **_dump(body))
    db.commit()
    return repair_out(db, r, True)


@router.get("/repairs/{rid}", dependencies=[RR])
def repairs_get(rid: int, db: Session = Depends(get_db)):
    return repair_out(db, get_or_404(db, Repair, rid, "Reparatur"), True)


@router.patch("/repairs/{rid}", dependencies=[RW])
def repairs_patch(rid: int, body: S.RepairPatch, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    r = R.update_repair(db, user.id, rid, _dump(body, exclude_unset=True))
    db.commit()
    return repair_out(db, r, True)


@router.post("/repairs/{rid}/status", dependencies=[RW])
def repairs_status(rid: int, body: S.RepairStatusIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    r = R.set_status(db, user.id, rid, body.status, body.note, body.on)
    db.commit()
    return repair_out(db, r, True)


@router.post("/repairs/{rid}/notes", dependencies=[RW], status_code=201)
def repairs_note(rid: int, body: S.NoteTextIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    R.add_note(db, user.id, rid, body.text)
    db.commit()
    return repair_out(db, get_or_404(db, Repair, rid, "Reparatur"), True)


@router.post("/repairs/{rid}/invoices", dependencies=[RW])
def repairs_link_invoice(rid: int, body: S.InvoiceLinkIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    R.link_invoice(db, user.id, rid, body.invoice_id)
    db.commit()
    return repair_out(db, get_or_404(db, Repair, rid, "Reparatur"), True)


# --- Kommunikation / Übergabeprotokolle -------------------------------------------------------------------------------------------------------
@router.get("/communications", dependencies=[TR])
def comm_list(party_id: int | None = None, lease_id: int | None = None, property_id: int | None = None, unit_id: int | None = None, repair_id: int | None = None,
              channel: str | None = None, db: Session = Depends(get_db)):
    rows = COM.query(db, party_id=party_id, lease_id=lease_id, property_id=property_id, unit_id=unit_id, repair_id=repair_id, channel=channel)
    return {"items": [ser(c) for c in rows[:500]]}


@router.post("/communications", dependencies=[TW], status_code=201)
def comm_create(body: S.CommunicationIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    d = _dump(body, exclude={"follow_up"})
    c = COM.create(db, user.id, follow_up=body.follow_up.model_dump() if body.follow_up else None, **d)
    db.commit()
    return ser(c)


@router.get("/handover-protocols", dependencies=[MR])
def handover_list(lease_id: int, db: Session = Depends(get_db)):
    return {"items": [ser(h) for h in db.scalars(select(HandoverProtocol).where(HandoverProtocol.lease_id == lease_id).order_by(HandoverProtocol.protocol_date))]}


@router.post("/handover-protocols", dependencies=[Depends(require("master:write"))], status_code=201)
def handover_create(body: S.HandoverIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    h = COM.create_handover(db, user.id, **_dump(body))
    db.commit()
    return ser(h)


# --- Historie ---------------------------------------------------------------------------------------------------------------------------------
@router.get("/history", dependencies=[MR])
def history(entity_type: str, entity_id: int, limit: int = Query(200, le=500), db: Session = Depends(get_db)):
    if entity_type not in ("party", "lease", "property", "unit", "repair", "task", "deposit", "invoice"):
        raise ServiceError("invalid", "Ungültiger Typ.")
    return {"items": js(H.entity_timeline(db, entity_type, entity_id, limit))}


# --- Dokumente (vollständige Verwaltung) -------------------------------------------------------------------------------------------------------
@router.get("/documents/search", dependencies=[DR])
def documents_search(q: str | None = None, doc_type: str | None = None, entity_type: str | None = None, entity_id: int | None = None, include_deleted: bool = False,
                     db: Session = Depends(get_db)):
    return {"items": [{**doc_out(d), "deleted_at": js(d.deleted_at), "delete_reason": d.delete_reason} for d in
                      DOC.query(db, q=q, doc_type=doc_type, entity_type=entity_type, entity_id=entity_id, include_deleted=include_deleted)]}


@router.post("/documents/{did}/links", dependencies=[DW])
def documents_link(did: int, body: S.DocLinkIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    d = DOC.add_link(db, user.id, did, body.entity_type, body.entity_id)
    db.commit()
    return doc_out(d)


@router.post("/documents/{did}/delete", dependencies=[DW])
def documents_delete(did: int, body: S.VoidIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    d = DOC.soft_delete(db, user.id, did, body.reason)
    db.commit()
    return {**doc_out(d), "deleted_at": js(d.deleted_at)}


@router.get("/leases/{lid}/missing-documents", dependencies=[MR])
def lease_missing_docs(lid: int, db: Session = Depends(get_db)):
    return {"missing": DOC.missing_for_lease(db, get_or_404(db, Lease, lid, "Vertrag")), "note": "Pflichtliste ist eine organisatorische Annahme, keine Rechtsaussage."}


# --- Dokument-Integrität / endgültige Entfernung / Datenintegrität -------------------------------------------------------------------------------
@router.get("/documents/verify-all", dependencies=[Depends(require("system:backup"))])
def documents_verify_all(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    problems = DOC.verify_all(db, _store(settings))
    return {"ok": not problems, "problems": problems}


@router.get("/documents/{did}/verify", dependencies=[DR])
def documents_verify(did: int, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return DOC.verify(_store(settings), get_or_404(db, Document, did, "Dokument"))


class PurgeIn(S.In):
    reason: str = S.Field(min_length=1)
    confirm: bool


@router.post("/documents/{did}/purge", dependencies=[Depends(require("document:purge"))])
def documents_purge(did: int, body: PurgeIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user), settings: Settings = Depends(get_settings)):
    if not body.confirm:
        raise ServiceError("confirmation_required", "Bestätigung erforderlich: Die Datei wird unwiderruflich entfernt.")
    d = DOC.purge(db, _store(settings), user.id, did, body.reason, settings.document_retention_days)
    db.commit()
    return {**doc_out(d), "purged_at": js(d.purged_at)}


@router.get("/system/integrity", dependencies=[Depends(require("system:backup"))])
def system_integrity(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    from leventum.services import integrity
    r = integrity.check(db)
    docs = DOC.verify_all(db, _store(settings))
    return {**r, "documents": {"ok": not docs, "problems": docs}, "ok": r["ok"] and not docs}
