from datetime import date, timedelta
from decimal import Decimal

from tests.helpers import World


def kpis(client):
    return {k["key"]: k for k in client.get("/api/v1/dashboard").json()["kpis"]}


def test_dashboard_kpis_are_real_and_empty_database_shows_zero(auth_client):
    k = kpis(auth_client)
    # ab Phase E hat jede Kennzahl eine echte Datenquelle; die Auslastungsquote ist ohne Einheiten bewusst nicht definiert (kein 0 %)
    assert all(x["available"] for key, x in k.items() if key != "occupancy_rate")
    for key in ("open_tasks", "overdue_tasks", "open_repairs"):
        assert k[key]["value"] == 0
    for key in ("properties", "units", "active_main_leases", "active_subleases", "active_tenants", "upcoming_contract_ends", "overdue_payments", "physical_vacancy"):
        assert k[key]["available"] is True and k[key]["value"] == 0
    for key in ("main_rent_obligations", "sublease_receivables", "open_receivables", "monthly_utility_costs", "economic_vacancy_cost"):
        assert k[key]["available"] is True and k[key]["value"] == "0.00" and k[key]["format"] == "eur"


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
    assert k["physical_vacancy"]["value"] == 1  # beide Zimmer von WE 1 belegt; WE 2 (ohne Räume) ist ein eigenes, unbelegtes Blatt
    assert k["main_rent_obligations"]["value"] == "1030.00" and k["sublease_receivables"]["value"] == "2740.00"


def test_occupancy_rate_is_share_of_occupied_leaves(auth_client, app):
    k = kpis(auth_client)
    assert k["occupancy_rate"]["available"] is False and k["occupancy_rate"]["value"] is None  # ohne Einheiten keine Quote statt 0 %
    w = World(app)
    w.activate_main()
    w.sub([w.ru_room(w.room1)], [w.tenant("Anna Test")], date(2026, 1, 1), None)
    w.db.commit()
    k = kpis(auth_client)
    assert k["physical_vacancy"]["value"] == 2
    assert k["occupancy_rate"]["format"] == "percent" and k["occupancy_rate"]["value"] == "50.0"  # Blätter: Bett A, Bett B (Zimmer 1, belegt), Zimmer 2, WE 2 ohne Räume -> 2 von 4; passend zu physical_vacancy == 2


def test_occupancy_rate_rounds_half_up_and_handles_zero():
    from leventum.services.dashboard import _occupancy_rate
    assert _occupancy_rate({"leaves_total": 16, "leaves_occupied": 1}) == "6.3"  # 6,25 -> ROUND_HALF_UP (nicht HALF_EVEN 6.2)
    assert _occupancy_rate({"leaves_total": 8, "leaves_occupied": 7}) == "87.5"
    assert _occupancy_rate({"leaves_total": 3, "leaves_occupied": 3}) == "100.0"
    assert _occupancy_rate({"leaves_total": 0, "leaves_occupied": 0}) is None
