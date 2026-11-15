"""Stammdaten bearbeiten und historisieren (Master-Review C1)."""
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from leventum.models import AuditEvent, Charge, CostType, Payment
from leventum.services import charges as C, leases as L, master as M, payments as P, utility as U
from leventum.services.errors import ServiceError
from tests.helpers import World
from tests.test_d_api import V, post, world  # noqa: F401


@pytest.fixture
def w(app):
    w = World(app)
    w.main_l = w.activate_main()
    w.sub_l = w.sub([w.ru_unit(w.we2)], [w.tenant("Max Mustermann")], date(2026, 1, 1), None)
    yield w
    w.db.close()


def last_audit(w, action, entity_id):
    return w.db.scalars(select(AuditEvent).where(AuditEvent.action == action, AuditEvent.entity_id == str(entity_id)).order_by(AuditEvent.id.desc())).first()


# ---- Vorher/Nachher-Protokoll ----------------------------------------------------------------------------------------------------------------
def test_party_edit_logs_before_after_and_masks_personal_data(w):
    t = w.sub_l.parties[1].party
    M.update_party(w.db, w.user.id, t.id, {"last_name": "Musterfrau", "city": "Potsdam", "iban": "DE89370400440532013000", "email": "neu@example.org"})
    ev = last_audit(w, "party.updated", t.id)
    ch = ev.details["changes"]
    assert ch["last_name"] == ["Mustermann", "Musterfrau"] and ch["city"] == [None, "Potsdam"]
    assert ch["iban"] == ["(geändert)", "(geändert)"] and ch["email"] == ["(geändert)", "(geändert)"]  # kein Klartext sensibler Daten im Protokoll
    assert "DE89" not in str(ev.details) and "neu@example.org" not in str(ev.details)
    assert t.display_name == "Max Musterfrau" and ev.actor_user_id == w.user.id
    M.update_party(w.db, w.user.id, t.id, {"city": "Potsdam"})  # unverändert → leere Änderungsliste
    assert last_audit(w, "party.updated", t.id).details["changes"] == {}


def test_property_unit_room_bed_edits_are_logged_with_values(w):
    M.update_property(w.db, w.user.id, w.prop.id, {"name": "Haus Bergmann Neu", "heating_type": "Fernwärme"})
    assert last_audit(w, "property.updated", w.prop.id).details["changes"]["name"] == ["Haus Bergmann", "Haus Bergmann Neu"]
    M.update_unit(w.db, w.user.id, w.we1.id, {"living_area": D("61.50"), "floor": "2"})
    assert last_audit(w, "unit.updated", w.we1.id).details["changes"]["living_area"] == ["60.00", "61.50"]
    M.update_room(w.db, w.user.id, w.room1.id, {"name": "Schlafzimmer", "area": D("22.00")})
    assert last_audit(w, "room.updated", w.room1.id).details["changes"]["name"] == ["Zimmer 1", "Schlafzimmer"]
    M.update_bed(w.db, w.user.id, w.bed1.id, {"label": "Bett Fenster"})
    assert last_audit(w, "bed.updated", w.bed1.id).details["changes"]["label"] == ["Bett A", "Bett Fenster"]


def test_duplicate_names_are_rejected_on_rename(w):
    with pytest.raises(ServiceError) as e:
        M.update_room(w.db, None, w.room2.id, {"name": "Zimmer 1"})
    assert e.value.code == "duplicate"
    with pytest.raises(ServiceError):
        M.update_bed(w.db, None, w.bed2.id, {"label": "Bett A"})
    with pytest.raises(ServiceError):
        M.update_unit(w.db, None, w.we2.id, {"unit_number": "WE 1"})
    with pytest.raises(ServiceError):
        M.update_room(w.db, None, w.room2.id, {"name": "  "})
    assert M.update_room(w.db, None, w.room1.id, {"name": "Zimmer 1"}).name == "Zimmer 1"  # gleicher Name = kein Konflikt


# ---- Deaktivieren nur wenn nicht vermietet ------------------------------------------------------------------------------------------------------
def test_cannot_deactivate_rented_unit_room_or_bed_but_unused_ones(w):
    bed_lease = w.sub([w.ru_bed(w.bed1)], [w.tenant("Anna Bett")], date(2026, 1, 1), None, type_code="bett")
    for fn, args in ((M.update_bed, (w.bed1.id,)), (M.update_room, (w.room1.id,)), (M.update_unit, (w.we1.id,))):
        with pytest.raises(ServiceError) as e:
            fn(w.db, None, *args, {"is_active": False})
        assert e.value.code == "in_use" and e.value.details["lease_id"] == bed_lease.id  # Raum/Wohneinheit mit vermietetem Bett ist ebenfalls geschützt
    assert M.update_bed(w.db, None, w.bed2.id, {"is_active": False}).is_active is False  # unbelegtes Bett
    assert M.update_room(w.db, None, w.room2.id, {"is_active": False}).is_active is False
    L.terminate_lease(w.db, None, bed_lease.id, terminated_on=date(2026, 2, 1), effective_on=date(2026, 3, 1))
    with pytest.raises(ServiceError):  # gekündigt, aber noch laufend → weiter geschützt
        M.update_bed(w.db, None, w.bed1.id, {"is_active": False})


