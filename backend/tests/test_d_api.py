from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from leventum.models import AppUser, Role
from leventum.security.passwords import hash_password
from tests.conftest import PW

V = "/api/v1"
IBAN = "DE89370400440532013000"


def post(c, path, body=None, status=(200, 201)):
    r = c.post(V + path, json=body if body is not None else {})
    assert r.status_code in status, f"{path}: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture
def world(auth_client):
    c = auth_client
    own = post(c, "/parties", {"kind": "company", "company_name": "Leventum Real Estate", "is_own_organization": True})
    owner = post(c, "/parties", {"kind": "person", "first_name": "Olga", "last_name": "Eigentümer", "roles": ["owner"]})
    tenant = post(c, "/parties", {"kind": "person", "first_name": "Max", "last_name": "Mustermann", "roles": ["tenant"], "iban": IBAN})
    prop = post(c, "/properties", {"name": "Haus Bergmann", "property_type": "mehrfamilienhaus", "owner_party_id": owner["id"]})
    unit = post(c, f"/properties/{prop['id']}/units", {"unit_number": "WE 1", "living_area": "60.00"})
    types = {t["code"]: t["id"] for t in c.get(V + "/lease-types").json()["items"]}
    rp, ru = post(c, "/rentable-units", {"property_id": prop["id"]}), post(c, "/rentable-units", {"property_id": prop["id"], "unit_id": unit["id"]})
    main = post(c, "/leases", {"kind": "main", "lease_type_id": types["hauptmiete"], "start_date": "2026-01-01", "subletting_permitted": True,
                               "parties": [{"party_id": owner["id"], "role": "lessor"}, {"party_id": own["id"], "role": "lessee"}], "rentable_unit_ids": [rp["id"]]})
    post(c, f"/leases/{main['id']}/terms", {"valid_from": "2026-01-01", "base_rent": "850.00"})
    post(c, f"/leases/{main['id']}/utility-agreements", {"valid_from": "2026-01-01", "mode": "prepayment", "monthly_amount": "180.00"})
    post(c, f"/leases/{main['id']}/activate")
    sub = post(c, "/leases", {"kind": "sub", "lease_type_id": types["wohnraum_unbefristet"], "start_date": "2026-01-01",
                              "parties": [{"party_id": own["id"], "role": "lessor"}, {"party_id": tenant["id"], "role": "lessee"}], "rentable_unit_ids": [ru["id"]]})
    post(c, f"/leases/{sub['id']}/terms", {"valid_from": "2026-01-01", "base_rent": "1150.00"})
    post(c, f"/leases/{sub['id']}/utility-agreements", {"valid_from": "2026-01-01", "mode": "prepayment", "monthly_amount": "220.00"})
    post(c, f"/leases/{sub['id']}/activate")
    return dict(c=c, own=own, owner=owner, tenant=tenant, prop=prop, unit=unit, main=main, sub=sub)


def test_charges_payments_and_economics_over_http(world):
    c = world["c"]
    g = post(c, "/charges/generate", {"from_month": "2026-01-01", "through_month": "2026-02-01"})
    assert g["created_count"] == 8 and post(c, "/charges/generate", {"from_month": "2026-01-01", "through_month": "2026-02-01"})["created_count"] == 0
    rent = next(x for x in c.get(V + f"/charges?lease_id={world['sub']['id']}").json()["items"] if x["charge_type"] == "base_rent" and x["period_start"] == "2026-01-01")
    assert rent["amount"] == "1150.00" and rent["open_amount"] == "1150.00" and rent["status"] == "open"
    p = post(c, "/payments", {"direction": "in", "booking_date": "2026-01-05", "amount": "400.00", "allocations": [{"charge_id": rent["id"], "amount": "400.00"}]})
    assert p["unallocated"] == "0.00"
    assert c.get(V + f"/charges?lease_id={world['sub']['id']}&status=overdue").json()["items"][-1]["status"] in ("partial", "open")
    r = c.post(V + f"/payments/{p['id']}/allocations", json={"charge_id": rent["id"], "amount": "10.00"})
    assert r.status_code == 409  # Zahlung bereits vollständig zugeordnet
    rev = post(c, f"/payments/{p['id']}/reverse", {"reason": "Rückläufer"})
    assert rev["is_reversal"] and rev["signed_amount"] == "-400.00"
    e = c.get(V + "/economics?start=2026-01-01&end=2026-01-31").json()
    assert e["soll"]["sub_total"] == "1370.00" and e["soll"]["main_total"] == "1030.00" and e["contribution"]["soll_basis"] == "340.00"
    assert e["status"] == "vorläufig" and e["deposits"].startswith("ausgeschlossen")
    assert c.get(V + "/economics?start=2026-01-02&end=2026-01-31").status_code == 400
    v = c.get(V + "/vacancy?start=2026-01-01&end=2026-01-31").json()
    assert v["snapshot"]["leaves_total"] == 1 and "physical" in v and "economic" in v


