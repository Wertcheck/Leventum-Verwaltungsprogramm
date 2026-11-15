from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from leventum.api import schemas as S
from leventum.api.deps import current_user, get_db, get_settings, require
from leventum.api.master import js, ser
from leventum.config import Settings
from leventum.models import (AppUser, BankAccount, BankImport, BankTransaction, Charge, Deposit, Document, DocumentLink, DunningNotice, Invoice, Lease,
                             LeaseAllocationWeight, Payment, Unit)
from leventum.services import bank as B, charges as C, deposits as D, documents as DOC, dunning as DN, economics as E, payments as P
from leventum.services.errors import ServiceError
from leventum.services import master as M
from leventum.services.master import get_or_404
from leventum.storage import LocalFileStore

router = APIRouter()
FR = Depends(require("finance:read"))
FW = Depends(require("finance:write"))
UP_LIMIT = 6 * 1024 * 1024


def _store(settings: Settings) -> LocalFileStore:
    return LocalFileStore(settings.documents_path, settings.max_upload_bytes)


def _dump(m, **kw):
    return m.model_dump(**kw)


# --- Sollstellungen --------------------------------------------------------------------------------------------------------------
def charge_out(db: Session, c: Charge) -> dict:
    return {**ser(c), "lease_label": M.lease_title(db, db.get(Lease, c.lease_id)), "open_amount": js(C.open_amount(db, c)) if not c.voided_at else None, "allocated": js(C.allocated(db, c.id)),
            "status": "voided" if c.voided_at else ("paid" if C.open_amount(db, c) <= 0 else "partial" if C.allocated(db, c.id) > 0 else "open")}


@router.get("/charges", dependencies=[FR])
def charges_list(lease_id: int | None = None, direction: str | None = None, status: str | None = None, month: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Charge).order_by(Charge.due_date.desc(), Charge.id.desc())
    if lease_id:
        stmt = stmt.where(Charge.lease_id == lease_id)
    if direction:
        stmt = stmt.where(Charge.direction == direction)
    if month:
        y, m = (int(x) for x in month.split("-"))
        stmt = stmt.where(Charge.period_start == date(y, m, 1))
    rows = [charge_out(db, c) for c in db.scalars(stmt.limit(1000))]
    if status:
        rows = [r for r in rows if r["status"] == status or (status == "overdue" and r["status"] in ("open", "partial") and r["due_date"] < date.today().isoformat())]
    return {"items": rows}


@router.post("/charges/preview", dependencies=[FR])
def charges_preview(body: S.ChargeGenerateIn, db: Session = Depends(get_db)):
    """Vorschau ohne Schreiben: was würde erzeugt, was existiert, welche Konflikte/Fehler gibt es."""
    r = C.generate_charges(db, None, from_month=body.from_month.replace(day=1), through_month=body.through_month.replace(day=1), lease_id=body.lease_id, dry_run=True)
    for x in r["would_create"]:
        x["lease_label"] = M.lease_title(db, db.get(Lease, x["lease_id"]))
    return js(r)


