from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select

from leventum.models import Charge, Payment, PaymentAllocation
from leventum.services import charges as C, leases as L, payments as P
from leventum.services.errors import ServiceError
from tests.helpers import World

TODAY = date(2026, 3, 15)


@pytest.fixture
def w(app):
    w = World(app)
    yield w
    w.db.close()


def setup_leases(w, rent=D("1150.00"), nk=D("220.00"), start=date(2026, 1, 1), nk_mode="prepayment"):
    main = w.activate_main()
    sub = w.sub([w.ru_unit(w.we2)], [w.tenant("Max Mustermann")], start, None, rent=rent, nk=nk, nk_mode=nk_mode)
    return main, sub


def gen(w, a=date(2026, 1, 1), b=date(2026, 3, 1), **kw):
    return C.generate_charges(w.db, None, from_month=a, through_month=b, today=TODAY, **kw)


def count(w, model=Charge):
    return w.db.scalar(select(func.count()).select_from(model))


# ---- Sollbetrag / Cent-Rechnung -----------------------------------------------------------------------------------------------------
def test_monthly_components_full_and_partial_months(w):
    main, sub = setup_leases(w, start=date(2026, 1, 16))
    assert C.monthly_components(sub, 2026, 2) == {"base_rent": D("1150.00"), "utility_prepayment": D("220.00")}
    jan = C.monthly_components(sub, 2026, 1)  # 16 von 31 Tagen
    assert jan == {"base_rent": D("593.55"), "utility_prepayment": D("113.55")}  # 1150×16/31=593.548…, 220×16/31=113.548…
    assert C.monthly_components(sub, 2025, 12) == {}


def test_rent_change_mid_month_is_one_amount_rounded_once(w):
    main, sub = setup_leases(w)
    L.add_term(w.db, None, sub.id, valid_from=date(2026, 3, 11), valid_to=None, base_rent=D("1250.00"))
    mar = C.monthly_components(sub, 2026, 3)["base_rent"]
    assert mar == (D("1150") * 10 / 31 + D("1250") * 21 / 31).quantize(D("0.01"))
    assert mar == D("1217.74")  # 370,968 + 846,774


def test_contract_end_and_termination_prorate(w):
    main, sub = setup_leases(w)
    L.terminate_lease(w.db, None, sub.id, terminated_on=date(2026, 2, 1), effective_on=date(2026, 3, 10))
    assert C.monthly_components(sub, 2026, 3)["base_rent"] == (D("1150") * 10 / 31).quantize(D("0.01")) == D("370.97")
    assert C.monthly_components(sub, 2026, 4) == {}


def test_day_based_rent_and_included_or_individual_utility_create_no_utility_charge(w):
    w.activate_main()
    s = w.sub([w.ru_bed(w.bed1)], [w.tenant("A B")], date(2026, 1, 1), date(2026, 1, 31), type_code="boardinghouse", rent=D("45.00"), nk_mode="included", activate=True)
    s.terms[0].rent_period = "day"
    assert C.monthly_components(s, 2026, 1) == {"base_rent": D("1395.00")}  # 31 Tage × 45
    for mode in ("individual", "none"):
        s2 = w.sub([w.ru_bed(w.bed2)], [w.tenant("C D")], date(2026, 2, 1), date(2026, 2, 28), type_code="bett", nk_mode=mode, activate=False)
        assert "utility_prepayment" not in C.monthly_components(s2, 2026, 2) and "utility_flat_rate" not in C.monthly_components(s2, 2026, 2)
        w.db.delete(s2)
        w.db.flush()


# ---- Erzeugung ------------------------------------------------------------------------------------------------------------------------------------
def test_generation_example_850_180_vs_1150_220_separate_directions(w):
    setup_leases(w)
    r = gen(w, b=date(2026, 1, 1))
    assert r["created_count"] == 4
    rows = w.db.scalars(select(Charge).order_by(Charge.id)).all()
    got = {(c.direction, c.charge_type): c.amount for c in rows}
    assert got == {("payable", "base_rent"): D("850.00"), ("payable", "utility_prepayment"): D("180.00"),
                   ("receivable", "base_rent"): D("1150.00"), ("receivable", "utility_prepayment"): D("220.00")}
    assert all(c.due_date == date(2026, 1, 1) for c in rows)


