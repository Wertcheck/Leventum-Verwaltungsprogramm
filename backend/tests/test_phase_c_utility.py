from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from leventum.models import CostType
from leventum.services import leases as L, utility as U
from leventum.services.errors import ServiceError
from tests.helpers import World

Y25 = (date(2025, 1, 1), date(2025, 12, 31))


@pytest.fixture
def w(app):
    w = World(app)
    w.ct = {c.name: c.id for c in w.db.scalars(select(CostType))}
    yield w
    w.db.close()


def stmt(w, main, units=None, period=Y25, **kw):
    return U.create_statement(w.db, None, main_lease_id=main.id, period_start=period[0], period_end=period[1],
                              unit_ids=[u.id for u in (units or [w.we1, w.we2])], **kw)


# ---- Rechenkerne ---------------------------------------------------------------------------------------------------------
def test_largest_remainder_sums_exactly():
    r = U.largest_remainder(D("100.00"), {"a": D(1), "b": D(1), "c": D(1)})
    assert sum(r.values()) == D("100.00") and sorted(r.values()) == [D("33.33"), D("33.33"), D("33.34")]
    r = U.largest_remainder(D("1234.56"), {"a": D("60.00"), "b": D("40.00")})
    assert r == {"a": D("740.74"), "b": D("493.82")} and sum(r.values()) == D("1234.56")
    assert sum(U.largest_remainder(D("-10.01"), {"a": D(1), "b": D(2)}).values()) == D("-10.01")
    with pytest.raises(ValueError):
        U.largest_remainder(D("1"), {"a": D(0)})


def test_months_overlap_day_exact():
    assert U.months_overlap(date(2025, 1, 1), None, *Y25) == 12
    assert U.months_overlap(date(2025, 7, 1), None, *Y25) == 6
    assert U.months_overlap(date(2025, 1, 16), date(2025, 1, 31), date(2025, 1, 1), date(2025, 1, 31)) == D(16) / D(31)
    assert U.months_overlap(date(2026, 1, 1), None, *Y25) == 0


# ---- Nebenkostenvereinbarungen (Ebene A und B) ----------------------------------------------------------------------------
def test_agreement_modes_are_validated_and_not_guessed(w):
    s = w.sub([w.ru_unit(w.we1)], [w.tenant("A B")], date(2026, 1, 1), None, nk_mode=None, activate=False) if False else None
    main = w.main(nk_mode="none")
    ag = lambda **k: L.add_utility_agreement(w.db, None, main.id, valid_from=date(2030, 1, 1), valid_to=None, **k)
    with pytest.raises(ServiceError): ag(mode="flat_rate")                      # Pauschale ohne Betrag
    with pytest.raises(ServiceError): ag(mode="included", monthly_amount=D("10"))  # enthalten mit Betrag
    with pytest.raises(ServiceError): ag(mode="flat_rate", monthly_amount=D("50"), settlement_agreed=True)  # Pauschale ≠ Abrechnung
    with pytest.raises(ServiceError): ag(mode="individual")                      # ohne Beschreibung
    flat = ag(mode="flat_rate", monthly_amount=D("50.00"))
    assert flat.settlement_agreed is False
    pre = L.add_utility_agreement(w.db, None, main.id, valid_from=date(2031, 1, 1), valid_to=None, mode="prepayment", monthly_amount=D("80"))
    assert pre.settlement_agreed is True
    ind = L.add_utility_agreement(w.db, None, main.id, valid_from=date(2032, 1, 1), valid_to=None, mode="individual", description="Strom nach Zähler, Rest Pauschale")
    assert ind.settlement_agreed is None  # ungeklärt statt geraten


def test_monthly_total_treats_modes_separately(w):
    w.activate_main()
    day = date(2026, 3, 1)
    cases = {"prepayment": D("220.00"), "flat_rate": D("220.00"), "included": D(0), "none": D(0), "individual": D(0)}
    for mode, util in cases.items():
        s = w.sub([w.ru_unit(w.we2)], [w.tenant("A B")], date(2026, 1, 1), date(2026, 12, 31), nk_mode=mode, activate=False)
        m = L.monthly_total(s, day)
        assert m["utility_mode"] == mode and m["utility_amount"] == util and m["total"] == D("1150.00") + util, mode
        w.db.delete(s); w.db.flush()


