from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from leventum.models import AppUser, Role
from leventum.security.passwords import hash_password
from tests.conftest import PW

V = "/api/v1"


def post(c, path, body=None, status=(200, 201)):
    r = c.post(V + path, json=body if body is not None else {})
    assert r.status_code in status, f"{path}: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture
def world(auth_client):
    c = auth_client
    own = post(c, "/parties", {"kind": "company", "company_name": "Leventum Real Estate", "is_own_organization": True})
    owner = post(c, "/parties", {"kind": "person", "first_name": "Olga", "last_name": "Eigentümer", "roles": ["owner"]})
    tenant = post(c, "/parties", {"kind": "person", "first_name": "Max", "last_name": "Mustermann", "roles": ["tenant"]})
    prop = post(c, "/properties", {"name": "Haus Bergmann", "property_type": "mehrfamilienhaus", "owner_party_id": owner["id"]})
    unit = post(c, f"/properties/{prop['id']}/units", {"unit_number": "WE 1", "living_area": "60.00"})
    types = {t["code"]: t["id"] for t in c.get(V + "/lease-types").json()["items"]}
    rp, ru = post(c, "/rentable-units", {"property_id": prop["id"]}), post(c, "/rentable-units", {"property_id": prop["id"], "unit_id": unit["id"]})
    end = (date.today() + timedelta(days=40)).isoformat()
    main = post(c, "/leases", {"kind": "main", "lease_type_id": types["hauptmiete"], "start_date": "2026-01-01", "subletting_permitted": True,
                               "parties": [{"party_id": owner["id"], "role": "lessor"}, {"party_id": own["id"], "role": "lessee"}], "rentable_unit_ids": [rp["id"]]})
    post(c, f"/leases/{main['id']}/terms", {"valid_from": "2026-01-01", "base_rent": "850.00"})
    post(c, f"/leases/{main['id']}/activate")
    sub = post(c, "/leases", {"kind": "sub", "lease_type_id": types["wohnraum_befristet"], "start_date": "2026-01-01", "end_date": end, "is_fixed_term": True,
                              "notice_period_months": 1, "parties": [{"party_id": own["id"], "role": "lessor"}, {"party_id": tenant["id"], "role": "lessee"}], "rentable_unit_ids": [ru["id"]]})
    post(c, f"/leases/{sub['id']}/terms", {"valid_from": "2026-01-01", "base_rent": "1150.00"})
    post(c, f"/leases/{sub['id']}/activate")
    return dict(c=c, tenant=tenant, owner=owner, prop=prop, unit=unit, main=main, sub=sub, end=end)


def role_client(app, role, name):
    with app.state.session_factory() as db:
        db.add(AppUser(username=name, display_name=name, password_hash=hash_password(PW), role_id=db.scalar(select(Role.id).where(Role.code == role))))
        db.commit()
    c = TestClient(app, headers={"X-Leventum-Client": "1"})
    assert c.post(V + "/auth/login", json={"username": name, "password": PW}).status_code == 200
    return c


