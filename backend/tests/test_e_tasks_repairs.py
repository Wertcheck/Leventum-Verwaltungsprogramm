from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from leventum.models import AuditEvent, Repair, RepairEvent
from leventum.services import economics as E, leases as L, master as M, payments as P, repairs as R, tasks as T
from leventum.services.errors import ServiceError
from tests.helpers import World

TODAY = date(2026, 3, 15)


@pytest.fixture
def w(app):
    w = World(app)
    w.main_l = w.activate_main()
    w.sub_l = w.sub([w.ru_unit(w.we2)], [w.tenant("Max Mustermann")], date(2026, 1, 1), None)
    yield w
    w.db.close()


# ---- Aufgaben ---------------------------------------------------------------------------------------------------------------------------------
def test_task_can_be_linked_to_every_supported_entity(w):
    inv = P.create_invoice(w.db, None, property_id=w.prop.id, amount=D("10.00"), invoice_date=date(2026, 1, 5))
    rep = R.create_repair(w.db, None, property_id=w.prop.id, title="Heizung defekt", reported_on=TODAY)
    links = {"party_id": w.owner.id, "property_id": w.prop.id, "unit_id": w.we1.id, "lease_id": w.sub_l.id, "invoice_id": inv.id, "repair_id": rep.id}
    for k, v in links.items():
        t = T.create_task(w.db, w.user.id, title=f"Aufgabe {k}", **{k: v})
        assert getattr(t, k) == v and t.status == "open" and t.priority == "normal" and t.created_by_user_id == w.user.id
    both = T.create_task(w.db, None, title="mehrfach", **links)
    assert all(getattr(both, k) == v for k, v in links.items())
    assert len(T.query(w.db, lease_id=w.sub_l.id)) == 2 and len(T.query(w.db, repair_id=rep.id)) == 2


def test_task_validation(w):
    for kw in (dict(title="  "), dict(title="x", lease_id=999), dict(title="x", party_id=999), dict(title="x", priority="sofort"), dict(title="x", assignee_user_id=999)):
        with pytest.raises(ServiceError):
            T.create_task(w.db, None, **kw)


def test_status_workflow_completed_at_reopen_and_cancel_reason(w):
    t = T.create_task(w.db, w.user.id, title="Schlüssel übergeben")
    T.set_status(w.db, w.user.id, t.id, "in_progress")
    T.set_status(w.db, w.user.id, t.id, "waiting", "Mieter meldet sich")
    assert t.completed_at is None
    T.set_status(w.db, w.user.id, t.id, "done")
    assert t.status == "done" and t.completed_at is not None
    T.set_status(w.db, w.user.id, t.id, "open")  # Wiedereröffnen
    assert t.completed_at is None
    with pytest.raises(ServiceError) as e:
        T.set_status(w.db, None, t.id, "cancelled")
    assert e.value.code == "reason_required"
    T.set_status(w.db, None, t.id, "cancelled", "nicht mehr nötig")
    assert t.status == "cancelled"
    with pytest.raises(ServiceError):
        T.set_status(w.db, None, t.id, "erledigt")
    with pytest.raises(ServiceError):
        T.update_task(w.db, None, t.id, {"status": "done"})  # Status nur über den Statuswechsel
    acts = [a.summary for a in w.db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "task", AuditEvent.entity_id == str(t.id), AuditEvent.action == "task.status"))]
    assert acts == ["Aufgabenstatus: open → in_progress", "Aufgabenstatus: in_progress → waiting", "Aufgabenstatus: waiting → done", "Aufgabenstatus: done → open", "Aufgabenstatus: open → cancelled"]


def test_filters_overdue_and_ordering(w):
    a = T.create_task(w.db, None, title="Spät", due_date=date(2026, 3, 1), priority="high", lease_id=w.sub_l.id)
    b = T.create_task(w.db, None, title="Bald", due_date=date(2026, 3, 20))
    c = T.create_task(w.db, None, title="Ohne Datum")
    d = T.create_task(w.db, None, title="Erledigt spät", due_date=date(2026, 2, 1))
    T.set_status(w.db, None, d.id, "done")
    assert [t.title for t in T.query(w.db)] == ["Erledigt spät", "Spät", "Bald", "Ohne Datum"]  # nach Fälligkeit, ohne Datum zuletzt
    assert [t.title for t in T.query(w.db, overdue=True, today=TODAY)] == ["Spät"]  # erledigte Aufgaben sind nie überfällig
    assert [t.title for t in T.query(w.db, priority="high")] == ["Spät"]
    assert {t.title for t in T.query(w.db, open_only=True)} == {"Spät", "Bald", "Ohne Datum"}
    assert [t.title for t in T.query(w.db, status="done")] == ["Erledigt spät"]
    assert [t.title for t in T.query(w.db, q="bald")] == ["Bald"] and [t.title for t in T.query(w.db, lease_id=w.sub_l.id)] == ["Spät"]
    assert T.is_overdue(a, TODAY) and not T.is_overdue(b, TODAY) and not T.is_overdue(c, TODAY)


# ---- Reparaturen ----------------------------------------------------------------------------------------------------------------------------------
def repair(w, **kw):
    return R.create_repair(w.db, w.user.id, **{"property_id": w.prop.id, "title": "Heizung defekt", "reported_on": TODAY, "unit_id": w.we2.id, "category": "heizung", **kw})