def test_dunning_flow_requires_manual_steps_over_http(world):
    c = world["c"]
    post(c, "/charges/generate", {"from_month": "2026-01-01", "through_month": "2026-01-01"})
    od = c.get(V + "/dunning/overdue?as_of=2026-02-10").json()
    assert len(od["items"]) == 2 and "kein automatischer Versand" in od["note"] and "nicht berechnet" in od["note"]
    n = post(c, "/dunning/prepare", {"as_of": "2026-02-10"})["created"][0]
    assert n["status"] == "draft" and n["level_name"] == "Zahlungserinnerung" and n["total_open"] == "1370.00"
    assert c.post(V + f"/dunning/notices/{n['id']}/approve").status_code == 422  # Frist-Platzhalter offen
    body = n["body"].replace("[Frist eintragen]", "28.02.2026")
    assert c.patch(V + f"/dunning/notices/{n['id']}", json={"body": body}).status_code == 200
    assert post(c, f"/dunning/notices/{n['id']}/approve")["status"] == "approved"
    sent = post(c, f"/dunning/notices/{n['id']}/mark-sent", {"sent_on": "2026-02-11", "via": "Brief"})
    assert sent["status"] == "sent"
    d = c.get(V + f"/dunning/notices/{n['id']}").json()
    assert [h["action"] for h in d["history"]] == ["dunning.prepared", "dunning.edited", "dunning.approved", "dunning.marked_sent"]


def test_bank_import_confirm_flow_over_http(world):
    c = world["c"]
    post(c, "/charges/generate", {"from_month": "2026-01-01", "through_month": "2026-01-01"})
    acc = post(c, "/bank/accounts", {"name": "Geschäftskonto"})
    csv = f"Buchungstag;Name;IBAN;Verwendungszweck;Betrag\n02.01.2026;Max Mustermann;{IBAN};Miete Januar;1.370,00\n03.01.2026;Fremd;;Spende;-5,00\n".encode()
    files = {"file": ("auszug.csv", csv, "text/csv")}
    prev = c.post(V + "/bank/imports/preview", data={"account_id": acc["id"]}, files=files).json()
    assert (prev["new_rows"], prev["duplicate_rows"], prev["errors"]) == (2, 0, [])
    assert c.get(V + "/bank/transactions").json()["items"] == []  # Vorschau speichert nichts
    imp = c.post(V + "/bank/imports", data={"account_id": acc["id"]}, files=files)
    assert imp.status_code == 201
    again = c.post(V + "/bank/imports", data={"account_id": acc["id"]}, files={"file": ("auszug.csv", csv, "text/csv")}).json()
    assert (again["new_rows"], again["duplicate_rows"]) == (0, 2)
    bad = c.post(V + "/bank/imports", data={"account_id": acc["id"]}, files={"file": ("x.csv", b"Buchungstag;Name;Betrag\nxx;a;1,00\n", "text/csv")})
    assert bad.status_code == 422 and bad.json()["detail"]["details"][0]["row"] == 2
    txs = c.get(V + "/bank/transactions?suggestions=true").json()["items"]
    t = next(x for x in txs if x["amount"] == "1370.00")
    assert t["status"] == "open" and t["suggestions"][0]["kind"] == "charges" and t["unmatched"] is False
    assert next(x for x in txs if x["amount"] == "-5.00")["unmatched"] is True
    unmatched = c.get(V + "/bank/transactions?only_unmatched=true").json()["items"]
    assert [x["amount"] for x in unmatched] == ["-5.00"]  # Prüfliste
    allocs = [{"charge_id": a["charge_id"], "amount": a["amount"]} for a in t["suggestions"][0]["allocations"]]
    assert c.post(V + f"/bank/transactions/{t['id']}/confirm", json={"allocations": allocs}).status_code == 422  # ohne confirm=true keine Übernahme
    assert c.post(V + f"/bank/transactions/{t['id']}/confirm", json={"confirm": False, "allocations": allocs}).status_code == 422
    assert c.get(V + "/payments").json()["items"] == []
    ok = post(c, f"/bank/transactions/{t['id']}/confirm", {"confirm": True, "allocations": allocs})
    assert ok["status"] == "confirmed" and len(c.get(V + "/payments").json()["items"]) == 1
    assert c.post(V + f"/bank/transactions/{t['id']}/confirm", json={"confirm": True, "allocations": allocs}).status_code == 409
    other = next(x for x in txs if x["amount"] == "-5.00")
    assert post(c, f"/bank/transactions/{other['id']}/ignore", {"reason": "privat"})["status"] == "ignored"