# ---- Eingehende Abrechnung: Nachzahlung / Guthaben -----------------------------------------------------------------------------
def build_statement(w, nk=D("180.00"), mode="prepayment"):
    main = w.activate_main(nk=nk, nk_mode=mode)
    st = stmt(w, main)
    U.add_line(w.db, None, st.id, cost_type_id=w.ct["Grundsteuer"], amount=D("1200.00"), allocation_key="area", allocable_status="allocable")
    U.add_line(w.db, None, st.id, cost_type_id=w.ct["Heizung"], amount=D("1100.00"), allocation_key="area")
    U.add_line(w.db, None, st.id, cost_type_id=w.ct["Hauswart"], amount=D("100.01"), allocation_key="equal", allocable_status="not_allocable")
    return main, st


def test_incoming_statement_nachzahlung(w):
    main, st = build_statement(w)  # Kosten 2400.01, Vorauszahlungen 12 × 180 = 2160
    c = U.compute_statement(w.db, st.id)
    assert c["total_costs"] == D("2400.01") and c["suggested_prepayments"] == D("2160.00")
    assert c["balance"] is None and any(x["code"] == "prepayments_missing" for x in c["warnings"])  # nicht stillschweigend 0
    U.set_prepayments(w.db, None, st.id, c["suggested_prepayments"], "agreed_calculated")
    c = U.compute_statement(w.db, st.id)
    assert c["balance"] == D("240.01") and c["direction"] == "nachzahlung"
    assert c["costs_by_allocable_status"] == {"unreviewed": D("1100.00"), "allocable": D("1200.00"), "not_allocable": D("100.01")}


def test_incoming_statement_guthaben_and_deviation_from_stated(w):
    main, st = build_statement(w)
    st.stated_balance = D("-50.00")
    U.set_prepayments(w.db, None, st.id, D("2600.00"), "statement")
    c = U.compute_statement(w.db, st.id)
    assert c["balance"] == D("-199.99") and c["direction"] == "guthaben"
    assert c["deviation_from_stated"] == D("-149.99") and any(x["code"] == "deviates_from_stated" for x in c["warnings"])
    U.set_prepayments(w.db, None, st.id, D("2400.01"), "manual")
    assert U.compute_statement(w.db, st.id)["direction"] == "ausgeglichen"


def test_prepayment_suggestion_with_rent_change_mid_period(w):
    main = w.activate_main(nk=D("180.00"))
    L.add_utility_agreement(w.db, None, main.id, valid_from=date(2025, 7, 1), valid_to=None, mode="prepayment", monthly_amount=D("200.00"))
    st = stmt(w, main)
    assert U.compute_statement(w.db, st.id)["suggested_prepayments"] == D("6") * D("180.00") + D("6") * D("200.00")


def test_upstream_flat_rate_is_not_counted_as_prepayment(w):
    main, st = build_statement(w, nk=D("150.00"), mode="flat_rate")
    c = U.compute_statement(w.db, st.id)
    assert c["suggested_prepayments"] == D("0.00")
    assert any(x["code"] == "agreement_flat_rate" for x in c["warnings"])


def test_statement_lifecycle_lock_and_validation(w):
    main, st = build_statement(w)
    with pytest.raises(ServiceError): U.set_status(w.db, None, st.id, "reviewed")  # nicht überspringen
    U.set_status(w.db, None, st.id, "captured")
    with pytest.raises(ServiceError) as e: U.set_status(w.db, None, st.id, "reviewed")  # Vorauszahlungen fehlen
    assert e.value.code == "incomplete"
    U.set_prepayments(w.db, None, st.id, D("2160.00"), "agreed_calculated")
    U.set_status(w.db, None, st.id, "reviewed")
    with pytest.raises(ServiceError) as e:
        U.add_line(w.db, None, st.id, cost_type_id=w.ct["Aufzug"], amount=D("1.00"))
    assert e.value.code == "locked"
    with pytest.raises(ServiceError): U.set_prepayments(w.db, None, st.id, D("1.00"), "manual")