def test_generation_is_idempotent_no_duplicate_charges(w):
    setup_leases(w)
    first = gen(w)
    second = gen(w)
    third = gen(w, lease_id=2)
    assert first["created_count"] == 12 and second["created_count"] == 0 and second["skipped_existing"] == 12 and third["created_count"] == 0
    assert count(w) == 12


def test_db_enforces_unique_active_charge(w):
    setup_leases(w)
    gen(w, b=date(2026, 1, 1))
    from sqlalchemy.exc import IntegrityError
    c = w.db.scalars(select(Charge)).first()
    w.db.add(Charge(lease_id=c.lease_id, direction=c.direction, charge_type=c.charge_type, period_start=c.period_start, period_end=c.period_end,
                    due_date=c.due_date, amount=c.amount, dedupe_key=c.dedupe_key))
    with pytest.raises(IntegrityError):
        w.db.flush()


def test_existing_charge_is_not_overwritten_after_term_change_conflict_reported(w):
    main, sub = setup_leases(w)
    gen(w, b=date(2026, 3, 1))
    L.add_term(w.db, None, sub.id, valid_from=date(2026, 3, 1), valid_to=None, base_rent=D("1200.00"))
    r = gen(w, b=date(2026, 3, 1))
    assert r["created_count"] == 0 and len(r["conflicts"]) == 1
    cf = r["conflicts"][0]
    assert (cf["existing_amount"], cf["calculated_amount"], cf["month"]) == (D("1150.00"), D("1200.00"), "2026-03")
    ch = w.db.get(Charge, cf["charge_id"])
    assert ch.amount == D("1150.00")  # unverändert
    C.void_charge(w.db, None, ch.id, "Mieterhöhung ab März")
    r2 = gen(w, b=date(2026, 3, 1))
    assert r2["created_count"] == 1 and r2["conflicts"] == []
    assert w.db.scalars(select(Charge).where(Charge.lease_id == sub.id, Charge.charge_type == "base_rent", Charge.voided_at.is_(None), Charge.period_start == date(2026, 3, 1))).one().amount == D("1200.00")


def test_drafts_cancelled_and_not_started_months_are_not_billed(w):
    w.activate_main()
    draft = w.sub([w.ru_unit(w.we2)], [w.tenant("A B")], date(2026, 1, 1), None, activate=False)
    r = gen(w)
    assert all(c.lease_id != draft.id for c in w.db.scalars(select(Charge)))
    setup_leases(w, start=date(2026, 3, 1))  # Vertrag beginnt erst im März → keine Januar/Februar-Sollstellungen der Untermiete
    # (setup_leases legt weiteren Hauptvertrag + Untermiete an; Untermiete nur ab März)
    w.db.flush()
    gen(w)
    sub_months = {c.period_start.month for c in w.db.scalars(select(Charge).where(Charge.direction == "receivable"))}
    assert sub_months == {3}


def test_generation_horizon_limit(w):
    setup_leases(w)
    with pytest.raises(ServiceError):
        C.generate_charges(w.db, None, from_month=date(2026, 1, 1), through_month=date(2027, 12, 1), today=TODAY)


def test_void_requires_reason_and_no_allocations(w):
    setup_leases(w)
    gen(w, b=date(2026, 1, 1))
    ch = w.db.scalars(select(Charge).where(Charge.direction == "receivable", Charge.charge_type == "base_rent")).one()
    p = P.create_payment(w.db, None, direction="in", booking_date=date(2026, 1, 3), amount=D("100.00"), allocations=[{"charge_id": ch.id, "amount": D("100.00")}])
    with pytest.raises(ServiceError) as e:
        C.void_charge(w.db, None, ch.id, "Fehler")
    assert e.value.code == "has_allocations"
    with pytest.raises(ServiceError):
        C.void_charge(w.db, None, ch.id, "  ")
    assert p.id


