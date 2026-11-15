"""Regressionstests zu Mängeln, die bei der visuellen Prüfung (Screenshots) aufgefallen sind."""
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from leventum.models import Charge
from leventum.services import charges as C, economics as E, master as M, payments as P, repairs as R, tasks as T
from tests.helpers import World
from tests.test_d_api import post, world  # noqa: F401  (HTTP-Testwelt wiederverwenden)

V = "/api/v1"


@pytest.fixture
def w(app):
    w = World(app)
    yield w
    w.db.close()


def test_prefix_helper_does_not_double_labels():
    assert M.prefixed("WE", "03") == "WE 03" and M.prefixed("WE", "WE 03") == "WE 03" and M.prefixed("WE", "we 3") == "we 3"
    assert M.prefixed("Zimmer", "Zimmer 1") == "Zimmer 1" and M.prefixed("Bett", "A") == "Bett A"


def test_space_and_leaf_labels_never_repeat_the_prefix(w):
    u = M.create_unit(w.db, None, w.prop.id, {"unit_number": "WE 03", "living_area": D("90.00")})
    r = M.create_room(w.db, None, u.id, {"name": "Zimmer 1"})
    b = M.create_bed(w.db, None, r.id, {"label": "Bett A"})
    ru = M.ensure_rentable_unit(w.db, None, property_id=w.prop.id, bed_id=b.id)
    assert M.space_label(w.db, ru) == "Haus Bergmann · WE 03 · Zimmer 1 · Bett A"
    labels = [l.label for l in E.Structure(w.db).leaves]
    assert "Haus Bergmann · WE 03 · Zimmer 1 · Bett A" in labels and not any("WE WE" in l or "Zimmer Zimmer" in l or "Bett Bett" in l for l in labels)
    # Bezeichnungen ohne Präfix bekommen es weiterhin
    assert "Haus Bergmann · WE 1 · Zimmer 1 · Bett A" in [M.space_label(w.db, M.ensure_rentable_unit(w.db, None, property_id=w.prop.id, bed_id=w.bed1.id))]


def test_lease_title_is_human_readable(w):
    w.activate_main()
    sub = w.sub([w.ru_unit(w.we2)], [w.tenant("Max Mustermann")], date(2026, 1, 1), None)
    assert M.lease_title(w.db, sub) == "Max Mustermann · Haus Bergmann · WE 2"
    assert M.lease_title(w.db, w.db.get(type(sub), 1)).startswith("Olga Eigentümer · Haus Bergmann")


def test_arrears_status_considers_partial_payments_and_due_dates(w):
    w.activate_main()
    sub = w.sub([w.ru_unit(w.we2)], [w.tenant("Max Mustermann")], date(2026, 1, 1), None)
    C.generate_charges(w.db, None, from_month=date(2026, 1, 1), through_month=date(2026, 1, 1), today=date(2026, 2, 1))
    assert C.arrears(w.db, sub.id, date(2026, 1, 1)) == {"status": "current", "amount": D("0.00"), "count": 0}  # am Fälligkeitstag noch nicht überfällig
    a = C.arrears(w.db, sub.id, date(2026, 2, 1))
    assert (a["status"], a["amount"], a["count"]) == ("arrears", D("1370.00"), 2)
    rent = w.db.scalars(select(Charge).where(Charge.lease_id == sub.id, Charge.charge_type == "base_rent")).one()
    P.create_payment(w.db, None, direction="in", booking_date=date(2026, 1, 5), amount=D("1150.00"), allocations=[{"charge_id": rent.id, "amount": D("1150.00")}])
    assert C.arrears(w.db, sub.id, date(2026, 2, 1))["amount"] == D("220.00")
    nk = w.db.scalars(select(Charge).where(Charge.lease_id == sub.id, Charge.charge_type == "utility_prepayment")).one()
    P.create_payment(w.db, None, direction="in", booking_date=date(2026, 1, 6), amount=D("220.00"), allocations=[{"charge_id": nk.id, "amount": D("220.00")}])
    assert C.arrears(w.db, sub.id, date(2026, 2, 1))["status"] == "current"


def test_status_texts_in_history_are_german(w):
    t = T.create_task(w.db, None, title="x")
    T.set_status(w.db, None, t.id, "waiting")
    r = R.create_repair(w.db, None, property_id=w.prop.id, title="y", reported_on=date(2026, 1, 1))
    R.set_status(w.db, None, r.id, "scheduled")
    texts = " ".join(e.text for e in R.view(w.db, r)["events"])
    assert "Gemeldet → Terminiert" in texts and "reported" not in texts.replace("Gemeldet: y", "") and "scheduled" not in texts


def test_tenants_api_shows_payment_status_and_arrears_filter(world):  # noqa: F811
    c = world["c"]
    post(c, "/charges/generate", {"allow_backdated": True, "from_month": "2026-01-01", "through_month": "2026-01-01"})
    row = c.get(V + "/tenants").json()["items"][0]
    assert row["payment_status"] == "arrears" and row["overdue_amount"] == "1370.00"
    assert [r["name"] for r in c.get(V + "/tenants?status=arrears").json()["items"]] == ["Max Mustermann"]
    ch = next(x for x in c.get(V + f"/charges?lease_id={world['sub']['id']}").json()["items"])
    assert ch["lease_label"].startswith("Max Mustermann · Haus Bergmann")
    od = c.get(V + "/dunning/overdue?as_of=2026-02-10").json()["items"]
    assert all(i["lease_label"].startswith("Max Mustermann") for i in od)


def test_dashboard_computes_month_figures_only_once(world, monkeypatch):  # noqa: F811
    calls = []
    original = E.current_month_figures
    monkeypatch.setattr(E, "current_month_figures", lambda db, today=None: (calls.append(1), original(db, today))[1])
    assert world["c"].get(V + "/dashboard").status_code == 200
    assert len(calls) == 1  # vorher: einmal je Kennzahl (5×) → über 1 s Ladezeit