def test_tasks_repairs_communications_over_http(world):
    c = world["c"]
    t = post(c, "/tasks", {"title": "Schlüssel nachmachen", "priority": "high", "due_date": "2020-01-01", "lease_id": world["sub"]["id"], "property_id": world["prop"]["id"]})
    assert t["overdue"] is True and t["status"] == "open"
    assert post(c, f"/tasks/{t['id']}/status", {"status": "done"})["overdue"] is False
    assert c.post(V + f"/tasks/{t['id']}/status", json={"status": "cancelled"}).status_code == 400  # Begründung fehlt
    assert c.post(V + "/tasks", json={"title": "x", "lease_id": 999}).status_code == 404
    assert c.patch(V + f"/tasks/{t['id']}", json={"status": "open"}).status_code == 422  # extra=forbid: Status nicht per PATCH
    assert [x["id"] for x in c.get(V + f"/tasks?lease_id={world['sub']['id']}&status=done").json()["items"]] == [t["id"]]
    r = post(c, "/repairs", {"property_id": world["prop"]["id"], "unit_id": world["unit"]["id"], "title": "Heizung defekt", "category": "heizung", "reported_on": "2026-03-01", "cost_estimate": "500.00", "priority": "urgent"})
    inv = post(c, "/invoices", {"property_id": world["prop"]["id"], "amount": "300.00", "invoice_date": "2026-03-10", "repair_id": r["id"]})
    r = c.get(V + f"/repairs/{r['id']}").json()
    assert r["costs"]["actual"] == "300.00" and r["costs"]["deviation_from_estimate"] == "-200.00" and r["costs"]["invoice_ids"] == [inv["id"]]
    r = post(c, f"/repairs/{r['id']}/status", {"status": "done", "on": "2026-03-12"})
    assert r["completed_on"] == "2026-03-12" and [e["kind"] for e in r["events"]][:2] == ["reported", "status"]
    task = post(c, "/tasks", {"title": "Handwerker bezahlen", "repair_id": r["id"]})
    assert c.get(V + f"/repairs/{r['id']}").json()["tasks"][0]["id"] == task["id"]
    cm = post(c, "/communications", {"channel": "email", "direction": "in", "subject": "Heizung kalt", "party_id": world["tenant"]["id"], "repair_id": r["id"],
                                      "follow_up": {"title": "Mieter zurückrufen"}})
    assert cm["subject"] == "Heizung kalt" and any(x["title"] == "Mieter zurückrufen" for x in c.get(V + "/tasks").json()["items"])
    assert c.post(V + "/communications", json={"channel": "email", "direction": "in", "subject": "x"}).status_code == 400  # ohne Zuordnung
    paths = c.app.openapi()["paths"]
    assert set(paths["/api/v1/communications"]) == {"get", "post"} and not any("send" in p for p in paths)  # kein Ändern/Löschen, kein Versand


def test_reminders_to_task_is_idempotent_and_linked(world):
    c = world["c"]
    rems = c.get(V + "/reminders").json()["items"]
    types = {r["type"] for r in rems}
    assert {"contract_end", "notice_deadline", "missing_document"} <= types
    ce = next(r for r in rems if r["type"] == "contract_end")
    assert ce["entity_id"] == world["sub"]["id"] and ce["task_id"] is None
    t = post(c, "/reminders/task", {"key": ce["key"]})
    assert t["source"] == "reminder" and t["lease_id"] == world["sub"]["id"] and t["due_date"] == world["end"]
    again = c.post(V + "/reminders/task", json={"key": ce["key"]})
    assert again.status_code == 409 and again.json()["detail"]["details"]["task_id"] == t["id"]
    assert next(r for r in c.get(V + "/reminders").json()["items"] if r["key"] == ce["key"])["task_id"] == t["id"]
    assert c.post(V + "/reminders/task", json={"key": "gibt-es-nicht"}).status_code == 404
    assert len(c.get(V + "/tasks?q=endet").json()["items"]) == 1


def test_documents_search_delete_and_download_protection(world, app):
    c = world["c"]
    up = c.post(V + "/documents", data={"entity_type": "lease", "entity_id": world["sub"]["id"], "doc_type": "mietvertrag"}, files={"file": ("Mietvertrag Mustermann.pdf", b"%PDF-1.4 mv", "application/pdf")})
    assert up.status_code == 201
    doc = up.json()
    miss = c.get(V + f"/leases/{world['sub']['id']}/missing-documents").json()["missing"]
    assert miss == ["uebergabeprotokoll"]
    assert [d["id"] for d in c.get(V + "/documents/search?q=mustermann").json()["items"]] == [doc["id"]]
    assert c.get(V + "/documents/search?doc_type=rechnung").json()["items"] == []
    assert c.post(V + f"/documents/{doc['id']}/links", json={"entity_type": "party", "entity_id": world["tenant"]["id"]}).status_code == 200
    assert c.post(V + f"/documents/{doc['id']}/delete", json={"reason": "  "}).status_code in (400, 422)
    assert c.post(V + f"/documents/{doc['id']}/delete", json={"reason": "Doppelt"}).status_code == 200
    assert c.get(V + f"/documents/{doc['id']}/download").status_code == 404 and c.get(V + "/documents/search").json()["items"] == []
    assert len(c.get(V + "/documents/search?include_deleted=true").json()["items"]) == 1
    assert c.get(V + f"/leases/{world['sub']['id']}/missing-documents").json()["missing"] == ["mietvertrag", "uebergabeprotokoll"]
    anon = TestClient(app, headers={"X-Leventum-Client": "1"})
    assert anon.get(V + "/documents/search").status_code == 401