# ---- Zahlungen / Teilzahlungen / Storno ----------------------------------------------------------------------------------------------------------
def rent_charge(w):
    setup_leases(w)
    gen(w, b=date(2026, 1, 1))
    return w.db.scalars(select(Charge).where(Charge.direction == "receivable", Charge.charge_type == "base_rent")).one()


def test_partial_payment_then_rest_exact_cents(w):
    ch = rent_charge(w)
    P.create_payment(w.db, None, direction="in", booking_date=date(2026, 1, 5), amount=D("400.33"), allocations=[{"charge_id": ch.id, "amount": D("400.33")}])
    assert C.open_amount(w.db, ch) == D("749.67") and C.allocated(w.db, ch.id) == D("400.33")
    P.create_payment(w.db, None, direction="in", booking_date=date(2026, 1, 20), amount=D("749.67"), allocations=[{"charge_id": ch.id, "amount": D("749.67")}])
    assert C.open_amount(w.db, ch) == D("0.00")


def test_open_amount_respects_as_of_date(w):
    ch = rent_charge(w)
    P.create_payment(w.db, None, direction="in", booking_date=date(2026, 1, 20), amount=D("1150.00"), allocations=[{"charge_id": ch.id, "amount": D("1150.00")}])
    assert C.open_amount(w.db, ch, date(2026, 1, 10)) == D("1150.00") and C.open_amount(w.db, ch, date(2026, 1, 20)) == D("0.00")


def test_overpayment_cannot_be_allocated_beyond_open_remainder_stays_unallocated(w):
    ch = rent_charge(w)
    p = P.create_payment(w.db, None, direction="in", booking_date=date(2026, 1, 5), amount=D("1300.00"))
    with pytest.raises(ServiceError) as e:
        P.allocate(w.db, None, p.id, charge_id=ch.id, amount=D("1300.00"))
    assert e.value.code == "exceeds_open"
    P.allocate(w.db, None, p.id, charge_id=ch.id, amount=D("1150.00"))
    v = P.payment_view(w.db, p)
    assert v["allocated"] == D("1150.00") and v["unallocated"] == D("150.00")  # Überzahlung = Guthaben des Zahlers, nicht verschwunden
    with pytest.raises(ServiceError) as e:
        P.allocate(w.db, None, p.id, charge_id=ch.id, amount=D("200.00"))
    assert e.value.code in ("exceeds_open", "exceeds_payment")


def test_direction_and_target_validation(w):
    ch = rent_charge(w)
    out = P.create_payment(w.db, None, direction="out", booking_date=date(2026, 1, 5), amount=D("100.00"))
    with pytest.raises(ServiceError) as e:
        P.allocate(w.db, None, out.id, charge_id=ch.id, amount=D("100.00"))
    assert e.value.code == "direction_mismatch"
    inn = P.create_payment(w.db, None, direction="in", booking_date=date(2026, 1, 6), amount=D("100.00"))
    with pytest.raises(ServiceError):
        P.allocate(w.db, None, inn.id, charge_id=ch.id, invoice_id=1, amount=D("1.00"))
    with pytest.raises(ServiceError):
        P.allocate(w.db, None, inn.id, amount=D("1.00"))
    with pytest.raises(ServiceError) as e:
        P.create_payment(w.db, None, direction="in", booking_date=date(2026, 1, 6), amount=D("0.00"))


def test_possible_duplicate_manual_payment_blocked_unless_accepted(w):
    kw = dict(direction="in", booking_date=date(2026, 1, 6), amount=D("100.00"), reference="Miete Jan")
    P.create_payment(w.db, None, **kw)
    with pytest.raises(ServiceError) as e:
        P.create_payment(w.db, None, **kw)
    assert e.value.code == "possible_duplicate"
    assert P.create_payment(w.db, None, accept_possible_duplicate=True, **kw).id


