"""Phase 3 / ADR 0002: Dashboard-KPI-Definitionen (upcoming_contract_ends, units, open_receivables/overdue_payments) und Stichtag `as_of`.
Alle Erwartungswerte sind von Hand relativ zu date.today() berechnet (zeitstabil), nicht aus dem Code abgeleitet.
Annahmen A1-A7 siehe docs/decisions/0002-dashboard-kpi-definitions.md."""
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from leventum.config import Settings
from leventum.main import create_app
from leventum.models import Charge
from leventum.services import charges as C, leases as L, master as M, payments as P
from tests.conftest import PW
from tests.helpers import World

V = "/api/v1"
TODAY = date.today()


def d(n: int) -> date:
    """Tag relativ zu heute."""
    return TODAY + timedelta(days=n)


def dash(client, **params):
    r = client.get(V + "/dashboard", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def kpis(client, **params):
    return {k["key"]: k for k in dash(client, **params)["kpis"]}


def val(client, key, **params):
    return kpis(client, **params)[key]["value"]


def make_client(tmp_path, days=None):
    kw = {} if days is None else {"contract_end_preview_days": days}
    app = create_app(Settings(data_dir=tmp_path / "data", frontend_dist=tmp_path / "nodist", **kw))
    c = TestClient(app, headers={"X-Leventum-Client": "1"})
    c.__enter__()
    r = c.post(V + "/auth/setup", json={"username": "admin", "password": PW, "display_name": "Admin"})
    assert r.status_code == 200, r.text
    return app, c


@pytest.fixture
def world(app, auth_client):
    w = World(app)
    w.activate_main()
    w.db.commit()
    yield w
    w.db.close()


def end_lease(w, end, *, start=None, unit="room1", activate=True):
    """Untermietvertrag auf je eigener Einheit (ohne Überschneidung); Haupt­vertrag läuft ab 2025-01-01 offen."""
    ru = {"room1": w.ru_room(w.room1), "room2": w.ru_room(w.room2), "we2": w.ru_unit(w.we2)}[unit]
    return w.sub([ru], [w.tenant(f"Mieter {unit}")], start or d(-100), end, activate=activate)


def reminder_ends(client):
    return {i["entity_id"] for i in client.get(V + "/reminders").json()["items"] if i["type"] == "contract_end"}


# ---------------------------------------------------------------------------------------------------------------------------------
# Einstellung
# ---------------------------------------------------------------------------------------------------------------------------------
def test_setting_default_is_90_and_env_override(monkeypatch):
    assert Settings().contract_end_preview_days == 90
    monkeypatch.setenv("LEVENTUM_CONTRACT_END_PREVIEW_DAYS", "45")
    assert Settings().contract_end_preview_days == 45


# ---------------------------------------------------------------------------------------------------------------------------------
# upcoming_contract_ends – Service contract_end_due
# ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("end_off,expected", [(0, 0), (1, 1), (60, 60), (90, 90), (91, None), (-1, None), (365, None)])
def test_contract_end_due_boundaries_service(world, end_off, expected):
    lease = end_lease(world, d(end_off))
    got = L.contract_end_due(lease, TODAY, 90)
    assert got == (None if expected is None else d(expected))


def test_contract_end_due_other_cases_service(world):
    open_end = end_lease(world, None, unit="room1")
    assert L.contract_end_due(open_end, TODAY, 90) is None  # offenes Ende
    future = end_lease(world, d(60), start=d(10), unit="room2")
    assert L.contract_end_due(future, TODAY, 90) is None  # nicht begonnen -> nicht laufend
    assert L.contract_end_due(future, d(10), 90) == d(60)  # am Beginntag läuft er, Ende in 50 Tagen
    draft = end_lease(world, d(30), unit="we2", activate=False)
    assert L.contract_end_due(draft, TODAY, 90) is None  # Entwurf läuft nicht


def test_contract_end_due_custom_days_service(world):
    lease = end_lease(world, d(31))
    assert L.contract_end_due(lease, TODAY, 30) is None and L.contract_end_due(lease, TODAY, 31) == d(31)
    assert L.contract_end_due(lease, TODAY, 180) == d(31)


def test_contract_end_due_terminated_uses_effective_end_service(world):
    lease = end_lease(world, d(200))  # vertragliches Ende weit außerhalb
    L.terminate_lease(world.db, None, lease.id, terminated_on=d(-5), effective_on=d(20))
    assert lease.status == "terminated"
    assert L.contract_end_due(lease, TODAY, 90) == d(20)  # A3: gekündigt, noch laufend, wirksames Ende zählt
    assert L.contract_end_due(lease, TODAY, 10) is None


# ---------------------------------------------------------------------------------------------------------------------------------
# upcoming_contract_ends – Dashboard (Standard 90 Tage)
# ---------------------------------------------------------------------------------------------------------------------------------
def test_future_start_lease_is_not_an_upcoming_end(world, auth_client):
    end_lease(world, d(60), start=d(10))
    world.db.commit()
    k = kpis(auth_client)
    assert k["active_subleases"]["value"] == 0  # Kontrolle: nicht begonnen
    assert k["upcoming_contract_ends"]["value"] == 0
    assert reminder_ends(auth_client) == set()  # Hinweis und Dashboard konsistent


def test_started_lease_with_end_in_preview_counts(world, auth_client):
    lease = end_lease(world, d(60))
    world.db.commit()
    assert val(auth_client, "upcoming_contract_ends") == 1
    assert reminder_ends(auth_client) == {lease.id}


@pytest.mark.parametrize("end_off,count", [(0, 1), (1, 1), (90, 1), (91, 0), (-1, 0)])
def test_end_boundaries_dashboard_and_reminder(world, auth_client, end_off, count):
    """A4: heute <= Ende <= heute+N, beide Grenzen inklusiv; gestern abgelaufen zählt nicht."""
    lease = end_lease(world, d(end_off))
    world.db.commit()
    assert val(auth_client, "upcoming_contract_ends") == count
    assert reminder_ends(auth_client) == ({lease.id} if count else set())


def test_open_end_lease_does_not_count(world, auth_client):
    end_lease(world, None)
    world.db.commit()
    assert val(auth_client, "upcoming_contract_ends") == 0 and reminder_ends(auth_client) == set()


def test_terminated_but_running_lease_counts_with_effective_end(world, auth_client):
    lease = end_lease(world, None)  # vertraglich offen, aber gekündigt zum Tag +25
    L.terminate_lease(world.db, None, lease.id, terminated_on=d(-5), effective_on=d(25))
    world.db.commit()
    assert val(auth_client, "upcoming_contract_ends") == 1
    assert reminder_ends(auth_client) == {lease.id}


def test_terminated_with_effective_end_beyond_preview_does_not_count(world, auth_client):
    lease = end_lease(world, d(30))  # vertragliches Ende in der Vorschau, aber Kündigung wirkt erst später -> wirksames Ende gilt
    L.terminate_lease(world.db, None, lease.id, terminated_on=d(-5), effective_on=d(120))
    world.db.commit()
    assert val(auth_client, "upcoming_contract_ends") == 0


def test_main_and_sub_leases_both_count(app, auth_client):
    w = World(app)
    w.activate_main(end=d(30))
    end_lease(w, d(20), unit="room1")
    w.db.commit()
    assert val(auth_client, "upcoming_contract_ends") == 2  # A2: Haupt- und Untermietvertrag
    assert len(reminder_ends(auth_client)) == 2
    w.db.close()


# ---------------------------------------------------------------------------------------------------------------------------------
# upcoming_contract_ends – konfigurierter Zeitraum (Dashboard UND Hinweise)
# ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("days,end_off,count", [(30, 30, 1), (30, 31, 0), (30, 60, 0), (180, 150, 1), (180, 180, 1), (180, 181, 0)])
def test_configured_preview_days_apply_to_dashboard_and_reminders(tmp_path, days, end_off, count):
    app, c = make_client(tmp_path, days)
    try:
        w = World(app)
        w.activate_main()
        lease = end_lease(w, d(end_off))
        w.db.commit()
        assert val(c, "upcoming_contract_ends") == count
        assert reminder_ends(c) == ({lease.id} if count else set())
        w.db.close()
    finally:
        c.__exit__(None, None, None)


# ---------------------------------------------------------------------------------------------------------------------------------
# units
# ---------------------------------------------------------------------------------------------------------------------------------
def test_units_and_properties_all_active(world, auth_client):
    k = kpis(auth_client)
    assert k["properties"]["value"] == 1 and k["units"]["value"] == 2
    assert k["physical_vacancy"]["value"] == 4  # Bett A, Bett B, Zimmer 2, WE 2 (ohne Zimmer)


def test_units_of_inactive_property_do_not_count(world, auth_client):
    M.update_property(world.db, None, world.prop.id, {"is_active": False})
    world.db.commit()
    k = kpis(auth_client)
    assert k["properties"]["value"] == 0
    assert k["units"]["value"] == 0  # beide Einheiten sind selbst aktiv, ihr Objekt aber nicht
    assert k["physical_vacancy"]["value"] == 0  # konsistent: keine Leerstandsblätter inaktiver Objekte


def test_deactivated_unit_does_not_count(world, auth_client):
    M.update_unit(world.db, None, world.we2.id, {"is_active": False})
    world.db.commit()
    k = kpis(auth_client)
    assert k["properties"]["value"] == 1 and k["units"]["value"] == 1
    assert k["physical_vacancy"]["value"] == 3  # Bett A, Bett B, Zimmer 2 (WE 2 inaktiv)


def test_units_second_property_active_counts_only_its_active_units(world, auth_client):
    p2 = M.create_property(world.db, None, {"name": "Haus Zwei", "property_type": "mehrfamilienhaus", "street": "Zweitweg 1",
                                            "city": "Berlin", "owner_party_id": world.owner.id})
    M.create_unit(world.db, None, p2.id, {"unit_number": "A1", "living_area": D("30.00")})
    M.create_unit(world.db, None, p2.id, {"unit_number": "A2", "living_area": D("30.00")})
    M.update_property(world.db, None, p2.id, {"is_active": False})
    world.db.commit()
    k = kpis(auth_client)
    assert k["properties"]["value"] == 1 and k["units"]["value"] == 2  # nur WE 1/WE 2 des aktiven Objekts


def test_empty_database_is_zero_and_has_as_of(auth_client):
    body = dash(auth_client)
    k = {x["key"]: x for x in body["kpis"]}
    assert k["units"]["value"] == 0 and k["properties"]["value"] == 0 and k["open_receivables"]["value"] == "0.00"
    assert k["upcoming_contract_ends"]["value"] == 0 and k["overdue_payments"]["value"] == 0
    assert body["as_of"] == TODAY.isoformat()


# ---------------------------------------------------------------------------------------------------------------------------------
# Hilfen für Forderungen/Zahlungen
# ---------------------------------------------------------------------------------------------------------------------------------
class Fin:
    def __init__(self, w):
        self.w = w
        self.tenant = w.tenant("Zahl Mieter")
        self.lease = w.sub([w.ru_room(w.room1)], [self.tenant], d(-400), None, nk_mode=None)
        self.n = 0

    def charge(self, amount, due):
        c = C.create_manual_charge(self.w.db, None, lease_id=self.lease.id, amount=D(amount), due_date=due, period_start=due,
                                   period_end=due + timedelta(days=29), note="Testforderung")
        return c

    def pay(self, amount, booking, *allocs):
        self.n += 1
        p = P.create_payment(self.w.db, None, direction="in", booking_date=booking, amount=D(amount), counterparty_party_id=self.tenant.id,
                             lease_id=self.lease.id, reference=f"T-{self.n}",
                             allocations=[{"charge_id": c.id, "amount": D(a)} for c, a in allocs])
        return p


@pytest.fixture
def fin(world):
    return Fin(world)


def pos(db, as_of=None):
    return C.receivable_position(db, as_of or TODAY)


def put(fin):
    fin.w.db.commit()
    fin.w.db.expire_all()


# ---------------------------------------------------------------------------------------------------------------------------------
# open_receivables / overdue_payments – Basisfälle (Dashboard + Service)
# ---------------------------------------------------------------------------------------------------------------------------------
def test_unpaid_charge_is_open_and_overdue(fin, auth_client):
    fin.charge("600.00", d(-20))
    put(fin)
    assert val(auth_client, "open_receivables") == "600.00" and val(auth_client, "overdue_payments") == 1
    r = pos(fin.w.db)
    assert r["open_total"] == D("600.00") and r["overdue_count"] == 1 and isinstance(r["open_total"], D) and isinstance(r["overdue_count"], int)


def test_fully_paid_charge_is_not_open(fin, auth_client):
    c = fin.charge("600.00", d(-20))
    fin.pay("600.00", d(-10), (c, "600.00"))
    put(fin)
    assert val(auth_client, "open_receivables") == "0.00" and val(auth_client, "overdue_payments") == 0
    r = pos(fin.w.db)
    assert r["open_total"] == D("0.00") and r["overdue_count"] == 0


def test_partial_payment_keeps_remainder_open_and_overdue(fin, auth_client):
    c = fin.charge("600.00", d(-20))
    fin.pay("250.00", d(-10), (c, "250.00"))
    put(fin)
    assert val(auth_client, "open_receivables") == "350.00" and val(auth_client, "overdue_payments") == 1
    r = pos(fin.w.db)
    assert r["open_total"] == D("350.00") and r["overdue_count"] == 1


def test_owner_example_600_500_100_future_booking_does_not_reduce_today(fin, auth_client):
    """ADR Vorgabe 3: 600 fällig; 500 heute gebucht, 100 mit Buchungsdatum in der Zukunft -> heute offen 100,00."""
    c = fin.charge("600.00", d(-20))
    fin.pay("500.00", TODAY, (c, "500.00"))
    fin.pay("100.00", d(5), (c, "100.00"))
    put(fin)
    assert val(auth_client, "open_receivables") == "100.00"
    assert val(auth_client, "overdue_payments") == 1  # Rest 100 offen, Fälligkeit vor heute
    r = pos(fin.w.db, TODAY)
    assert r["open_total"] == D("100.00") and r["overdue_count"] == 1
    # Service-Ebene (Dashboard lehnt Zukunfts-Stichtage ab): am Buchungstag der zweiten Zahlung ist alles bezahlt (Buchungsdatum <= Stichtag)
    assert pos(fin.w.db, d(5))["open_total"] == D("0.00") and pos(fin.w.db, d(4))["open_total"] == D("100.00")


def test_payment_with_only_future_booking_date_does_not_reduce_today(fin, auth_client):
    c = fin.charge("600.00", d(-20))
    fin.pay("600.00", d(3), (c, "600.00"))
    put(fin)
    assert val(auth_client, "open_receivables") == "600.00" and val(auth_client, "overdue_payments") == 1
    assert pos(fin.w.db, TODAY)["open_total"] == D("600.00")
    assert pos(fin.w.db, d(3))["open_total"] == D("0.00")  # Booking-Tag zählt (<=)


# ---------------------------------------------------------------------------------------------------------------------------------
# historische Stichtage via as_of
# ---------------------------------------------------------------------------------------------------------------------------------
def test_historical_as_of_single_payment(fin, auth_client):
    c = fin.charge("600.00", d(-40))
    fin.pay("600.00", d(-10), (c, "600.00"))
    put(fin)
    assert val(auth_client, "open_receivables", as_of=d(-11).isoformat()) == "600.00"  # Tag vor der Zahlung
    assert val(auth_client, "open_receivables", as_of=d(-10).isoformat()) == "0.00"    # am Buchungstag zählt sie
    assert val(auth_client, "open_receivables", as_of=d(-9).isoformat()) == "0.00"
    assert val(auth_client, "overdue_payments", as_of=d(-11).isoformat()) == 1
    assert val(auth_client, "overdue_payments", as_of=d(-10).isoformat()) == 0
    assert val(auth_client, "open_receivables") == "0.00"  # heute


# Szenario S2: 800 fällig am Tag -40; Zahlungen 200 (Tag -30), 300 (Tag -20), 100 (Tag -10). Offen je Stichtag von Hand:
#   <= -31: 800 | -30..-21: 600 | -20..-11: 300 | -10..heute: 200. Fälligkeit zählt für open_total nicht (A1), nur das Zahlungsdatum.
@pytest.mark.parametrize("as_of_off,open_total,overdue", [
    (-45, "800.00", 0),   # vor der Fälligkeit: offen (A1), aber nicht überfällig (Fälligkeit -40 !< -45)
    (-41, "800.00", 0),   # Fälligkeit -40 !< -41
    (-40, "800.00", 0),   # Fälligkeit am Stichtag ist nicht überfällig (due < as_of)
    (-39, "800.00", 1),
    (-31, "800.00", 1),
    (-30, "600.00", 1),   # erste Zahlung am Stichtag
    (-25, "600.00", 1),
    (-20, "300.00", 1),
    (-15, "300.00", 1),
    (-10, "200.00", 1),
    (0, "200.00", 1),
])
def test_multiple_payments_different_booking_dates_per_as_of(fin, auth_client, as_of_off, open_total, overdue):
    c = fin.charge("800.00", d(-40))
    fin.pay("200.00", d(-30), (c, "200.00"))
    fin.pay("300.00", d(-20), (c, "300.00"))
    fin.pay("100.00", d(-10), (c, "100.00"))
    put(fin)
    as_of = d(as_of_off)
    r = pos(fin.w.db, as_of)
    assert r["open_total"] == D(open_total) and r["overdue_count"] == overdue
    k = kpis(auth_client, as_of=as_of.isoformat())
    assert k["open_receivables"]["value"] == open_total and k["overdue_payments"]["value"] == overdue


def test_payment_booked_by_allocation_time_not_by_creation(fin, auth_client):
    """A5: nach Buchungsdatum, nicht nach Zuordnungszeitpunkt: heute erfasste Zahlung mit Buchungsdatum -10 wirkt ab Tag -10."""
    c = fin.charge("100.00", d(-30))
    fin.pay("100.00", d(-10), (c, "100.00"))  # heute angelegt und zugeordnet
    put(fin)
    assert pos(fin.w.db, d(-11))["open_total"] == D("100.00")
    assert pos(fin.w.db, d(-10))["open_total"] == D("0.00")


def test_reversal_acts_from_its_own_booking_date(fin, auth_client):
    """A5: Storno per Gegenbuchung wirkt ab seinem Buchungsdatum; davor zählt die Zahlung noch als bezahlt."""
    c = fin.charge("600.00", d(-30))
    p = fin.pay("600.00", d(-10), (c, "600.00"))
    P.reverse_payment(fin.w.db, None, p.id, reason="Fehlbuchung", booking_date=TODAY)
    put(fin)
    assert pos(fin.w.db, d(-11))["open_total"] == D("600.00")  # vor der Zahlung
    assert pos(fin.w.db, d(-5))["open_total"] == D("0.00") and pos(fin.w.db, d(-5))["overdue_count"] == 0
    assert pos(fin.w.db, TODAY)["open_total"] == D("600.00") and pos(fin.w.db, TODAY)["overdue_count"] == 1
    assert val(auth_client, "open_receivables") == "600.00"
    assert val(auth_client, "open_receivables", as_of=d(-5).isoformat()) == "0.00"


def test_overpayment_is_not_netted_across_charges(fin, auth_client):
    """A7: Zahlung 500, nur 100 zugeordnet; die zweite Forderung (200) bleibt voll offen, keine negative Verrechnung."""
    a = fin.charge("100.00", d(-20))
    fin.charge("200.00", d(-10))
    fin.pay("500.00", d(-5), (a, "100.00"))
    put(fin)
    assert val(auth_client, "open_receivables") == "200.00" and val(auth_client, "overdue_payments") == 1
    r = pos(fin.w.db)
    assert r["open_total"] == D("200.00") and r["overdue_count"] == 1


def test_overpaid_charge_cannot_go_negative(fin, auth_client):
    c = fin.charge("100.00", d(-20))
    fin.pay("100.00", d(-5), (c, "100.00"))
    fin.charge("50.00", d(-1))  # eine weitere, offene Forderung
    put(fin)
    assert pos(fin.w.db)["open_total"] == D("50.00")


def test_future_due_charge_counts_to_open_but_not_to_overdue(fin, auth_client):
    """A1: offen unabhängig von der Fälligkeit; überfällig nur bei due_date < Stichtag."""
    fin.charge("300.00", d(10))
    put(fin)
    assert val(auth_client, "open_receivables") == "300.00" and val(auth_client, "overdue_payments") == 0
    r = pos(fin.w.db)
    assert r["open_total"] == D("300.00") and r["overdue_count"] == 0


def test_due_today_is_open_but_not_overdue(fin, auth_client):
    fin.charge("120.00", TODAY)
    put(fin)
    assert val(auth_client, "open_receivables") == "120.00" and val(auth_client, "overdue_payments") == 0


def test_voided_charge_is_not_counted(fin, auth_client):
    gone = fin.charge("400.00", d(-20))
    fin.charge("100.00", d(-20))
    C.void_charge(fin.w.db, None, gone.id, "Fehlerhaft angelegt")
    put(fin)
    assert val(auth_client, "open_receivables") == "100.00" and val(auth_client, "overdue_payments") == 1
    r = pos(fin.w.db)
    assert r["open_total"] == D("100.00") and r["overdue_count"] == 1


def test_payable_charges_are_not_receivables(world, auth_client):
    """Verbindlichkeiten der Hauptmiete (direction=payable) gehören nicht zu den Mietforderungen."""
    main = next(x for x in world.db.query(L.Lease).all() if x.kind == "main")
    C.create_manual_charge(world.db, None, lease_id=main.id, amount=D("700.00"), due_date=d(-5), period_start=d(-5), period_end=d(24), note="Hauptmiete")
    world.db.commit()
    assert val(auth_client, "open_receivables") == "0.00" and val(auth_client, "overdue_payments") == 0
    assert pos(world.db)["open_total"] == D("0.00")


def test_no_as_of_equals_today(fin, auth_client):
    c = fin.charge("800.00", d(-40))
    fin.pay("200.00", d(-30), (c, "200.00"))
    fin.charge("55.00", d(7))
    put(fin)
    a, b = kpis(auth_client), kpis(auth_client, as_of=TODAY.isoformat())
    assert {k: v["value"] for k, v in a.items()} == {k: v["value"] for k, v in b.items()}
    assert a["open_receivables"]["value"] == "655.00"  # 600 + 55 (A1)


# ---------------------------------------------------------------------------------------------------------------------------------
# API-Vertrag: as_of, historical_supported, Rechte, Einmal-Berechnung
# ---------------------------------------------------------------------------------------------------------------------------------
def test_as_of_in_future_is_422(auth_client):
    assert auth_client.get(V + "/dashboard", params={"as_of": d(1).isoformat()}).status_code == 422
    assert auth_client.get(V + "/dashboard", params={"as_of": d(365).isoformat()}).status_code == 422


def test_as_of_invalid_format_is_422(auth_client):
    assert auth_client.get(V + "/dashboard", params={"as_of": "gestern"}).status_code == 422
    assert auth_client.get(V + "/dashboard", params={"as_of": "2026-13-40"}).status_code == 422


def test_response_shape_has_as_of_and_historical_supported(auth_client):
    past = d(-30)
    body = dash(auth_client, as_of=past.isoformat())
    assert body["as_of"] == past.isoformat()
    assert {"kpis", "warnings", "tasks", "as_of"} <= set(body)
    assert all(isinstance(k["historical_supported"], bool) for k in body["kpis"])
    k = {x["key"]: x for x in body["kpis"]}
    assert k["open_receivables"]["historical_supported"] is True and k["overdue_payments"]["historical_supported"] is True
    assert dash(auth_client)["as_of"] == TODAY.isoformat()


def test_dashboard_requires_login(client):
    assert client.get(V + "/dashboard").status_code == 401
    assert client.get(V + "/dashboard", params={"as_of": TODAY.isoformat()}).status_code == 401


def test_month_figures_computed_exactly_once_per_call_with_as_of(world, auth_client, monkeypatch):
    from leventum.services import economics as E
    calls = []
    original = E.current_month_figures
    monkeypatch.setattr(E, "current_month_figures", lambda *a, **kw: (calls.append(1), original(*a, **kw))[1])
    assert auth_client.get(V + "/dashboard").status_code == 200
    assert len(calls) == 1
    calls.clear()
    assert auth_client.get(V + "/dashboard", params={"as_of": d(-3).isoformat()}).status_code == 200
    assert len(calls) <= 1  # as_of darf die teure Monatsauswertung nicht vervielfachen


def test_dashboard_read_permission_unchanged_for_all_roles():
    """Das Recht dashboard:read bleibt unverändert; die Routenabdeckung prüft die bestehende Rechte-Suite."""
    from leventum.security.permissions import ROLE_PERMISSIONS, has_permission
    assert all(has_permission(role, "dashboard:read") for role in ROLE_PERMISSIONS)


# ---------------------------------------------------------------------------------------------------------------------------------
# Bekannte Einschränkungen A6 – NICHT als bestanden ausweisen
# ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.xfail(strict=False, reason="bekannte Einschränkung A6(a): spätere Rücknahme einer Zuordnung ändert historische Stichtage rückwirkend")
def test_a6a_deallocate_does_not_change_history(fin, auth_client):
    c = fin.charge("600.00", d(-40))
    p = fin.pay("600.00", d(-30), (c, "600.00"))
    put(fin)
    before = pos(fin.w.db, d(-20))["open_total"]
    assert before == D("0.00")
    P.deallocate(fin.w.db, None, p.id, charge_id=c.id, amount=D("600.00"), reason="Fehlzuordnung")
    put(fin)
    assert pos(fin.w.db, d(-20))["open_total"] == before  # Wunsch-Verhalten; real verändert sich der historische Wert (A6a)


@pytest.mark.xfail(strict=False, reason="bekannte Einschränkung A6(b): heute stornierte Sollstellungen fehlen in historischen Stichtagen")
def test_a6b_voided_charge_still_open_in_history(fin, auth_client):
    c = fin.charge("400.00", d(-40))
    C.void_charge(fin.w.db, None, c.id, "Fehlerhaft")
    put(fin)
    assert pos(fin.w.db, d(-20))["open_total"] == D("400.00")  # Wunsch-Verhalten (A6b)
