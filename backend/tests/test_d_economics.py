"""Wirtschaftlichkeit/Leerstand. Alle Erwartungswerte sind von Hand nachgerechnet (siehe Kommentare)."""
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from leventum.models import Charge, UtilityStatement
from leventum.services import charges as C, economics as E, leases as L, master as M, payments as P, utility as U
from leventum.services.errors import ServiceError
from tests.helpers import World

JAN = (date(2026, 1, 1), date(2026, 1, 31))
JAN_FEB = (date(2026, 1, 1), date(2026, 2, 28))


@pytest.fixture
def w(app):
    w = World(app)
    w.prop.is_active = False  # Standardobjekt der Testwelt soll Kennzahlen nicht verfälschen
    yield w
    w.db.close()


def prop(w, name="Eco"):
    return M.create_property(w.db, None, {"name": name, "property_type": "mehrfamilienhaus", "owner_party_id": w.owner.id})


def unit(w, p, num, area=None):
    return M.create_unit(w.db, None, p.id, {"unit_number": num, "living_area": D(area) if area else None})


def ru(w, p, u=None, room=None, bed=None):
    return M.ensure_rentable_unit(w.db, None, property_id=p.id, unit_id=u.id if u else None, room_id=room.id if room else None, bed_id=bed.id if bed else None)


def rep(w, scope="portfolio", id_=None, period=JAN):
    return E.Engine(w.db, *period).report(scope, id_)


def main_on(w, rus, rent, nk=None, start=date(2025, 1, 1), end=None, **kw):
    lease = w.main(rus=rus, start=start, end=end, rent=D(rent), nk=D(nk) if nk else None, nk_mode="prepayment" if nk else "none")
    L.activate_lease(w.db, None, lease.id)
    for k, v in kw.items():
        setattr(lease, k, v)
    return lease


def sub_on(w, rus, rent, nk=None, start=date(2026, 1, 1), end=None, name="Max Mustermann"):
    return w.sub(rus, [w.tenant(name)], start, end, rent=D(rent), nk=D(nk) if nk else None, nk_mode="prepayment" if nk else "none")


def two_units(w):
    p = prop(w)
    a, b = unit(w, p, "A", "60.00"), unit(w, p, "B", "40.00")
    main = main_on(w, [ru(w, p)], "850.00", "180.00")
    return p, a, b, main


# ---- Soll: Beispiel 850/180 ↔ 1150/220, Aufteilung auf Wohneinheiten, Summenkonsistenz ------------------------------------------------------------------
def test_portfolio_soll_example_and_contribution_labels(w):
    p, a, b, main = two_units(w)
    sub_on(w, [ru(w, p, a)], "1150.00", "220.00")
    r = rep(w)
    s, c = r["soll"], r["contribution"]
    assert (s["sub_rent"], s["sub_utility"], s["sub_total"]) == (D("1150.00"), D("220.00"), D("1370.00"))
    assert (s["main_rent"], s["main_utility"], s["main_total"]) == (D("850.00"), D("180.00"), D("1030.00"))
    assert (c["rent_margin_soll"], c["utility_flow_soll"], c["soll_basis"]) == (D("300.00"), D("40.00"), D("340.00"))
    assert r["status"] == "vorläufig" and "kein Gewinn" in c["label"] and "Gewinn" not in str(r["scope"])
    assert r["ist"]["in_total"] == D("0.00")  # Soll ≠ Ist: ohne Zahlungen ist Ist null


def test_main_rent_distributed_by_area_to_units_and_scopes_add_up(w):
    p, a, b, main = two_units(w)
    sub_on(w, [ru(w, p, a)], "1150.00", "220.00")
    ra, rb, rp = rep(w, "unit", a.id), rep(w, "unit", b.id), rep(w, "property", p.id)
    assert (ra["soll"]["main_rent"], ra["soll"]["main_utility"]) == (D("510.00"), D("108.00"))  # 60 %
    assert (rb["soll"]["main_rent"], rb["soll"]["main_utility"]) == (D("340.00"), D("72.00"))   # 40 %
    assert ra["contribution"]["soll_basis"] == D("752.00") and rb["contribution"]["soll_basis"] == D("-412.00")
    assert ra["contribution"]["soll_basis"] + rb["contribution"]["soll_basis"] == rp["contribution"]["soll_basis"] == rep(w)["contribution"]["soll_basis"] == D("340.00")
    rru = rep(w, "rentable_unit", ru(w, p, a).id)
    assert rru["soll"]["sub_total"] == D("1370.00") and rru["soll"]["main_total"] == D("618.00")


