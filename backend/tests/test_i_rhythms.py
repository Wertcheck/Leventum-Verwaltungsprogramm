"""Abrechnungsrhythmen (Master-Review C3): vierteljährlich, halbjährlich, jährlich – Vorschau, Überlappungsschutz, Rückwirkung."""
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select

from leventum.models import Charge
from leventum.services import charges as C, economics as E, leases as L
from leventum.services.errors import ServiceError
from tests.helpers import World

TODAY = date(2026, 3, 10)


@pytest.fixture
def w(app):
    w = World(app)
    w.activate_main()
    yield w
    w.db.close()


def sub(w, rhythm, start=date(2026, 1, 1), end=None, unit=None, rent=D("1150.00"), nk=D("220.00"), name="Max Mustermann", **kw):
    return w.sub([w.ru_unit(unit or w.we2)], [w.tenant(name)], start, end, rent=rent, nk=nk, payment_rhythm=rhythm, **kw)


def gen(w, a, b, lease=None, **kw):
    return C.generate_charges(w.db, None, from_month=a, through_month=b, lease_id=lease.id if lease else None, today=kw.pop("today", TODAY), **kw)


def charges(w, lease, ctype=None):
    stmt = select(Charge).where(Charge.lease_id == lease.id, Charge.voided_at.is_(None)).order_by(Charge.period_start, Charge.charge_type)
    return [c for c in w.db.scalars(stmt) if ctype is None or c.charge_type == ctype]


def test_period_start_months_are_calendar_aligned():
    f = lambda r, a, b: [(y, m, n) for y, m, n in C.period_months(r, a, b)]
    assert f("quarterly", date(2026, 1, 1), date(2026, 12, 1)) == [(2026, 1, 3), (2026, 4, 3), (2026, 7, 3), (2026, 10, 3)]
    assert f("half_yearly", date(2026, 1, 1), date(2027, 6, 1)) == [(2026, 1, 6), (2026, 7, 6), (2027, 1, 6)]
    assert f("yearly", date(2026, 1, 1), date(2027, 12, 1)) == [(2026, 1, 12), (2027, 1, 12)]
    assert f("monthly", date(2026, 2, 1), date(2026, 4, 1)) == [(2026, 2, 1), (2026, 3, 1), (2026, 4, 1)]
    assert f("quarterly", date(2026, 2, 1), date(2026, 3, 1)) == []  # keine Periode beginnt im Bereich
    assert C._period_end(2026, 10, 3) == date(2026, 12, 31) and C._period_end(2026, 11, 3) == date(2027, 1, 31)


@pytest.mark.parametrize("rhythm,n,first_due", [("quarterly", 3, date(2026, 1, 1)), ("half_yearly", 6, date(2026, 1, 1)), ("yearly", 12, date(2026, 1, 1))])
def test_full_period_amounts_are_n_times_monthly_and_due_at_period_start(w, rhythm, n, first_due):
    s = sub(w, rhythm)
    r = gen(w, date(2026, 1, 1), date(2026, 1, 1), s, forbid_backdated=False)
    got = {c.charge_type: c for c in charges(w, s)}
    assert got["base_rent"].amount == D("1150.00") * n and got["utility_prepayment"].amount == D("220.00") * n
    assert (got["base_rent"].period_start, got["base_rent"].due_date) == (date(2026, 1, 1), first_due)
    assert got["base_rent"].period_end == C._period_end(2026, 1, n) and r["created_count"] == 2


def test_quarterly_total_equals_monthly_total_over_a_year(w):
    q_ = sub(w, "quarterly", name="Quartal Mieter")
    m_ = sub(w, "monthly", unit=w.we1, name="Monat Mieter")
    gen(w, date(2026, 1, 1), date(2026, 12, 1), q_, today=date(2026, 1, 5)); gen(w, date(2026, 1, 1), date(2026, 12, 1), m_, today=date(2026, 1, 5))
    total = lambda lease: sum(c.amount for c in charges(w, lease))
    assert total(q_) == total(m_) == (D("1150.00") + D("220.00")) * 12
    assert len(charges(w, q_)) == 8 and len(charges(w, m_)) == 24  # 4 Quartale × 2 Arten vs. 12 Monate × 2 Arten


def test_mid_period_start_and_end_are_prorated_per_month_and_cent_exact(w):
    s = sub(w, "quarterly", start=date(2026, 2, 15), end=date(2026, 5, 20), rent=D("1000.00"), nk=D("201.00"))
    gen(w, date(2026, 1, 1), date(2026, 4, 1), s)
    by = {(c.charge_type, c.period_start): c for c in charges(w, s)}
    feb = D("1000") * 14 / 28  # 15.–28.2. = 14 Tage
    q1 = (feb + D("1000")).quantize(D("0.01"))  # Jan: vor Vertragsbeginn = 0; Feb anteilig 500; März voll 1000
    assert q1 == D("1500.00") and by[("base_rent", date(2026, 1, 1))].amount == q1
    may = (D("1000") * 20 / 31).quantize(D("0.01"))  # 1.–20.5.
    assert by[("base_rent", date(2026, 4, 1))].amount == D("1000") + may == D("1645.16")  # April voll + Mai anteilig; Juni nach Vertragsende = 0
    # Einzelrundung je Monat, nicht Rundung der Summe: NK 201 × 14/28 = 100.50, Mär/Apr/Mai je volle bzw. anteilige Beträge
    nk_q1 = by[("utility_prepayment", date(2026, 1, 1))].amount
    assert nk_q1 == D("100.50") + D("201.00")
    assert by[("base_rent", date(2026, 1, 1))].due_date == date(2026, 2, 15)  # Fälligkeit nicht vor Vertragsbeginn