def test_statement_input_validation(w):
    main = w.activate_main(start=date(2025, 1, 1), end=date(2025, 12, 31))
    with pytest.raises(ServiceError): U.create_statement(w.db, None, main_lease_id=main.id, period_start=date(2027, 1, 1), period_end=date(2027, 12, 31), unit_ids=[w.we1.id])
    other_prop = __import__("leventum.services.master", fromlist=["x"]).create_property(w.db, None, {"name": "Anderes", "property_type": "wohnung"})
    foreign = __import__("leventum.services.master", fromlist=["x"]).create_unit(w.db, None, other_prop.id, {"unit_number": "1"})
    with pytest.raises(ServiceError): U.create_statement(w.db, None, main_lease_id=main.id, period_start=Y25[0], period_end=Y25[1], unit_ids=[foreign.id])
    sub = w.sub([w.ru_unit(w.we1)], [w.tenant("A B")], date(2025, 1, 1), date(2025, 12, 31))
    with pytest.raises(ServiceError): U.create_statement(w.db, None, main_lease_id=sub.id, period_start=Y25[0], period_end=Y25[1], unit_ids=[w.we1.id])


# ---- Verteilung auf Wohneinheiten --------------------------------------------------------------------------------------------------
def test_allocation_by_area_equal_and_exact_sum(w):
    main, st = build_statement(w)
    a = U.allocate_statement(w.db, st.id)
    # WE1 60 m², WE2 40 m²: Grundsteuer 1200 → 720/480; Heizung 1100 → 660/440; Hauswart 100.01 gleich → 50.01/50.00 (Cent nach größtem Rest, Gleichstand deterministisch)
    by_line = {l["cost_type"]: l["shares"] for l in a["lines"]}
    assert by_line["Grundsteuer"] == {w.we1.id: D("720.00"), w.we2.id: D("480.00")}
    assert by_line["Heizung"] == {w.we1.id: D("660.00"), w.we2.id: D("440.00")}
    assert sum(by_line["Hauswart"].values()) == D("100.01")
    assert sum(a["per_unit"].values()) == D("2400.01") and a["unallocated"] == D("0.00") and not a["warnings"]


def test_allocation_custom_persons_weights_and_missing_inputs_are_reported(w):
    main = w.activate_main()
    st = stmt(w, main)
    U.add_line(w.db, None, st.id, cost_type_id=w.ct["Wasserversorgung"], amount=D("900.00"), allocation_key="persons", weights={w.we1.id: D("3"), w.we2.id: D("1")})
    U.add_line(w.db, None, st.id, cost_type_id=w.ct["Entwässerung"], amount=D("300.00"), allocation_key="consumption")  # ohne Gewichte
    U.add_line(w.db, None, st.id, cost_type_id=w.ct["Aufzug"], amount=D("50.00"), allocation_key="none")
    a = U.allocate_statement(w.db, st.id)
    assert a["per_unit"] == {w.we1.id: D("675.00"), w.we2.id: D("225.00")}
    assert a["unallocated"] == D("350.00")  # nichts wird geraten oder gleichverteilt
    assert {x["code"] for x in a["warnings"]} == {"weights_missing", "no_key"}


def test_allocation_by_area_without_area_data_is_not_guessed(w):
    w.we2.living_area = None
    main = w.activate_main()
    st = stmt(w, main)
    U.add_line(w.db, None, st.id, cost_type_id=w.ct["Heizung"], amount=D("100.00"), allocation_key="area")
    a = U.allocate_statement(w.db, st.id)
    assert a["unallocated"] == D("100.00") and a["warnings"][0]["code"] == "missing_area"


def test_weights_outside_scope_rejected(w):
    main = w.activate_main()
    st = stmt(w, main, units=[w.we1])
    with pytest.raises(ServiceError):
        U.add_line(w.db, None, st.id, cost_type_id=w.ct["Heizung"], amount=D("1.00"), allocation_key="custom", weights={w.we2.id: D(1)})


