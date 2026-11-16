"""Aggregierte Mieterakte für das Detailpanel: Stammdaten, Verträge, Soll, Zahlungen, Offene Posten, Kaution, Dokumente, Aufgaben, Reparaturen, Aktivität.
Alles in wenigen, begrenzten Abfragen (keine Abfrage je Zeile)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from leventum import domain
from leventum.security.finance_access import FINANCE_DOC_TYPES
from leventum.models import (Charge, Deposit, Document, DocumentLink, Lease, LeaseItem, LeaseParty, Party, Payment, PaymentAllocation, Repair, Task)
from leventum.services import deposits as dep, history as H, leases as L, master as M
from leventum.services.charges import allocated_by_charge, arrears_bulk
from leventum.services.errors import NotFound
from leventum.services.utility import q

LIMIT = 15


def overview(db: Session, party_id: int, today: date | None = None, include_finance: bool = True) -> dict:
    """include_finance=False (Recht finance:read fehlt): keine Finanzabfragen; Ergebnis ohne Schlüssel 'finance', je Vertrag payment_status/overdue_amount/deposit = None.
    Der Soll-Wert 'monthly' (Vertragskonditionen, Stammdaten) bleibt."""
    today = today or date.today()
    party = db.get(Party, party_id)
    if party is None:
        raise NotFound("Partei")
    rows = db.execute(select(LeaseParty.role, Lease).join(Lease, Lease.id == LeaseParty.lease_id).where(LeaseParty.party_id == party_id, Lease.status != "cancelled")
                      .options(selectinload(Lease.items).joinedload(LeaseItem.rentable_unit), selectinload(Lease.terms), selectinload(Lease.utility_agreements),
                               selectinload(Lease.parties).joinedload(LeaseParty.party), selectinload(Lease.lease_type))).all()
    leases = sorted({l.id: (role, l) for role, l in rows}.values(), key=lambda rl: rl[1].start_date, reverse=True)
    lids = [l.id for _, l in leases]
    arrears = arrears_bulk(db, [l.id for r, l in leases if l.kind == "sub"], today) if include_finance else {}
    deposits = {d.lease_id: d for d in db.scalars(select(Deposit).where(Deposit.lease_id.in_(lids)).options(selectinload(Deposit.transactions)))} if lids and include_finance else {}
    lease_out = []
    for role, l in leases:
        ph = L.phase(l, today)
        d = deposits.get(l.id)
        lease_out.append({"id": l.id, "kind": l.kind, "role": role, "type": l.lease_type.name, "phase": ph, "status": l.status, "start_date": l.start_date, "end_date": L.effective_end(l),
                          "contract_number": l.contract_number, "spaces": [M.space_label(db, i.rentable_unit) for i in l.items],
                          "monthly": L.monthly_total(l, max(today, l.start_date)), "payment_rhythm": l.payment_rhythm,
                          "payment_status": arrears.get(l.id, {}).get("status"), "overdue_amount": arrears.get(l.id, {}).get("amount"),
                          "deposit": dep.summary(d, l, today) if d else None})
    sub_ids = [l.id for _, l in leases if l.kind == "sub"] if include_finance else []
    # Offene Posten (Forderungen) und letzte Zahlungseingänge
    # Zahlungen wirken erst ab ihrem Buchungsdatum (Stichtag heute) – wie Dashboard, Forderungsliste und Mahnwesen (Entscheidung Phase I 2.3; Review-Befund F-1)
    alloc = allocated_by_charge(db, None, today) if sub_ids else {}
    open_items, open_total, overdue_total = [], Decimal("0.00"), Decimal("0.00")
    if sub_ids:
        for c in db.scalars(select(Charge).where(Charge.lease_id.in_(sub_ids), Charge.direction == "receivable", Charge.voided_at.is_(None)).order_by(Charge.due_date)):
            o = q(c.amount - Decimal(alloc.get(c.id, 0)))
            if o > 0:
                open_total = q(open_total + o)
                if c.due_date < today:
                    overdue_total = q(overdue_total + o)
                if len(open_items) < LIMIT:
                    open_items.append({"charge_id": c.id, "lease_id": c.lease_id, "charge_type": c.charge_type, "period_start": c.period_start, "due_date": c.due_date, "amount": c.amount, "open_amount": o,
                                       "overdue": c.due_date < today})
    payments = []
    if sub_ids:
        pay_rows = db.execute(select(Payment.id, Payment.booking_date, Payment.amount, Payment.is_reversal, func.sum(PaymentAllocation.amount))
                              .join(PaymentAllocation, PaymentAllocation.payment_id == Payment.id).join(Charge, Charge.id == PaymentAllocation.charge_id)
                              .where(Charge.lease_id.in_(sub_ids), Payment.direction == "in").group_by(Payment.id).order_by(Payment.booking_date.desc(), Payment.id.desc()).limit(LIMIT)).all()
        payments = [{"payment_id": i, "booking_date": bd, "amount": a, "is_reversal": rev, "allocated": q(Decimal(al))} for i, bd, a, rev, al in pay_rows]
    doc_stmt = select(Document).join(DocumentLink).where(Document.deleted_at.is_(None), or_(
        (DocumentLink.entity_type == "party") & (DocumentLink.entity_id == party_id), (DocumentLink.entity_type == "lease") & (DocumentLink.entity_id.in_(lids or [-1]))))
    if not include_finance:  # Finanzdokumente (Rechnung, BK-Abrechnung, Kaution) ohne finance:read ausblenden
        doc_stmt = doc_stmt.where(Document.doc_type.not_in(sorted(FINANCE_DOC_TYPES)))
    docs = db.scalars(doc_stmt.order_by(Document.id.desc()).limit(LIMIT)).unique().all()
    tasks = db.scalars(select(Task).where(Task.status.in_(domain.TASK_OPEN), or_(Task.party_id == party_id, Task.lease_id.in_(lids or [-1]))).order_by(Task.due_date.is_(None), Task.due_date).limit(LIMIT)).all()
    repairs = db.scalars(select(Repair).where(or_(Repair.reported_by_party_id == party_id, Repair.lease_id.in_(lids or [-1]))).order_by(Repair.reported_on.desc()).limit(LIMIT)).all()
    out = {"party": party, "roles": sorted(r.role for r in party.roles), "leases": lease_out,
           "documents": docs, "tasks": tasks, "repairs": repairs, "activity": H.party_timeline(db, party_id, limit=LIMIT, include_finance=include_finance)}
    if include_finance:
        out["finance"] = {"open_total": open_total, "overdue_total": overdue_total, "open_items": open_items, "recent_payments": payments,
                          "monthly_soll_total": q(sum((x["monthly"]["total"] for x in lease_out if x["phase"] in ("active", "notice") and x["kind"] == "sub" and x["monthly"].get("available")), Decimal(0)))}
    return out
