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
from leventum.services.errors import ServiceError
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


def test_overpayment_cannot_create_negative_netting(fin, auth_client):
    """Überzahlung: Zahlung 130 auf Forderung 100. Die Zuordnung über den offenen Betrag hinaus scheitert (exceeds_open, 409);
    die nicht zugeordneten 30 erscheinen nirgends als negativer Betrag, open_total bleibt Restbetrag der anderen Forderung (A7)."""
    c = fin.charge("100.00", d(-20))
    fin.charge("50.00", d(-1))
    p = fin.pay("130.00", d(-5), (c, "100.00"))
    put(fin)
    with pytest.raises(ServiceError) as ei:
        P.allocate(fin.w.db, None, p.id, charge_id=c.id, amount=D("30.00"))  # Forderung c ist voll bezahlt, offen 0,00
    assert ei.value.code == "exceeds_open" and ei.value.status == 409
    put(fin)
    assert C.allocated(fin.w.db, c.id) == D("100.00")  # keine Zuordnung über den Forderungsbetrag hinaus entstanden
    assert P.unallocated(fin.w.db, fin.w.db.get(type(p), p.id)) == D("30.00")  # Rest bleibt unzugeordnet (kein Guthaben-Verrechnen)
    r = pos(fin.w.db)
    assert r["open_total"] == D("50.00") and r["overdue_count"] == 1 and r["open_total"] >= 0  # nicht 20,00 (= 50 - 30)
    assert val(auth_client, "open_receivables") == "50.00" and val(auth_client, "overdue_payments") == 1
    assert pos(fin.w.db, d(-6))["open_total"] == D("150.00")  # vor der Zahlung beide Forderungen voll offen (100 + 50)


def test_overpaid_allocation_at_payment_creation_is_rejected_and_leaves_no_negative(fin, auth_client):
    """Zahlung 150 mit Zuordnung 150 auf Forderung 100 wird abgewiesen; nach Rollback bleibt die Forderung voll offen (100,00)."""
    c = fin.charge("100.00", d(-20))
    put(fin)
    with pytest.raises(ServiceError) as ei:
        fin.pay("150.00", d(-5), (c, "150.00"))
    assert ei.value.code == "exceeds_open"
    fin.w.db.rollback()
    put(fin)
    assert pos(fin.w.db)["open_total"] == D("100.00") and C.allocated(fin.w.db, c.id) == D("0.00")
    assert val(auth_client, "open_receivables") == "100.00"


def test_fully_paid_charge_with_unallocated_surplus_is_zero_not_negative(fin, auth_client):
    c = fin.charge("100.00", d(-20))
    fin.pay("130.00", d(-5), (c, "100.00"))
    put(fin)
    assert pos(fin.w.db)["open_total"] == D("0.00") and val(auth_client, "open_receivables") == "0.00"


# Befund F1 (vorbestehende Semantik, auch in charges.open_amount): Storno VOR Originalzahlung -> offen > Forderungsbetrag.
@pytest.mark.xfail(strict=True, reason="Befund F1: Storno vor Originalzahlung führt zu offen > Forderungsbetrag – Entscheidung ausstehend")
def test_f1_reversal_booked_before_original_payment_never_exceeds_charge(fin, auth_client):
    """Forderung 600 (fällig -30); Zahlung 600 gebucht -5; Storno mit Buchungsdatum -20 (vor der Originalzahlung).
    Stichtag -10: Storno (-600) wirkt, Original (+600) noch nicht -> real offen 1200. Erwünscht: offen <= Forderungsbetrag 600."""
    c = fin.charge("600.00", d(-30))
    p = fin.pay("600.00", d(-5), (c, "600.00"))
    P.reverse_payment(fin.w.db, None, p.id, reason="Fehlbuchung", booking_date=d(-20))
    put(fin)
    assert pos(fin.w.db, d(-10))["open_total"] <= D("600.00")


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
    """dashboard._fig cached je Request unter ("_fig", as_of); die vier Monats-KPIs teilen sich dadurch GENAU EINE Berechnung.
    Exakt 1 (nicht 0: die KPIs main_rent_obligations u. a. werden immer berechnet; nicht >1: Cache). Die Monatswerte beziehen
    sich immer auf den heutigen Monat (ADR 0002 A6), as_of ändert sie daher nicht."""
    from leventum.services import economics as E
    calls = []
    original = E.current_month_figures
    monkeypatch.setattr(E, "current_month_figures", lambda *a, **kw: (calls.append(1), original(*a, **kw))[1])
    today_kpis = kpis(auth_client)
    assert len(calls) == 1
    month_keys = ("main_rent_obligations", "sublease_receivables", "monthly_utility_costs", "economic_vacancy_cost", "physical_vacancy")
    for as_of in (d(-3), d(-200), TODAY):
        calls.clear()
        k = kpis(auth_client, as_of=as_of.isoformat())
        assert len(calls) == 1, as_of
        assert all(k[key]["value"] == today_kpis[key]["value"] for key in month_keys)
        assert all(k[key]["historical_supported"] is False for key in month_keys)
    assert today_kpis["main_rent_obligations"]["value"] != "0.00"  # Kontrolle: Wert nicht trivial (Hauptmiete 850 + 180 NK, tagesanteilig)