def test_reversal_is_counter_booking_original_untouched_and_open_amount_restored(w):
    ch = rent_charge(w)
    p = P.create_payment(w.db, None, direction="in", booking_date=date(2026, 1, 5), amount=D("1150.00"), allocations=[{"charge_id": ch.id, "amount": D("1150.00")}])
    assert C.open_amount(w.db, ch) == 0
    rev = P.reverse_payment(w.db, None, p.id, reason="Rücklastschrift", booking_date=date(2026, 1, 12))
    assert rev.is_reversal and rev.reverses_payment_id == p.id and rev.amount == D("1150.00")
    assert p.amount == D("1150.00") and p.booking_date == date(2026, 1, 5)  # Original unverändert
    assert C.open_amount(w.db, ch) == D("1150.00") and C.open_amount(w.db, ch, date(2026, 1, 8)) == 0  # historischer Stand bleibt nachvollziehbar
    assert P.payment_view(w.db, p)["reversed"] is True and P.payment_view(w.db, rev)["signed_amount"] == D("-1150.00")
    for fn in (lambda: P.reverse_payment(w.db, None, p.id, reason="x"), lambda: P.reverse_payment(w.db, None, rev.id, reason="x"),
               lambda: P.allocate(w.db, None, p.id, charge_id=ch.id, amount=D("1.00"))):
        with pytest.raises(ServiceError):
            fn()
    assert count(w, Payment) == 2  # nichts gelöscht


def test_deallocate_is_append_only_and_validated(w):
    ch = rent_charge(w)
    p = P.create_payment(w.db, None, direction="in", booking_date=date(2026, 1, 5), amount=D("500.00"), allocations=[{"charge_id": ch.id, "amount": D("500.00")}])
    with pytest.raises(ServiceError):
        P.deallocate(w.db, None, p.id, charge_id=ch.id, amount=D("600.00"), reason="x")
    P.deallocate(w.db, None, p.id, charge_id=ch.id, amount=D("200.00"), reason="falsche Sollstellung")
    rows = w.db.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == p.id).order_by(PaymentAllocation.id)).all()
    assert [r.amount for r in rows] == [D("500.00"), D("-200.00")]
    assert C.open_amount(w.db, ch) == D("850.00") and P.payment_view(w.db, p)["unallocated"] == D("200.00")


def test_invoice_payment_and_duplicates(w):
    sup = __import__("leventum.services.master", fromlist=["x"]).create_party(w.db, None, {"kind": "company", "company_name": "Sanitär GmbH"}, ["service_provider"])
    inv = P.create_invoice(w.db, None, property_id=w.prop.id, unit_id=w.we1.id, supplier_party_id=sup.id, invoice_number="R-1", amount=D("238.00"), invoice_date=date(2026, 2, 1))
    with pytest.raises(ServiceError) as e:
        P.create_invoice(w.db, None, property_id=w.prop.id, supplier_party_id=sup.id, invoice_number="R-1", amount=D("1.00"), invoice_date=date(2026, 2, 1))
    assert e.value.code == "duplicate"
    p = P.create_payment(w.db, None, direction="out", booking_date=date(2026, 2, 10), amount=D("100.00"), allocations=[{"invoice_id": inv.id, "amount": D("100.00")}])
    assert P.invoice_open(w.db, inv) == D("138.00")
    with pytest.raises(ServiceError):
        P.allocate(w.db, None, p.id, invoice_id=inv.id, amount=D("1.00"))  # Zahlung ist ausgeschöpft
    inn = P.create_payment(w.db, None, direction="in", booking_date=date(2026, 2, 11), amount=D("5.00"))
    with pytest.raises(ServiceError):
        P.allocate(w.db, None, inn.id, invoice_id=inv.id, amount=D("5.00"))
    with pytest.raises(ServiceError):  # Einheit eines anderen Objekts
        other = __import__("leventum.services.master", fromlist=["x"])
        o = other.create_property(w.db, None, {"name": "X", "property_type": "wohnung"})
        P.create_invoice(w.db, None, property_id=o.id, unit_id=w.we1.id, amount=D("1.00"), invoice_date=date(2026, 2, 1))