def test_soll_equals_generated_charges(w):
    p, a, b, main = two_units(w)
    sub_on(w, [ru(w, p, a)], "1150.00", "220.00")
    C.generate_charges(w.db, None, from_month=JAN_FEB[0], through_month=date(2026, 2, 1), today=date(2026, 3, 1))
    r = rep(w, period=JAN_FEB)
    rec = sum(c.amount for c in w.db.scalars(select(Charge).where(Charge.direction == "receivable")))
    pay = sum(c.amount for c in w.db.scalars(select(Charge).where(Charge.direction == "payable")))
    assert (rec, pay) == (r["soll"]["sub_total"], r["soll"]["main_total"]) == (D("2740.00"), D("2060.00"))


def test_cent_rounding_exact_across_three_beds(w):
    p = prop(w)
    u = unit(w, p, "A", "30.00")
    room = M.create_room(w.db, None, u.id, {"name": "R"})
    beds = [M.create_bed(w.db, None, room.id, {"label": x}) for x in "123"]
    main_on(w, [ru(w, p, u)], "100.00")
    r = rep(w)
    assert r["soll"]["main_rent"] == D("100.00")
    parts = [rep(w, "rentable_unit", ru(w, p, u, room, b).id)["soll"]["main_rent"] for b in beds]
    assert sorted(parts) == [D("33.33"), D("33.33"), D("33.34")] and sum(parts) == D("100.00")


# ---- Leerstand: Bett-/Zimmerebene, nicht alles-oder-nichts -----------------------------------------------------------------------------------------------
def room_with_beds(w):
    p = prop(w)
    u = unit(w, p, "C", "30.00")
    room = M.create_room(w.db, None, u.id, {"name": "R"})
    beds = [M.create_bed(w.db, None, room.id, {"label": x}) for x in ("1", "2", "3")]
    main_on(w, [ru(w, p, u)], "900.00")
    sub_on(w, [ru(w, p, u, room, beds[0])], "300.00", name="Anna Eins")
    sub_on(w, [ru(w, p, u, room, beds[1])], "300.00", name="Bernd Zwei")
    return p, u, room, beds


def test_room_with_three_beds_two_occupied_is_neither_empty_nor_fully_rented(w):
    p, u, room, beds = room_with_beds(w)
    v = E.vacancy_report(w.db, *JAN)
    assert (v["snapshot"]["leaves_total"], v["snapshot"]["leaves_occupied"], v["snapshot"]["leaves_vacant"]) == (3, 2, 1)
    assert v["physical"]["vacancy_rate_by_count_percent"] == D("33.33") and v["physical"]["vacancy_rate_by_weight_percent"] == D("33.33")
    assert v["economic"]["cost"] == D("300.00")  # nur das freie Bett (900 / 3), nicht das ganze Zimmer
    vac = {r["label"].split("Bett ")[-1]: r for r in v["rows"]}
    assert vac["3"]["days_vacant"] == 31 and vac["1"]["days_vacant"] == 0 and vac["3"]["economic_vacancy_cost"] == D("300.00")
    assert vac["1"]["economic_vacancy_cost"] == vac["2"]["economic_vacancy_cost"] == D("0.00")


def test_room_and_bed_scopes_no_double_counting(w):
    p, u, room, beds = room_with_beds(w)
    room_r = rep(w, "rentable_unit", ru(w, p, u, room).id)
    assert (room_r["soll"]["sub_total"], room_r["soll"]["main_total"], room_r["contribution"]["soll_basis"]) == (D("600.00"), D("900.00"), D("-300.00"))
    assert room_r["vacancy"]["economic_vacancy_cost"] == D("300.00")
    b = [rep(w, "rentable_unit", ru(w, p, u, room, x).id) for x in beds]
    assert [x["contribution"]["soll_basis"] for x in b] == [D("0.00"), D("0.00"), D("-300.00")]
    assert sum(x["contribution"]["soll_basis"] for x in b) == room_r["contribution"]["soll_basis"] == rep(w)["contribution"]["soll_basis"]
    assert rep(w, "rentable_unit", ru(w, p).id)["soll"] == rep(w, "property", p.id)["soll"]  # Objektebene = Objektsumme