def test_generation_is_idempotent_and_never_creates_duplicates(w):
    s = sub(w, "quarterly")
    a = gen(w, date(2026, 1, 1), date(2026, 12, 1), s, today=date(2026, 1, 5))
    b = gen(w, date(2026, 1, 1), date(2026, 12, 1), s, today=date(2026, 1, 5))
    assert a["created_count"] == 8 and b["created_count"] == 0 and b["skipped_existing"] == 8
    assert w.db.scalar(select(func.count()).select_from(Charge).where(Charge.lease_id == s.id)) == 8


def test_rhythm_change_cannot_double_bill_overlapping_periods(w):
    s = sub(w, "monthly")
    gen(w, date(2026, 1, 1), date(2026, 2, 1), s)  # Jan + Feb monatlich erzeugt
    s.payment_rhythm = "quarterly"
    r = gen(w, date(2026, 1, 1), date(2026, 3, 1), s)
    assert r["created_count"] == 0 and {c["reason"] for c in r["conflicts"]} == {"period_overlap"} and len(r["conflicts"]) == 2
    assert "existing_period" in r["conflicts"][0]
    r2 = gen(w, date(2026, 4, 1), date(2026, 4, 1), s)  # ab dem nächsten Quartal ohne Überschneidung
    assert r2["created_count"] == 2 and not r2["conflicts"]
    assert sum(c.amount for c in charges(w, s, "base_rent") if c.period_start < date(2026, 3, 1)) == D("2300.00")  # unverändert


def test_conflict_when_terms_changed_after_generation_without_overwrite(w):
    s = sub(w, "quarterly")
    gen(w, date(2026, 1, 1), date(2026, 1, 1), s)
    L.add_term(w.db, None, s.id, valid_from=date(2026, 3, 1), valid_to=None, base_rent=D("1200.00"))
    r = gen(w, date(2026, 1, 1), date(2026, 1, 1), s)
    assert r["created_count"] == 0 and r["conflicts"][0]["reason"] == "amount_differs"
    old = charges(w, s, "base_rent")[0]
    assert old.amount == D("3450.00")  # nicht überschrieben
    assert r["conflicts"][0]["calculated_amount"] == D("1150") * 2 + D("1200")


def test_preview_writes_nothing_and_matches_real_generation(w):
    s = sub(w, "half_yearly")
    before = w.db.scalar(select(func.count()).select_from(Charge))
    pv = gen(w, date(2026, 1, 1), date(2026, 7, 1), s, dry_run=True)
    assert w.db.scalar(select(func.count()).select_from(Charge)) == before and pv["dry_run"] is True and pv["would_create_count"] == 4
    real = gen(w, date(2026, 1, 1), date(2026, 7, 1), s)
    assert real["created_count"] == 4
    assert {(x["charge_type"], x["period_start"], x["period_end"], x["amount"], x["due_date"]) for x in pv["would_create"]} == \
        {(c.charge_type, c.period_start, c.period_end, c.amount, c.due_date) for c in charges(w, s)}  # Vorschau = tatsächliches Ergebnis


def test_backdated_requires_explicit_confirmation(w):
    s = sub(w, "monthly")
    pv = gen(w, date(2026, 1, 1), date(2026, 3, 1), s, dry_run=True)
    assert pv["backdated_count"] == 4 and pv["would_create_count"] == 6  # Jan, Feb sind vergangen (heute = 10.3.), März läuft
    with pytest.raises(ServiceError) as e:
        gen(w, date(2026, 1, 1), date(2026, 3, 1), s, forbid_backdated=True)
    assert e.value.code == "backdated_confirmation_required" and e.value.details["backdated_count"] == 4
    assert w.db.scalar(select(func.count()).select_from(Charge).where(Charge.lease_id == s.id)) == 0  # nichts geschrieben
    assert gen(w, date(2026, 3, 1), date(2026, 3, 1), s, forbid_backdated=True)["created_count"] == 2  # laufender Monat ohne Bestätigung
    assert gen(w, date(2026, 1, 1), date(2026, 2, 1), s, forbid_backdated=False)["created_count"] == 4  # mit Bestätigung


def test_incomplete_contract_data_gives_clear_errors_and_on_demand_is_skipped(w):
    from leventum.models import Lease
    nt = w.sub([w.ru_unit(w.we1)], [w.tenant("Ohne Konditionen")], date(2026, 1, 1), None, nk_mode=None, activate=False)
    nt.status = "active"  # aktiv ohne Mietkonditionen (z. B. am Service vorbei)
    nt.terms.clear()
    od = sub(w, "on_demand", unit=w.we2, name="Nach Bedarf")
    r = gen(w, date(2026, 1, 1), date(2026, 1, 1), dry_run=True)
    assert any(e["code"] == "no_terms" and e["lease_id"] == nt.id for e in r["errors"])
    assert any(n["code"] == "on_demand" and n["lease_id"] == od.id for n in r["notes"])
    assert all(c["lease_id"] not in (nt.id, od.id) for c in r["would_create"])


def test_economics_soll_over_full_quarter_equals_quarterly_charges(w):
    s = sub(w, "quarterly")
    gen(w, date(2026, 1, 1), date(2026, 1, 1), s)
    rep = E.Engine(w.db, date(2026, 1, 1), date(2026, 3, 31), today=date(2026, 12, 31)).report("portfolio")
    assert rep["soll"]["sub_total"] == sum(c.amount for c in charges(w, s)) == D("4110.00")  # Soll (monatlich abgegrenzt) = Quartals-Sollstellung