@pytest.mark.parametrize("role", ["admin", "verwaltung", "buchhaltung", "objektbetreuung", "lesend"])
def test_dashboard_read_permission_all_roles_with_and_without_as_of(app, auth_client, role):
    """Jede Rolle liest /dashboard ohne as_of (200). Mit as_of nur mit finance:read (admin/buchhaltung/lesend → 200 mit Stichtag, Zukunft 422);
    verwaltung/objektbetreuung → 403, auch bei Zukunftsdatum (Rechteprüfung vor Stichtagsvalidierung). Geändert nach Eigentümerentscheidung
    Phase I (vorher: alle Rollen 200); Details in test_i2_finance_permissions.py."""
    from sqlalchemy import select
    from leventum.models import AppUser, Role
    from leventum.security.passwords import hash_password
    with app.state.session_factory() as db:
        db.add(AppUser(username=f"u_{role}", display_name=role, password_hash=hash_password(PW), role_id=db.scalar(select(Role.id).where(Role.code == role))))
        db.commit()
    c = TestClient(app, headers={"X-Leventum-Client": "1"})
    assert c.post(V + "/auth/login", json={"username": f"u_{role}", "password": PW}).status_code == 200
    past = d(-7).isoformat()
    r1, r2 = c.get(V + "/dashboard"), c.get(V + "/dashboard", params={"as_of": past})
    assert r1.status_code == 200 and r1.json()["as_of"] == TODAY.isoformat()
    future = c.get(V + "/dashboard", params={"as_of": d(1).isoformat()})
    if role in ("admin", "buchhaltung", "lesend"):
        assert r2.status_code == 200 and r2.json()["as_of"] == past
        assert future.status_code == 422  # Recht vorhanden, Zukunft weiter abgelehnt
    else:
        assert r2.status_code == 403 and future.status_code == 403


def test_dashboard_as_of_requires_same_right_as_without(app, auth_client, monkeypatch):
    """Ohne Login 401 (auch mit as_of). Entzug des Rechts dashboard:read -> 403, gleichermaßen ohne und mit as_of (kein Seitenpfad)."""
    from sqlalchemy import select
    from leventum.models import AppUser, Role
    from leventum.security import permissions as perms
    from leventum.security.passwords import hash_password
    anon = TestClient(app, headers={"X-Leventum-Client": "1"})
    assert anon.get(V + "/dashboard").status_code == 401
    assert anon.get(V + "/dashboard", params={"as_of": d(-7).isoformat()}).status_code == 401
    with app.state.session_factory() as db:
        db.add(AppUser(username="leser2", display_name="L", password_hash=hash_password(PW), role_id=db.scalar(select(Role.id).where(Role.code == "lesend"))))
        db.commit()
    c = TestClient(app, headers={"X-Leventum-Client": "1"})
    assert c.post(V + "/auth/login", json={"username": "leser2", "password": PW}).status_code == 200
    assert c.get(V + "/dashboard", params={"as_of": d(-7).isoformat()}).status_code == 200
    monkeypatch.setitem(perms.ROLE_PERMISSIONS, "lesend", {"master:read"})
    assert c.get(V + "/dashboard").status_code == 403
    assert c.get(V + "/dashboard", params={"as_of": d(-7).isoformat()}).status_code == 403
    assert c.get(V + "/dashboard", params={"as_of": d(1).isoformat()}).status_code == 403  # Recht wird vor der Stichtagsprüfung geprüft