def test_whole_unit_lease_spreads_income_over_rooms_by_area_without_double_counting(w):
    p = prop(w)
    u = unit(w, p, "E", "50.00")
    r1, r2 = M.create_room(w.db, None, u.id, {"name": "R1", "area": D("20.00")}), M.create_room(w.db, None, u.id, {"name": "R2", "area": D("10.00")})
    main_on(w, [ru(w, p, u)], "600.00")
    sub_on(w, [ru(w, p, u)], "900.00")
    a, b = rep(w, "rentable_unit", ru(w, p, u, r1).id), rep(w, "rentable_unit", ru(w, p, u, r2).id)
    assert (a["soll"]["sub_total"], a["soll"]["main_total"]) == (D("600.00"), D("400.00"))
    assert (b["soll"]["sub_total"], b["soll"]["main_total"]) == (D("300.00"), D("200.00"))
    assert rep(w, "unit", u.id)["soll"]["sub_total"] == D("900.00") and rep(w)["soll"]["sub_total"] == D("900.00")
    assert E.vacancy_report(w.db, *JAN)["economic"]["cost"] == D("0.00")


# ---- Zeitbezug ------------------------------------------------------------------------------------------------------------------------------------------------------
def single(w, rent="1000.00"):
    p = prop(w)
    u = unit(w, p, "D", "50.00")
    return p, u


def test_vacancy_before_sub_lease_start_is_prorated_by_day(w):
    p, u = single(w)
    main_on(w, [ru(w, p, u)], "1000.00")
    sub_on(w, [ru(w, p, u)], "1000.00", start=date(2026, 1, 16))
    r = rep(w)
    assert r["soll"]["main_total"] == D("1000.00") and r["soll"]["sub_total"] == D("516.13")  # 16/31
    assert r["vacancy"]["economic_vacancy_cost"] == D("483.87")                                 # 15/31
    assert r["contribution"]["soll_basis"] == D("-483.87")
    v = E.vacancy_report(w.db, *JAN)
    assert v["physical"]["vacancy_rate_by_count_percent"] == D("48.39") and v["economic"]["days_vacant_with_main_obligation"] == 15


def test_tenant_change_without_gap_has_no_vacancy_and_gap_has(w):
    p, u = single(w)
    main_on(w, [ru(w, p, u)], "1000.00")
    sub_on(w, [ru(w, p, u)], "1000.00", start=date(2026, 1, 1), end=date(2026, 1, 31), name="Erster Mieter")
    sub_on(w, [ru(w, p, u)], "1000.00", start=date(2026, 2, 1), end=date(2026, 2, 28), name="Zweiter Mieter")
    assert rep(w, period=JAN_FEB)["vacancy"]["economic_vacancy_cost"] == D("0.00")
    p2, u2 = single(w)
    main_on(w, [ru(w, p2, u2)], "1000.00")
    sub_on(w, [ru(w, p2, u2)], "1000.00", start=date(2026, 1, 1), end=date(2026, 1, 20), name="Dritter")
    sub_on(w, [ru(w, p2, u2)], "1000.00", start=date(2026, 1, 26), end=date(2026, 1, 31), name="Vierter")
    assert rep(w, "unit", u2.id)["vacancy"]["economic_vacancy_cost"] == D("161.29")  # Lücke 21.–25.1. = 5 Tage: 1000×5/31


def test_main_rent_change_and_main_lease_end_are_time_based(w):
    p, u = single(w)
    main = main_on(w, [ru(w, p, u)], "1000.00", end=date(2026, 2, 14))
    L.add_term(w.db, None, main.id, valid_from=date(2026, 2, 1), valid_to=None, base_rent=D("1100.00"))
    sub_on(w, [ru(w, p, u)], "1500.00", start=date(2026, 1, 1), end=date(2026, 2, 14))
    r = rep(w, period=JAN_FEB)
    assert r["soll"]["main_rent"] == D("1000.00") + D("550.00")  # Februar: 1100 × 14/28
    assert r["soll"]["sub_rent"] == D("1500.00") + D("750.00")
    assert r["vacancy"]["economic_vacancy_cost"] == D("0.00")
    assert rep(w, period=(date(2026, 3, 1), date(2026, 3, 31)))["soll"]["main_total"] == D("0.00")  # nach Vertragsende keine Verpflichtung


def test_no_main_obligation_means_physical_but_not_economic_vacancy(w):
    p, u = single(w)
    v = E.vacancy_report(w.db, *JAN)
    assert v["snapshot"]["leaves_vacant"] == 1 and v["physical"]["vacancy_rate_by_count_percent"] == D("100.00")
    assert v["economic"]["cost"] == D("0.00") and v["economic"]["days_vacant_with_main_obligation"] == 0