def test_repair_creation_validation_and_initial_event(w):
    r = repair(w, priority="urgent", lease_id=w.sub_l.id, reported_by_party_id=w.sub_l.parties[1].party_id)
    ev = w.db.scalars(select(RepairEvent).where(RepairEvent.repair_id == r.id)).all()
    assert r.status == "reported" and [e.kind for e in ev] == ["reported"]
    other = M.create_property(w.db, None, {"name": "Anderes", "property_type": "wohnung"})
    ou = M.create_unit(w.db, None, other.id, {"unit_number": "1"})
    for kw in (dict(unit_id=ou.id), dict(category="ufo"), dict(priority="x"), dict(cost_estimate=D("-1")), dict(contractor_party_id=999), dict(title=" ")):
        with pytest.raises(ServiceError):
            repair(w, **kw)


def test_status_history_cancel_reason_and_completion_date(w):
    r = repair(w)
    R.set_status(w.db, None, r.id, "scheduled")
    R.update_repair(w.db, None, r.id, {"scheduled_for": date(2026, 3, 20), "contractor_party_id": w.owner.id, "cost_estimate": D("500.00")})
    R.set_status(w.db, None, r.id, "in_progress")
    R.add_note(w.db, None, r.id, "Monteur war vor Ort, Ersatzteil bestellt")
    R.set_status(w.db, None, r.id, "done", on=date(2026, 3, 22))
    assert r.completed_on == date(2026, 3, 22) and not R.is_open(r)
    kinds = [e.kind for e in R.view(w.db, r)["events"]]
    assert kinds == ["reported", "status", "scheduled", "contractor", "estimate", "status", "note", "status"]
    R.set_status(w.db, None, r.id, "in_progress", "Mangel besteht weiter")  # Wiedereröffnung ist nachvollziehbar
    assert r.completed_on is None and R.is_open(r)
    with pytest.raises(ServiceError) as e:
        R.set_status(w.db, None, r.id, "cancelled")
    assert e.value.code == "reason_required"
    with pytest.raises(ServiceError):
        R.update_repair(w.db, None, r.id, {"status": "done"})
    with pytest.raises(ServiceError):
        R.add_note(w.db, None, r.id, " ")


def test_actual_costs_come_only_from_linked_non_voided_invoices(w):
    r = repair(w, cost_estimate=D("500.00"))
    assert R.costs(w.db, r)["actual"] == D("0.00") and R.costs(w.db, r)["deviation_from_estimate"] == D("-500.00")
    i1 = P.create_invoice(w.db, None, property_id=w.prop.id, unit_id=w.we2.id, invoice_number="A1", amount=D("300.00"), invoice_date=date(2026, 3, 18), repair_id=r.id)
    i2 = P.create_invoice(w.db, None, property_id=w.prop.id, invoice_number="A2", amount=D("250.00"), invoice_date=date(2026, 3, 19))
    R.link_invoice(w.db, None, r.id, i2.id)
    c = R.costs(w.db, r)
    assert (c["actual"], c["deviation_from_estimate"], c["invoice_ids"]) == (D("550.00"), D("50.00"), [i1.id, i2.id])
    P.create_payment(w.db, None, direction="out", booking_date=date(2026, 3, 25), amount=D("300.00"), allocations=[{"invoice_id": i1.id, "amount": D("300.00")}])
    c = R.costs(w.db, r)
    assert (c["paid"], c["open"]) == (D("300.00"), D("250.00"))
    P.void_invoice(w.db, None, i2.id, "falsche Rechnung")
    assert R.costs(w.db, r)["actual"] == D("300.00")  # storniert → nicht mehr in den Kosten
    assert w.db.scalars(select(RepairEvent).where(RepairEvent.kind == "invoice")).all()


def test_invoice_linking_rules(w):
    r1, r2 = repair(w), repair(w, title="Fenster")
    other = M.create_property(w.db, None, {"name": "Anderes", "property_type": "wohnung"})
    foreign = P.create_invoice(w.db, None, property_id=other.id, amount=D("5.00"), invoice_date=TODAY)
    with pytest.raises(ServiceError):
        R.link_invoice(w.db, None, r1.id, foreign.id)  # anderes Objekt
    with pytest.raises(ServiceError):
        P.create_invoice(w.db, None, property_id=other.id, amount=D("5.00"), invoice_date=TODAY, repair_id=r1.id)
    inv = P.create_invoice(w.db, None, property_id=w.prop.id, amount=D("5.00"), invoice_date=TODAY)
    R.link_invoice(w.db, None, r1.id, inv.id)
    R.link_invoice(w.db, None, r1.id, inv.id)  # idempotent
    with pytest.raises(ServiceError) as e:
        R.link_invoice(w.db, None, r2.id, inv.id)
    assert e.value.code == "conflict"


def test_repair_cost_flows_into_economics_object_costs_exactly_once(w):
    w.prop.is_active = True
    r = repair(w)
    P.create_invoice(w.db, None, property_id=w.prop.id, unit_id=w.we2.id, amount=D("238.00"), invoice_date=date(2026, 1, 20), repair_id=r.id)
    rep = E.Engine(w.db, date(2026, 1, 1), date(2026, 1, 31)).report("portfolio")
    assert rep["soll"]["object_costs"] == D("238.00")
    assert E.Engine(w.db, date(2026, 1, 1), date(2026, 1, 31)).report("unit", w.we2.id)["soll"]["object_costs"] == D("238.00")


def test_tasks_linked_to_repair_are_part_of_the_repair_view(w):
    r = repair(w)
    t = T.create_task(w.db, None, title="Handwerker anrufen", repair_id=r.id, property_id=w.prop.id)
    assert [x.id for x in R.view(w.db, r)["tasks"]] == [t.id]
