"""Mieter-Detailpanel (Master-Review B4): Inhalt, Trennung der Mieter, Performance."""
import io
import time
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import event, select

from leventum.models import Charge
from leventum.services import (charges as C, communications as COM, deposits as DEP, documents as DOC, master as M, payments as P, repairs as R, tasks as T,
                               tenant_overview as TO)
from leventum.storage import LocalFileStore
from tests.helpers import World

TODAY = date(2026, 3, 15)


@pytest.fixture
def w(app):
    w = World(app)
    w.main_l = w.activate_main()
    yield w
    w.db.close()


def setup_tenant(w, name="Max Mustermann", unit=None):
    t = w.tenant(name)
    s = w.sub([w.ru_unit(unit or w.we2)], [t], date(2026, 1, 1), None, contract_number=f"M-{name[:2]}")
    return t, s


def test_overview_contains_all_requested_sections_for_the_selected_tenant_only(w, settings):
    t, s = setup_tenant(w)
    other, so = setup_tenant(w, "Anna Andere", w.we1)
    C.generate_charges(w.db, None, from_month=date(2026, 1, 1), through_month=date(2026, 3, 1), today=TODAY)
    rent_jan = w.db.scalars(select(Charge).where(Charge.lease_id == s.id, Charge.charge_type == "base_rent", Charge.period_start == date(2026, 1, 1))).one()
    P.create_payment(w.db, None, direction="in", booking_date=date(2026, 1, 5), amount=D("900.00"), allocations=[{"charge_id": rent_jan.id, "amount": D("900.00")}])  # Teilzahlung
    DEP.add_transaction(w.db, None, DEP.ensure_deposit(w.db, None, s.id, agreed_amount=D("2000.00")).id, kind="paid", amount=D("2000.00"), transaction_date=date(2026, 1, 3))
    store = LocalFileStore(settings.documents_path, 4096)
    DOC.upload(w.db, store, None, stream=io.BytesIO(b"%PDF-1 mv"), filename="mv.pdf", doc_type="mietvertrag", entity_type="lease", entity_id=s.id)
    DOC.upload(w.db, store, None, stream=io.BytesIO(b"%PDF-1 fremd"), filename="fremd.pdf", doc_type="mietvertrag", entity_type="lease", entity_id=so.id)
    T.create_task(w.db, None, title="Schlüssel", lease_id=s.id); T.create_task(w.db, None, title="Fremde Aufgabe", lease_id=so.id)
    R.create_repair(w.db, None, property_id=w.prop.id, title="Heizung", reported_on=date(2026, 2, 1), lease_id=s.id)
    COM.create(w.db, w.user.id, channel="email", direction="in", subject="Frage", party_id=t.id)
    o = TO.overview(w.db, t.id, TODAY)
    assert o["party"].display_name == "Max Mustermann" and o["roles"] == ["tenant"]
    [lease] = o["leases"]
    assert lease["id"] == s.id and lease["phase"] == "active" and lease["spaces"][0].endswith("WE 2") and lease["monthly"]["total"] == D("1370.00")
    assert lease["deposit"]["held"] == D("2000.00") and lease["deposit"]["lease_kind"] == "sub" and lease["payment_status"] == "arrears"
    f = o["finance"]
    assert f["monthly_soll_total"] == D("1370.00") and f["overdue_total"] == f["open_total"] == D("1370.00") * 3 - D("900.00")  # Jan–Mär fällig, 900 gezahlt
    assert [(x["period_start"].month, x["charge_type"], x["open_amount"]) for x in f["open_items"]][0] == (1, "base_rent", D("250.00"))  # Teilzahlung reduziert den offenen Betrag
    assert [(p["amount"], p["allocated"]) for p in f["recent_payments"]] == [(D("900.00"), D("900.00"))]
    assert [d.original_name for d in o["documents"]] == ["mv.pdf"] and [t_.title for t_ in o["tasks"]] == ["Schlüssel"] and [r.title for r in o["repairs"]] == ["Heizung"]
    assert any("Frage" in a["summary"] for a in o["activity"]) and not any("Fremde" in a["summary"] or "Anna" in a["summary"] for a in o["activity"])


def test_overview_for_person_without_contract_and_unknown_id(w):
    lonely = w.tenant("Lisa Ohne Vertrag")
    o = TO.overview(w.db, lonely.id, TODAY)
    assert o["leases"] == [] and o["finance"]["open_total"] == D("0.00") and o["documents"] == [] and o["finance"]["monthly_soll_total"] == D("0.00")
    from leventum.services.errors import NotFound
    with pytest.raises(NotFound):
        TO.overview(w.db, 99999)