def test_dashboard_read_permission_unchanged_for_all_roles():
    """Das Recht dashboard:read bleibt unverändert; die Routenabdeckung prüft die bestehende Rechte-Suite."""
    from leventum.security.permissions import ROLE_PERMISSIONS, has_permission
    assert all(has_permission(role, "dashboard:read") for role in ROLE_PERMISSIONS)


# ---------------------------------------------------------------------------------------------------------------------------------
# T3: contract_end_due mit nicht-heutigem Stichtag (Service)
# ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("as_of_off,expected_end", [
    (-101, None),  # Vertrag (Beginn -100) läuft noch nicht
    (-100, None),  # Beginntag: läuft, Ende in 130 Tagen > 90
    (-61, None),   # Ende in 91 Tagen
    (-60, 30),     # Ende in genau 90 Tagen (Grenze inklusiv)
    (0, 30),       # heute: Ende in 30 Tagen
    (30, 30),      # Stichtag = Ende (inklusiv, läuft am letzten Tag noch)
    (31, None),    # Ende liegt vor dem Stichtag, Vertrag läuft nicht mehr
])
def test_contract_end_due_historical_and_shifted_as_of_service(world, as_of_off, expected_end):
    lease = end_lease(world, d(30), start=d(-100))
    got = L.contract_end_due(lease, d(as_of_off), 90)
    assert got == (None if expected_end is None else d(expected_end))


def test_contract_end_due_future_start_lease_at_various_as_of_service(world):
    lease = end_lease(world, d(60), start=d(10))
    assert L.contract_end_due(lease, d(-30), 90) is None  # vor Beginn: nicht laufend, auch wenn Ende in 90 Tagen läge
    assert L.contract_end_due(lease, d(9), 90) is None    # Vortag des Beginns
    assert L.contract_end_due(lease, d(10), 90) == d(60)  # Beginntag
    assert L.contract_end_due(lease, d(10), 49) is None and L.contract_end_due(lease, d(10), 50) == d(60)
    assert L.contract_end_due(lease, d(61), 90) is None


def test_upcoming_ends_list_respects_as_of_service(world):
    a = end_lease(world, d(-10), start=d(-100), unit="room1")
    b = end_lease(world, d(40), start=d(-20), unit="room2")
    world.db.commit()
    assert {x.id: e for x, e in L.upcoming_ends(world.db, d(-30), 90) if x.kind == "sub"} == {a.id: d(-10)}  # b beginnt erst -20
    assert {x.id: e for x, e in L.upcoming_ends(world.db, TODAY, 90) if x.kind == "sub"} == {b.id: d(40)}   # a ist heute beendet