def test_unbefristet_contracts_do_not_break_interval_math(w):
    assert E.subtract([(date(2025, 1, 1), date.max)], [(date(2026, 1, 1), date.max)]) == [(date(2025, 1, 1), date(2025, 12, 31))]
    assert E.union([(date(2025, 1, 1), date.max), (date(2026, 1, 1), date.max)]) == [(date(2025, 1, 1), date.max)]
    assert E.subtract([(date(2026, 1, 1), date(2026, 1, 31))], [(date(2026, 1, 10), date(2026, 1, 12))]) == [(date(2026, 1, 1), date(2026, 1, 9)), (date(2026, 1, 13), date(2026, 1, 31))]


# ---- Ist, Offen, Rückstände, Objektkosten ---------------------------------------------------------------------------------------------------------------------------------
def with_payments(w):
    p, a, b, main = two_units(w)
    sub = sub_on(w, [ru(w, p, a)], "1150.00", "220.00")
    C.generate_charges(w.db, None, from_month=JAN[0], through_month=JAN[0], today=date(2026, 2, 1))
    rent = w.db.scalars(select(Charge).where(Charge.lease_id == sub.id, Charge.charge_type == "base_rent")).one()
    P.create_payment(w.db, None, direction="in", booking_date=date(2026, 1, 5), amount=D("1000.00"), allocations=[{"charge_id": rent.id, "amount": D("1000.00")}])
    for c in w.db.scalars(select(Charge).where(Charge.direction == "payable")):
        P.create_payment(w.db, None, direction="out", booking_date=date(2026, 1, 3), amount=c.amount, reference=f"M{c.id}", allocations=[{"charge_id": c.id, "amount": c.amount}])
    inv = P.create_invoice(w.db, None, property_id=p.id, unit_id=a.id, invoice_number="R1", amount=D("238.00"), invoice_date=date(2026, 1, 20))
    P.create_payment(w.db, None, direction="out", booking_date=date(2026, 1, 25), amount=D("100.00"), allocations=[{"invoice_id": inv.id, "amount": D("100.00")}])
    return p, a, b, sub, rent, inv


def test_ist_offen_and_object_costs_are_separate_from_soll(w):
    p, a, b, sub, rent, inv = with_payments(w)
    r = rep(w)
    assert r["ist"]["in_from_subleases"] == D("1000.00") and r["ist"]["out_main_rent"] == D("1030.00") and r["ist"]["out_invoices"] == D("100.00")
    assert (r["ist"]["in_total"], r["ist"]["out_total"], r["contribution"]["ist_basis"]) == (D("1000.00"), D("1130.00"), D("-130.00"))
    assert r["soll"]["object_costs"] == D("238.00") and r["contribution"]["soll_basis"] == D("340.00") - D("238.00")  # Soll: Rechnung voll, unabhängig von Zahlung
    o = r["offen_zum_stichtag"]
    assert (o["receivables"], o["receivables_overdue"], o["payables"], o["invoices"]) == (D("370.00"), D("370.00"), D("0.00"), D("138.00"))  # 1370 − 1000
    assert rep(w, "unit", a.id)["soll"]["object_costs"] == D("238.00") and rep(w, "unit", b.id)["soll"]["object_costs"] == D("0.00")
    assert rep(w, "unit", a.id)["offen_zum_stichtag"]["receivables"] == D("370.00")


def test_payments_outside_period_and_reversal_by_date(w):
    p, a, b, sub, rent, inv = with_payments(w)
    pay = w.db.scalars(select(P.Payment).where(P.Payment.amount == D("1000.00"))).one()
    P.reverse_payment(w.db, None, pay.id, reason="Rücklastschrift", booking_date=date(2026, 2, 5))
    jan, feb, both = rep(w), rep(w, period=(date(2026, 2, 1), date(2026, 2, 28))), rep(w, period=JAN_FEB)
    assert jan["ist"]["in_from_subleases"] == D("1000.00") and feb["ist"]["in_from_subleases"] == D("-1000.00") and both["ist"]["in_from_subleases"] == D("0.00")
    assert jan["offen_zum_stichtag"]["receivables"] == D("370.00")  # Stand 31.1.: Zahlung noch gültig


def test_unallocated_payments_are_flagged_and_only_in_ist_total(w):
    p, a, b, sub, rent, inv = with_payments(w)
    P.create_payment(w.db, None, direction="in", booking_date=date(2026, 1, 28), amount=D("50.00"), property_id=p.id, reference="unklar")
    r = rep(w)
    assert r["ist"]["in_other_unallocated"] == D("50.00") and r["ist"]["in_total"] == D("1050.00")
    assert any(x["code"] == "unallocated_payments" for x in r["warnings"])
    assert rep(w, "property", p.id)["ist"]["in_total"] == D("1050.00") and rep(w, "unit", a.id)["ist"]["in_total"] == D("1000.00")
    assert any(x["code"] == "object_level_costs_excluded" for x in rep(w, "unit", a.id)["warnings"])