def test_phase_in_overview_marks_ended_and_future_leases(w):
    t = w.tenant("Zwei Verträge")
    old = w.sub([w.ru_unit(w.we2)], [t], date(2025, 1, 1), date(2025, 12, 31))
    new = w.sub([w.ru_unit(w.we2)], [t], date(2026, 6, 1), None)
    ph = {l["id"]: l["phase"] for l in TO.overview(w.db, t.id, TODAY)["leases"]}
    assert ph == {old.id: "ended", new.id: "upcoming"}


class Counter:
    def __init__(self, engine):
        self.n = 0
        event.listen(engine, "before_cursor_execute", self._inc)
        self.engine = engine

    def _inc(self, *a, **k):
        self.n += 1

    def close(self):
        event.remove(self.engine, "before_cursor_execute", self._inc)


def test_tenant_list_and_overview_stay_fast_and_use_bounded_queries_with_many_tenants(w, app):
    p = M.create_property(w.db, None, {"name": "Großobjekt", "property_type": "mehrfamilienhaus", "owner_party_id": w.owner.id})
    main = w.main(rus=[M.ensure_rentable_unit(w.db, None, property_id=p.id)], start=date(2025, 1, 1))
    from leventum.services import leases as L
    L.activate_lease(w.db, None, main.id)
    N = 60
    first = None
    for i in range(N):
        u = M.create_unit(w.db, None, p.id, {"unit_number": f"U{i:03d}", "living_area": D("50.00")})
        t = w.tenant(f"Mieter{i:03d} Test")
        s = w.sub([M.ensure_rentable_unit(w.db, None, property_id=p.id, unit_id=u.id)], [t], date(2026, 1, 1), None)
        first = first or t
    C.generate_charges(w.db, None, from_month=date(2026, 1, 1), through_month=date(2026, 3, 1), today=TODAY)
    w.db.commit()
    from fastapi.testclient import TestClient
    from tests.conftest import PW
    c = TestClient(app, headers={"X-Leventum-Client": "1"})
    from leventum.models import AppUser
    from leventum.security.passwords import hash_password
    w.user.password_hash = hash_password(PW); w.db.commit()
    assert c.post("/api/v1/auth/login", json={"username": "tester", "password": PW}).status_code == 200
    cnt = Counter(app.state.engine)
    t0 = time.perf_counter(); r = c.get("/api/v1/tenants?limit=50"); dt_list = time.perf_counter() - t0
    list_queries = cnt.n
    cnt.n = 0
    t0 = time.perf_counter(); o = c.get(f"/api/v1/tenants/{first.id}/overview"); dt_ov = time.perf_counter() - t0
    ov_queries = cnt.n
    cnt.close()
    print(f"\n[Messung] 60 Mieter: Liste {list_queries} Abfragen/{dt_list*1000:.0f} ms, Detailpanel {ov_queries} Abfragen/{dt_ov*1000:.0f} ms")
    body = r.json()
    assert r.status_code == 200 and len(body["items"]) == 50 and body["total"] >= N and all(i["payment_status"] == "arrears" for i in body["items"] if i.get("lease_id"))
    assert o.status_code == 200 and o.json()["finance"]["open_total"] == "4110.00"
    assert list_queries < 250, f"Mieterliste: {list_queries} Abfragen"  # gemessen 132 bei 60 Mietern: linear (≈2 je Vertrag für Raumbezeichnungen), nicht mehr je Mieter mehrere Abfragen
    assert ov_queries < 80, f"Detailpanel: {ov_queries} Abfragen"
    assert dt_list < 2.0 and dt_ov < 1.0, (dt_list, dt_ov)
    p2 = c.get("/api/v1/tenants?limit=50&offset=50").json()
    assert p2["offset"] == 50 and len(p2["items"]) == body["total"] - 50 and not ({i["name"] for i in p2["items"]} & {i["name"] for i in body["items"]})  # Paginierung ohne Überlappung


def test_overview_endpoint_permissions_and_404(world, app):
    from fastapi.testclient import TestClient
    c = world["c"]
    r = c.get(f"/api/v1/tenants/{world['tenant']['id']}/overview")
    assert r.status_code == 200 and r.json()["leases"][0]["phase"] in ("active", "ended", "upcoming") and r.json()["party"]["display_name"] == "Max Mustermann"
    assert c.get("/api/v1/tenants/99999/overview").status_code == 404
    assert TestClient(app, headers={"X-Leventum-Client": "1"}).get(f"/api/v1/tenants/{world['tenant']['id']}/overview").status_code == 401
from tests.test_d_api import world  # noqa: E402,F401