# ---------------------------------------------------------------------------------------------------------------------------------
# T2: API mit as_of in der Vergangenheit für Vertrags-KPIs
# ---------------------------------------------------------------------------------------------------------------------------------
def test_contract_kpis_and_hint_with_historical_as_of(app, auth_client):
    """Von Hand (Haupt­vertrag ab -250, offen):
    A room1: -100..-10 (läuft zum Stichtag -30/-15, heute beendet) | B room2: -20..+40 (beginnt nach Stichtag -30, läuft heute)
    C we2: ab -200, offen, gekündigt (Kündigung -5, wirksam +20). Vorschau 90 Tage.
      Stichtag -260: Hauptvertrag noch nicht begonnen -> alles 0.
      Stichtag -150: nur C läuft (1 Sub, 1 Mieter, Hint 1), Ende +20 liegt > 90 Tage nach -150 -> 0 anstehende Enden.
      Stichtag  -30: A, C laufen (B nicht) -> 2/2, Enden A (-10), C (+20) -> 2, Hint 1.
      Stichtag  -15: A, B, C laufen -> 3/3, Enden 3, Hint 1.
      heute        : B, C laufen (A beendet) -> 2/2, Enden B (+40), C (+20) = 2."""
    w = World(app)
    w.activate_main(start=d(-250))
    end_lease(w, d(-10), start=d(-100), unit="room1")
    end_lease(w, d(40), start=d(-20), unit="room2")
    c_lease = end_lease(w, None, start=d(-200), unit="we2")
    L.terminate_lease(w.db, None, c_lease.id, terminated_on=d(-5), effective_on=d(20))
    w.db.commit()
    try:
        def at(off):
            return kpis(auth_client) if off is None else kpis(auth_client, as_of=d(off).isoformat())
        expected = {  # off -> (main, subs, tenants, ends, hint_subs, hint_tenants)
            -260: (0, 0, 0, 0, None, None),
            -150: (1, 1, 1, 0, "davon 1 in Kündigung", "davon 1 in Kündigung"),
            -30: (1, 2, 2, 2, "davon 1 in Kündigung", "davon 1 in Kündigung"),
            -15: (1, 3, 3, 3, "davon 1 in Kündigung", "davon 1 in Kündigung"),
            None: (1, 2, 2, 2, "davon 1 in Kündigung", "davon 1 in Kündigung"),
        }
        for off, (main, subs, ten, ends, h_subs, h_ten) in expected.items():
            k = at(off)
            got = (k["active_main_leases"]["value"], k["active_subleases"]["value"], k["active_tenants"]["value"], k["upcoming_contract_ends"]["value"],
                   k["active_subleases"]["hint"], k["active_tenants"]["hint"])
            assert got == (main, subs, ten, ends, h_subs, h_ten), off
            assert all(k[x]["historical_supported"] is True for x in ("active_main_leases", "active_subleases", "active_tenants", "upcoming_contract_ends"))
    finally:
        w.db.close()


def test_main_lease_end_counts_only_within_window_of_historical_as_of(app, auth_client):
    w = World(app)
    w.activate_main(start=d(-250), end=d(-100))  # Hauptvertrag endete vor 100 Tagen
    w.db.commit()
    try:
        assert val(auth_client, "active_main_leases") == 0 and val(auth_client, "upcoming_contract_ends") == 0  # heute beendet
        assert val(auth_client, "active_main_leases", as_of=d(-150).isoformat()) == 1
        assert val(auth_client, "upcoming_contract_ends", as_of=d(-150).isoformat()) == 1  # Ende -100 liegt 50 Tage nach dem Stichtag
        assert val(auth_client, "upcoming_contract_ends", as_of=d(-191).isoformat()) == 0  # 91 Tage vorher: außerhalb
        assert val(auth_client, "upcoming_contract_ends", as_of=d(-190).isoformat()) == 1  # genau 90 Tage: inklusiv
        assert val(auth_client, "active_main_leases", as_of=d(-99).isoformat()) == 0
    finally:
        w.db.close()


