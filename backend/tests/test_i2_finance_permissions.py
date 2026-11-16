"""Eigentümerentscheidung: Finanzinformationen nur mit Recht finance:read (Dashboard, Hinweise, Mieterübersicht, Routen-Matrix).

Rollen (security/permissions.py): admin(*), buchhaltung und lesend HABEN finance:read; verwaltung und objektbetreuung NICHT.
Soll-Verhalten (Lücken 1-5, 8) wird VOR der Implementierung teilweise fehlschlagen; die Tests dürfen nicht abgeschwächt werden.
Lücke 6 (Vertragskonditionen) ist bewusst NICHT Teil der Änderung: `GET /leases/{id}` (terms, monthly_total) bleibt Stammdatum mit master:read
- bewusste Entscheidung, Eigentümerbestätigung offen (ein Test hält nur den heutigen Zustand fest).

Testwelt (erfundene Daten, Werte von Hand): Untermietvertrag (Zimmer 1, Miete 1150,00, ohne NK) mit EINER überfälligen Sollstellung von
600,00 (fällig vor 20 Tagen, nichts gezahlt) und einer überfälligen Kaution (vereinbart 2300,00, fällig vor 10 Tagen, nichts gezahlt).
Der aktive Hauptmietvertrag (ab 2025-01-01, NK-Vorauszahlung) erzeugt den Hinweis utility_statement_due (Vorjahr ohne Abrechnung).
Beträge 600,00 und 2300,00 kommen sonst nirgends vor und dienen als Leck-Marker."""
import re
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from leventum.security.permissions import has_permission
from leventum.services import charges as C
from tests.helpers import World
from tests.test_e_api import role_client

V = "/api/v1"
TODAY = date.today()
FIN_KPIS = ["main_rent_obligations", "sublease_receivables", "open_receivables", "overdue_payments", "monthly_utility_costs", "economic_vacancy_cost"]
FIN_KPIS_OPTIONAL = ["overdue_receivables"]  # künftig, falls vorhanden
NON_FIN_KPIS = ["properties", "units", "active_main_leases", "active_subleases", "active_tenants", "open_tasks", "overdue_tasks", "open_repairs", "upcoming_contract_ends"]
FIN_TYPES = {"overdue_payment", "deposit_overdue", "utility_statement_due"}
NO_FIN_ROLES = ["verwaltung", "objektbetreuung"]
FIN_ROLES = ["buchhaltung", "lesend", "admin"]
MONEY = re.compile(r"\d+[.,]\d{2}")
MARKERS = ("600.00", "600,00", "2300.00", "2.300,00")


def d(n):
    return TODAY + timedelta(days=n)


@pytest.fixture
def scene(app, auth_client):
    """Welt + überfällige Forderung (600,00) + überfällige Kaution (2300,00); Rollen-Clients je Rolle."""
    w = World(app)
    w.activate_main()
    tenant = w.tenant("Zahl Mieter")
    lease = w.sub([w.ru_room(w.room1)], [tenant], d(-400), None, nk_mode=None)
    C.create_manual_charge(w.db, None, lease_id=lease.id, amount=D("600.00"), due_date=d(-20), period_start=d(-20), period_end=d(9), note="Testforderung")
    w.db.commit()
    r = auth_client.post(V + "/deposits", json={"lease_id": lease.id, "agreed_amount": "2300.00", "due_date": d(-10).isoformat()})
    assert r.status_code == 201, r.text
    clients = {"admin": auth_client}
    for role in NO_FIN_ROLES + FIN_ROLES:
        if role != "admin":
            clients[role] = role_client(app, role, f"u_{role}")
    # Kontrolle der Rechtelage selbst (Entscheidung des Eigentümers)
    assert [has_permission(r_, "finance:read") for r_ in NO_FIN_ROLES] == [False, False]
    assert all(has_permission(r_, "finance:read") for r_ in FIN_ROLES)
    yield {"w": w, "tenant": tenant, "lease": lease, "c": clients, "admin": auth_client}
    w.db.close()


def kpi_map(body):
    return {k["key"]: k for k in body["kpis"]}


def assert_no_leak(text):
    for m in MARKERS:
        assert m not in text, f"Finanzwert {m} im Body"