# ---- Ebene B: Vergleich, Pauschale vs. Vorauszahlung -----------------------------------------------------------------------------------
def test_comparison_separates_flat_rate_prepayment_included_and_individual(w):
    main, st = build_statement(w)
    w.sub([w.ru_unit(w.we1)], [w.tenant("Pre Zahler")], date(2025, 1, 1), None, nk=D("200.00"), nk_mode="prepayment")
    w.sub([w.ru_unit(w.we2)], [w.tenant("Pau Schal")], date(2025, 1, 1), None, nk=D("150.00"), nk_mode="flat_rate")
    c = U.compare_with_downstream(w.db, st.id)
    rows = {r["unit_id"]: r for r in c["rows"]}
    r1, r2 = rows[w.we1.id], rows[w.we2.id]
    assert r1["downstream_prepayments_soll"] == D("2400.00") and r1["downstream_flat_rates_soll"] == D("0.00")
    assert r2["downstream_prepayments_soll"] == D("0.00") and r2["downstream_flat_rates_soll"] == D("1800.00")
    assert r1["agreements"][0]["claim_status"] == "settlement_agreed_review_required" and r1["claim_possible"] is True
    assert r2["agreements"][0]["claim_status"] == "no_claim_flat_rate" and r2["claim_possible"] is False
    # tatsächliche verteilte Kosten WE1: 720+660+50.01(Anteil Hauswart) ; WE2: 480+440+50.00
    assert r1["allocated_actual_costs"] == D("1430.01") and r2["allocated_actual_costs"] == D("970.00")
    assert r1["nk_result_before_settlement"] == D("2400.00") - D("1430.01")
    assert r2["nk_result_before_settlement"] == D("1800.00") - D("970.00")
    imp = c["impact_on_preliminary_contribution"]["nk_result_before_downstream_settlement"]
    assert imp == D("4200.00") - D("2400.01")
    assert "NICHT" in c["impact_on_preliminary_contribution"]["note"]


def test_comparison_included_and_individual_never_claimable(w):
    main, st = build_statement(w)
    w.sub([w.ru_unit(w.we1)], [w.tenant("A B")], date(2025, 1, 1), None, nk_mode="included")
    w.sub([w.ru_unit(w.we2)], [w.tenant("C D")], date(2025, 1, 1), None, nk_mode="individual")
    rows = {r["unit_id"]: r for r in U.compare_with_downstream(w.db, st.id)["rows"]}
    assert rows[w.we1.id]["agreements"][0]["claim_status"] == "no_claim_included_in_rent" and not rows[w.we1.id]["claim_possible"]
    assert rows[w.we2.id]["agreements"][0]["claim_status"] == "undetermined_manual_review" and not rows[w.we2.id]["claim_possible"]
    assert rows[w.we1.id]["downstream_prepayments_soll"] == D("0.00")  # 'enthalten' addiert keine NK-Soll-Beträge


def test_comparison_prorates_partial_period_and_handles_room_level_and_vacancy(w):
    main, st = build_statement(w)
    # nur Juli–Dezember vermietet, zwei Zimmer in WE1 mit je eigener Vorauszahlung
    w.sub([w.ru_room(w.room1)], [w.tenant("A B")], date(2025, 7, 1), None, nk=D("60.00"), type_code="zimmer")
    w.sub([w.ru_room(w.room2)], [w.tenant("C D")], date(2025, 10, 1), date(2025, 12, 31), nk=D("50.00"), type_code="zimmer")
    r1 = {r["unit_id"]: r for r in U.compare_with_downstream(w.db, st.id)["rows"]}[w.we1.id]
    assert r1["downstream_prepayments_soll"] == D("6") * D("60.00") + D("3") * D("50.00")
    assert len(r1["agreements"]) == 2


def test_comparison_flags_property_level_sublease_as_unattributable(w):
    main, st = build_statement(w)
    L_ = w.sub([w.ru_prop()], [w.tenant("Haus Mieter")], date(2025, 1, 1), None, nk=D("500.00"))
    c = U.compare_with_downstream(w.db, st.id)
    assert c["unattributable_subleases"] == [L_.id] and any(x["code"] == "unattributable_sublease" for x in c["warnings"])
    assert all(r["downstream_prepayments_soll"] == D("0.00") for r in c["rows"])


def test_statement_creation_does_not_touch_subleases_or_create_claims(w):
    main, st = build_statement(w)
    sub = w.sub([w.ru_unit(w.we1)], [w.tenant("A B")], date(2025, 1, 1), None, nk=D("200.00"), nk_mode="flat_rate")
    snapshot = [(a.mode, a.monthly_amount, a.settlement_agreed) for a in sub.utility_agreements]
    U.compare_with_downstream(w.db, st.id); U.compute_statement(w.db, st.id); U.allocate_statement(w.db, st.id)
    assert snapshot == [(a.mode, a.monthly_amount, a.settlement_agreed) for a in sub.utility_agreements]
    import sqlalchemy as sa
    assert "charge" not in sa.inspect(w.db.get_bind()).get_table_names()  # es gibt (noch) keine Forderungstabelle