def test_history_and_dashboard_use_real_data(world):
    c = world["c"]
    post(c, "/communications", {"channel": "phone", "direction": "in", "subject": "Anruf Mieter", "party_id": world["tenant"]["id"]})
    h = c.get(V + f"/history?entity_type=party&entity_id={world['tenant']['id']}").json()["items"]
    assert any("Anruf Mieter" in i["summary"] for i in h) and any(i["actor"] == "Admin" for i in h) and h == sorted(h, key=lambda i: i["at"], reverse=True)
    assert c.get(V + "/history?entity_type=geheim&entity_id=1").status_code == 400
    post(c, "/tasks", {"title": "Überfällig", "due_date": "2020-01-01"})
    post(c, "/repairs", {"property_id": world["prop"]["id"], "title": "Offen", "reported_on": "2026-03-01"})
    d = c.get(V + "/dashboard").json()
    k = {x["key"]: x for x in d["kpis"]}
    assert (k["open_tasks"]["value"], k["overdue_tasks"]["value"], k["open_repairs"]["value"]) == (1, 1, 1) and all(x["available"] for x in d["kpis"])
    assert d["tasks"][0]["title"] == "Überfällig" and d["tasks"][0]["overdue"] is True
    assert any(w["type"] == "contract_end" for w in d["warnings"]) and len(d["warnings"]) <= 8


def test_role_permissions_for_operations(world, app):
    betreuung = role_client(app, "objektbetreuung", "betreuer")
    assert betreuung.post(V + "/tasks", json={"title": "Treppenhaus reinigen"}).status_code == 201
    assert betreuung.post(V + "/repairs", json={"property_id": world["prop"]["id"], "title": "Tür", "reported_on": "2026-03-01"}).status_code == 201
    assert betreuung.post(V + "/parties", json={"kind": "person", "last_name": "X"}).status_code == 403          # keine Stammdaten
    assert betreuung.post(V + "/charges/generate", json={"from_month": "2026-01-01", "through_month": "2026-01-01"}).status_code == 403  # keine Finanzen
    assert betreuung.get(V + "/economics?start=2026-01-01&end=2026-01-31").status_code == 403
    buch = role_client(app, "buchhaltung", "buchhalter")
    assert buch.post(V + "/repairs", json={"property_id": world["prop"]["id"], "title": "x", "reported_on": "2026-03-01"}).status_code == 403
    assert buch.post(V + "/documents", data={"entity_type": "property", "entity_id": world["prop"]["id"]}, files={"file": ("b.pdf", b"%PDF-1", "application/pdf")}).status_code == 201
    leser = role_client(app, "lesend", "leser")
    assert leser.get(V + "/tasks").status_code == 200 and leser.get(V + "/repairs").status_code == 200 and leser.get(V + "/reminders").status_code == 200
    for path, body in (("/tasks", {"title": "x"}), ("/repairs", {"property_id": 1, "title": "x", "reported_on": "2026-01-01"}), ("/communications", {"channel": "email", "direction": "in", "subject": "x", "party_id": 1}),
                       ("/reminders/task", {"key": "k"}), ("/documents/1/delete", {"reason": "x"})):
        assert leser.post(V + path, json=body).status_code == 403, path