# ---------------------------------------------------------------------------------------------------------------------------------
# 1. GET /dashboard
# ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("role", NO_FIN_ROLES)
def test_dashboard_without_finance_read_hides_finance_kpis_and_warnings(scene, role):
    r = scene["c"][role].get(V + "/dashboard")
    assert r.status_code == 200, r.text
    k = kpi_map(r.json())
    for key in FIN_KPIS + FIN_KPIS_OPTIONAL:
        assert key not in k, f"{role}: Finanz-KPI {key} darf ohne finance:read nicht ausgeliefert werden"
    for key in NON_FIN_KPIS:
        assert key in k, f"{role}: nicht-finanzieller KPI {key} muss bleiben"
    assert k["properties"]["value"] == 1 and k["units"]["value"] == 2  # Werte unverändert (Objekt 1, WE 1 und WE 2)
    assert k["active_main_leases"]["value"] == 1 and k["active_subleases"]["value"] == 1 and k["active_tenants"]["value"] == 1
    assert {w_["type"] for w_ in r.json()["warnings"]}.isdisjoint(FIN_TYPES)
    assert_no_leak(r.text)


@pytest.mark.parametrize("role", FIN_ROLES)
def test_dashboard_with_finance_read_keeps_everything(scene, role):
    r = scene["c"][role].get(V + "/dashboard")
    assert r.status_code == 200, r.text
    k = kpi_map(r.json())
    for key in FIN_KPIS + NON_FIN_KPIS:
        assert key in k, f"{role}: {key} fehlt"
    assert k["open_receivables"]["value"] == "600.00"   # eine Forderung 600,00 unbezahlt (Kaution zählt NICHT zu Mietforderungen)
    assert k["overdue_payments"]["value"] == 1          # genau eine überfällige Sollstellung
    types = {w_["type"] for w_ in r.json()["warnings"]}
    assert "overdue_payment" in types                   # severity critical -> steht in den ersten 8 Hinweisen


def test_dashboard_warning_types_with_finance_read_are_complete_via_reminders(scene):
    """Kontrolle des Szenarios: alle drei Finanz-Hinweistypen existieren überhaupt (sonst wäre das Fehlen ohne Recht kein Beweis)."""
    items = scene["admin"].get(V + "/reminders").json()["items"]
    assert FIN_TYPES <= {i["type"] for i in items}


# ---------------------------------------------------------------------------------------------------------------------------------
# 2. GET /dashboard?as_of=
# ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("role", NO_FIN_ROLES)
@pytest.mark.parametrize("as_of", [d(-7).isoformat(), TODAY.isoformat(), d(1).isoformat(), d(400).isoformat(), "gestern", "2026-13-40"],
                         ids=["past", "today", "future", "far-future", "invalid-text", "invalid-date"])
def test_dashboard_as_of_without_finance_read_is_403_before_validation(scene, role, as_of):
    """Rechteprüfung VOR Stichtagsvalidierung: auch ungültig/Zukunft -> 403 {detail:{code:forbidden}}, nie 422/200."""
    r = scene["c"][role].get(V + "/dashboard", params={"as_of": as_of})
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "forbidden"
    assert_no_leak(r.text)


@pytest.mark.parametrize("role", FIN_ROLES)
def test_dashboard_as_of_with_finance_read(scene, role):
    c = scene["c"][role]
    past = d(-7).isoformat()
    r = c.get(V + "/dashboard", params={"as_of": past})
    assert r.status_code == 200 and r.json()["as_of"] == past
    assert kpi_map(r.json())["open_receivables"]["value"] == "600.00"  # Forderung bestand bereits (fällig -20), unbezahlt
    assert c.get(V + "/dashboard", params={"as_of": d(1).isoformat()}).status_code == 422  # Zukunft weiter abgelehnt
    assert c.get(V + "/dashboard", params={"as_of": "gestern"}).status_code == 422


def test_dashboard_as_of_requires_login(client):
    assert client.get(V + "/dashboard", params={"as_of": d(-7).isoformat()}).status_code == 401
    assert client.get(V + "/dashboard", params={"as_of": d(1).isoformat()}).status_code == 401


# ---------------------------------------------------------------------------------------------------------------------------------
# 3. GET /reminders und POST /reminders/task
# ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("role", NO_FIN_ROLES)
def test_reminders_without_finance_read_hide_finance_types_but_keep_others(scene, role):
    full = scene["admin"].get(V + "/reminders").json()["items"]
    r = scene["c"][role].get(V + "/reminders")
    assert r.status_code == 200
    got = r.json()["items"]
    assert {i["type"] for i in got}.isdisjoint(FIN_TYPES)
    assert {i["key"] for i in got} == {i["key"] for i in full if i["type"] not in FIN_TYPES}  # alles Übrige bleibt unverändert
    assert len(got) > 0
    assert_no_leak(r.text)


