"""Kautionsverwaltung. Bewusst OHNE Bezug zu Charge/Payment: Kautionen sind weder Ertrag noch Betriebsausgabe,
und es gibt keine Verrechnung zwischen Haupt- und Untermietkaution (jede Kaution gehört zu genau einem Vertrag)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from leventum import domain
from leventum.models import Deposit, DepositTransaction, Lease
from leventum.services import audit
from leventum.services.errors import ServiceError
from leventum.services.master import get_or_404
from leventum.services.utility import q


def _sum(d: Deposit, kind: str) -> Decimal:
    return q(sum((t.amount for t in d.transactions if t.kind == kind and t.voided_at is None), Decimal(0)))


def summary(d: Deposit, lease: Lease, today: date | None = None) -> dict:
    today = today or date.today()
    paid, refunded, retained = _sum(d, "paid"), _sum(d, "refunded"), _sum(d, "retained")
    held = q(paid - refunded - retained)
    open_ = q(max(d.agreed_amount - paid, Decimal(0)))
    if paid == 0:
        status = "open"
    elif open_ > 0:
        status = "partially_paid"
    else:
        status = "paid"
    if paid > 0 and held == 0:
        status = "settled"          # vollständig zurückgezahlt/einbehalten
    elif paid > 0 and (refunded > 0 or retained > 0):
        status = "partially_refunded"
    return {"id": d.id, "lease_id": d.lease_id, "lease_kind": lease.kind, "agreed_amount": d.agreed_amount, "due_date": d.due_date,
            "paid": paid, "open": open_, "refunded": refunded, "retained": retained, "held": held, "status": status,
            "overdue": bool(open_ > 0 and d.due_date and d.due_date < today),
            "direction_note": "Leventum → Vermieter (Leventum ist Zahlungspflichtiger)" if lease.kind == "main" else "Mieter → Leventum (Leventum hält die Kaution)",
            "note": d.note}


def ensure_deposit(db: Session, actor_id: int | None, lease_id: int, *, agreed_amount: Decimal | None = None, due_date: date | None = None,
                   note: str | None = None) -> Deposit:
    lease = get_or_404(db, Lease, lease_id, "Vertrag")
    if lease.status == "cancelled":
        raise ServiceError("invalid_state", "Für stornierte Verträge keine Kaution.", 409)
    amount = agreed_amount if agreed_amount is not None else lease.deposit_amount
    if amount is None or amount < 0:
        raise ServiceError("invalid", "Vereinbarter Kautionsbetrag (≥ 0) erforderlich.")
    d = lease_deposit(db, lease_id)
    if d is None:
        d = Deposit(lease_id=lease.id, agreed_amount=amount, due_date=due_date, note=note)
        db.add(d)
        action = "deposit.created"
    else:
        if amount < _sum(d, "paid"):
            raise ServiceError("invalid", "Der vereinbarte Betrag darf nicht unter dem bereits gezahlten liegen.", 409)
        d.agreed_amount, d.due_date, d.note = amount, due_date or d.due_date, note if note is not None else d.note
        action = "deposit.updated"
    db.flush()
    audit.record(db, action, actor_user_id=actor_id, entity_type="deposit", entity_id=d.id, summary="Kaution vereinbart",
                 details={"lease_id": lease.id, "agreed_amount": str(amount)})
    return d


def lease_deposit(db: Session, lease_id: int) -> Deposit | None:
    from sqlalchemy import select
    return db.scalar(select(Deposit).where(Deposit.lease_id == lease_id))


def add_transaction(db: Session, actor_id: int | None, deposit_id: int, *, kind: str, amount: Decimal, transaction_date: date,
                    reason: str | None = None, note: str | None = None, bank_transaction_id: int | None = None) -> DepositTransaction:
    d = get_or_404(db, Deposit, deposit_id, "Kaution")
    lease = db.get(Lease, d.lease_id)
    if kind not in domain.DEPOSIT_TX_KINDS:
        raise ServiceError("invalid", "Ungültige Kautionsbuchung.")
    if amount <= 0:
        raise ServiceError("invalid", "Betrag muss größer 0 sein.")
    s = summary(d, lease)
    if kind == "paid" and amount > s["open"]:
        raise ServiceError("exceeds_open", f"Zahlung ({amount}) übersteigt den offenen Kautionsbetrag ({s['open']}).", 409)
    if kind in ("refunded", "retained") and amount > s["held"]:
        raise ServiceError("exceeds_held", f"Betrag ({amount}) übersteigt die gehaltene Kaution ({s['held']}).", 409)
    if kind == "retained" and not (reason or "").strip():
        raise ServiceError("reason_required", "Für einen Einbehalt ist eine Begründung erforderlich.")
    t = DepositTransaction(deposit_id=d.id, kind=kind, amount=amount, transaction_date=transaction_date, reason=reason, note=note,
                           bank_transaction_id=bank_transaction_id, created_by_user_id=actor_id)
    d.transactions.append(t)
    db.flush()
    audit.record(db, f"deposit.{kind}", actor_user_id=actor_id, entity_type="deposit", entity_id=d.id, summary=f"Kautionsbuchung: {kind}",
                 details={"amount": str(amount), "reason": reason, "transaction_id": t.id})
    return t


def void_transaction(db: Session, actor_id: int | None, transaction_id: int, reason: str) -> DepositTransaction:
    t = get_or_404(db, DepositTransaction, transaction_id, "Kautionsbuchung")
    if t.voided_at:
        raise ServiceError("already_voided", "Bereits storniert.", 409)
    if not reason.strip():
        raise ServiceError("invalid", "Begründung erforderlich.")
    d = db.get(Deposit, t.deposit_id)
    t.voided_at, t.void_reason = datetime.now(timezone.utc), reason.strip()
    db.flush()
    if summary(d, db.get(Lease, d.lease_id))["held"] < 0:  # Stornierung einer Einzahlung würde Rückzahlungen unbedeckt lassen
        t.voided_at, t.void_reason = None, None
        raise ServiceError("would_underflow", "Die Stornierung würde eine negative gehaltene Kaution erzeugen.", 409)
    audit.record(db, "deposit.transaction_voided", actor_user_id=actor_id, entity_type="deposit", entity_id=d.id, summary="Kautionsbuchung storniert",
                 details={"transaction_id": t.id, "reason": reason})
    return t
