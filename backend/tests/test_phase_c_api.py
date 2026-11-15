from sqlalchemy import select

from leventum.models import AppUser, Role
from leventum.security.passwords import hash_password
from tests.conftest import PW

V = "/api/v1"


def post(c, path, body, status=201):
    r = c.post(V + path, json=body)
    assert r.status_code == status, r.text
    return r.json()


def build(c):
    own = post(c, "/parties", {"kind": "company", "company_name": "Leventum Real Estate", "is_own_organization": True})
    owner = post(c, "/parties", {"kind": "person", "first_name": "Olga", "last_name": "Eigentümer", "roles": ["owner"]})
    tenant = post(c, "/parties", {"kind": "person", "first_name": "Max", "last_name": "Mustermann", "roles": ["tenant"]})
    prop = post(c, "/properties", {"name": "Haus Bergmann", "property_type": "mehrfamilienhaus", "street": "Bergmannstraße 12",
                                   "city": "Berlin", "owner_party_id": owner["id"], "total_area": "100.00"})
    unit = post(c, f"/properties/{prop['id']}/units", {"unit_number": "WE 03", "living_area": "78.50", "rooms_count": 3})
    room = post(c, f"/units/{unit['id']}/rooms", {"name": "Zimmer 1"})
    bed = post(c, f"/rooms/{room['id']}/beds", {"label": "Bett A"})
    types = {t["code"]: t["id"] for t in c.get(V + "/lease-types").json()["items"]}
    return own, owner, tenant, prop, unit, room, bed, types


def test_full_flow_over_http(auth_client):
    c = auth_client
    own, owner, tenant, prop, unit, room, bed, types = build(c)
    ru_prop = post(c, "/rentable-units", {"property_id": prop["id"]})
    ru_bed = post(c, "/rentable-units", {"property_id": prop["id"], "bed_id": bed["id"]})
    assert ru_prop["level"] == "property" and ru_bed["level"] == "bed" and ru_bed["label"].endswith("WE 03 · Zimmer 1 · Bett A")
    main = post(c, "/leases", {"kind": "main", "lease_type_id": types["hauptmiete"], "start_date": "2026-01-01", "subletting_permitted": True,
                               "parties": [{"party_id": owner["id"], "role": "lessor"}, {"party_id": own["id"], "role": "lessee"}],
                               "rentable_unit_ids": [ru_prop["id"]]})
    post(c, f"/leases/{main['id']}/terms", {"valid_from": "2026-01-01", "base_rent": "850.00"})
    post(c, f"/leases/{main['id']}/utility-agreements", {"valid_from": "2026-01-01", "mode": "prepayment", "monthly_amount": "180.00"})
    assert c.post(f"{V}/leases/{main['id']}/activate").json()["status"] == "active"
    sub = post(c, "/leases", {"kind": "sub", "lease_type_id": types["bett"], "start_date": "2026-02-01", "end_date": "2026-07-31", "is_fixed_term": True,
                              "intended_use": "monteur", "parties": [{"party_id": own["id"], "role": "lessor"}, {"party_id": tenant["id"], "role": "lessee"}],
                              "rentable_unit_ids": [ru_bed["id"]]})
    post(c, f"/leases/{sub['id']}/terms", {"valid_from": "2026-02-01", "base_rent": "300.00", "other_charges": "25.00"})
    post(c, f"/leases/{sub['id']}/utility-agreements", {"valid_from": "2026-02-01", "mode": "flat_rate", "monthly_amount": "40.00"})
    r = c.post(f"{V}/leases/{sub['id']}/activate")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["monthly_total"]["total"] == "365.00" and d["monthly_total"]["utility_mode"] == "flat_rate"  # Geld als String
    assert d["legal_review_status"] == "not_reviewed" and d["legal_basis_ref"] is None
    assert any(h["code"] == "legal_not_reviewed" for h in d["validation"]["hints"])
    # Mieterübersicht
    t = c.get(V + "/tenants").json()["items"]
    assert t[0]["name"] == "Max Mustermann" and t[0]["lease_raw_status"] == "active" and t[0]["lease_status"] == "ended" and t[0]["payment_status"] == "current" and t[0]["overdue_amount"] == "0.00"  # keine Sollstellung überfällig
    # Der Vertrag endete am 31.07.2026 → zeitbezogene Phase "Beendet", obwohl der Rohstatus noch "active" ist (Befund B2)
    assert [r["name"] for r in c.get(V + "/tenants?status=ended").json()["items"]] == ["Max Mustermann"] and c.get(V + "/tenants?status=active").json()["items"] == []
    # Wohneinheit gilt über Bettbelegung als belegt (Stichtag: heute liegt nach Vertragsende → vacant)
    u = c.get(V + "/units").json()["items"][0]
    assert u["occupancy_status"] in ("vacant", "occupied") and "living_area" in u and u["living_area"] == "78.50"
    # Suche
    res = c.get(V + "/search?q=berg").json()["items"]
    assert {"property"} <= {x["type"] for x in res}
    assert any(x["type"] == "lease" for x in c.get(V + "/search?q=mustermann").json()["items"])
    # Mieterakte
    pa = c.get(f"{V}/parties/{tenant['id']}").json()
    assert pa["leases"][0]["id"] == sub["id"] and pa["history"]


