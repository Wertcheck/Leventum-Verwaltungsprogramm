from datetime import date, timedelta
from decimal import Decimal

from tests.helpers import World


def kpis(client):
    return {k["key"]: k for k in client.get("/api/v1/dashboard").json()["kpis"]}


def test_dashboard_unavailable_kpis_stay_empty_and_available_are_real(auth_client):
    k = kpis(auth_client)
    for key in ("main_rent_obligations", "sublease_receivables", "open_receivables", "overdue_payments", "monthly_utility_costs", "open_tasks"):
        assert k[key]["available"] is False and k[key]["value"] is None
    for key in ("properties", "units", "active_main_leases", "active_subleases", "active_tenants", "upcoming_contract_ends"):
        assert k[key]["available"] is True and k[key]["value"] == 0


def test_dashboard_counts_from_real_data(auth_client, app):
    w = World(app)
    w.activate_main()
    t1, t2 = w.tenant("Anna Test"), w.tenant("Bernd Test")
    ru1, ru2 = w.ru_room(w.room1), w.ru_room(w.room2)
    w.sub([ru1], [t1], date(2026, 1, 1), None)
    w.sub([ru2], [t2], date(2026, 1, 1), date.today() + timedelta(days=30))
    w.db.commit()
    k = kpis(auth_client)
    assert k["properties"]["value"] == 1 and k["units"]["value"] == 2
    assert k["active_main_leases"]["value"] == 1 and k["active_subleases"]["value"] == 2
    assert k["active_tenants"]["value"] == 2 and k["upcoming_contract_ends"]["value"] == 1