def test_deposit_payments_never_enter_economics_even_with_unallocated_flow(w):
    from leventum.services import deposits as DEP
    p, a, b, main = two_units(w)
    s = sub_on(w, [ru(w, p, a)], "1150.00", "220.00")
    DEP.add_transaction(w.db, None, DEP.ensure_deposit(w.db, None, s.id, agreed_amount=D("3000.00")).id, kind="paid", amount=D("3000.00"), transaction_date=date(2026, 1, 3))
    r = rep(w)
    assert r["ist"]["in_total"] == D("0.00") and r["soll"]["sub_total"] == D("1370.00") and r["contribution"]["ist_basis"] == D("0.00")


# ---- Verteilung ohne Daten / individuelle Methode ------------------------------------------------------------------------------------------------------------------------------
def test_missing_area_is_not_guessed_and_cost_is_kept_unallocated_on_property_level(w):
    p = prop(w)
    a, b = unit(w, p, "A", None), unit(w, p, "B", None)
    main_on(w, [ru(w, p)], "850.00", "180.00")
    r = rep(w)
    assert r["soll"]["main_total"] == D("1030.00")  # Kosten sind real und bleiben im Portfolio
    assert rep(w, "property", p.id)["soll"]["main_total"] == D("1030.00")
    assert rep(w, "unit", a.id)["soll"]["main_total"] == D("0.00")
    assert any(x["code"] == "missing_allocation_data" for x in r["warnings"])


def test_equal_and_custom_methods_per_main_lease(w):
    p = prop(w)
    a, b = unit(w, p, "A", None), unit(w, p, "B", None)
    main = main_on(w, [ru(w, p)], "850.00", "180.00", allocation_method="equal")
    assert (rep(w, "unit", a.id)["soll"]["main_rent"], rep(w, "unit", b.id)["soll"]["main_rent"]) == (D("425.00"), D("425.00"))
    main.allocation_method = "custom"
    from leventum.models import LeaseAllocationWeight
    for u, wt in ((a, "3"), (b, "1")):
        w.db.add(LeaseAllocationWeight(lease_id=main.id, unit_id=u.id, weight=D(wt)))
    w.db.flush()
    assert (rep(w, "unit", a.id)["soll"]["main_rent"], rep(w, "unit", b.id)["soll"]["main_rent"]) == (D("637.50"), D("212.50"))
    assert rep(w)["soll"]["main_rent"] == D("850.00")


# ---- Betriebskosten-Abrechnung (Ebene A) in der Wirtschaftlichkeit ---------------------------------------------------------------------------------------------------------------------
def test_upstream_utility_settlement_shown_separately(w):
    p, a, b, main = two_units(w)
    sub_on(w, [ru(w, p, a)], "1150.00", "220.00")
    st = U.create_statement(w.db, None, main_lease_id=main.id, period_start=JAN[0], period_end=JAN[1], unit_ids=[a.id, b.id])
    ct = w.db.scalar(select(__import__("leventum.models", fromlist=["x"]).CostType).where(__import__("leventum.models", fromlist=["x"]).CostType.name == "Heizung"))
    U.add_line(w.db, None, st.id, cost_type_id=ct.id, amount=D("300.00"), allocation_key="area")
    U.set_prepayments(w.db, None, st.id, D("180.00"), "agreed_calculated")
    r = rep(w)
    s = r["contribution"]["utility_settlement_upstream"]
    assert s["balance"] == D("120.00") and s["statements_counted"] == 1
    assert r["contribution"]["soll_basis"] == D("340.00") and r["contribution"]["soll_basis_incl_upstream_settlement"] == D("220.00")
    assert rep(w, "unit", a.id)["contribution"]["utility_settlement_upstream"] is None


def test_period_must_be_whole_months(w):
    for s, e in ((date(2026, 1, 2), date(2026, 1, 31)), (date(2026, 1, 1), date(2026, 1, 30)), (date(2026, 2, 1), date(2026, 1, 31)), (date(2020, 1, 1), date(2026, 1, 31))):
        with pytest.raises(ServiceError):
            E.Engine(w.db, s, e)
    with pytest.raises(ServiceError):
        rep(w, "property")


def test_empty_database_reports_zero_without_errors(w):
    r = rep(w)
    assert r["soll"]["sub_total"] == D("0.00") and r["vacancy"]["physical_vacancy_rate_by_count"] is None