def test_validation_errors_are_structured_422(auth_client):
    c = auth_client
    own, owner, tenant, prop, unit, room, bed, types = build(c)
    ru = post(c, "/rentable-units", {"property_id": prop["id"], "unit_id": unit["id"]})
    sub = post(c, "/leases", {"kind": "sub", "lease_type_id": types["zimmer"], "start_date": "2026-02-01",
                              "parties": [{"party_id": own["id"], "role": "lessor"}, {"party_id": tenant["id"], "role": "lessee"}],
                              "rentable_unit_ids": [ru["id"]]})
    r = c.post(f"{V}/leases/{sub['id']}/activate")
    assert r.status_code == 422
    det = r.json()["detail"]
    assert det["code"] == "validation_failed" and any(e["code"] == "not_covered" for e in det["details"]["errors"])
    assert c.get(f"{V}/leases/{sub['id']}").json()["status"] == "draft"  # nichts halb aktiviert


def test_input_validation_and_conflicts(auth_client):
    c = auth_client
    own, owner, tenant, prop, unit, room, bed, types = build(c)
    assert c.post(f"{V}/properties/{prop['id']}/units", json={"unit_number": "WE 03"}).status_code == 409
    assert c.post(f"{V}/properties/{prop['id']}/units", json={"unit_number": "X", "living_area": "10.123"}).status_code == 422  # > 2 Nachkommastellen
    assert c.post(f"{V}/properties/{prop['id']}/units", json={"unit_number": "X", "unbekannt": 1}).status_code == 422  # extra=forbid
    assert c.post(f"{V}/parties", json={"kind": "person"}).status_code == 400  # Name fehlt
    assert c.get(f"{V}/leases/999").status_code == 404
    lease = post(c, "/leases", {"kind": "main", "lease_type_id": types["hauptmiete"], "start_date": "2026-01-01",
                                "parties": [], "rentable_unit_ids": [post(c, "/rentable-units", {"property_id": prop["id"]})["id"]]})
    assert c.post(f"{V}/leases/{lease['id']}/terms", json={"valid_from": "2026-01-01", "base_rent": "-1"}).status_code == 422
    assert c.patch(f"{V}/leases/{lease['id']}", json={"status": "active"}).status_code == 422  # Status nicht per PATCH
    assert c.patch(f"{V}/leases/{lease['id']}", json={"legal_review_status": "reviewed"}).status_code == 422


def test_incoming_statement_over_http(auth_client):
    c = auth_client
    own, owner, tenant, prop, unit, room, bed, types = build(c)
    ru = post(c, "/rentable-units", {"property_id": prop["id"]})
    main = post(c, "/leases", {"kind": "main", "lease_type_id": types["hauptmiete"], "start_date": "2025-01-01", "subletting_permitted": True,
                               "parties": [{"party_id": owner["id"], "role": "lessor"}, {"party_id": own["id"], "role": "lessee"}], "rentable_unit_ids": [ru["id"]]})
    post(c, f"/leases/{main['id']}/utility-agreements", {"valid_from": "2025-01-01", "mode": "prepayment", "monthly_amount": "180.00"})
    st = post(c, "/utility-statements", {"main_lease_id": main["id"], "period_start": "2025-01-01", "period_end": "2025-12-31", "unit_ids": [unit["id"]]})
    ct = {x["name"]: x["id"] for x in c.get(V + "/cost-types").json()["items"]}
    post(c, f"/utility-statements/{st['id']}/lines", {"cost_type_id": ct["Heizung"], "amount": "2400.00", "allocation_key": "area"})
    r = c.put(f"{V}/utility-statements/{st['id']}/prepayments", json={"amount": "2160.00", "source": "agreed_calculated"})
    assert r.json()["balance"] == "240.00" and r.json()["direction"] == "nachzahlung"
    alloc = c.get(f"{V}/utility-statements/{st['id']}/allocation").json()
    assert alloc["per_unit"] == {str(unit["id"]): "2400.00"}
    cmp_ = c.get(f"{V}/utility-statements/{st['id']}/comparison").json()
    assert cmp_["rows"][0]["allocated_actual_costs"] == "2400.00"
    assert c.post(f"{V}/utility-statements/{st['id']}/status", json={"status": "reviewed"}).status_code == 409  # Schritte nicht überspringen


def test_read_only_role_cannot_write_and_audit_trail_exists(auth_client, app):
    from fastapi.testclient import TestClient
    with app.state.session_factory() as db:
        db.add(AppUser(username="leser", display_name="Leser", password_hash=hash_password(PW),
                       role_id=db.scalar(select(Role.id).where(Role.code == "lesend"))))
        db.commit()
    c = TestClient(app, headers={"X-Leventum-Client": "1"})
    assert c.post(V + "/auth/login", json={"username": "leser", "password": PW}).status_code == 200
    assert c.get(V + "/parties").status_code == 200
    assert c.post(V + "/parties", json={"kind": "person", "last_name": "X"}).status_code == 403
    assert c.get(V + "/system/backups").status_code == 403
    assert c.get(V + "/utility-statements").status_code == 200  # finance:read
    assert c.post(V + "/utility-statements", json={}).status_code == 403
    build(auth_client)
    with app.state.session_factory() as db:
        from leventum.models import AuditEvent
        acts = {a.action for a in db.scalars(select(AuditEvent))}
        assert {"party.created", "property.created", "unit.created", "room.created", "bed.created"} <= acts
