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


def receivable_position(db: Session, as_of: date) -> dict:
    """ZENTRALE Definition „offene/überfällige Mietforderungen zum Stichtag“ (ADR 0002), reiner Lesepfad, gruppierte Abfrage (kein N+1).
    Berücksichtigt: Forderungen direction=receivable, nicht storniert; je Forderung abzüglich Zuordnungen von Zahlungen mit
    booking_date <= as_of (Stornobuchungen wirken ab eigenem Buchungsdatum). Nur Restbeträge > 0 (keine Verrechnung über Forderungen, A7).
    open_total: unabhängig von der Fälligkeit (A1); overdue_count: offener Rest und due_date < as_of."""
    from leventum.models import Payment
    paid = (select(PaymentAllocation.charge_id.label("cid"), func.sum(PaymentAllocation.amount).label("paid"))
            .join(Payment, Payment.id == PaymentAllocation.payment_id)
            .where(PaymentAllocation.charge_id.is_not(None), Payment.booking_date <= as_of)
            .group_by(PaymentAllocation.charge_id).subquery())
    rows = db.execute(select(Charge.lease_id, Charge.amount, Charge.due_date, paid.c.paid).outerjoin(paid, paid.c.cid == Charge.id)
                      .where(Charge.direction == "receivable", Charge.voided_at.is_(None)))
    total, overdue = Decimal(0), 0
    by_lease: dict[int, list[tuple[date, Decimal]]] = {}
    for lease_id, amount, due, p in rows:
        rest = q(Decimal(amount) - (Decimal(p) if p is not None else Decimal(0)))
        if rest > 0:
            total += rest
            if due < as_of:
                overdue += 1
                by_lease.setdefault(lease_id, []).append((due, rest))
    return {"open_total": q(total), "overdue_count": overdue, "overdue_by_lease": by_lease}  # by_lease: Detail für Hinweise, gleiche Semantik


def period_months(rhythm: str, first_month: date, through_month: date):
    """Kalenderbasierte Abrechnungsperioden, die im Bereich [first_month, through_month] BEGINNEN: (Startmonat, Anzahl Monate).
    Quartale beginnen im Jan/Apr/Jul/Okt, Halbjahre im Jan/Jul, Jahre im Januar (Annahme, siehe docs)."""
    n = domain.RHYTHM_MONTHS[rhythm]
    for y, m in month_range(first_month, through_month):
        if (m - 1) % n == 0:
            yield y, m, n