# ---- Historische Finanzdaten bleiben unverändert -------------------------------------------------------------------------------------------------
def snapshot(w):
    return [(c.id, c.amount, c.period_start, c.period_end, c.due_date, c.dedupe_key, c.voided_at) for c in w.db.scalars(select(Charge).order_by(Charge.id))] + \
           [(p.id, p.amount, p.booking_date, p.direction) for p in w.db.scalars(select(Payment).order_by(Payment.id))]


def test_editing_master_data_and_conditions_never_changes_existing_charges_or_payments(w):
    C.generate_charges(w.db, None, from_month=date(2026, 1, 1), through_month=date(2026, 3, 1), today=date(2026, 4, 1))
    rent = w.db.scalars(select(Charge).where(Charge.lease_id == w.sub_l.id, Charge.charge_type == "base_rent")).first()
    P.create_payment(w.db, None, direction="in", booking_date=date(2026, 1, 5), amount=D("1150.00"), allocations=[{"charge_id": rent.id, "amount": D("1150.00")}])
    before = snapshot(w)
    M.update_party(w.db, None, w.sub_l.parties[1].party.id, {"last_name": "Neuername", "iban": "DE89370400440532013000"})
    M.update_unit(w.db, None, w.we2.id, {"living_area": D("45.00")})
    M.update_property(w.db, None, w.prop.id, {"name": "Umbenannt"})
    L.add_term(w.db, None, w.sub_l.id, valid_from=date(2026, 4, 1), valid_to=None, base_rent=D("1300.00"))  # Mieterhöhung = neue Version
    L.add_utility_agreement(w.db, None, w.sub_l.id, valid_from=date(2026, 4, 1), valid_to=None, mode="flat_rate", monthly_amount=D("250.00"))
    L.update_lease(w.db, None, w.sub_l.id, {"notice_period_months": 3, "internal_notes": "x"})
    assert snapshot(w) == before  # Sollstellungen und Zahlungen unverändert
    old = w.sub_l.terms[0]
    assert (old.valid_from, old.valid_to, old.base_rent) == (date(2026, 1, 1), date(2026, 3, 31), D("1150.00"))  # alte Konditionen bleiben als Version erhalten
    assert [(t.valid_from, t.base_rent) for t in w.sub_l.terms] == [(date(2026, 1, 1), D("1150.00")), (date(2026, 4, 1), D("1300.00"))]
    assert [a.mode for a in w.sub_l.utility_agreements] == ["prepayment", "flat_rate"]
    g = C.generate_charges(w.db, None, from_month=date(2026, 3, 1), through_month=date(2026, 4, 1), lease_id=w.sub_l.id, today=date(2026, 4, 1))
    assert g["created_count"] == 2 and g["conflicts"] == []  # nur April neu (zu neuen Konditionen), März unverändert vorhanden


def test_changing_lease_dates_reports_orphaned_charges_but_changes_none(w):
    C.generate_charges(w.db, None, from_month=date(2026, 1, 1), through_month=date(2026, 6, 1), lease_id=w.sub_l.id, today=date(2026, 7, 1))
    before = snapshot(w)
    lease = L.update_lease(w.db, w.user.id, w.sub_l.id, {"end_date": date(2026, 3, 31), "is_fixed_term": True})
    outside = {c.id for c in w.db.scalars(select(Charge).where(Charge.lease_id == w.sub_l.id)) if c.period_start > date(2026, 3, 31)}
    assert set(lease._impact) == outside and len(outside) == 6  # Apr–Jun × 2 Arten
    assert snapshot(w) == before
    assert set(last_audit(w, "lease.updated", w.sub_l.id).details["charges_outside_period"]) == outside
    assert last_audit(w, "lease.updated", w.sub_l.id).details["changes"]["end_date"] == [None, "2026-03-31"]