@pytest.mark.parametrize("role", FIN_ROLES)
def test_reminders_with_finance_read_contain_finance_types(scene, role):
    items = scene["c"][role].get(V + "/reminders").json()["items"]
    assert FIN_TYPES <= {i["type"] for i in items}
    overdue = next(i for i in items if i["type"] == "overdue_payment")
    assert overdue["amount"] == "600.00"


@pytest.mark.parametrize("role", NO_FIN_ROLES)
@pytest.mark.parametrize("typ", sorted(FIN_TYPES))
def test_reminder_to_task_for_finance_type_without_finance_read_is_403(scene, role, typ):
    """task:write haben verwaltung und objektbetreuung -> die Ablehnung muss aus finance:read kommen (403, nicht 404/201)."""
    assert has_permission(role, "task:write")
    key = next(i["key"] for i in scene["admin"].get(V + "/reminders").json()["items"] if i["type"] == typ)
    before = scene["admin"].get(V + "/tasks").json()["items"]
    r = scene["c"][role].post(V + "/reminders/task", json={"key": key})
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "forbidden"
    assert_no_leak(r.text)
    assert scene["admin"].get(V + "/tasks").json()["items"] == before  # keine Aufgabe entstanden


def test_reminder_to_task_controls(scene):
    """Kontrollen: mit finance:read (admin) entsteht die Aufgabe zur überfälligen Zahlung; ohne Recht bleibt eine Nicht-Finanz-Erinnerung möglich."""
    items = scene["admin"].get(V + "/reminders").json()["items"]
    other = next(i["key"] for i in items if i["type"] not in FIN_TYPES)
    assert scene["c"]["verwaltung"].post(V + "/reminders/task", json={"key": other}).status_code == 201
    key = next(i["key"] for i in items if i["type"] == "overdue_payment")
    assert scene["admin"].post(V + "/reminders/task", json={"key": key}).status_code == 201


# ---------------------------------------------------------------------------------------------------------------------------------
# 4. GET /tenants
# ---------------------------------------------------------------------------------------------------------------------------------
def _tenant_row(body, party_id):
    return next(i for i in body["items"] if i["party_id"] == party_id)


@pytest.mark.parametrize("role", NO_FIN_ROLES)
def test_tenants_without_finance_read_hide_payment_status(scene, role):
    r = scene["c"][role].get(V + "/tenants")
    assert r.status_code == 200
    row = _tenant_row(r.json(), scene["tenant"].id)
    assert row.get("payment_status") is None and row.get("overdue_amount") is None
    assert row["lease_id"] == scene["lease"].id  # Mieterliste selbst bleibt (master:read)
    assert_no_leak(r.text)
    assert "arrears" not in r.text


