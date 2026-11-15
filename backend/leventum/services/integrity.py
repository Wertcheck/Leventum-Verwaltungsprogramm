"""Datenintegritätsprüfung (nur lesend). Findet Zustände, die die Services verhindern sollen, falls sie auf anderem Weg entstanden sind."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from leventum import domain
from leventum.models import Bed, Charge, Invoice, Lease, Payment, PaymentAllocation, RentableUnit, Room, Unit
from leventum.services.leases import _span, overlaps
from leventum.services.master import chain, space_key_for, spatially_related


def check(db: Session) -> dict:
    f: list[dict] = []
    add = lambda code, msg, **ref: f.append({"code": code, "message": msg, **ref})
    units = {u.id: u for u in db.scalars(select(Unit))}
    rooms = {r.id: r for r in db.scalars(select(Room))}
    beds = {b.id: b for b in db.scalars(select(Bed))}
    for r in rooms.values():
        if r.unit_id not in units:
            add("orphan_room", f"Zimmer {r.id} hat keine Wohneinheit.", room_id=r.id)
        elif r.is_active and not units[r.unit_id].is_active:
            add("active_room_inactive_unit", f"Zimmer {r.id} ist aktiv, seine Wohneinheit nicht.", room_id=r.id)
    for b in beds.values():
        if b.room_id not in rooms:
            add("orphan_bed", f"Bett {b.id} hat kein Zimmer.", bed_id=b.id)
        elif b.is_active and not rooms[b.room_id].is_active:
            add("active_bed_inactive_room", f"Bett {b.id} ist aktiv, sein Zimmer nicht.", bed_id=b.id)
    seen: dict[str, int] = {}
    rus = list(db.scalars(select(RentableUnit)))
    for ru in rus:
        key = space_key_for(ru.property_id, ru.unit_id, ru.room_id, ru.bed_id)
        if ru.space_key != key:
            add("space_key_mismatch", f"Vermietungseinheit {ru.id}: Schlüssel {ru.space_key!r} ≠ {key!r}.", rentable_unit_id=ru.id)
        if key in seen:
            add("duplicate_rentable_unit", f"Vermietungseinheit {ru.id} doppelt zu {seen[key]} ({key}).", rentable_unit_id=ru.id)
        seen[key] = ru.id
        u, r, b = units.get(ru.unit_id), rooms.get(ru.room_id), beds.get(ru.bed_id)
        if ru.unit_id and (u is None or u.property_id != ru.property_id):
            add("bad_parent_chain", f"Vermietungseinheit {ru.id}: Wohneinheit gehört nicht zum Objekt.", rentable_unit_id=ru.id)
        if ru.room_id and (r is None or r.unit_id != ru.unit_id):
            add("bad_parent_chain", f"Vermietungseinheit {ru.id}: Zimmer gehört nicht zur Wohneinheit.", rentable_unit_id=ru.id)
        if ru.bed_id and (b is None or b.room_id != ru.room_id):
            add("bad_parent_chain", f"Vermietungseinheit {ru.id}: Bett gehört nicht zum Zimmer.", rentable_unit_id=ru.id)
    # Überschneidende laufende Untermietverträge (sollte der Service verhindern)
    subs = list(db.scalars(select(Lease).where(Lease.kind == "sub", Lease.status.in_(domain.RUNNING_STATUS))))
    for i, a in enumerate(subs):
        for b in subs[i + 1:]:
            if overlaps(_span(a), _span(b)) and any(spatially_related(x.rentable_unit, y.rentable_unit) for x in a.items for y in b.items):
                add("overlapping_subleases", f"Untermietverträge {a.id} und {b.id} überschneiden sich räumlich und zeitlich.", lease_ids=[a.id, b.id])
    # Finanzen
    for c in db.scalars(select(Charge).where(Charge.voided_at.is_not(None), Charge.dedupe_key.is_not(None))):
        add("voided_charge_with_key", f"Stornierte Sollstellung {c.id} blockiert noch ihren Duplikatschlüssel.", charge_id=c.id)
    for cid, total in db.execute(select(PaymentAllocation.charge_id, func.sum(PaymentAllocation.amount)).where(PaymentAllocation.charge_id.is_not(None)).group_by(PaymentAllocation.charge_id)):
        c = db.get(Charge, cid)
        if Decimal(total) > c.amount or Decimal(total) < 0:
            add("charge_over_allocated", f"Sollstellung {cid}: zugeordnet {Decimal(total)} bei Betrag {c.amount}.", charge_id=cid)
    for iid, total in db.execute(select(PaymentAllocation.invoice_id, func.sum(PaymentAllocation.amount)).where(PaymentAllocation.invoice_id.is_not(None)).group_by(PaymentAllocation.invoice_id)):
        inv = db.get(Invoice, iid)
        if Decimal(total) > inv.amount or Decimal(total) < 0:
            add("invoice_over_allocated", f"Rechnung {iid}: zugeordnet {Decimal(total)} bei Betrag {inv.amount}.", invoice_id=iid)
    for pid, total in db.execute(select(PaymentAllocation.payment_id, func.sum(PaymentAllocation.amount)).group_by(PaymentAllocation.payment_id)):
        p = db.get(Payment, pid)
        signed = -p.amount if p.is_reversal else p.amount
        if abs(Decimal(total)) > abs(signed):
            add("payment_over_allocated", f"Zahlung {pid}: zugeordnet {Decimal(total)} bei Betrag {signed}.", payment_id=pid)
    return {"ok": not f, "findings": f, "checked": {"rentable_units": len(rus), "rooms": len(rooms), "beds": len(beds), "running_subleases": len(subs)}}
