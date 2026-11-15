from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session

from leventum import domain
from leventum.api import schemas as S
from leventum.api.deps import current_user, get_db, require
from leventum.models import (AuditEvent, Bed, CostType, Lease, LeaseNote, LeaseType, Party, PartyRole, Property, RentableUnit,
                             Room, Unit, UtilityStatement, UtilityStatementUnit)
from leventum.models import AppUser
from leventum.services import charges as C, leases as L, master as M, utility as U
from leventum.services.errors import NotFound


def ser(obj, *extra_skip) -> dict:
    """ORM-Zeile → JSON-sicheres dict. Geld/Flächen als String-Dezimal, Datum ISO."""
    out = {}
    for c in inspect(obj).mapper.column_attrs:
        v = getattr(obj, c.key)
        out[c.key] = js(v)
    return out


def js(v):
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): js(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [js(x) for x in v]
    return v


router = APIRouter()
R = Depends(require("master:read"))
W = Depends(require("master:write"))


def _dump(m, **kw):
    return m.model_dump(exclude_unset=kw.pop("exclude_unset", False), **kw)


# --- Parteien --------------------------------------------------------------------------------------------
def party_out(p: Party) -> dict:
    return {**ser(p), "roles": sorted(r.role for r in p.roles)}


@router.get("/parties", dependencies=[R])
def parties_list(role: str | None = None, q: str | None = None, active: bool | None = None, limit: int = Query(200, le=1000),
                 offset: int = 0, db: Session = Depends(get_db)):
    stmt = select(Party).order_by(Party.display_name)
    if role:
        stmt = stmt.join(PartyRole).where(PartyRole.role == role)
    if q:
        stmt = stmt.where(func.lower(Party.display_name).like(f"%{q.lower()}%"))
    if active is not None:
        stmt = stmt.where(Party.is_active == active)
    return {"items": [party_out(p) for p in db.scalars(stmt.limit(limit).offset(offset))]}


@router.post("/parties", dependencies=[W], status_code=201)
def parties_create(body: S.PartyIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    data = _dump(body, exclude={"roles"})
    p = M.create_party(db, user.id, data, body.roles)
    db.commit()
    return party_out(p)


@router.get("/parties/{party_id}", dependencies=[R])
def parties_get(party_id: int, db: Session = Depends(get_db)):
    p = M.get_or_404(db, Party, party_id, "Partei")
    leases = db.scalars(select(Lease).join(L.LeaseParty).where(L.LeaseParty.party_id == p.id).order_by(Lease.start_date.desc())).all()
    history = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "party", AuditEvent.entity_id == str(p.id))
                         .order_by(AuditEvent.occurred_at.desc()).limit(50)).all()
    return {**party_out(p), "leases": [lease_brief(db, x) for x in leases],
            "history": [{"at": js(h.occurred_at), "action": h.action, "summary": h.summary} for h in history]}