# ---- Geprüfte Nebenkostenabrechnung: Verteilung eingefroren --------------------------------------------------------------------------------------
def build_statement(w):
    ct = {c.name: c.id for c in w.db.scalars(select(CostType))}
    st = U.create_statement(w.db, None, main_lease_id=w.main_l.id, period_start=date(2025, 6, 1), period_end=date(2025, 12, 31), unit_ids=[w.we1.id, w.we2.id])
    U.add_line(w.db, None, st.id, cost_type_id=ct["Heizung"], amount=D("1000.00"), allocation_key="area")
    U.set_prepayments(w.db, None, st.id, D("700.00"), "manual")
    return st


def test_reviewed_statement_keeps_frozen_allocation_when_area_changes(w):
    st = build_statement(w)
    live = U.allocate_statement(w.db, st.id)
    assert live["frozen"] is False and live["per_unit"] == {w.we1.id: D("600.00"), w.we2.id: D("400.00")}  # 60 : 40
    M.update_unit(w.db, None, w.we2.id, {"living_area": D("60.00")})
    assert U.allocate_statement(w.db, st.id)["per_unit"] == {w.we1.id: D("500.00"), w.we2.id: D("500.00")}  # vor der Prüfung: live
    M.update_unit(w.db, None, w.we2.id, {"living_area": D("40.00")})
    U.set_status(w.db, None, st.id, "captured"); U.set_status(w.db, None, st.id, "reviewed")
    M.update_unit(w.db, None, w.we2.id, {"living_area": D("200.00")})  # nach der Prüfung
    frozen = U.allocate_statement(w.db, st.id)
    assert frozen["frozen"] is True and frozen["per_unit"] == {w.we1.id: D("600.00"), w.we2.id: D("400.00")}
    assert frozen["frozen_at"] and frozen["unallocated"] == D("0.00") and frozen["lines"][0]["shares"][w.we1.id] == D("600.00")
    cmpr = U.compare_with_downstream(w.db, st.id)
    assert {r["unit_id"]: r["allocated_actual_costs"] for r in cmpr["rows"]} == {w.we1.id: D("600.00"), w.we2.id: D("400.00")}  # Vergleich nutzt die eingefrorene Verteilung
    with pytest.raises(ServiceError) as e:
        U.add_line(w.db, None, st.id, cost_type_id=1, amount=D("1.00"))
    assert e.value.code == "locked"


def test_unit_patch_api_warns_about_reviewed_statements(world):
    c = world["c"]
    ct = {x["name"]: x["id"] for x in c.get(V + "/cost-types").json()["items"]}
    st = post(c, "/utility-statements", {"main_lease_id": world["main"]["id"], "period_start": "2026-01-01", "period_end": "2026-01-31", "unit_ids": [world["unit"]["id"]]})
    post(c, f"/utility-statements/{st['id']}/lines", {"cost_type_id": ct["Heizung"], "amount": "100.00", "allocation_key": "area"})
    c.put(V + f"/utility-statements/{st['id']}/prepayments", json={"amount": "90.00", "source": "manual"})
    post(c, f"/utility-statements/{st['id']}/status", {"status": "captured"}); post(c, f"/utility-statements/{st['id']}/status", {"status": "reviewed"})
    r = c.patch(V + f"/units/{world['unit']['id']}", json={"living_area": "70.00"})
    assert r.status_code == 200 and r.json()["warnings"][0]["code"] == "area_changed" and "1 bereits geprüfte" in r.json()["warnings"][0]["message"]
    assert c.get(V + f"/utility-statements/{st['id']}/allocation").json()["frozen"] is True


def test_room_and_bed_patch_endpoints_and_lease_impact_message(world):
    c = world["c"]
    room = post(c, f"/units/{world['unit']['id']}/rooms", {"name": "Zimmer 1"})
    bed = post(c, f"/rooms/{room['id']}/beds", {"label": "Bett A"})
    assert c.patch(V + f"/rooms/{room['id']}", json={"name": "Wohnzimmer", "area": "21.50"}).json()["name"] == "Wohnzimmer"
    assert c.patch(V + f"/beds/{bed['id']}", json={"label": "Bett 1"}).json()["label"] == "Bett 1"
    assert c.patch(V + f"/beds/{bed['id']}", json={"unbekannt": 1}).status_code == 422
    post(c, "/charges/generate", {"allow_backdated": True, "from_month": "2026-01-01", "through_month": "2026-06-01", "lease_id": world["sub"]["id"]})
    r = c.patch(V + f"/leases/{world['sub']['id']}", json={"end_date": "2026-02-28"})
    assert r.status_code == 200 and len(r.json()["impact"]["charges_outside_period"]) == 8  # Mär–Jun × 2 Arten and "NICHT verändert" in r.json()["impact"]["message"]