@router.post("/charges/generate", dependencies=[FW])
def charges_generate(body: S.ChargeGenerateIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    r = C.generate_charges(db, user.id, from_month=body.from_month.replace(day=1), through_month=body.through_month.replace(day=1), lease_id=body.lease_id,
                           forbid_backdated=not body.allow_backdated)
    db.commit()
    return js({k: v for k, v in r.items() if k != "would_create"})


@router.post("/charges", dependencies=[FW], status_code=201)
def charges_manual(body: S.ChargeManualIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    c = C.create_manual_charge(db, user.id, **_dump(body))
    db.commit()
    return charge_out(db, c)


@router.post("/charges/{cid}/void", dependencies=[FW])
def charges_void(cid: int, body: S.VoidIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    c = C.void_charge(db, user.id, cid, body.reason)
    db.commit()
    return charge_out(db, c)


# --- Zahlungen ----------------------------------------------------------------------------------------------------------------------
@router.get("/payments", dependencies=[FR])
def payments_list(direction: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Payment).order_by(Payment.booking_date.desc(), Payment.id.desc())
    if direction:
        stmt = stmt.where(Payment.direction == direction)
    return {"items": [js(P.payment_view(db, p)) for p in db.scalars(stmt.limit(500))]}


@router.post("/payments", dependencies=[FW], status_code=201)
def payments_create(body: S.PaymentIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    d = _dump(body, exclude={"allocations"})
    p = P.create_payment(db, user.id, allocations=[a.model_dump() for a in body.allocations], **d)
    db.commit()
    return js(P.payment_view(db, p))


@router.post("/payments/{pid}/allocations", dependencies=[FW], status_code=201)
def payments_allocate(pid: int, body: S.AllocationIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    P.allocate(db, user.id, pid, charge_id=body.charge_id, invoice_id=body.invoice_id, amount=body.amount)
    db.commit()
    return js(P.payment_view(db, get_or_404(db, Payment, pid, "Zahlung")))


@router.post("/payments/{pid}/deallocate", dependencies=[FW])
def payments_deallocate(pid: int, body: S.DeallocIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    P.deallocate(db, user.id, pid, charge_id=body.charge_id, invoice_id=body.invoice_id, amount=body.amount, reason=body.reason)
    db.commit()
    return js(P.payment_view(db, get_or_404(db, Payment, pid, "Zahlung")))


@router.post("/payments/{pid}/reverse", dependencies=[FW])
def payments_reverse(pid: int, body: S.ReverseIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    rev = P.reverse_payment(db, user.id, pid, reason=body.reason, booking_date=body.booking_date)
    db.commit()
    return js(P.payment_view(db, rev))


# --- Rechnungen ----------------------------------------------------------------------------------------------------------------------
def invoice_out(db: Session, i: Invoice) -> dict:
    return {**ser(i), "open_amount": js(P.invoice_open(db, i)) if not i.voided_at else None,
            "status": "voided" if i.voided_at else ("paid" if P.invoice_open(db, i) <= 0 else "partial" if P.invoice_allocated(db, i.id) > 0 else "open")}


@router.get("/invoices", dependencies=[FR])
def invoices_list(property_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(Invoice).order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
    if property_id:
        stmt = stmt.where(Invoice.property_id == property_id)
    return {"items": [invoice_out(db, i) for i in db.scalars(stmt.limit(500))]}


@router.post("/invoices", dependencies=[FW], status_code=201)
def invoices_create(body: S.InvoiceIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    i = P.create_invoice(db, user.id, **_dump(body))
    db.commit()
    return invoice_out(db, i)


@router.post("/invoices/{iid}/void", dependencies=[FW])
def invoices_void(iid: int, body: S.VoidIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    i = P.void_invoice(db, user.id, iid, body.reason)
    db.commit()
    return invoice_out(db, i)


# --- Dokumente -----------------------------------------------------------------------------------------------------------------------
def doc_out(d: Document) -> dict:
    return {"id": d.id, "original_name": d.original_name, "mime": d.mime, "size": d.size, "doc_type": d.doc_type, "uploaded_at": js(d.uploaded_at),
            "links": [{"entity_type": l.entity_type, "entity_id": l.entity_id} for l in d.links]}


@router.post("/documents", dependencies=[Depends(require("document:write"))], status_code=201)
async def documents_upload(file: UploadFile = File(...), entity_type: str = Form(...), entity_id: int = Form(...), doc_type: str = Form("sonstige"),
                           db: Session = Depends(get_db), user: AppUser = Depends(current_user), settings: Settings = Depends(get_settings)):
    data = await file.read(settings.max_upload_bytes + 1)
    import io
    doc = DOC.upload(db, _store(settings), user.id, stream=io.BytesIO(data), filename=file.filename or "datei", doc_type=doc_type, entity_type=entity_type, entity_id=entity_id)
    db.commit()
    return doc_out(doc)


@router.get("/documents", dependencies=[Depends(require("document:read"))])
def documents_list(entity_type: str, entity_id: int, db: Session = Depends(get_db)):
    return {"items": [doc_out(d) for d in DOC.for_entity(db, entity_type, entity_id)]}


@router.get("/documents/{did}/download", dependencies=[Depends(require("document:read"))])
def documents_download(did: int, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    d = get_or_404(db, Document, did, "Dokument")
    if d.deleted_at:
        raise ServiceError("deleted", "Das Dokument wurde gelöscht.", 404)
    store = _store(settings)
    res = DOC.verify(store, d)  # vor jedem Download: Datei vorhanden, lesbar, unverändert?
    if not res["ok"]:
        from leventum.services import audit
        audit.record(db, "document.integrity_failed", actor_user_id=None, entity_type="document", entity_id=d.id, summary=f"Dokument-Integrität verletzt: {res['problem']}", details={"problem": res["problem"]})
        db.commit()
        raise ServiceError("file_missing" if res["problem"] in ("missing", "unreadable") else "file_corrupt", res["message"], 404 if res["problem"] == "missing" else 409)
    safe = d.original_name.replace('"', "")
    return StreamingResponse(store.open(d.storage_key), media_type=d.mime, headers={"Content-Disposition": f'attachment; filename="{safe}"', "X-Content-Type-Options": "nosniff"})


# --- Kautionen -----------------------------------------------------------------------------------------------------------------------
def deposit_out(db: Session, d: Deposit) -> dict:
    lease = db.get(Lease, d.lease_id)
    return {**js(D.summary(d, lease)), "transactions": [ser(t) for t in d.transactions],
            "parties": [{"party_id": p.party_id, "name": p.party.display_name, "role": p.role} for p in lease.parties]}


@router.get("/deposits", dependencies=[FR])
def deposits_list(kind: str | None = None, db: Session = Depends(get_db)):
    out = []
    for d in db.scalars(select(Deposit).order_by(Deposit.id.desc())):
        o = deposit_out(db, d)
        if kind is None or o["lease_kind"] == kind:
            out.append(o)
    return {"items": out}


@router.post("/deposits", dependencies=[FW], status_code=201)
def deposits_create(body: S.DepositIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    d = D.ensure_deposit(db, user.id, body.lease_id, agreed_amount=body.agreed_amount, due_date=body.due_date, note=body.note)
    db.commit()
    return deposit_out(db, d)


@router.get("/deposits/{did}", dependencies=[FR])
def deposits_get(did: int, db: Session = Depends(get_db)):
    return deposit_out(db, get_or_404(db, Deposit, did, "Kaution"))


@router.post("/deposits/{did}/transactions", dependencies=[FW], status_code=201)
def deposits_tx(did: int, body: S.DepositTxIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    D.add_transaction(db, user.id, did, **_dump(body))
    db.commit()
    return deposit_out(db, get_or_404(db, Deposit, did, "Kaution"))


@router.post("/deposit-transactions/{tid}/void", dependencies=[FW])
def deposits_tx_void(tid: int, body: S.VoidIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    t = D.void_transaction(db, user.id, tid, body.reason)
    db.commit()
    return deposit_out(db, get_or_404(db, Deposit, t.deposit_id, "Kaution"))


# --- Mahnwesen -----------------------------------------------------------------------------------------------------------------------
def notice_out(n: DunningNotice, full: bool = True) -> dict:
    o = {**ser(n), "level_name": __import__("leventum.domain", fromlist=["x"]).DUNNING_LEVELS[n.level]}
    if full:
        o["lines"] = [ser(l) for l in n.lines]
    return o


@router.get("/dunning/overdue", dependencies=[FR])
def dunning_overdue(as_of: date | None = None, grace_days: int = Query(0, ge=0, le=60), db: Session = Depends(get_db)):
    items = DN.candidates(db, as_of, grace_days)
    labels = {i["lease_id"]: M.lease_title(db, db.get(Lease, i["lease_id"])) for i in items}
    return {"items": js([{**i, "lease_label": labels[i["lease_id"]]} for i in items]), "summary": js(DN.summarize(items)), "min_days_between_levels": DN.MIN_DAYS_BETWEEN_LEVELS,
            "note": "Gebühren und Verzugszinsen werden nicht berechnet. Es erfolgt kein automatischer Versand."}


@router.post("/dunning/prepare", dependencies=[FW])
def dunning_prepare(body: S.DunningPrepareIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    ns = DN.prepare_notices(db, user.id, **_dump(body))
    db.commit()
    return {"created": [notice_out(n) for n in ns]}


@router.get("/dunning/notices", dependencies=[FR])
def dunning_list(status: str | None = None, lease_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(DunningNotice).order_by(DunningNotice.id.desc())
    if status:
        stmt = stmt.where(DunningNotice.status == status)
    if lease_id:
        stmt = stmt.where(DunningNotice.lease_id == lease_id)
    return {"items": [notice_out(n, False) for n in db.scalars(stmt.limit(300))]}


@router.get("/dunning/notices/{nid}", dependencies=[FR])
def dunning_get(nid: int, db: Session = Depends(get_db)):
    from leventum.models import AuditEvent
    n = get_or_404(db, DunningNotice, nid, "Mahnung")
    hist = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "dunning_notice", AuditEvent.entity_id == str(nid)).order_by(AuditEvent.id))
    return {**notice_out(n), "history": [{"at": js(h.occurred_at), "action": h.action, "summary": h.summary, "actor_user_id": h.actor_user_id} for h in hist]}


@router.patch("/dunning/notices/{nid}", dependencies=[FW])
def dunning_edit(nid: int, body: S.DunningEditIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    n = DN.update_draft(db, user.id, nid, **_dump(body, exclude_unset=True))
    db.commit()
    return notice_out(n)


@router.post("/dunning/notices/{nid}/approve", dependencies=[FW])
def dunning_approve(nid: int, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    n = DN.approve(db, user.id, nid)
    db.commit()
    return notice_out(n)


@router.post("/dunning/notices/{nid}/mark-sent", dependencies=[FW])
def dunning_sent(nid: int, body: S.SentIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    n = DN.mark_sent(db, user.id, nid, sent_on=body.sent_on, via=body.via)
    db.commit()
    return notice_out(n)


@router.post("/dunning/notices/{nid}/cancel", dependencies=[FW])
def dunning_cancel(nid: int, body: S.ReasonIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    n = DN.cancel(db, user.id, nid, body.reason)
    db.commit()
    return notice_out(n)


# --- Bankimport ----------------------------------------------------------------------------------------------------------------------
@router.get("/bank/accounts", dependencies=[FR])
def bank_accounts(db: Session = Depends(get_db)):
    return {"items": [ser(a) for a in db.scalars(select(BankAccount).where(BankAccount.is_active.is_(True)))]}


@router.post("/bank/accounts", dependencies=[FW], status_code=201)
def bank_account_create(body: S.BankAccountIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    a = B.create_account(db, user.id, body.name, body.iban)
    db.commit()
    return ser(a)


async def _read(file: UploadFile) -> bytes:
    data = await file.read(UP_LIMIT + 1)
    if len(data) > UP_LIMIT:
        raise ServiceError("too_large", "Datei zu groß (max. 5 MB).", 413)
    return data


def _opts(mapping: str | None, delimiter: str | None) -> dict:
    o: dict = {}
    if mapping:
        try:
            o["mapping"] = json.loads(mapping)
        except ValueError:
            raise ServiceError("invalid", "Spaltenzuordnung ist kein gültiges JSON.")
    if delimiter:
        o["delimiter"] = delimiter
    return o


@router.post("/bank/imports/preview", dependencies=[FW])
async def bank_preview(account_id: int = Form(...), format: str = Form("csv"), mapping: str | None = Form(None), delimiter: str | None = Form(None),
                       file: UploadFile = File(...), db: Session = Depends(get_db)):
    return js(B.preview(db, account_id, await _read(file), format, _opts(mapping, delimiter)))


@router.post("/bank/imports", dependencies=[FW], status_code=201)
async def bank_import(account_id: int = Form(...), format: str = Form("csv"), mapping: str | None = Form(None), delimiter: str | None = Form(None),
                      file: UploadFile = File(...), db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    imp = B.import_statement(db, user.id, account_id, file.filename or "import.csv", await _read(file), format, _opts(mapping, delimiter))
    db.commit()
    return ser(imp)


@router.get("/bank/imports", dependencies=[FR])
def bank_imports(db: Session = Depends(get_db)):
    return {"items": [ser(i) for i in db.scalars(select(BankImport).order_by(BankImport.id.desc()).limit(100))]}


def txn_out(db: Session, t: BankTransaction, with_suggestions: bool) -> dict:
    o = ser(t)
    o.pop("raw", None)
    if with_suggestions and t.status == "open":
        s = B.suggest(db, t)
        for x in s:
            if x.get("lease_id"):
                x["lease_label"] = M.lease_title(db, db.get(Lease, x["lease_id"]))
        o["suggestions"], o["unmatched"] = js(s), not s
    return o


@router.get("/bank/transactions", dependencies=[FR])
def bank_transactions(status: str | None = None, account_id: int | None = None, suggestions: bool = False, only_unmatched: bool = False,
                      limit: int = Query(300, le=1000), db: Session = Depends(get_db)):
    stmt = select(BankTransaction).order_by(BankTransaction.booking_date.desc(), BankTransaction.id.desc())
    if status:
        stmt = stmt.where(BankTransaction.status == status)
    if account_id:
        stmt = stmt.where(BankTransaction.account_id == account_id)
    rows = [txn_out(db, t, suggestions or only_unmatched) for t in db.scalars(stmt.limit(limit))]
    if only_unmatched:
        rows = [r for r in rows if r.get("unmatched")]
    return {"items": rows}


@router.get("/bank/transactions/{tid}", dependencies=[FR])
def bank_transaction(tid: int, db: Session = Depends(get_db)):
    return txn_out(db, get_or_404(db, BankTransaction, tid, "Bankbuchung"), True)


@router.post("/bank/transactions/{tid}/confirm", dependencies=[FW])
def bank_confirm(tid: int, body: S.ConfirmIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    if body.kind == "deposit":
        if body.deposit_id is None or body.deposit_kind is None:
            raise ServiceError("invalid", "Für Kautionsbuchungen deposit_id und deposit_kind angeben.")
        B.confirm_deposit(db, user.id, tid, deposit_id=body.deposit_id, kind=body.deposit_kind, reason=body.reason)
    else:
        B.confirm_payment(db, user.id, tid, allocations=[a.model_dump() for a in body.allocations], counterparty_party_id=body.counterparty_party_id,
                          lease_id=body.lease_id, property_id=body.property_id, note=body.note, accept_possible_duplicate=body.accept_possible_duplicate)
    db.commit()
    return txn_out(db, get_or_404(db, BankTransaction, tid, "Bankbuchung"), False)


@router.post("/bank/transactions/{tid}/ignore", dependencies=[FW])
def bank_ignore(tid: int, body: S.ReasonIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    t = B.ignore(db, user.id, tid, body.reason)
    db.commit()
    return txn_out(db, t, False)


@router.post("/bank/transactions/{tid}/reopen", dependencies=[FW])
def bank_reopen(tid: int, body: S.ReasonIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    t = B.reopen(db, user.id, tid, body.reason)
    db.commit()
    return txn_out(db, t, False)


# --- Auswertungen ---------------------------------------------------------------------------------------------------------------------
@router.get("/economics", dependencies=[FR])
def economics(start: date, end: date, scope: str = "portfolio", id: int | None = None, db: Session = Depends(get_db)):
    return js(E.Engine(db, start, end).report(scope, id))


@router.get("/vacancy", dependencies=[FR])
def vacancy(start: date, end: date, property_id: int | None = None, db: Session = Depends(get_db)):
    return js(E.vacancy_report(db, start, end, property_id))


# --- Hauptmiete: Verteilungsmethode -----------------------------------------------------------------------------------------------------
@router.put("/leases/{lid}/allocation", dependencies=[Depends(require("master:write"))])
def lease_allocation(lid: int, body: S.LeaseAllocationIn, db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    from leventum.services import audit
    lease = get_or_404(db, Lease, lid, "Vertrag")
    if lease.kind != "main":
        raise ServiceError("invalid", "Die Verteilungsmethode gilt nur für Hauptmietverträge.")
    if body.method == "custom":
        for uid in body.weights:
            get_or_404(db, Unit, uid, "Wohneinheit")
    lease.allocation_method = body.method
    for w in db.scalars(select(LeaseAllocationWeight).where(LeaseAllocationWeight.lease_id == lid)):
        db.delete(w)
    db.flush()
    if body.method == "custom":
        for uid, w in body.weights.items():
            db.add(LeaseAllocationWeight(lease_id=lid, unit_id=uid, weight=w))
    audit.record(db, "lease.allocation_set", actor_user_id=user.id, entity_type="lease", entity_id=lid, summary=f"Verteilungsmethode: {body.method}",
                 details={"weights": {str(k): str(v) for k, v in body.weights.items()}})
    db.commit()
    return {"lease_id": lid, "method": body.method, "weights": js(body.weights)}