def _period_end(y: int, m: int, n: int) -> date:
    ey, em = (y + (m - 1 + n - 1) // 12), (m - 1 + n - 1) % 12 + 1
    return date(ey, em, monthrange(ey, em)[1])


def period_amounts(lease: Lease, y: int, m: int, n: int) -> dict[str, Decimal]:
    """Summe der (je Monat tagesanteilig gerundeten) Monatsbeträge der Periode → identisch zu n einzelnen Monats-Sollstellungen."""
    acc: dict[str, Decimal] = defaultdict(Decimal)
    cy, cm = y, m
    for _ in range(n):
        for t, v in monthly_components(lease, cy, cm).items():
            acc[t] += v
        cy, cm = (cy + 1, 1) if cm == 12 else (cy, cm + 1)
    return {k: q(v) for k, v in acc.items() if q(v) > 0}


def charge_key(lease_id: int, ctype: str, y: int, m: int, n: int) -> str:
    return f"{lease_id}:{ctype}:{y}-{m:02d}" if n == 1 else f"{lease_id}:{ctype}:{y}-{m:02d}+{n}m"


def generate_charges(db: Session, actor_id: int | None, *, from_month: date, through_month: date, lease_id: int | None = None,
                     today: date | None = None, dry_run: bool = False, forbid_backdated: bool = False) -> dict:
    """Erzeugt fehlende Sollstellungen je Vertragsrhythmus (monatlich, vierteljährlich, halbjährlich, jährlich); fällig am Fälligkeitstag des Periodenbeginns.
    Idempotent (dedupe_key) und überlappungsgeschützt: Bestehende Sollstellungen werden NIE verändert; abweichende Beträge oder Überschneidungen
    mit bestehenden Perioden (z. B. nach Rhythmuswechsel) werden als Konflikt gemeldet. `dry_run` schreibt nichts (Vorschau).
    `forbid_backdated`: rückwirkende Perioden (Ende vor dem aktuellen Monat) werden nur nach ausdrücklicher Bestätigung erzeugt."""
    today = today or date.today()
    if through_month < from_month:
        raise ServiceError("invalid", "Zeitraum ungültig.")
    if (through_month.year - today.year) * 12 + through_month.month - today.month > 12:
        raise ServiceError("invalid", "Sollstellungen dürfen höchstens 12 Monate im Voraus erzeugt werden.")
    stmt = select(Lease).where(Lease.status.in_(BILLABLE_STATUS))
    if lease_id:
        stmt = stmt.where(Lease.id == lease_id)
    plan, skipped, conflicts, errors, notes = [], 0, [], [], []
    this_month = date(today.year, today.month, 1)
    for lease in db.scalars(stmt.order_by(Lease.id)):
        rhythm = lease.payment_rhythm
        if rhythm not in domain.RHYTHM_MONTHS:
            notes.append({"lease_id": lease.id, "code": "on_demand", "message": f"Vertrag {lease.id}: Zahlungsrhythmus „{rhythm}“ – keine automatische Sollstellung."})
            continue
        if not lease.terms:
            errors.append({"lease_id": lease.id, "code": "no_terms", "message": f"Vertrag {lease.id} hat keine Mietkonditionen – Sollstellung nicht möglich."})
            continue
        if not 1 <= (lease.payment_due_day or 0) <= 31:
            errors.append({"lease_id": lease.id, "code": "bad_due_day", "message": f"Vertrag {lease.id}: ungültiger Fälligkeitstag."})
            continue
        end = effective_end(lease) or OPEN_END
        for y, m, n in period_months(rhythm, from_month, through_month):
            ps, pe = date(y, m, 1), _period_end(y, m, n)
            if ps > end or pe < lease.start_date:
                continue
            existing_all = list(db.scalars(select(Charge).where(Charge.lease_id == lease.id, Charge.voided_at.is_(None), Charge.period_start <= pe, Charge.period_end >= ps)))
            for ctype, amount in period_amounts(lease, y, m, n).items():
                key = charge_key(lease.id, ctype, y, m, n)
                same = [c for c in existing_all if c.charge_type == ctype and c.dedupe_key == key]
                if same:
                    if same[0].amount == amount:
                        skipped += 1
                    else:
                        conflicts.append({"charge_id": same[0].id, "lease_id": lease.id, "charge_type": ctype, "month": f"{y}-{m:02d}", "reason": "amount_differs",
                                          "existing_amount": same[0].amount, "calculated_amount": amount})
                    continue
                overlap = [c for c in existing_all if c.charge_type == ctype and c.source == "generated"]
                if overlap:  # andere Periodenlänge bereits abgerechnet → keine Doppelbuchung
                    conflicts.append({"charge_id": overlap[0].id, "lease_id": lease.id, "charge_type": ctype, "month": f"{y}-{m:02d}", "reason": "period_overlap",
                                      "existing_amount": overlap[0].amount, "calculated_amount": amount,
                                      "existing_period": f"{overlap[0].period_start} – {overlap[0].period_end}"})
                    continue
                plan.append({"lease_id": lease.id, "charge_type": ctype, "period_start": ps, "period_end": pe, "months": n, "amount": amount,
                             "due_date": max(due_date_for(lease, y, m), lease.start_date), "key": key, "direction": direction_for(lease), "backdated": pe < this_month})
    backdated = sum(1 for p in plan if p["backdated"])
    result = {"dry_run": dry_run, "would_create": [{k: v for k, v in p.items() if k != "key"} for p in plan], "would_create_count": len(plan), "backdated_count": backdated,
              "skipped_existing": skipped, "conflicts": conflicts, "errors": errors, "notes": notes}
    if dry_run:
        return result
    if forbid_backdated and backdated:
        raise ServiceError("backdated_confirmation_required", f"{backdated} Sollstellung(en) betreffen vergangene Zeiträume (rückwirkend). Bitte ausdrücklich bestätigen.", 409,
                           {"backdated_count": backdated})
    created = []
    for p in plan:
        c = Charge(lease_id=p["lease_id"], direction=p["direction"], charge_type=p["charge_type"], period_start=p["period_start"], period_end=p["period_end"],
                   due_date=p["due_date"], amount=p["amount"], dedupe_key=p["key"], source="generated", created_by_user_id=actor_id)
        db.add(c)
        created.append(c)
    db.flush()
    audit.record(db, "charge.generated", actor_user_id=actor_id, entity_type="charge",
                 summary=f"{len(created)} Sollstellungen erzeugt", details={"created": len(created), "skipped": skipped, "conflicts": len(conflicts), "backdated": backdated,
                                                                            "from": str(from_month), "through": str(through_month)})
    return {**result, "created": [c.id for c in created], "created_count": len(created)}


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


def arrears(db: Session, lease_id: int, today: date | None = None) -> dict:
    """Zahlungsstatus eines Untermietvertrags: überfällige Forderungen, die nach Teilzahlungen noch offen sind."""
    today = today or date.today()
    total, n = Decimal("0.00"), 0
    for c in db.scalars(select(Charge).where(Charge.lease_id == lease_id, Charge.direction == "receivable", Charge.voided_at.is_(None), Charge.due_date < today)):
        o = open_amount(db, c)
        if o > 0:
            total += o
            n += 1
    return {"status": "arrears" if n else "current", "amount": q(total), "count": n}


def arrears_bulk(db: Session, lease_ids: list[int], today: date | None = None) -> dict[int, dict]:
    """Wie `arrears`, aber für viele Verträge mit zwei Abfragen (statt einer je Vertrag)."""
    today = today or date.today()
    out = {i: {"status": "current", "amount": Decimal("0.00"), "count": 0} for i in lease_ids}
    if not lease_ids:
        return out
    alloc = dict(db.execute(select(PaymentAllocation.charge_id, func.sum(PaymentAllocation.amount)).where(PaymentAllocation.charge_id.is_not(None)).group_by(PaymentAllocation.charge_id)).all())
    for c in db.scalars(select(Charge).where(Charge.lease_id.in_(lease_ids), Charge.direction == "receivable", Charge.voided_at.is_(None), Charge.due_date < today)):
        o = q(c.amount - Decimal(alloc.get(c.id, 0)))
        if o > 0:
            r = out[c.lease_id]
            r["amount"], r["count"], r["status"] = q(r["amount"] + o), r["count"] + 1, "arrears"
    return out