@router.patch("/parties/{party_id}", dependencies=[W])
def parties_patch(party_id: int, body: S.PartyPatch, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    data = _dump(body, exclude_unset=True, exclude={"roles"})
    p = M.update_party(db, user.id, party_id, data, body.roles)
    db.commit()
    return party_out(p)


# --- Objekte / Raumhierarchie ----------------------------------------------------------------------------------
@router.get("/properties", dependencies=[R])
def properties_list(q: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Property).order_by(Property.name)
    if q:
        stmt = stmt.where(or_(func.lower(Property.name).like(f"%{q.lower()}%"), func.lower(Property.city).like(f"%{q.lower()}%")))
    out = []
    for p in db.scalars(stmt):
        n = db.scalar(select(func.count()).select_from(Unit).where(Unit.property_id == p.id))
        owner = db.get(Party, p.owner_party_id) if p.owner_party_id else None
        out.append({**ser(p), "unit_count": n, "owner_name": owner.display_name if owner else None})
    return {"items": out}


@router.post("/properties", dependencies=[W], status_code=201)
def properties_create(body: S.PropertyIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    p = M.create_property(db, user.id, _dump(body))
    db.commit()
    return ser(p)


@router.get("/properties/{property_id}", dependencies=[R])
def properties_get(property_id: int, db: Session = Depends(get_db)):
    p = M.get_or_404(db, Property, property_id, "Objekt")
    tree = []
    for u in db.scalars(select(Unit).where(Unit.property_id == p.id).order_by(Unit.unit_number)):
        rooms = []
        for r in db.scalars(select(Room).where(Room.unit_id == u.id).order_by(Room.name)):
            rooms.append({**ser(r), "beds": [ser(b) for b in db.scalars(select(Bed).where(Bed.room_id == r.id).order_by(Bed.label))]})
        tree.append({**ser(u), "rooms": rooms})
    rus = [{**ser(r), "label": M.space_label(db, r)} for r in db.scalars(select(RentableUnit).where(RentableUnit.property_id == p.id))]
    n_rooms = sum(len(u["rooms"]) for u in tree)
    n_beds = sum(len(r["beds"]) for u in tree for r in u["rooms"])
    made = {lvl: sum(1 for r in rus if r["level"] == lvl) for lvl in ("property", "unit", "room", "bed")}
    # Zusammenfassung: vorhandene Einheiten vs. als Vermietungseinheit angelegte (ein Zimmer ist ein Raum; erst die Vermietungseinheit macht es vermietbar)
    summary = {"units": len(tree), "rooms": n_rooms, "beds": n_beds,
               "rentable": {"property": {"created": made["property"], "possible": 1}, "unit": {"created": made["unit"], "possible": len(tree)},
                            "room": {"created": made["room"], "possible": n_rooms}, "bed": {"created": made["bed"], "possible": n_beds}}}
    return {**ser(p), "units": tree, "rentable_units": rus, "summary": summary}


@router.patch("/properties/{property_id}", dependencies=[W])
def properties_patch(property_id: int, body: S.PropertyPatch, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    p = M.update_property(db, user.id, property_id, _dump(body, exclude_unset=True))
    db.commit()
    return ser(p)


@router.post("/properties/{property_id}/units", dependencies=[W], status_code=201)
def units_create(property_id: int, body: S.UnitIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    u = M.create_unit(db, user.id, property_id, _dump(body))
    db.commit()
    return ser(u)


@router.get("/units", dependencies=[R])
def units_list(property_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(Unit).order_by(Unit.property_id, Unit.unit_number)
    if property_id:
        stmt = stmt.where(Unit.property_id == property_id)
    today = date.today()
    out = []
    for u in db.scalars(stmt):
        ru = db.scalar(select(RentableUnit).where(RentableUnit.unit_id == u.id, RentableUnit.level == "unit"))
        probe = ru or RentableUnit(level="unit", property_id=u.property_id, unit_id=u.id)
        occ = L.occupancy_on(db, probe, today)
        # Belegung auch über Zimmer/Betten: Raum-/Bett-Einheiten der Wohneinheit prüfen
        for sub in db.scalars(select(RentableUnit).where(RentableUnit.unit_id == u.id)):
            for lease in L.occupancy_on(db, sub, today):
                if lease not in occ:
                    occ.append(lease)
        status = u.manual_status or ("occupied" if occ else "vacant")
        out.append({**ser(u), "occupancy_status": status, "active_sublease_ids": [x.id for x in occ]})
    return {"items": out}


@router.patch("/units/{unit_id}", dependencies=[W])
def units_patch(unit_id: int, body: S.UnitPatch, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    data = _dump(body, exclude_unset=True)
    area_changed = "living_area" in data and M.get_or_404(db, Unit, unit_id, "Wohneinheit").living_area != data["living_area"]
    u = M.update_unit(db, user.id, unit_id, data)
    warnings = []
    if area_changed:
        n = db.scalar(select(func.count()).select_from(UtilityStatement).join(UtilityStatementUnit, UtilityStatementUnit.statement_id == UtilityStatement.id)
                      .where(UtilityStatementUnit.unit_id == unit_id, UtilityStatement.status == "reviewed"))
        warnings.append({"code": "area_changed", "message": "Die Fläche beeinflusst künftige Verteilungen (Nebenkosten, Hauptmiete, Auswertungen)."
                         + (f" {n} bereits geprüfte Abrechnung(en) bleiben unverändert (eingefrorene Verteilung)." if n else "")})
    db.commit()
    return {**ser(u), "warnings": warnings}


@router.patch("/rooms/{room_id}", dependencies=[W])
def rooms_patch(room_id: int, body: S.RoomPatch, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    r = M.update_room(db, user.id, room_id, _dump(body, exclude_unset=True))
    db.commit()
    return ser(r)


@router.patch("/beds/{bed_id}", dependencies=[W])
def beds_patch(bed_id: int, body: S.BedPatch, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    b = M.update_bed(db, user.id, bed_id, _dump(body, exclude_unset=True))
    db.commit()
    return ser(b)


@router.post("/units/{unit_id}/rooms", dependencies=[W], status_code=201)
def rooms_create(unit_id: int, body: S.RoomIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    r = M.create_room(db, user.id, unit_id, _dump(body))
    db.commit()
    return ser(r)


@router.post("/rooms/{room_id}/beds", dependencies=[W], status_code=201)
def beds_create(room_id: int, body: S.BedIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    b = M.create_bed(db, user.id, room_id, _dump(body))
    db.commit()
    return ser(b)


@router.post("/rentable-units", dependencies=[W], status_code=201)
def rentable_create(body: S.RentableIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    ru = M.ensure_rentable_unit(db, user.id, **_dump(body))
    db.commit()
    return {**ser(ru), "label": M.space_label(db, ru)}


@router.get("/rentable-units", dependencies=[R])
def rentable_list(property_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(RentableUnit)
    if property_id:
        stmt = stmt.where(RentableUnit.property_id == property_id)
    return {"items": [{**ser(r), "label": M.space_label(db, r)} for r in db.scalars(stmt)]}


# --- Verträge ----------------------------------------------------------------------------------------------------
@router.get("/lease-types", dependencies=[R])
def lease_types(db: Session = Depends(get_db)):
    return {"items": [ser(t) for t in db.scalars(select(LeaseType).where(LeaseType.is_active.is_(True)).order_by(LeaseType.id))],
            "legal_reference_suggestions": domain.LEGAL_REF_SUGGESTIONS,
            "legal_notice": "Vorschlagsliste nur zur Dokumentation. Die Software ordnet Verträge nicht rechtlich ein."}


@router.get("/cost-types", dependencies=[R])
def cost_types(db: Session = Depends(get_db)):
    return {"items": [ser(c) for c in db.scalars(select(CostType).order_by(CostType.name))]}


def lease_brief(db: Session, lease: Lease) -> dict:
    return {"id": lease.id, "kind": lease.kind, "status": lease.status, "type": lease.lease_type.name,
            "start_date": js(lease.start_date), "end_date": js(L.effective_end(lease)),
            "spaces": [M.space_label(db, i.rentable_unit) for i in lease.items],
            "parties": [{"party_id": p.party_id, "name": p.party.display_name, "role": p.role} for p in lease.parties]}


def lease_detail(db: Session, lease: Lease) -> dict:
    today = date.today()
    ref = today if lease.start_date <= today else lease.start_date
    return {**ser(lease), **lease_brief(db, lease),
            "items": [{"rentable_unit_id": i.rentable_unit_id, "label": M.space_label(db, i.rentable_unit), "level": i.rentable_unit.level} for i in lease.items],
            "terms": [ser(t) for t in lease.terms], "utility_agreements": [ser(a) for a in lease.utility_agreements],
            "notes": [ser(n) for n in db.scalars(select(LeaseNote).where(LeaseNote.lease_id == lease.id).order_by(LeaseNote.id))],
            "monthly_total": js(L.monthly_total(lease, ref)), "validation": js(L.validate_lease(db, lease).as_dict())
            if lease.status in ("draft", "active", "terminated") else None}


@router.get("/leases", dependencies=[R])
def leases_list(kind: str | None = None, status: str | None = None, party_id: int | None = None, property_id: int | None = None,
                db: Session = Depends(get_db)):
    stmt = select(Lease).order_by(Lease.start_date.desc())
    if kind:
        stmt = stmt.where(Lease.kind == kind)
    if status:
        stmt = stmt.where(Lease.status == status)
    if party_id:
        stmt = stmt.where(Lease.id.in_(select(L.LeaseParty.lease_id).where(L.LeaseParty.party_id == party_id)))
    if property_id:
        stmt = stmt.where(Lease.id.in_(select(L.LeaseItem.lease_id).join(RentableUnit).where(RentableUnit.property_id == property_id)))
    return {"items": [lease_brief(db, x) for x in db.scalars(stmt)]}


@router.post("/leases", dependencies=[W], status_code=201)
def leases_create(body: S.LeaseIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    d = _dump(body, exclude={"parties", "rentable_unit_ids"})
    lease = L.create_lease(db, user.id, parties=[p.model_dump() for p in body.parties],
                           rentable_unit_ids=body.rentable_unit_ids, **d)
    db.commit()
    return lease_detail(db, lease)


@router.get("/leases/{lease_id}", dependencies=[R])
def leases_get(lease_id: int, db: Session = Depends(get_db)):
    return lease_detail(db, M.get_or_404(db, Lease, lease_id, "Vertrag"))


@router.patch("/leases/{lease_id}", dependencies=[W])
def leases_patch(lease_id: int, body: S.LeasePatch, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    lease = L.update_lease(db, user.id, lease_id, _dump(body, exclude_unset=True))
    impact = getattr(lease, "_impact", [])
    db.commit()
    out = lease_detail(db, lease)
    if impact:
        out["impact"] = {"charges_outside_period": impact, "message": f"{len(impact)} bereits erzeugte Sollstellung(en) liegen außerhalb der neuen Laufzeit. Sie wurden NICHT verändert und müssen bei Bedarf einzeln storniert werden."}
    return out


@router.get("/leases/{lease_id}/validation", dependencies=[R])
def leases_validation(lease_id: int, db: Session = Depends(get_db)):
    return js(L.validate_lease(db, M.get_or_404(db, Lease, lease_id, "Vertrag")).as_dict())


@router.post("/leases/{lease_id}/terms", dependencies=[W], status_code=201)
def leases_term(lease_id: int, body: S.TermIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    t = L.add_term(db, user.id, lease_id, **_dump(body))
    db.commit()
    return ser(t)


@router.post("/leases/{lease_id}/utility-agreements", dependencies=[W], status_code=201)
def leases_utility(lease_id: int, body: S.UtilityAgreementIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    a = L.add_utility_agreement(db, user.id, lease_id, **_dump(body))
    db.commit()
    return ser(a)


@router.post("/leases/{lease_id}/notes", dependencies=[W], status_code=201)
def leases_note(lease_id: int, body: S.NoteIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    n = L.add_note(db, user.id, lease_id, body.kind, body.text)
    db.commit()
    return ser(n)


@router.post("/leases/{lease_id}/legal-review", dependencies=[W])
def leases_legal(lease_id: int, body: S.LegalReviewIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    lease = L.set_legal_review(db, user.id, lease_id, body.status, basis_ref=body.basis_ref, basis_note=body.basis_note)
    db.commit()
    return lease_detail(db, lease)


@router.post("/leases/{lease_id}/activate", dependencies=[W])
def leases_activate(lease_id: int, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    try:
        lease, v = L.activate_lease(db, user.id, lease_id)
    except L.ServiceError:
        db.rollback()
        raise
    db.commit()
    return {**lease_detail(db, lease), "activation_warnings": js(v.as_dict())}


@router.post("/leases/{lease_id}/terminate", dependencies=[W])
def leases_terminate(lease_id: int, body: S.TerminateIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    lease = L.terminate_lease(db, user.id, lease_id, terminated_on=body.terminated_on, effective_on=body.effective_on)
    db.commit()
    return lease_detail(db, lease)


@router.post("/leases/{lease_id}/cancel", dependencies=[W])
def leases_cancel(lease_id: int, body: S.CancelIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    lease = L.cancel_lease(db, user.id, lease_id, body.reason)
    db.commit()
    return lease_detail(db, lease)


# --- Mieterübersicht ---------------------------------------------------------------------------------------------------
@router.get("/tenants", dependencies=[R])
def tenants(status: str | None = None, property_id: int | None = None, q: str | None = None, limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
            db: Session = Depends(get_db)):
    """Eine Zeile je Mieter und Untermietvertrag (gebündelte Abfragen, paginiert). Phase = zeitbezogener Vertragszustand (upcoming|active|notice|ended|draft);
    Zahlungsstatus: arrears = überfällige, offene Forderungen nach Teilzahlungen."""
    from sqlalchemy.orm import selectinload
    today = date.today()
    stmt = select(Party).join(PartyRole).where(PartyRole.role == "tenant").order_by(Party.display_name)
    if q:
        stmt = stmt.where(func.lower(Party.display_name).like(f"%{q.lower()}%"))
    parties = list(db.scalars(stmt))
    pids = [p.id for p in parties]
    by_party: dict[int, list[Lease]] = {i: [] for i in pids}
    if pids:
        rows = db.execute(select(L.LeaseParty.party_id, Lease).join(Lease, Lease.id == L.LeaseParty.lease_id).where(
            L.LeaseParty.party_id.in_(pids), L.LeaseParty.role.in_(("lessee", "co_lessee")), Lease.kind == "sub", Lease.status != "cancelled")
            .options(selectinload(Lease.items).joinedload(L.LeaseItem.rentable_unit), selectinload(Lease.terms), selectinload(Lease.utility_agreements))).all()
        for pid, lease in rows:
            by_party[pid].append(lease)
    arrears = C.arrears_bulk(db, [l.id for ls in by_party.values() for l in ls], today)
    last = dict(db.execute(select(AuditEvent.entity_id, func.max(AuditEvent.occurred_at)).where(AuditEvent.entity_type == "party").group_by(AuditEvent.entity_id)).all()) if pids else {}
    out = []
    for p in parties:
        last_act = js(last.get(str(p.id)))
        leases = by_party[p.id]
        if not leases:
            if status is None and property_id is None:
                out.append({"party_id": p.id, "name": p.display_name, "lease_id": None, "lease_status": "no_lease", "last_activity": last_act})
            continue
        for lease in leases:
            ar = arrears[lease.id]
            ph = L.phase(lease, today)
            if status == "arrears" and ar["status"] != "arrears":
                continue
            if status and status != "arrears" and ph != {"terminated": "notice"}.get(status, status):
                continue
            if property_id and property_id not in {i.rentable_unit.property_id for i in lease.items}:
                continue
            out.append({"party_id": p.id, "name": p.display_name, "lease_id": lease.id, "lease_status": ph, "lease_raw_status": lease.status,
                        "spaces": [M.space_label(db, i.rentable_unit) for i in lease.items], "start_date": js(lease.start_date), "end_date": js(L.effective_end(lease)),
                        "monthly_total": js(L.monthly_total(lease, max(today, lease.start_date))), "payment_status": ar["status"], "overdue_amount": js(ar["amount"]), "last_activity": last_act})
    return {"items": out[offset:offset + limit], "total": len(out), "limit": limit, "offset": offset}


@router.get("/tenants/{party_id}/overview", dependencies=[R])
def tenant_overview(party_id: int, db: Session = Depends(get_db)):
    from leventum.services import tenant_overview as TO
    o = TO.overview(db, party_id)
    doc = lambda d: {"id": d.id, "original_name": d.original_name, "doc_type": d.doc_type, "size": d.size, "uploaded_at": d.uploaded_at}
    return js({"party": party_out(o["party"]), "leases": o["leases"], "finance": o["finance"], "documents": [doc(d) for d in o["documents"]],
               "tasks": [{"id": t.id, "title": t.title, "status": t.status, "priority": t.priority, "due_date": t.due_date, "lease_id": t.lease_id} for t in o["tasks"]],
               "repairs": [{"id": r.id, "title": r.title, "status": r.status, "priority": r.priority, "reported_on": r.reported_on} for r in o["repairs"]],
               "activity": [{"at": a["at"], "summary": a["summary"], "actor": a["actor"], "source": a["source"]} for a in o["activity"]]})


# --- Nebenkosten (Ebene A + Vergleich) ---------------------------------------------------------------------------------------
def statement_out(st: UtilityStatement) -> dict:
    return {**ser(st), "unit_ids": [u.unit_id for u in st.units],
            "lines": [{**ser(l), "cost_type": l.cost_type.name, "weights": {str(w.unit_id): js(w.weight) for w in l.weights}} for l in st.lines]}


@router.get("/utility-statements", dependencies=[Depends(require("finance:read"))])
def statements_list(property_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(UtilityStatement).order_by(UtilityStatement.period_start.desc())
    if property_id:
        stmt = stmt.where(UtilityStatement.property_id == property_id)
    return {"items": [{**ser(s), "line_count": len(s.lines)} for s in db.scalars(stmt)]}


@router.post("/utility-statements", dependencies=[Depends(require("finance:write"))], status_code=201)
def statements_create(body: S.StatementIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    st = U.create_statement(db, user.id, **_dump(body))
    db.commit()
    return statement_out(st)


@router.get("/utility-statements/{sid}", dependencies=[Depends(require("finance:read"))])
def statements_get(sid: int, db: Session = Depends(get_db)):
    st = M.get_or_404(db, UtilityStatement, sid, "Abrechnung")
    return {**statement_out(st), "computed": js(U.compute_statement(db, sid))}


@router.post("/utility-statements/{sid}/lines", dependencies=[Depends(require("finance:write"))], status_code=201)
def statements_line(sid: int, body: S.LineIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    ln = U.add_line(db, user.id, sid, **_dump(body))
    db.commit()
    return ser(ln)


@router.put("/utility-statements/{sid}/prepayments", dependencies=[Depends(require("finance:write"))])
def statements_prepay(sid: int, body: S.PrepaymentIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    U.set_prepayments(db, user.id, sid, body.amount, body.source)
    db.commit()
    return js(U.compute_statement(db, sid))


@router.post("/utility-statements/{sid}/status", dependencies=[Depends(require("finance:write"))])
def statements_status(sid: int, body: S.StatusIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    U.set_status(db, user.id, sid, body.status)
    db.commit()
    return js(U.compute_statement(db, sid))


@router.get("/utility-statements/{sid}/allocation", dependencies=[Depends(require("finance:read"))])
def statements_alloc(sid: int, db: Session = Depends(get_db)):
    return js(U.allocate_statement(db, sid))


@router.get("/utility-statements/{sid}/comparison", dependencies=[Depends(require("finance:read"))])
def statements_compare(sid: int, db: Session = Depends(get_db)):
    return js(U.compare_with_downstream(db, sid))


# --- Globale Suche -------------------------------------------------------------------------------------------------------------
@router.get("/search", dependencies=[R])
def search(q: str = Query(min_length=2, max_length=100), db: Session = Depends(get_db)):
    like = f"%{q.lower()}%"
    res = []
    for p in db.scalars(select(Party).where(func.lower(Party.display_name).like(like)).limit(10)):
        res.append({"type": "party", "id": p.id, "title": p.display_name, "subtitle": ", ".join(sorted(r.role for r in p.roles)), "path": f"/parteien/{p.id}"})
    for p in db.scalars(select(Property).where(or_(func.lower(Property.name).like(like), func.lower(Property.street).like(like),
                                                   func.lower(Property.city).like(like))).limit(10)):
        res.append({"type": "property", "id": p.id, "title": p.name, "subtitle": f"{p.street or ''} {p.city or ''}".strip(), "path": f"/objekte/{p.id}"})
    for u in db.scalars(select(Unit).where(func.lower(Unit.unit_number).like(like)).limit(10)):
        res.append({"type": "unit", "id": u.id, "title": f"WE {u.unit_number}", "subtitle": db.get(Property, u.property_id).name, "path": f"/objekte/{u.property_id}"})
    for ln in db.scalars(select(Lease).where(or_(func.lower(Lease.contract_number).like(like),
                                                Lease.id.in_(select(L.LeaseParty.lease_id).join(Party).where(func.lower(Party.display_name).like(like))))).limit(10)):
        res.append({"type": "lease", "id": ln.id, "title": f"{'Hauptmietvertrag' if ln.kind == 'main' else 'Untermietvertrag'} {ln.contract_number or ln.id}",
                    "subtitle": ", ".join(p.party.display_name for p in ln.parties[:3]), "path": f"/vertraege/{ln.id}"})
    return {"items": res}