# ---------------------------------------------------------------------------------------------------------------------------------
# T4: mehrere Verträge und Forderungen bei historischem Stichtag
# ---------------------------------------------------------------------------------------------------------------------------------
def test_multi_lease_multi_charge_historical_totals_and_overdue_by_lease(world, auth_client):
    """Vertrag 1 (room1): a1 500 fällig -50, a2 300 fällig -20, a3 200 fällig +10. Vertrag 2 (room2): b1 400 fällig -45, b2 100 fällig -5.
    Zahlungen: p1 500 (Buchung -40) -> a1; p2 150 (-15) -> a2; p3 400 (-3) -> b1. Alle Werte von Hand je Stichtag:
      -60: offen 1500 (500+300+200+400+100), überfällig 0 (keine Fälligkeit < -60)
      -44: offen 1500, überfällig 2 (a1 -50, b1 -45)
      -30: p1 gebucht: offen 1000 (300+200+400+100), überfällig 1 (nur b1; a2 fällig -20 !< -30)
      -10: p2 gebucht: offen 850 (150+200+400+100), überfällig 2 (a2 Rest 150, b1 400; b2 fällig -5 !< -10)
       -2: p3 gebucht: offen 450 (150+200+100), überfällig 2 (a2 150, b2 100)
       heute: wie -2."""
    w = world
    fin1 = Fin(w)
    tenant2 = w.tenant("Zwei Mieter")
    lease2 = w.sub([w.ru_room(w.room2)], [tenant2], d(-400), None, nk_mode=None)

    def charge(lease, amount, due):
        return C.create_manual_charge(w.db, None, lease_id=lease.id, amount=D(amount), due_date=due, period_start=due, period_end=due + timedelta(days=29), note="T4")
    a1, a2, a3 = (charge(fin1.lease, "500.00", d(-50)), charge(fin1.lease, "300.00", d(-20)), charge(fin1.lease, "200.00", d(10)))
    b1, b2 = charge(lease2, "400.00", d(-45)), charge(lease2, "100.00", d(-5))
    fin1.pay("500.00", d(-40), (a1, "500.00"))
    fin1.pay("150.00", d(-15), (a2, "150.00"))
    P.create_payment(w.db, None, direction="in", booking_date=d(-3), amount=D("400.00"), counterparty_party_id=tenant2.id, lease_id=lease2.id,
                     reference="T4-b1", allocations=[{"charge_id": b1.id, "amount": D("400.00")}])
    assert b2.id and a3.id
    put(fin1)
    l1, l2 = fin1.lease.id, lease2.id
    cases = [  # (Stichtag-Offset, offen, überfällig, overdue_by_lease)
        (-60, "1500.00", 0, {}),
        (-44, "1500.00", 2, {l1: [(d(-50), D("500.00"))], l2: [(d(-45), D("400.00"))]}),
        (-30, "1000.00", 1, {l2: [(d(-45), D("400.00"))]}),
        (-10, "850.00", 2, {l1: [(d(-20), D("150.00"))], l2: [(d(-45), D("400.00"))]}),
        (-2, "450.00", 2, {l1: [(d(-20), D("150.00"))], l2: [(d(-5), D("100.00"))]}),
        (0, "450.00", 2, {l1: [(d(-20), D("150.00"))], l2: [(d(-5), D("100.00"))]}),
    ]
    for off, open_total, overdue, by_lease in cases:
        r = pos(w.db, d(off))
        assert r["open_total"] == D(open_total), off
        assert r["overdue_count"] == overdue, off
        assert r["overdue_by_lease"] == by_lease, off
        k = kpis(auth_client, as_of=d(off).isoformat())
        assert k["open_receivables"]["value"] == open_total and k["overdue_payments"]["value"] == overdue, off
        assert sum(len(v) for v in r["overdue_by_lease"].values()) == r["overdue_count"]


# ---------------------------------------------------------------------------------------------------------------------------------
# T5: POST /reminders/task mit konfiguriertem Vorschauzeitraum
# ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("days,end_off,created", [(30, 40, False), (39, 40, False), (40, 40, True), (60, 40, True)])
def test_reminder_to_task_respects_configured_preview_days(tmp_path, days, end_off, created):
    """Aufgabe nur, wenn die contract_end-Erinnerung im konfigurierten Fenster liegt (Grenze inklusiv); sonst 404 not_found, keine Aufgabe."""
    app, c = make_client(tmp_path, days)
    try:
        w = World(app)
        w.activate_main()
        lease = end_lease(w, d(end_off))
        w.db.commit()
        key = f"contract_end:{lease.id}:{d(end_off).isoformat()}"
        listed = [i for i in c.get(V + "/reminders").json()["items"] if i["type"] == "contract_end"]
        r = c.post(V + "/reminders/task", json={"key": key})
        if created:
            assert [i["key"] for i in listed] == [key]
            assert r.status_code == 201, r.text
            assert r.json()["lease_id"] == lease.id and r.json()["due_date"] == d(end_off).isoformat()
            again = c.post(V + "/reminders/task", json={"key": key})
            assert again.status_code == 409 and again.json()["detail"]["code"] == "exists"  # Idempotenz: keine zweite Aufgabe
        else:
            assert listed == []
            assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found"
            assert not any(t.get("lease_id") == lease.id for t in c.get(V + "/tasks").json()["items"])
        w.db.close()
    finally:
        c.__exit__(None, None, None)


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