def test_deposits_over_http_and_documents_protected(world, app):
    c = world["c"]
    d = post(c, "/deposits", {"lease_id": world["sub"]["id"], "agreed_amount": "2000.00", "due_date": "2026-01-01"})
    assert d["lease_kind"] == "sub" and d["open"] == "2000.00"
    d = post(c, f"/deposits/{d['id']}/transactions", {"kind": "paid", "amount": "2000.00", "transaction_date": "2026-01-03"})
    assert d["status"] == "paid" and d["held"] == "2000.00"
    assert c.post(V + f"/deposits/{d['id']}/transactions", json={"kind": "retained", "amount": "100.00", "transaction_date": "2026-09-01"}).status_code == 400
    assert c.get(V + "/payments").json()["items"] == []
    up = c.post(V + "/documents", data={"entity_type": "deposit", "entity_id": d["id"], "doc_type": "kaution"}, files={"file": ("beleg.pdf", b"%PDF-1.4 beleg", "application/pdf")})
    assert up.status_code == 201, up.text
    doc = up.json()
    dl = c.get(V + f"/documents/{doc['id']}/download")
    assert dl.status_code == 200 and dl.content == b"%PDF-1.4 beleg" and "attachment" in dl.headers["content-disposition"] and dl.headers["x-content-type-options"] == "nosniff"
    assert c.post(V + "/documents", data={"entity_type": "deposit", "entity_id": d["id"]}, files={"file": ("a.exe", b"MZ", "application/octet-stream")}).status_code == 422
    anon = TestClient(app, headers={"X-Leventum-Client": "1"})
    assert anon.get(V + f"/documents/{doc['id']}/download").status_code == 401
    assert TestClient(app).post(V + "/documents", data={"entity_type": "deposit", "entity_id": 1}, files={"file": ("a.pdf", b"%PDF-1", "application/pdf")}).status_code == 403  # CSRF-Header fehlt


def test_read_only_role_cannot_book_or_confirm(world, app):
    with app.state.session_factory() as db:
        db.add(AppUser(username="leser", display_name="L", password_hash=hash_password(PW), role_id=db.scalar(select(Role.id).where(Role.code == "lesend"))))
        db.commit()
    r = TestClient(app, headers={"X-Leventum-Client": "1"})
    assert r.post(V + "/auth/login", json={"username": "leser", "password": PW}).status_code == 200
    assert r.get(V + "/charges").status_code == 200 and r.get(V + "/economics?start=2026-01-01&end=2026-01-31").status_code == 200
    for path, body in (("/charges/generate", {"from_month": "2026-01-01", "through_month": "2026-01-01"}), ("/payments", {"direction": "in", "booking_date": "2026-01-01", "amount": "1.00"}),
                       ("/bank/transactions/1/confirm", {"confirm": True}), ("/dunning/prepare", {}), ("/deposits", {"lease_id": 1, "agreed_amount": "1.00"})):
        assert r.post(V + path, json=body).status_code == 403, path