@pytest.mark.parametrize("role", NO_FIN_ROLES)
def test_tenants_arrears_filter_without_finance_read_is_403(scene, role):
    r = scene["c"][role].get(V + "/tenants", params={"status": "arrears"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "forbidden"


@pytest.mark.parametrize("role", FIN_ROLES)
def test_tenants_with_finance_read_unchanged(scene, role):
    c = scene["c"][role]
    row = _tenant_row(c.get(V + "/tenants").json(), scene["tenant"].id)
    assert row["payment_status"] == "arrears" and row["overdue_amount"] == "600.00"
    flt = c.get(V + "/tenants", params={"status": "arrears"})
    assert flt.status_code == 200 and [i["party_id"] for i in flt.json()["items"]] == [scene["tenant"].id]


# ---------------------------------------------------------------------------------------------------------------------------------
# 5. GET /tenants/{id}/overview
# ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("role", NO_FIN_ROLES)
def test_tenant_overview_without_finance_read_has_no_finance(scene, role):
    r = scene["c"][role].get(V + f"/tenants/{scene['tenant'].id}/overview")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "finance" not in body
    assert len(body["leases"]) == 1
    for lease in body["leases"]:
        assert lease.get("payment_status") is None and lease.get("overdue_amount") is None and lease.get("deposit") is None
    assert_no_leak(r.text)
    assert body["party"]["id"] == scene["tenant"].id  # Rest der Mieterakte bleibt


@pytest.mark.parametrize("role", FIN_ROLES)
def test_tenant_overview_with_finance_read_unchanged(scene, role):
    body = scene["c"][role].get(V + f"/tenants/{scene['tenant'].id}/overview").json()
    assert body["finance"]["open_total"] == "600.00" and body["finance"]["overdue_total"] == "600.00"
    lease = body["leases"][0]
    assert lease["payment_status"] == "arrears" and lease["overdue_amount"] == "600.00"
    assert lease["deposit"] is not None and lease["deposit"]["agreed_amount"] == "2300.00"


# ---------------------------------------------------------------------------------------------------------------------------------
# 6. Vertragskonditionen (bewusste Entscheidung, Eigentümerbestätigung offen)
# ---------------------------------------------------------------------------------------------------------------------------------
def test_lease_terms_stay_master_data_for_verwaltung_documented_decision(scene):
    """BEWUSSTE ENTSCHEIDUNG, EIGENTÜMERBESTÄTIGUNG OFFEN: Vertragskonditionen sind Stammdaten (master:read); verwaltung sieht terms/monthly_total.
    Dieser Test hält nur den heutigen Zustand fest; ändert der Eigentümer die Entscheidung, ist er bewusst anzupassen."""
    assert not has_permission("verwaltung", "finance:read") and has_permission("verwaltung", "master:read")
    r = scene["c"]["verwaltung"].get(V + f"/leases/{scene['lease'].id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [t["base_rent"] for t in body["terms"]] == ["1150.00"]
    assert body["monthly_total"] is not None and body["monthly_total"]["total"] == "1150.00"


# ---------------------------------------------------------------------------------------------------------------------------------
# 7. Routen-Matrix aus OpenAPI (neue Finanzrouten mit diesen Präfixen werden automatisch mitgeprüft)
# ---------------------------------------------------------------------------------------------------------------------------------
PREFIXES = tuple(V + p for p in ("/bank", "/charges", "/deposits", "/dunning", "/economics", "/invoices", "/payments", "/utility-statements", "/vacancy"))
WRITE_EXPLICIT = [("POST", "/charges/generate"), ("POST", "/payments"), ("POST", "/deposits"),
                  ("POST", "/bank/imports"), ("POST", "/invoices"), ("POST", "/utility-statements")]
# /charges/preview ist ein LESENDER Dry-Run (schreibt nichts) und verlangt bewusst finance:read (Entscheidung des Orchestrators, Eigentümerbestätigung offen):
# lesend darf ihn aufrufen, verwaltung/objektbetreuung nicht (Matrix-Test oben).
READ_ONLY_PREVIEW = ("POST", "/charges/preview")


def _is_finance_path(path):
    return any(path == p or path.startswith(p + "/") for p in PREFIXES)


def finance_routes(app, methods):
    out = []
    for path, ops in app.openapi()["paths"].items():
        if _is_finance_path(path):
            for m in ops:
                if m.upper() in methods:
                    out.append((m.upper(), re.sub(r"\{[^}]+\}", "1", path)))
    return sorted(out)


def call(c, method, path):
    return c.request(method, path, json={} if method in ("POST", "PATCH", "PUT") else None)


def test_matrix_route_discovery_is_not_empty(app):
    get = finance_routes(app, {"GET"})
    assert len(get) >= 15  # heute 17 GET-Routen in diesen Präfixen; Entdeckung darf nicht still leer laufen
    assert ("GET", V + "/vacancy") in get and ("GET", V + "/economics") in get and ("GET", V + "/bank/transactions/1") in get
    for method, path in WRITE_EXPLICIT:
        assert (method, V + path) in finance_routes(app, {method})


@pytest.mark.parametrize("role", NO_FIN_ROLES)
def test_matrix_all_finance_routes_are_403_without_finance_read(app, scene, role):
    """Jede Methode jeder Route unter den Finanzpräfixen: ohne finance:read immer 403 (auch lesende Vorschauen, auch schreibende)."""
    c = scene["c"][role]
    wrong = []
    for method, path in finance_routes(app, {"GET", "POST", "PUT", "PATCH", "DELETE"}):
        r = call(c, method, path)
        if r.status_code != 403:
            wrong.append(f"{role} {method} {path}: {r.status_code}")
        else:
            assert not MONEY.search(r.text) and "Traceback" not in r.text, f"{method} {path}"
    assert wrong == []


@pytest.mark.parametrize("role", FIN_ROLES)
def test_matrix_get_finance_routes_are_not_403_with_finance_read(app, scene, role):
    c = scene["c"][role]
    wrong = [f"{role} GET {p}: 403" for m, p in finance_routes(app, {"GET"}) if call(c, m, p).status_code == 403]
    assert wrong == []


@pytest.mark.parametrize("role", ["lesend", *NO_FIN_ROLES])
@pytest.mark.parametrize("method,path", [pytest.param(m, V + p, id=f"{m} {p}") for m, p in WRITE_EXPLICIT])
def test_matrix_write_finance_routes_are_403_for_non_writers(scene, role, method, path):
    """lesend hat finance:read, aber nicht finance:write: schreibende Finanzrouten → 403."""
    r = call(scene["c"][role], method, path)
    assert r.status_code == 403, f"{role} {method} {path}: {r.status_code}"
    assert r.json()["detail"]["code"] == "forbidden"
    assert not MONEY.search(r.text) and "Traceback" not in r.text


def test_read_only_preview_is_allowed_with_finance_read_but_not_without(scene):
    """Entscheidung: /charges/preview (Dry-Run ohne Schreiben) braucht finance:read, nicht finance:write."""
    m, p = READ_ONLY_PREVIEW
    for role in ("lesend", "buchhaltung", "admin"):
        assert call(scene["c"][role], m, V + p).status_code != 403, role
    for role in NO_FIN_ROLES:
        assert call(scene["c"][role], m, V + p).status_code == 403, role


def test_matrix_write_finance_routes_not_403_for_writers(scene):
    """Kontrolle: buchhaltung/admin kommen an die Route (Validierungs-/Fachfehler, aber nicht 403)."""
    for role in ("buchhaltung", "admin"):
        for method, path in WRITE_EXPLICIT:
            assert call(scene["c"][role], method, V + path).status_code != 403, f"{role} {method} {path}"


@pytest.mark.parametrize("role", ["lesend", *NO_FIN_ROLES])
def test_matrix_all_other_write_finance_routes_403_for_non_writers_except_read_only_preview(app, scene, role):
    """Neue schreibende Finanzrouten werden mitgeprüft: finance:write fehlt lesend -> 403. Einzige Ausnahme: der lesende Dry-Run /charges/preview."""
    exceptions = {("POST", V + READ_ONLY_PREVIEW[1])}
    wrong = []
    for method, path in finance_routes(app, {"POST", "PUT", "PATCH", "DELETE"}):
        if (method, path) in exceptions:
            continue
        r = call(scene["c"][role], method, path)
        if r.status_code != 403:
            wrong.append(f"{role} {method} {path}: {r.status_code}")
    assert wrong == []


# ---- ohne Login -----------------------------------------------------------------------------------------------------------------
def test_matrix_all_finance_routes_401_without_login(app, client):
    wrong = []
    for method, path in finance_routes(app, {"GET", "POST", "PUT", "PATCH", "DELETE"}):
        r = call(client, method, path)
        if r.status_code != 401:
            wrong.append(f"{method} {path}: {r.status_code}")
    assert wrong == []


# ---------------------------------------------------------------------------------------------------------------------------------
# 8. 403-Antworten ohne Beträge/Traceback
# ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("role", NO_FIN_ROLES)
def test_403_bodies_carry_no_amounts_or_traceback(scene, role):
    c = scene["c"][role]
    reminders = scene["admin"].get(V + "/reminders").json()["items"]
    key = next(i["key"] for i in reminders if i["type"] == "overdue_payment")
    calls = [("GET", V + "/charges", None), ("GET", V + "/deposits", None), ("GET", V + "/economics?start=2026-01-01&end=2026-01-31", None),
             ("GET", V + "/dashboard?as_of=" + d(-7).isoformat(), None), ("GET", V + "/tenants?status=arrears", None),
             ("POST", V + "/reminders/task", {"key": key}), ("POST", V + "/payments", {}), ("GET", V + "/dunning/overdue", None)]
    for method, path, body in calls:
        r = c.request(method, path, json=body)
        assert r.status_code == 403, f"{method} {path}: {r.status_code}"
        assert not MONEY.search(r.text), f"Betrag im 403-Body von {method} {path}: {r.text}"
        assert "Traceback" not in r.text and "File \"" not in r.text
        assert set(r.json()) == {"detail"} and r.json()["detail"]["code"] == "forbidden"
