"""Zahlungen und Zuordnungen. Zahlungen und Zuordnungen sind append-only; Korrekturen erfolgen per Gegenbuchung."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from leventum import domain
from leventum.models import Charge, Invoice, Lease, Party, Payment, PaymentAllocation, Property
from leventum.services import audit
from leventum.services.charges import open_amount as charge_open
from leventum.services.errors import ServiceError
from leventum.services.master import get_or_404
from leventum.services.utility import q

ZERO = Decimal("0.00")


def signed(p: Payment) -> Decimal:
    return -p.amount if p.is_reversal else p.amount


def allocated_total(db: Session, payment_id: int) -> Decimal:
    return q(Decimal(db.scalar(select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(PaymentAllocation.payment_id == payment_id))))


def unallocated(db: Session, p: Payment) -> Decimal:
    return q(signed(p) - allocated_total(db, p.id))


def is_reversed(db: Session, p: Payment) -> bool:
    return db.scalar(select(Payment.id).where(Payment.reverses_payment_id == p.id)) is not None


def invoice_allocated(db: Session, invoice_id: int, as_of: date | None = None) -> Decimal:
    stmt = select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(PaymentAllocation.invoice_id == invoice_id)
    if as_of is not None:
        stmt = stmt.join(Payment, Payment.id == PaymentAllocation.payment_id).where(Payment.booking_date <= as_of)
    return q(Decimal(db.scalar(stmt)))


def invoice_open(db: Session, inv: Invoice, as_of: date | None = None) -> Decimal:
    return q(inv.amount - invoice_allocated(db, inv.id, as_of))


def _find_duplicate(db: Session, direction, booking_date, amount, counterparty_id, reference) -> Payment | None:
    stmt = select(Payment).where(Payment.direction == direction, Payment.booking_date == booking_date, Payment.amount == amount,
                                 Payment.is_reversal.is_(False))
    stmt = stmt.where(Payment.counterparty_party_id.is_(None) if counterparty_id is None else Payment.counterparty_party_id == counterparty_id)
    for p in db.scalars(stmt):
        if (p.reference or "").strip().lower() == (reference or "").strip().lower() and not is_reversed(db, p):
            return p
    return None


def create_payment(db: Session, actor_id: int | None, *, direction: str, booking_date: date, amount: Decimal,
                   counterparty_party_id: int | None = None, lease_id: int | None = None, property_id: int | None = None,
                   method: str = "bank_transfer", reference: str | None = None, note: str | None = None, source: str = "manual",
                   allocations: list[dict] | None = None, accept_possible_duplicate: bool = False) -> Payment:
    if direction not in domain.PAYMENT_DIRECTIONS or method not in domain.PAYMENT_METHODS:
        raise ServiceError("invalid", "Ungültige Richtung oder Zahlungsart.")
    if amount <= 0:
        raise ServiceError("invalid", "Der Zahlungsbetrag muss größer 0 sein.")
    if counterparty_party_id is not None:
        get_or_404(db, Party, counterparty_party_id, "Zahlungspartner")
    if lease_id is not None:
        get_or_404(db, Lease, lease_id, "Vertrag")
    if property_id is not None:
        get_or_404(db, Property, property_id, "Objekt")
    if not accept_possible_duplicate and (dup := _find_duplicate(db, direction, booking_date, amount, counterparty_party_id, reference)):
        raise ServiceError("possible_duplicate", f"Eine gleiche Zahlung existiert bereits (#{dup.id}).", 409, {"payment_id": dup.id})
    p = Payment(direction=direction, booking_date=booking_date, amount=amount, counterparty_party_id=counterparty_party_id, lease_id=lease_id,
                property_id=property_id, method=method, reference=reference, source=source, note=note, created_by_user_id=actor_id)
    db.add(p)
    db.flush()
    audit.record(db, "payment.created", actor_user_id=actor_id, entity_type="payment", entity_id=p.id,
                 summary=f"Zahlung {'Eingang' if direction == 'in' else 'Ausgang'} erfasst", details={"amount": str(amount), "source": source})
    for a in allocations or []:
        allocate(db, actor_id, p.id, charge_id=a.get("charge_id"), invoice_id=a.get("invoice_id"), amount=a["amount"])
    return p


def allocate(db: Session, actor_id: int | None, payment_id: int, *, charge_id: int | None = None, invoice_id: int | None = None,
             amount: Decimal, reason: str | None = None) -> PaymentAllocation:
    p = get_or_404(db, Payment, payment_id, "Zahlung")
    if (charge_id is None) == (invoice_id is None):
        raise ServiceError("invalid", "Genau ein Ziel (Sollstellung oder Rechnung) angeben.")
    if p.is_reversal or is_reversed(db, p):
        raise ServiceError("invalid_state", "Stornierte Zahlungen und Stornobuchungen können nicht zugeordnet werden.", 409)
    if amount <= 0:
        raise ServiceError("invalid", "Der Zuordnungsbetrag muss größer 0 sein.")
    if amount > unallocated(db, p):
        raise ServiceError("exceeds_payment", f"Zuordnung ({amount}) übersteigt den nicht zugeordneten Zahlungsbetrag ({unallocated(db, p)}).", 409)
    if charge_id is not None:
        c = get_or_404(db, Charge, charge_id, "Sollstellung")
        if c.voided_at:
            raise ServiceError("voided_target", "Die Sollstellung ist storniert.", 409)
        if (c.direction == "receivable") != (p.direction == "in"):
            raise ServiceError("direction_mismatch", "Zahlungsrichtung passt nicht zur Sollstellung (Forderung ↔ Eingang, Verbindlichkeit ↔ Ausgang).", 409)
        if amount > charge_open(db, c):
            raise ServiceError("exceeds_open", f"Zuordnung ({amount}) übersteigt den offenen Betrag der Sollstellung ({charge_open(db, c)}).", 409)
    else:
        inv = get_or_404(db, Invoice, invoice_id, "Rechnung")
        if inv.voided_at:
            raise ServiceError("voided_target", "Die Rechnung ist storniert.", 409)
        if p.direction != "out":
            raise ServiceError("direction_mismatch", "Rechnungen werden nur durch Zahlungsausgänge beglichen.", 409)
        if amount > invoice_open(db, inv):
            raise ServiceError("exceeds_open", f"Zuordnung ({amount}) übersteigt den offenen Rechnungsbetrag ({invoice_open(db, inv)}).", 409)
    row = PaymentAllocation(payment_id=p.id, charge_id=charge_id, invoice_id=invoice_id, amount=amount, reason=reason, created_by_user_id=actor_id)
    db.add(row)
    db.flush()
    audit.record(db, "payment.allocated", actor_user_id=actor_id, entity_type="payment", entity_id=p.id, summary="Zahlung zugeordnet",
                 details={"charge_id": charge_id, "invoice_id": invoice_id, "amount": str(amount)})
    return row


def deallocate(db: Session, actor_id: int | None, payment_id: int, *, charge_id: int | None = None, invoice_id: int | None = None,
               amount: Decimal, reason: str) -> PaymentAllocation:
    p = get_or_404(db, Payment, payment_id, "Zahlung")
    if not reason.strip():
        raise ServiceError("invalid", "Begründung erforderlich.")
    if p.is_reversal or is_reversed(db, p):
        raise ServiceError("invalid_state", "Stornierte Zahlungen können nicht geändert werden.", 409)
    stmt = select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(PaymentAllocation.payment_id == p.id)
    stmt = stmt.where(PaymentAllocation.charge_id == charge_id) if charge_id is not None else stmt.where(PaymentAllocation.invoice_id == invoice_id)
    current = q(Decimal(db.scalar(stmt)))
    if amount <= 0 or amount > current:
        raise ServiceError("exceeds_allocation", f"Es sind nur {current} zugeordnet.", 409)
    row = PaymentAllocation(payment_id=p.id, charge_id=charge_id, invoice_id=invoice_id, amount=-amount, reason=reason.strip(), created_by_user_id=actor_id)
    db.add(row)
    db.flush()
    audit.record(db, "payment.deallocated", actor_user_id=actor_id, entity_type="payment", entity_id=p.id, summary="Zuordnung zurückgenommen",
                 details={"charge_id": charge_id, "invoice_id": invoice_id, "amount": str(amount), "reason": reason})
    return row


def reverse_payment(db: Session, actor_id: int | None, payment_id: int, *, reason: str, booking_date: date | None = None) -> Payment:
    """Storno per Gegenbuchung. Das Original bleibt unverändert; seine Zuordnungen werden durch negative Zuordnungen der Stornobuchung aufgehoben."""
    p = get_or_404(db, Payment, payment_id, "Zahlung")
    if p.is_reversal:
        raise ServiceError("invalid_state", "Eine Stornobuchung kann nicht storniert werden.", 409)
    if is_reversed(db, p):
        raise ServiceError("already_reversed", "Die Zahlung ist bereits storniert.", 409)
    if not reason.strip():
        raise ServiceError("invalid", "Begründung erforderlich.")
    rev = Payment(direction=p.direction, booking_date=booking_date or date.today(), amount=p.amount, is_reversal=True, reverses_payment_id=p.id,
                  counterparty_party_id=p.counterparty_party_id, lease_id=p.lease_id, property_id=p.property_id, method=p.method,
                  reference=f"Storno zu Zahlung {p.id}: {reason.strip()}", source=p.source, created_by_user_id=actor_id)
    db.add(rev)
    db.flush()
    rows = db.execute(select(PaymentAllocation.charge_id, PaymentAllocation.invoice_id, func.sum(PaymentAllocation.amount))
                      .where(PaymentAllocation.payment_id == p.id).group_by(PaymentAllocation.charge_id, PaymentAllocation.invoice_id)).all()
    for cid, iid, total in rows:
        total = q(Decimal(total))
        if total != 0:
            db.add(PaymentAllocation(payment_id=rev.id, charge_id=cid, invoice_id=iid, amount=-total, reason="Storno", created_by_user_id=actor_id))
    db.flush()
    audit.record(db, "payment.reversed", actor_user_id=actor_id, entity_type="payment", entity_id=p.id, summary="Zahlung storniert (Gegenbuchung)",
                 details={"reversal_id": rev.id, "reason": reason})
    return rev


def payment_view(db: Session, p: Payment) -> dict:
    return {"id": p.id, "direction": p.direction, "booking_date": p.booking_date, "amount": p.amount, "is_reversal": p.is_reversal,
            "reverses_payment_id": p.reverses_payment_id, "reversed": is_reversed(db, p) if not p.is_reversal else False,
            "signed_amount": signed(p), "allocated": allocated_total(db, p.id), "unallocated": unallocated(db, p),
            "counterparty_party_id": p.counterparty_party_id, "lease_id": p.lease_id, "property_id": p.property_id, "method": p.method,
            "reference": p.reference, "source": p.source, "note": p.note}


# --- Rechnungen ---------------------------------------------------------------------------------------------------------
def create_invoice(db: Session, actor_id: int | None, *, property_id: int, amount: Decimal, invoice_date: date, **f) -> Invoice:
    from leventum.models import CostType, Unit
    prop = get_or_404(db, Property, property_id, "Objekt")
    if amount <= 0:
        raise ServiceError("invalid", "Betrag muss größer 0 sein.")
    if f.get("unit_id") is not None and get_or_404(db, Unit, f["unit_id"], "Wohneinheit").property_id != prop.id:
        raise ServiceError("invalid", "Wohneinheit gehört nicht zum Objekt.")
    if f.get("supplier_party_id") is not None:
        get_or_404(db, Party, f["supplier_party_id"], "Lieferant")
    if f.get("repair_id") is not None:
        from leventum.models import Repair
        if get_or_404(db, Repair, f["repair_id"], "Reparatur").property_id != prop.id:
            raise ServiceError("invalid", "Die Reparatur gehört zu einem anderen Objekt.")
    if f.get("cost_type_id") is not None:
        get_or_404(db, CostType, f["cost_type_id"], "Kostenart")
    if f.get("invoice_number") and f.get("supplier_party_id") is not None and db.scalar(
            select(Invoice.id).where(Invoice.supplier_party_id == f["supplier_party_id"], Invoice.invoice_number == f["invoice_number"])):
        raise ServiceError("duplicate", "Diese Rechnungsnummer existiert für den Lieferanten bereits.", 409)
    inv = Invoice(property_id=prop.id, amount=amount, invoice_date=invoice_date, created_by_user_id=actor_id, **f)
    db.add(inv)
    db.flush()
    audit.record(db, "invoice.created", actor_user_id=actor_id, entity_type="invoice", entity_id=inv.id, summary="Rechnung erfasst", details={"amount": str(amount)})
    return inv


def void_invoice(db: Session, actor_id: int | None, invoice_id: int, reason: str) -> Invoice:
    from datetime import datetime, timezone
    inv = get_or_404(db, Invoice, invoice_id, "Rechnung")
    if inv.voided_at:
        raise ServiceError("already_voided", "Bereits storniert.", 409)
    if not reason.strip():
        raise ServiceError("invalid", "Begründung erforderlich.")
    if invoice_allocated(db, inv.id) != 0:
        raise ServiceError("has_allocations", "Der Rechnung sind Zahlungen zugeordnet; zuerst zurücknehmen.", 409)
    inv.voided_at, inv.void_reason = datetime.now(timezone.utc), reason.strip()
    audit.record(db, "invoice.voided", actor_user_id=actor_id, entity_type="invoice", entity_id=inv.id, summary="Rechnung storniert", details={"reason": reason})
    db.flush()
    return inv
