"""Sollstellungen. Der monatliche Soll-Betrag wird ausschließlich aus Mietkonditionen und Nebenkostenvereinbarung
berechnet (`monthly_components`). Dieselbe Funktion speist Sollstellungen UND Wirtschaftlichkeit, damit beide übereinstimmen."""
from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from leventum import domain
from leventum.models import Charge, Lease, PaymentAllocation
from leventum.services import audit
from leventum.services.errors import ServiceError
from leventum.services.leases import OPEN_END, effective_end
from leventum.services.master import get_or_404
from leventum.services.utility import q

BILLABLE_STATUS = ("active", "terminated", "ended")


def month_range(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def monthly_components(lease: Lease, y: int, m: int) -> dict[str, Decimal]:
    """Soll je Monat und Betragsart, tagesgenau anteilig (Tage/Tage des Monats); Rundung einmal je Art auf Cent.
    Tagesbasierte Mieten (rent_period = day) = Tagessatz × Tage."""
    dim = monthrange(y, m)[1]
    first, last = date(y, m, 1), date(y, m, dim)
    ls, le = lease.start_date, effective_end(lease) or OPEN_END
    acc: dict[str, Decimal] = defaultdict(Decimal)
    for t in lease.terms:
        s, e = max(t.valid_from, ls, first), min(t.valid_to or OPEN_END, le, last)
        if e < s:
            continue
        days = (e - s).days + 1
        f = Decimal(days) / dim if t.rent_period == "month" else Decimal(days)
        acc["base_rent"] += t.base_rent * f
        acc["other_charges"] += t.other_charges * f
    for a in lease.utility_agreements:
        if a.mode not in ("prepayment", "flat_rate") or not a.monthly_amount:
            continue
        s, e = max(a.valid_from, ls, first), min(a.valid_to or OPEN_END, le, last)
        if e < s:
            continue
        acc["utility_prepayment" if a.mode == "prepayment" else "utility_flat_rate"] += a.monthly_amount * Decimal((e - s).days + 1) / dim
    return {k: q(v) for k, v in acc.items() if q(v) > 0}


def direction_for(lease: Lease) -> str:
    return "receivable" if lease.kind == "sub" else "payable"


def due_date_for(lease: Lease, y: int, m: int) -> date:
    return date(y, m, min(lease.payment_due_day, monthrange(y, m)[1]))


def allocated(db: Session, charge_id: int, as_of: date | None = None) -> Decimal:
    from leventum.models import Payment
    stmt = select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(PaymentAllocation.charge_id == charge_id)
    if as_of is not None:
        stmt = stmt.join(Payment, Payment.id == PaymentAllocation.payment_id).where(Payment.booking_date <= as_of)
    v = db.scalar(stmt)
    return (Decimal(v) if not isinstance(v, Decimal) else v).quantize(Decimal("0.01"))


def open_amount(db: Session, charge: Charge, as_of: date | None = None) -> Decimal:
    return q(charge.amount - allocated(db, charge.id, as_of))


def generate_charges(db: Session, actor_id: int | None, *, from_month: date, through_month: date, lease_id: int | None = None,
                     today: date | None = None) -> dict:
    """Erzeugt fehlende Sollstellungen. Idempotent (dedupe_key). Bestehende Sollstellungen werden NIE verändert;
    weicht der berechnete Betrag ab (z. B. nach Konditionsänderung), wird ein Konflikt gemeldet."""
    today = today or date.today()
    if through_month < from_month:
        raise ServiceError("invalid", "Zeitraum ungültig.")
    if (through_month.year - today.year) * 12 + through_month.month - today.month > 12:
        raise ServiceError("invalid", "Sollstellungen dürfen höchstens 12 Monate im Voraus erzeugt werden.")
    stmt = select(Lease).where(Lease.status.in_(BILLABLE_STATUS))
    if lease_id:
        stmt = stmt.where(Lease.id == lease_id)
    created, skipped, conflicts = [], 0, []
    for lease in db.scalars(stmt.order_by(Lease.id)):
        end = effective_end(lease) or OPEN_END
        for y, m in month_range(from_month, through_month):
            if date(y, m, 1) > end or date(y, m, monthrange(y, m)[1]) < lease.start_date:
                continue
            for ctype, amount in monthly_components(lease, y, m).items():
                key = f"{lease.id}:{ctype}:{y}-{m:02d}"
                existing = db.scalar(select(Charge).where(Charge.dedupe_key == key))
                if existing:
                    if existing.amount == amount:
                        skipped += 1
                    else:
                        conflicts.append({"charge_id": existing.id, "lease_id": lease.id, "charge_type": ctype, "month": f"{y}-{m:02d}",
                                          "existing_amount": existing.amount, "calculated_amount": amount})
                    continue
                c = Charge(lease_id=lease.id, direction=direction_for(lease), charge_type=ctype, period_start=date(y, m, 1),
                           period_end=date(y, m, monthrange(y, m)[1]), due_date=due_date_for(lease, y, m), amount=amount,
                           dedupe_key=key, source="generated", created_by_user_id=actor_id)
                db.add(c)
                created.append(c)
    db.flush()
    audit.record(db, "charge.generated", actor_user_id=actor_id, entity_type="charge",
                 summary=f"{len(created)} Sollstellungen erzeugt", details={"created": len(created), "skipped": skipped, "conflicts": len(conflicts),
                                                                            "from": str(from_month), "through": str(through_month)})
    return {"created": [c.id for c in created], "created_count": len(created), "skipped_existing": skipped, "conflicts": conflicts}


def void_charge(db: Session, actor_id: int | None, charge_id: int, reason: str) -> Charge:
    c = get_or_404(db, Charge, charge_id, "Sollstellung")
    if c.voided_at:
        raise ServiceError("already_voided", "Die Sollstellung ist bereits storniert.", 409)
    if not reason.strip():
        raise ServiceError("invalid", "Begründung erforderlich.")
    if allocated(db, c.id) != 0:
        raise ServiceError("has_allocations", "Der Sollstellung sind Zahlungen zugeordnet; Zuordnungen zuerst zurücknehmen.", 409)
    c.voided_at, c.voided_by_user_id, c.void_reason, c.dedupe_key = datetime.now(timezone.utc), actor_id, reason.strip(), None
    audit.record(db, "charge.voided", actor_user_id=actor_id, entity_type="charge", entity_id=c.id, summary="Sollstellung storniert", details={"reason": reason})
    db.flush()
    return c


def create_manual_charge(db: Session, actor_id: int | None, *, lease_id: int, amount: Decimal, due_date: date, period_start: date,
                         period_end: date, note: str) -> Charge:
    lease = get_or_404(db, Lease, lease_id, "Vertrag")
    if lease.status not in BILLABLE_STATUS:
        raise ServiceError("invalid_state", "Für Entwürfe oder stornierte Verträge sind keine Sollstellungen möglich.", 409)
    if amount <= 0 or not note.strip():
        raise ServiceError("invalid", "Betrag > 0 und Begründung erforderlich.")
    c = Charge(lease_id=lease.id, direction=direction_for(lease), charge_type="other", period_start=period_start, period_end=period_end,
               due_date=due_date, amount=amount, source="manual", note=note.strip(), created_by_user_id=actor_id)
    db.add(c)
    db.flush()
    audit.record(db, "charge.created", actor_user_id=actor_id, entity_type="charge", entity_id=c.id, summary="Manuelle Sollstellung", details={"amount": str(amount)})
    return c
