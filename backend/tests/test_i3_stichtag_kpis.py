"""Phase I3 (VOR der Implementierung geschrieben): einheitliche Stichtagslogik und getrennte Dashboard-KPIs.
Eigentümerentscheidung:
  A) open_receivables (alle offenen, fälligkeitsunabhängig) bleibt; NEU overdue_receivables (nur Fälligkeit < Stichtag, EUR); overdue_payments (Anzahl) bleibt;
     NEU upcoming_main_lease_ends / upcoming_sublease_ends, upcoming_contract_ends = Summe beider.
  B) services/stichtag.py: resolve(raw, today=None) und meta(view, st, ...).
  C) ALLE Ansichten: Zahlungen wirken erst ab Payment.booking_date <= Stichtag (auch heute): /charges, /dunning/overdue, Mahnentwurf, Bankvorschläge,
     arrears/arrears_bulk (/tenants). AUSNAHME: payments.allocate nutzt weiterhin ALLE Zuordnungen (kein Doppel-Zuordnen).
  D) Szenarien. Alle Erwartungswerte sind von Hand relativ zu date.today() berechnet (zeitstabil), nicht aus dem Code abgeleitet.
Schnittstellenannahmen sind am Ende der Datei bzw. im Übergabebericht dokumentiert. Tests werden nicht abgeschwächt."""
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from leventum.config import Settings
from leventum.main import create_app
from leventum.services import charges as C, dunning as DN, leases as L, master as M, payments as P
from leventum.services.errors import ServiceError
from tests.conftest import PW
from tests.helpers import World

V = "/api/v1"
TODAY = date.today()
TENANT_IBAN = "DE89370400440532013000"


def d(n: int) -> date:
    """Tag relativ zu heute."""
    return TODAY + timedelta(days=n)


def iso(n: int) -> str:
    return d(n).isoformat()


# ---------------------------------------------------------------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------------------------------------------------------------
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


def get_ok(client, path, **params):
    r = client.get(V + path, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def code_of(resp):
    return resp.json()["detail"]["code"]


@pytest.fixture
def world(app, auth_client):
    w = World(app)
    w.activate_main()
    w.db.commit()
    yield w
    w.db.close()


@pytest.fixture
def bare(app, auth_client):
    """Testwelt OHNE Hauptmietvertrag (für Haupt-/Untermietvertragsenden mit eigenem Hauptvertrag)."""
    w = World(app)
    w.db.commit()
    yield w
    w.db.close()


def end_lease(w, end, *, start=None, unit="room1", activate=True):
    ru = {"room1": w.ru_room(w.room1), "room2": w.ru_room(w.room2), "we2": w.ru_unit(w.we2)}[unit]
    return w.sub([ru], [w.tenant(f"Mieter {unit}")], start or d(-100), end, activate=activate)


class Fin:
    """Ein Untermietvertrag (Beginn vor 400 Tagen, offen) mit handgebuchten Forderungen und Zahlungen."""

    def __init__(self, w, name="Zahl Mieter"):
        self.w = w
        self.tenant = w.tenant(name)
        self.lease = w.sub([w.ru_room(w.room1)], [self.tenant], d(-400), None, nk_mode=None)
        self.n = 0

    def charge(self, amount, due):
        return C.create_manual_charge(self.w.db, None, lease_id=self.lease.id, amount=D(amount), due_date=due, period_start=due,
                                      period_end=due + timedelta(days=29), note="Testforderung")

    def pay(self, amount, booking, *allocs):
        self.n += 1
        return P.create_payment(self.w.db, None, direction="in", booking_date=booking, amount=D(amount), counterparty_party_id=self.tenant.id,
                                lease_id=self.lease.id, reference=f"I3-{self.n}", allocations=[{"charge_id": c.id, "amount": D(a)} for c, a in allocs])


@pytest.fixture
def fin(world):
    return Fin(world)


def put(fin):
    fin.w.db.commit()
    fin.w.db.expire_all()


def charge_row(client, charge_id, **params):
    items = get_ok(client, "/charges", **params)["items"]
    rows = [r for r in items if r["id"] == charge_id]
    assert len(rows) == 1, (charge_id, items)
    return rows[0]


def overdue_items(client, **params):
    return get_ok(client, "/dunning/overdue", **params)["items"]


# ---------------------------------------------------------------------------------------------------------------------------------
# B) services/stichtag.py – resolve() und meta() (Service-Ebene, Tabellentests)
# ---------------------------------------------------------------------------------------------------------------------------------
def stichtag():
    from leventum.services import stichtag as ST  # Import im Test: Modul existiert vor der Implementierung noch nicht
    return ST


@pytest.mark.parametrize("raw,expected_off,mode", [
    (None, 0, "current"),
    (TODAY, 0, "current"),
    (TODAY.isoformat(), 0, "current"),
    (d(-1), -1, "historical"),
    (d(-1).isoformat(), -1, "historical"),
    (d(-365), -365, "historical"),
    (d(-30).isoformat(), -30, "historical"),
])
def test_resolve_valid_inputs_table(raw, expected_off, mode):
    st = stichtag().resolve(raw)
    assert st.as_of == d(expected_off) and isinstance(st.as_of, date)
    assert st.today == TODAY
    assert st.mode == mode
    assert st.is_historical is (mode == "historical")


def test_resolve_with_explicit_today_is_deterministic():
    ST = stichtag()
    fixed = date(2026, 3, 15)
    st = ST.resolve("2026-03-15", today=fixed)
    assert (st.as_of, st.today, st.mode, st.is_historical) == (fixed, fixed, "current", False)
    st = ST.resolve(date(2026, 3, 14), today=fixed)
    assert (st.as_of, st.today, st.mode, st.is_historical) == (date(2026, 3, 14), fixed, "historical", True)
    st = ST.resolve(None, today=fixed)
    assert (st.as_of, st.today, st.mode) == (fixed, fixed, "current")
    st = ST.resolve("2025-12-31", today=fixed)
    assert st.as_of == date(2025, 12, 31) and st.mode == "historical"


@pytest.mark.parametrize("raw", [d(1), d(1).isoformat(), d(365), d(365).isoformat(), "2999-01-01"])
def test_resolve_future_is_as_of_in_future_422(raw):
    with pytest.raises(ServiceError) as ei:
        stichtag().resolve(raw)
    assert ei.value.code == "as_of_in_future" and ei.value.status == 422


def test_resolve_future_relative_to_explicit_today():
    with pytest.raises(ServiceError) as ei:
        stichtag().resolve("2026-03-16", today=date(2026, 3, 15))
    assert ei.value.code == "as_of_in_future" and ei.value.status == 422


@pytest.mark.parametrize("raw", ["gestern", "2026-13-40", "31.12.2025", "2026-02-30", "abc-de-fg"])
def test_resolve_invalid_format_is_invalid_as_of_422(raw):
    with pytest.raises(ServiceError) as ei:
        stichtag().resolve(raw)
    assert ei.value.code == "invalid_as_of" and ei.value.status == 422


def test_meta_current_and_historical_shape():
    ST = stichtag()
    cur = ST.meta("charges", ST.resolve(None))
    assert cur["view"] == "charges" and cur["mode"] == "current" and cur["as_of"] == TODAY.isoformat()
    assert isinstance(cur["historical_supported"], bool)
    hist = ST.meta("charges", ST.resolve(d(-30)))
    assert hist["view"] == "charges" and hist["mode"] == "historical" and hist["as_of"] == iso(-30)
    assert isinstance(hist["historical_supported"], bool)
    for m in (cur, hist):
        assert "limitations" not in m or (isinstance(m["limitations"], list) and all(isinstance(x, str) for x in m["limitations"]))


def test_meta_uses_given_view_name():
    ST = stichtag()
    for view in ("dunning", "dashboard", "tenants"):
        assert ST.meta(view, ST.resolve(None))["view"] == view


def test_meta_limitations_are_passed_through():
    """Annahme: meta(view, st, limitations=[...]) und meta(..., historical_supported=...) als Schlüsselwortargumente."""
    ST = stichtag()
    m = ST.meta("economics", ST.resolve(None), limitations=["Hinweis A", "Hinweis B"])
    assert m["limitations"] == ["Hinweis A", "Hinweis B"]


def test_meta_historical_supported_keyword():
    ST = stichtag()
    assert ST.meta("x", ST.resolve(None), historical_supported=False)["historical_supported"] is False
    assert ST.meta("x", ST.resolve(None), historical_supported=True)["historical_supported"] is True


# ---------------------------------------------------------------------------------------------------------------------------------
# A) KPI overdue_receivables
# ---------------------------------------------------------------------------------------------------------------------------------
def test_overdue_receivables_kpi_metadata(world, auth_client):
    k = kpis(auth_client)["overdue_receivables"]
    assert k["format"] == "eur" and k["available"] is True and k["historical_supported"] is True
    assert isinstance(k["definition"], str) and len(k["definition"]) > 20
    assert k["value"] == "0.00"
    assert kpis(auth_client, as_of=iso(-10))["overdue_receivables"]["historical_supported"] is True


def test_overdue_receivables_empty_database(auth_client):
    assert val(auth_client, "overdue_receivables") == "0.00" and val(auth_client, "open_receivables") == "0.00"


def test_not_yet_due_charge_counts_open_not_overdue(fin, auth_client):
    fin.charge("300.00", d(10))
    put(fin)
    assert val(auth_client, "open_receivables") == "300.00"
    assert val(auth_client, "overdue_receivables") == "0.00"
    assert val(auth_client, "overdue_payments") == 0


def test_due_today_is_not_overdue(fin, auth_client):
    fin.charge("120.00", TODAY)
    put(fin)
    assert val(auth_client, "open_receivables") == "120.00" and val(auth_client, "overdue_receivables") == "0.00"


def test_due_yesterday_is_overdue(fin, auth_client):
    fin.charge("120.00", d(-1))
    put(fin)
    assert val(auth_client, "open_receivables") == "120.00" and val(auth_client, "overdue_receivables") == "120.00"
    assert val(auth_client, "overdue_payments") == 1


def test_overdue_unpaid_charge(fin, auth_client):
    fin.charge("600.00", d(-20))
    put(fin)
    assert val(auth_client, "open_receivables") == "600.00" and val(auth_client, "overdue_receivables") == "600.00"


def test_fully_paid_charge_not_overdue(fin, auth_client):
    c = fin.charge("600.00", d(-20))
    fin.pay("600.00", d(-10), (c, "600.00"))
    put(fin)
    assert val(auth_client, "open_receivables") == "0.00" and val(auth_client, "overdue_receivables") == "0.00"
    assert val(auth_client, "overdue_payments") == 0


def test_partial_payment_remainder_is_overdue(fin, auth_client):
    c = fin.charge("600.00", d(-20))
    fin.pay("250.00", d(-10), (c, "250.00"))
    put(fin)
    assert val(auth_client, "open_receivables") == "350.00" and val(auth_client, "overdue_receivables") == "350.00"
    assert val(auth_client, "overdue_payments") == 1


def test_mixed_charges_open_vs_overdue(fin, auth_client):
    """A 600 fällig -20 (250 gezahlt) -> offen 350, überfällig | B 300 fällig +10 -> offen, nicht überfällig | C 120 fällig heute -> offen, nicht überfällig
    offen = 350 + 300 + 120 = 770, überfällig = 350, Anzahl überfällig 1."""
    a = fin.charge("600.00", d(-20))
    fin.charge("300.00", d(10))
    fin.charge("120.00", TODAY)
    fin.pay("250.00", d(-10), (a, "250.00"))
    put(fin)
    assert val(auth_client, "open_receivables") == "770.00"
    assert val(auth_client, "overdue_receivables") == "350.00"
    assert val(auth_client, "overdue_payments") == 1


def test_future_payment_does_not_reduce_overdue_today(fin, auth_client):
    """Eigentümerbeispiel 600/500/100: 500 heute gebucht, 100 mit Buchungsdatum +5 -> heute offen 100, überfällig 100."""
    c = fin.charge("600.00", d(-20))
    fin.pay("500.00", TODAY, (c, "500.00"))
    fin.pay("100.00", d(5), (c, "100.00"))
    put(fin)
    assert val(auth_client, "open_receivables") == "100.00"
    assert val(auth_client, "overdue_receivables") == "100.00"
    assert val(auth_client, "overdue_payments") == 1


# Szenario aus Handrechnung: 800 fällig -40; Zahlungen 200 (-30), 300 (-20), 100 (-10); zusätzlich 100 fällig -5 (unbezahlt).
#   Stichtag -45: offen 900 (800 + 100), überfällig 0 (Fälligkeiten -40/-5 nicht < -45)
#   -41: 900 / 0 | -40: 900 / 0 (Fälligkeit am Stichtag nicht überfällig) | -39: 900 / 800 | -30: 700 / 600 | -20: 400 / 300
#   -10: 300 / 200 | -6: 300 / 200 | -5: 300 / 200 (100 fällig am Stichtag zählt nicht) | -4: 300 / 300 | heute: 300 / 300
@pytest.mark.parametrize("off,open_total,overdue_amount,overdue_count", [
    (-45, "900.00", "0.00", 0), (-41, "900.00", "0.00", 0), (-40, "900.00", "0.00", 0), (-39, "900.00", "800.00", 1),
    (-31, "900.00", "800.00", 1), (-30, "700.00", "600.00", 1), (-20, "400.00", "300.00", 1), (-10, "300.00", "200.00", 1),
    (-6, "300.00", "200.00", 1), (-5, "300.00", "200.00", 1), (-4, "300.00", "300.00", 2), (0, "300.00", "300.00", 2),
])
def test_multiple_payments_overdue_per_as_of(fin, auth_client, off, open_total, overdue_amount, overdue_count):
    c = fin.charge("800.00", d(-40))
    fin.charge("100.00", d(-5))
    fin.pay("200.00", d(-30), (c, "200.00"))
    fin.pay("300.00", d(-20), (c, "300.00"))
    fin.pay("100.00", d(-10), (c, "100.00"))
    put(fin)
    k = kpis(auth_client, as_of=iso(off))
    assert k["open_receivables"]["value"] == open_total
    assert k["overdue_receivables"]["value"] == overdue_amount
    assert k["overdue_payments"]["value"] == overdue_count
    assert D(k["overdue_receivables"]["value"]) <= D(k["open_receivables"]["value"])  # Invariante


def test_historical_split_open_vs_overdue_two_charges(fin, auth_client):
    """Charge a 600 fällig -50, Charge b 100 fällig -5, keine Zahlung. Stichtag -20: offen 700, überfällig 600 (b erst ab -4 überfällig)."""
    fin.charge("600.00", d(-50))
    fin.charge("100.00", d(-5))
    put(fin)
    k = kpis(auth_client, as_of=iso(-20))
    assert k["open_receivables"]["value"] == "700.00" and k["overdue_receivables"]["value"] == "600.00"
    k = kpis(auth_client, as_of=iso(-60))
    assert k["open_receivables"]["value"] == "700.00" and k["overdue_receivables"]["value"] == "0.00"


def test_reversal_between_as_of_overdue(fin, auth_client):
    """Zahlung 600 (-10), Gegenbuchung heute. Stichtag -5: bezahlt -> 0/0; heute: wieder offen und überfällig (Fälligkeit -30)."""
    c = fin.charge("600.00", d(-30))
    p = fin.pay("600.00", d(-10), (c, "600.00"))
    P.reverse_payment(fin.w.db, None, p.id, reason="Fehlbuchung", booking_date=TODAY)
    put(fin)
    k = kpis(auth_client, as_of=iso(-5))
    assert k["open_receivables"]["value"] == "0.00" and k["overdue_receivables"]["value"] == "0.00"
    k = kpis(auth_client)
    assert k["open_receivables"]["value"] == "600.00" and k["overdue_receivables"]["value"] == "600.00"
    k = kpis(auth_client, as_of=iso(-11))
    assert k["open_receivables"]["value"] == "600.00" and k["overdue_receivables"]["value"] == "600.00"


def test_voided_and_payable_not_in_overdue_receivables(world, fin, auth_client):
    gone = fin.charge("400.00", d(-20))
    fin.charge("100.00", d(-20))
    C.void_charge(world.db, None, gone.id, "Fehlerhaft angelegt")
    main = next(x for x in world.db.query(L.Lease).all() if x.kind == "main")
    C.create_manual_charge(world.db, None, lease_id=main.id, amount=D("700.00"), due_date=d(-5), period_start=d(-5), period_end=d(24), note="Hauptmiete")
    put(fin)
    assert val(auth_client, "open_receivables") == "100.00" and val(auth_client, "overdue_receivables") == "100.00"


def test_overdue_receivables_never_exceeds_open_receivables(fin, auth_client):
    a = fin.charge("500.00", d(-60))
    fin.charge("250.00", d(-1))
    fin.charge("80.00", d(3))
    fin.pay("200.00", d(-30), (a, "200.00"))
    fin.pay("50.00", d(2), (a, "50.00"))
    put(fin)
    for off in (-70, -61, -59, -30, -2, 0):
        k = kpis(auth_client, as_of=iso(off))
        assert D(k["overdue_receivables"]["value"]) <= D(k["open_receivables"]["value"]), off


# ---------------------------------------------------------------------------------------------------------------------------------
# A) Vertragsenden getrennt: Haupt-/Untermietverträge
# ---------------------------------------------------------------------------------------------------------------------------------
END_KEYS = ("upcoming_main_lease_ends", "upcoming_sublease_ends", "upcoming_contract_ends")


def ends(client, **params):
    k = kpis(client, **params)
    return k["upcoming_main_lease_ends"]["value"], k["upcoming_sublease_ends"]["value"], k["upcoming_contract_ends"]["value"]


def test_new_contract_end_kpis_metadata(world, auth_client):
    k = kpis(auth_client)
    for key in ("upcoming_main_lease_ends", "upcoming_sublease_ends"):
        assert key in k, key
        assert k[key]["available"] is True and k[key]["historical_supported"] is True
        assert isinstance(k[key]["definition"], str) and len(k[key]["definition"]) > 20
        assert isinstance(k[key]["value"], int)
    assert k["upcoming_contract_ends"]["historical_supported"] is True


def test_main_and_sub_ends_are_counted_separately_and_summed(bare, auth_client):
    w = bare
    w.activate_main(end=d(30))
    end_lease(w, d(20), unit="room1")
    end_lease(w, d(25), unit="room2")
    w.db.commit()
    assert ends(auth_client) == (1, 2, 3)


def test_only_sublease_end_counts_for_sub(world, auth_client):
    end_lease(world, d(40))
    world.db.commit()
    assert ends(auth_client) == (0, 1, 1)  # Hauptvertrag der Testwelt hat offenes Ende


def test_only_main_end_counts_for_main(bare, auth_client):
    bare.activate_main(end=d(60))
    bare.db.commit()
    assert ends(auth_client) == (1, 0, 1)


@pytest.mark.parametrize("off,count", [(0, 1), (1, 1), (89, 1), (90, 1), (91, 0), (-1, 0), (365, 0)])
def test_main_end_boundaries_default_90(bare, auth_client, off, count):
    bare.activate_main(start=d(-250), end=d(off))
    bare.db.commit()
    assert ends(auth_client) == (count, 0, count)


@pytest.mark.parametrize("off,count", [(0, 1), (1, 1), (89, 1), (90, 1), (91, 0), (-1, 0), (365, 0)])
def test_sub_end_boundaries_default_90(world, auth_client, off, count):
    end_lease(world, d(off))
    world.db.commit()
    assert ends(auth_client) == (0, count, count)


def test_excluded_main_cases_open_end_not_started_expired(bare, auth_client):
    """Offenes Ende, noch nicht begonnen, abgelaufen zählen nicht (Haupt)."""
    bare.activate_main()  # offen
    bare.db.commit()
    assert ends(auth_client) == (0, 0, 0)


def test_main_future_start_does_not_count(bare, auth_client):
    bare.activate_main(start=d(10), end=d(60))
    bare.db.commit()
    assert ends(auth_client) == (0, 0, 0)


def test_main_expired_does_not_count(bare, auth_client):
    bare.activate_main(start=d(-250), end=d(-100))
    bare.db.commit()
    assert ends(auth_client) == (0, 0, 0)


def test_sub_excluded_cases_open_future_expired_draft(world, auth_client):
    end_lease(world, None, unit="room1")                      # offenes Ende
    end_lease(world, d(60), start=d(10), unit="room2")        # nicht begonnen
    end_lease(world, d(30), unit="we2", activate=False)       # Entwurf
    world.db.commit()
    assert ends(auth_client) == (0, 0, 0)


def test_sub_expired_does_not_count(world, auth_client):
    end_lease(world, d(-10), start=d(-100))
    world.db.commit()
    assert ends(auth_client) == (0, 0, 0)


def test_terminated_sub_counts_with_effective_end(world, auth_client):
    lease = end_lease(world, None)
    L.terminate_lease(world.db, None, lease.id, terminated_on=d(-5), effective_on=d(25))
    world.db.commit()
    assert ends(auth_client) == (0, 1, 1)


@pytest.mark.parametrize("days,main_off,sub_off,exp_main,exp_sub", [
    (30, 30, 25, 1, 1), (30, 31, 31, 0, 0), (30, 60, 30, 0, 1), (30, 31, 30, 0, 1),
    (180, 180, 150, 1, 1), (180, 181, 181, 0, 0), (180, 200, 180, 0, 1), (180, 181, 180, 0, 1),
])
def test_configured_preview_days_for_main_and_sub(tmp_path, days, main_off, sub_off, exp_main, exp_sub):
    """Einstellung contract_end_preview_days (30/180) gilt für beide Vertragsarten, beide Grenzen inklusiv."""
    app, c = make_client(tmp_path, days)
    try:
        w = World(app)
        w.activate_main(end=d(main_off))
        end_lease(w, d(sub_off))
        w.db.commit()
        assert ends(c) == (exp_main, exp_sub, exp_main + exp_sub)
        w.db.close()
    finally:
        c.__exit__(None, None, None)


def test_contract_end_kpis_historical_as_of_split(bare, auth_client):
    """Hauptvertrag -250..-100, Untermietvertrag -240..-120 (Vorschau 90 Tage).
    Stichtag -150: Haupt Ende in 50 Tagen -> 1; Sub Ende in 30 Tagen -> 1; gesamt 2.
    Stichtag -121: Sub endet morgen -> 1; Haupt -> 1.  Stichtag -119: Sub beendet (läuft nicht) -> 0; Haupt Ende in 19 Tagen -> 1.
    Stichtag -191: Haupt Ende in 91 Tagen -> 0; Sub Ende in 71 Tagen -> 1 (Sub läuft ab -240).  Heute: beide beendet -> 0/0."""
    w = bare
    w.activate_main(start=d(-250), end=d(-100))
    end_lease(w, d(-120), start=d(-240))
    w.db.commit()
    assert ends(auth_client, as_of=iso(-150)) == (1, 1, 2)
    assert ends(auth_client, as_of=iso(-121)) == (1, 1, 2)
    assert ends(auth_client, as_of=iso(-119)) == (1, 0, 1)
    assert ends(auth_client, as_of=iso(-191)) == (0, 1, 1)
    assert ends(auth_client) == (0, 0, 0)


def test_contract_end_total_equals_sum_over_many_as_of(bare, auth_client):
    w = bare
    w.activate_main(start=d(-250), end=d(40))
    end_lease(w, d(-20), start=d(-240), unit="room1")
    end_lease(w, d(35), start=d(-30), unit="room2")
    w.db.commit()
    for off in (-260, -200, -100, -25, -10, -1, 0):  # kein Zukunftsstichtag (würde 422 liefern, siehe Stichtag-Entscheidung)
        m, s, t = ends(auth_client, as_of=iso(off))
        assert t == m + s, off


# ---------------------------------------------------------------------------------------------------------------------------------
# C) Zahlungen wirken erst ab Buchungsdatum – GET /charges
# ---------------------------------------------------------------------------------------------------------------------------------
def test_charges_list_future_payment_does_not_reduce_today(fin, auth_client):
    c = fin.charge("600.00", d(-20))
    fin.pay("600.00", d(3), (c, "600.00"))
    put(fin)
    row = charge_row(auth_client, c.id)
    assert row["open_amount"] == "600.00" and row["status"] == "open"


def test_charges_list_partial_with_future_remainder(fin, auth_client):
    c = fin.charge("600.00", d(-20))
    fin.pay("500.00", TODAY, (c, "500.00"))
    fin.pay("100.00", d(5), (c, "100.00"))
    put(fin)
    row = charge_row(auth_client, c.id)
    assert row["open_amount"] == "100.00" and row["status"] == "partial"


def test_charges_list_past_payment_is_paid_and_partial_is_partial(fin, auth_client):
    a = fin.charge("600.00", d(-20))
    b = fin.charge("400.00", d(-20))
    fin.pay("600.00", d(-10), (a, "600.00"))
    fin.pay("150.00", d(-10), (b, "150.00"))
    put(fin)
    ra, rb = charge_row(auth_client, a.id), charge_row(auth_client, b.id)
    assert (ra["open_amount"], ra["status"]) == ("0.00", "paid")
    assert (rb["open_amount"], rb["status"]) == ("250.00", "partial")


def test_charges_list_not_due_charge_is_open(fin, auth_client):
    c = fin.charge("300.00", d(10))
    put(fin)
    row = charge_row(auth_client, c.id)
    assert row["open_amount"] == "300.00" and row["status"] == "open"


@pytest.mark.parametrize("off,open_amount,status", [(-11, "600.00", "open"), (-10, "0.00", "paid"), (-9, "0.00", "paid"), (0, "0.00", "paid")])
def test_charges_list_historical_as_of_around_booking_day(fin, auth_client, off, open_amount, status):
    c = fin.charge("600.00", d(-40))
    fin.pay("600.00", d(-10), (c, "600.00"))
    put(fin)
    row = charge_row(auth_client, c.id, as_of=iso(off))
    assert (row["open_amount"], row["status"]) == (open_amount, status)


def test_charges_list_multiple_payments_each_as_of(fin, auth_client):
    """800 fällig -40; 200 (-30), 300 (-20), 100 (-10). Offen: -31: 800 | -30: 600 | -20: 300 | -10: 200."""
    c = fin.charge("800.00", d(-40))
    fin.pay("200.00", d(-30), (c, "200.00"))
    fin.pay("300.00", d(-20), (c, "300.00"))
    fin.pay("100.00", d(-10), (c, "100.00"))
    put(fin)
    for off, exp, status in ((-31, "800.00", "open"), (-30, "600.00", "partial"), (-20, "300.00", "partial"), (-10, "200.00", "partial")):
        row = charge_row(auth_client, c.id, as_of=iso(off))
        assert (row["open_amount"], row["status"]) == (exp, status), off


def test_charges_list_reversal_between_as_of(fin, auth_client):
    """Zahlung 600 bei -10, Gegenbuchung heute: Stichtag -5 bezahlt, heute wieder offen."""
    c = fin.charge("600.00", d(-30))
    p = fin.pay("600.00", d(-10), (c, "600.00"))
    P.reverse_payment(fin.w.db, None, p.id, reason="Fehlbuchung", booking_date=TODAY)
    put(fin)
    mid = charge_row(auth_client, c.id, as_of=iso(-5))
    assert (mid["open_amount"], mid["status"]) == ("0.00", "paid")
    now = charge_row(auth_client, c.id)
    assert now["open_amount"] == "600.00"
    assert charge_row(auth_client, c.id, as_of=iso(-11))["open_amount"] == "600.00"


def test_charges_list_overdue_filter_includes_charge_with_only_future_payment(fin, auth_client):
    c = fin.charge("600.00", d(-20))
    fin.pay("600.00", d(3), (c, "600.00"))
    put(fin)
    ids = [r["id"] for r in get_ok(auth_client, "/charges", status="overdue")["items"]]
    assert c.id in ids


def test_charges_list_stichtag_block_current_and_historical(fin, auth_client):
    fin.charge("100.00", d(-5))
    put(fin)
    cur = get_ok(auth_client, "/charges")["stichtag"]
    assert cur["view"] == "charges" and cur["mode"] == "current" and cur["as_of"] == TODAY.isoformat() and isinstance(cur["historical_supported"], bool)
    same = get_ok(auth_client, "/charges", as_of=TODAY.isoformat())["stichtag"]
    assert same["mode"] == "current" and same["as_of"] == TODAY.isoformat()
    hist = get_ok(auth_client, "/charges", as_of=iso(-7))["stichtag"]
    assert hist["view"] == "charges" and hist["mode"] == "historical" and hist["as_of"] == iso(-7)


def test_charges_list_future_as_of_is_422(auth_client):
    for off in (1, 365):
        r = auth_client.get(V + "/charges", params={"as_of": iso(off)})
        assert r.status_code == 422 and code_of(r) == "as_of_in_future"


@pytest.mark.parametrize("raw", ["gestern", "2026-13-40", "31.12.2025"])
def test_charges_list_invalid_as_of_is_422(auth_client, raw):
    r = auth_client.get(V + "/charges", params={"as_of": raw})
    assert r.status_code == 422 and code_of(r) == "invalid_as_of"


def test_charges_list_requires_login(client):
    assert client.get(V + "/charges", params={"as_of": TODAY.isoformat()}).status_code == 401


# ---------------------------------------------------------------------------------------------------------------------------------
# C) GET /payments – is_future_dated
# ---------------------------------------------------------------------------------------------------------------------------------
def test_payments_list_is_future_dated_flag(fin, auth_client):
    c = fin.charge("300.00", d(-20))
    past = fin.pay("100.00", d(-1), (c, "100.00"))
    now = fin.pay("100.00", TODAY, (c, "100.00"))
    future = fin.pay("100.00", d(1), (c, "100.00"))
    put(fin)
    rows = {p["id"]: p for p in get_ok(auth_client, "/payments")["items"]}
    assert rows[past.id]["is_future_dated"] is False
    assert rows[now.id]["is_future_dated"] is False
    assert rows[future.id]["is_future_dated"] is True
    assert all(isinstance(p["is_future_dated"], bool) for p in rows.values())


def test_payments_list_is_future_dated_for_reversal_booking(fin, auth_client):
    c = fin.charge("300.00", d(-20))
    p = fin.pay("100.00", d(-3), (c, "100.00"))
    rev = P.reverse_payment(fin.w.db, None, p.id, reason="Fehlbuchung", booking_date=d(2))
    put(fin)
    rows = {x["id"]: x for x in get_ok(auth_client, "/payments")["items"]}
    assert rows[p.id]["is_future_dated"] is False and rows[rev.id]["is_future_dated"] is True


# ---------------------------------------------------------------------------------------------------------------------------------
# C) GET /dunning/overdue
# ---------------------------------------------------------------------------------------------------------------------------------
def test_dunning_overdue_future_payment_does_not_reduce_today(fin, auth_client):
    c = fin.charge("600.00", d(-20))
    fin.pay("600.00", d(3), (c, "600.00"))
    put(fin)
    items = {i["charge_id"]: i for i in overdue_items(auth_client)}
    assert c.id in items and items[c.id]["open_amount"] == "600.00"


def test_dunning_overdue_partial_with_future_remainder(fin, auth_client):
    c = fin.charge("600.00", d(-20))
    fin.pay("500.00", TODAY, (c, "500.00"))
    fin.pay("100.00", d(5), (c, "100.00"))
    put(fin)
    items = {i["charge_id"]: i for i in overdue_items(auth_client)}
    assert items[c.id]["open_amount"] == "100.00"
    body = get_ok(auth_client, "/dunning/overdue")
    assert body["summary"]["by_state"]["due"]["open_amount"] == "100.00"


def test_dunning_overdue_fully_paid_in_past_and_not_due_are_absent(fin, auth_client):
    paid = fin.charge("600.00", d(-20))
    fin.pay("600.00", d(-10), (paid, "600.00"))
    not_due = fin.charge("300.00", d(10))
    put(fin)
    ids = {i["charge_id"] for i in overdue_items(auth_client)}
    assert paid.id not in ids and not_due.id not in ids


@pytest.mark.parametrize("off,present,amount", [(-11, True, "600.00"), (-10, False, None), (-5, False, None), (0, False, None)])
def test_dunning_overdue_historical_as_of(fin, auth_client, off, present, amount):
    c = fin.charge("600.00", d(-40))
    fin.pay("600.00", d(-10), (c, "600.00"))
    put(fin)
    items = {i["charge_id"]: i for i in overdue_items(auth_client, as_of=iso(off))}
    assert (c.id in items) is present
    if present:
        assert items[c.id]["open_amount"] == amount and items[c.id]["days_overdue"] == (d(off) - d(-40)).days


def test_dunning_overdue_reversal_between_as_of(fin, auth_client):
    c = fin.charge("600.00", d(-30))
    p = fin.pay("600.00", d(-10), (c, "600.00"))
    P.reverse_payment(fin.w.db, None, p.id, reason="Fehlbuchung", booking_date=TODAY)
    put(fin)
    assert c.id not in {i["charge_id"] for i in overdue_items(auth_client, as_of=iso(-5))}
    now = {i["charge_id"]: i for i in overdue_items(auth_client)}
    assert now[c.id]["open_amount"] == "600.00"


def test_dunning_overdue_stichtag_block(fin, auth_client):
    fin.charge("100.00", d(-5))
    put(fin)
    cur = get_ok(auth_client, "/dunning/overdue")["stichtag"]
    assert cur["mode"] == "current" and cur["as_of"] == TODAY.isoformat() and isinstance(cur["view"], str) and cur["view"]
    assert isinstance(cur["historical_supported"], bool)
    hist = get_ok(auth_client, "/dunning/overdue", as_of=iso(-3))["stichtag"]
    assert hist["mode"] == "historical" and hist["as_of"] == iso(-3)


def test_dunning_overdue_future_as_of_is_422(auth_client):
    r = auth_client.get(V + "/dunning/overdue", params={"as_of": iso(1)})
    assert r.status_code == 422 and code_of(r) == "as_of_in_future"
    assert auth_client.get(V + "/dunning/overdue", params={"as_of": iso(365)}).status_code == 422


def test_dunning_overdue_invalid_as_of_is_422(auth_client):
    assert auth_client.get(V + "/dunning/overdue", params={"as_of": "gestern"}).status_code == 422


# ---------------------------------------------------------------------------------------------------------------------------------
# C) Mahnentwürfe
# ---------------------------------------------------------------------------------------------------------------------------------
def test_dunning_draft_total_ignores_future_payment(fin):
    c = fin.charge("600.00", d(-20))
    fin.pay("600.00", d(3), (c, "600.00"))
    put(fin)
    notices = DN.prepare_notices(fin.w.db, None)
    assert len(notices) == 1
    n = notices[0]
    assert n.total_open == D("600.00") and [ln.open_amount for ln in n.lines] == [D("600.00")]


def test_dunning_draft_total_partial_with_future_remainder(fin):
    c = fin.charge("600.00", d(-20))
    fin.pay("500.00", TODAY, (c, "500.00"))
    fin.pay("100.00", d(5), (c, "100.00"))
    put(fin)
    notices = DN.prepare_notices(fin.w.db, None)
    assert len(notices) == 1 and notices[0].total_open == D("100.00")
    assert [ln.open_amount for ln in notices[0].lines] == [D("100.00")]


def test_dunning_draft_with_future_payment_can_be_approved_not_stale(fin):
    """Konsequenz aus C: die Freigabeprüfung (veraltet?) rechnet mit demselben heutigen Stichtag wie die Erstellung, sonst wäre jeder Entwurf mit Zukunftszahlung sofort 'stale'."""
    c = fin.charge("600.00", d(-20))
    fin.pay("600.00", d(3), (c, "600.00"))
    put(fin)
    n = DN.prepare_notices(fin.w.db, None)[0]
    DN.update_draft(fin.w.db, None, n.id, body=n.body.replace("[Frist eintragen]", "01.01.2030"))
    approved = DN.approve(fin.w.db, None, n.id)
    assert approved.status == "approved"


def test_dunning_draft_none_when_paid_in_past(fin):
    c = fin.charge("600.00", d(-20))
    fin.pay("600.00", d(-1), (c, "600.00"))
    put(fin)
    assert DN.prepare_notices(fin.w.db, None) == []


# ---------------------------------------------------------------------------------------------------------------------------------
# C) charges.arrears / arrears_bulk / GET /tenants
# ---------------------------------------------------------------------------------------------------------------------------------
def test_arrears_service_future_payment_does_not_reduce_today(fin):
    c = fin.charge("600.00", d(-20))
    fin.pay("600.00", d(3), (c, "600.00"))
    put(fin)
    for res in (C.arrears(fin.w.db, fin.lease.id), C.arrears_bulk(fin.w.db, [fin.lease.id])[fin.lease.id]):
        assert res["status"] == "arrears" and res["amount"] == D("600.00") and res["count"] == 1


def test_arrears_service_partial_with_future_remainder(fin):
    c = fin.charge("600.00", d(-20))
    fin.pay("500.00", TODAY, (c, "500.00"))
    fin.pay("100.00", d(5), (c, "100.00"))
    put(fin)
    for res in (C.arrears(fin.w.db, fin.lease.id), C.arrears_bulk(fin.w.db, [fin.lease.id])[fin.lease.id]):
        assert res["status"] == "arrears" and res["amount"] == D("100.00") and res["count"] == 1


def test_arrears_service_paid_and_not_due_are_current(fin):
    a = fin.charge("600.00", d(-20))
    fin.pay("600.00", d(-5), (a, "600.00"))
    fin.charge("300.00", d(10))
    put(fin)
    for res in (C.arrears(fin.w.db, fin.lease.id), C.arrears_bulk(fin.w.db, [fin.lease.id])[fin.lease.id]):
        assert res["status"] == "current" and res["amount"] == D("0.00") and res["count"] == 0


def test_tenants_payment_status_and_overdue_amount_future_payment(fin, auth_client):
    c = fin.charge("600.00", d(-20))
    fin.pay("500.00", TODAY, (c, "500.00"))
    fin.pay("100.00", d(5), (c, "100.00"))
    put(fin)
    rows = [r for r in get_ok(auth_client, "/tenants")["items"] if r.get("lease_id") == fin.lease.id]
    assert len(rows) == 1 and rows[0]["payment_status"] == "arrears" and rows[0]["overdue_amount"] == "100.00"
    only = get_ok(auth_client, "/tenants", status="arrears")["items"]
    assert fin.lease.id in {r["lease_id"] for r in only}


def test_tenants_future_payment_fully_covering_still_arrears_today(fin, auth_client):
    c = fin.charge("600.00", d(-20))
    fin.pay("600.00", d(3), (c, "600.00"))
    put(fin)
    row = next(r for r in get_ok(auth_client, "/tenants")["items"] if r.get("lease_id") == fin.lease.id)
    assert row["payment_status"] == "arrears" and row["overdue_amount"] == "600.00"


def test_tenants_current_when_paid_in_past(fin, auth_client):
    c = fin.charge("600.00", d(-20))
    fin.pay("600.00", d(-2), (c, "600.00"))
    put(fin)
    row = next(r for r in get_ok(auth_client, "/tenants")["items"] if r.get("lease_id") == fin.lease.id)
    assert row["payment_status"] == "current" and row["overdue_amount"] == "0.00"


# ---------------------------------------------------------------------------------------------------------------------------------
# C) Ausnahme: payments.allocate zählt ALLE bestehenden Zuordnungen (kein Doppel-Zuordnen)
# ---------------------------------------------------------------------------------------------------------------------------------
def test_allocate_still_counts_future_dated_allocations_exceeds_open(fin):
    c = fin.charge("100.00", d(-20))
    fin.pay("100.00", d(5), (c, "100.00"))        # Zukunftszahlung, bereits voll zugeordnet
    other = fin.pay("50.00", TODAY)               # heute gebuchte, noch unzugeordnete Zahlung
    put(fin)
    with pytest.raises(ServiceError) as ei:
        P.allocate(fin.w.db, None, other.id, charge_id=c.id, amount=D("10.00"))
    assert ei.value.code == "exceeds_open" and ei.value.status == 409
    fin.w.db.rollback()
    assert C.allocated(fin.w.db, c.id) == D("100.00")  # keine zweite Zuordnung entstanden
    assert P.unallocated(fin.w.db, fin.w.db.get(type(other), other.id)) == D("50.00")


def test_allocate_remaining_amount_boundary_with_future_allocation(fin):
    """Forderung 100; zukünftige Zahlung ordnet 60 zu; heutige Zahlung darf genau 40 zuordnen, nicht 41."""
    c = fin.charge("100.00", d(-20))
    fin.pay("60.00", d(5), (c, "60.00"))
    other = fin.pay("100.00", TODAY)
    put(fin)
    with pytest.raises(ServiceError) as ei:
        P.allocate(fin.w.db, None, other.id, charge_id=c.id, amount=D("40.01"))
    assert ei.value.code == "exceeds_open" and ei.value.status == 409
    fin.w.db.rollback()
    P.allocate(fin.w.db, None, other.id, charge_id=c.id, amount=D("40.00"))
    put(fin)
    assert C.allocated(fin.w.db, c.id) == D("100.00")
    with pytest.raises(ServiceError) as ei2:
        P.allocate(fin.w.db, None, other.id, charge_id=c.id, amount=D("0.01"))
    assert ei2.value.code == "exceeds_open"


def test_create_payment_with_allocation_over_remaining_with_future_allocation_rejected(fin):
    c = fin.charge("100.00", d(-20))
    fin.pay("100.00", d(5), (c, "100.00"))
    put(fin)
    with pytest.raises(ServiceError) as ei:
        fin.pay("30.00", TODAY, (c, "30.00"))
    assert ei.value.code == "exceeds_open"
    fin.w.db.rollback()


def test_allocate_api_exceeds_open_409_with_future_allocation(fin, auth_client):
    c = fin.charge("100.00", d(-20))
    fin.pay("100.00", d(5), (c, "100.00"))
    other = fin.pay("50.00", TODAY)
    put(fin)
    r = auth_client.post(V + f"/payments/{other.id}/allocations", json={"charge_id": c.id, "amount": "10.00"})
    assert r.status_code == 409 and code_of(r) == "exceeds_open"


# ---------------------------------------------------------------------------------------------------------------------------------
# C) Bankimport-Vorschläge
# ---------------------------------------------------------------------------------------------------------------------------------
BANK_HEAD = "Buchungstag;Valuta;Name Zahlungsbeteiligter;IBAN Zahlungsbeteiligter;Verwendungszweck;Betrag;Währung\n"


def test_bank_suggestion_ignores_future_dated_payment(app, world):
    from sqlalchemy import select
    from leventum.models import BankTransaction
    from leventum.services import bank as B
    fin = Fin(world, name="Max Mustermann")
    M.update_party(world.db, None, fin.tenant.id, {"iban": TENANT_IBAN})
    c = fin.charge("600.00", d(-20))
    fin.pay("600.00", d(3), (c, "600.00"))  # heute noch nicht wirksam
    acc = B.create_account(world.db, None, "Geschäftskonto", "DE00 1234")
    row = f"{TODAY.strftime('%d.%m.%Y')};{TODAY.strftime('%d.%m.%Y')};Max Mustermann;DE89 3704 0044 0532 0130 00;Miete;600,00;EUR"
    B.import_statement(world.db, None, acc.id, "x.csv", (BANK_HEAD + row + "\n").encode())
    world.db.commit()
    world.db.expire_all()
    t = world.db.scalars(select(BankTransaction)).one()
    suggestions = B.suggest(world.db, t)
    charge_sugs = [s for s in suggestions if s["kind"] == "charges" and s["lease_id"] == fin.lease.id]
    assert charge_sugs, suggestions
    allocs = charge_sugs[0]["allocations"]
    assert [(a["charge_id"], a["amount"]) for a in allocs] == [(c.id, D("600.00"))]
    assert allocs[0]["open_before"] == D("600.00")


# ---------------------------------------------------------------------------------------------------------------------------------
# C) GET /economics – Block 'stichtag'
# ---------------------------------------------------------------------------------------------------------------------------------
def _month_first(y, m):
    return date(y + (m - 1) // 12, (m - 1) % 12 + 1, 1)


def _month_last(y, m):
    return _month_first(y, m + 1) - timedelta(days=1)


def test_economics_stichtag_block_period_in_past(world, auth_client):
    """Zeitraum = ganze Kalendermonate (Vorgabe des Endpunkts): drei Monate vor dem letzten abgeschlossenen Monat bis zu dessen Ende."""
    end = _month_first(TODAY.year, TODAY.month) - timedelta(days=1)          # Ende des Vormonats (< heute)
    start = _month_first(TODAY.year, TODAY.month - 3)
    body = get_ok(auth_client, "/economics", start=start.isoformat(), end=end.isoformat())
    st = body["stichtag"]
    assert st["mode"] == "datenstand" and st["as_of"] == end.isoformat() and isinstance(st["view"], str) and st["view"]
    assert st["historical_supported"] is True
    assert isinstance(st["limitations"], list) and len(st["limitations"]) > 0 and all(isinstance(x, str) and x for x in st["limitations"])
    assert body["datenstand"]["data_as_of"] == end.isoformat()
    assert body["prognose_periodenende"] is None


def test_economics_stichtag_block_period_beyond_today_is_capped_at_today(world, auth_client):
    start = _month_first(TODAY.year, TODAY.month)
    end = _month_last(TODAY.year, TODAY.month + 1)                              # Ende des Folgemonats (> heute)
    body = get_ok(auth_client, "/economics", start=start.isoformat(), end=end.isoformat())
    st = body["stichtag"]
    assert st["mode"] == "datenstand" and st["as_of"] == TODAY.isoformat() == body["datenstand"]["data_as_of"]
    assert st["historical_supported"] is True and len(st["limitations"]) > 0
    # reine Prognose bleibt im eigenen Feld, nicht im Stichtag-Block
    assert body["prognose_periodenende"]["is_forecast"] is True and body["prognose_periodenende"]["as_of"] == end.isoformat()
    assert "prognose" not in " ".join(st.keys()).lower()


def test_economics_stichtag_block_current_month(world, auth_client):
    """Laufender Monat: Periodenende >= heute -> Datenstand = heute."""
    start, end = _month_first(TODAY.year, TODAY.month), _month_last(TODAY.year, TODAY.month)
    st = get_ok(auth_client, "/economics", start=start.isoformat(), end=end.isoformat())["stichtag"]
    assert st["mode"] == "datenstand" and st["as_of"] == TODAY.isoformat()


# ---------------------------------------------------------------------------------------------------------------------------------
# C) GET /dashboard – Block 'stichtag'
# ---------------------------------------------------------------------------------------------------------------------------------
def test_dashboard_stichtag_block_current(auth_client):
    st = dash(auth_client)["stichtag"]
    assert st["view"] == "dashboard" and st["mode"] == "current" and st["as_of"] == TODAY.isoformat()
    assert isinstance(st["historical_supported"], bool) and st["historical_available"] is True  # admin besitzt finance:read


def test_dashboard_stichtag_block_historical(auth_client):
    body = dash(auth_client, as_of=iso(-30))
    st = body["stichtag"]
    assert st["view"] == "dashboard" and st["mode"] == "historical" and st["as_of"] == iso(-30) == body["as_of"]
    assert isinstance(st["historical_supported"], bool) and st["historical_available"] is True


def test_dashboard_as_of_today_is_current_mode(auth_client):
    assert dash(auth_client, as_of=TODAY.isoformat())["stichtag"]["mode"] == "current"


def test_dashboard_as_of_errors_unchanged(auth_client):
    r = auth_client.get(V + "/dashboard", params={"as_of": iso(1)})
    assert r.status_code == 422 and code_of(r) == "as_of_in_future"
    r = auth_client.get(V + "/dashboard", params={"as_of": "gestern"})
    assert r.status_code == 422 and code_of(r) == "invalid_as_of"


# ---------------------------------------------------------------------------------------------------------------------------------
# Konsistenz über alle Ansichten (heute): Forderungsliste = Dashboard = Mahnwesen = Mieterübersicht
# ---------------------------------------------------------------------------------------------------------------------------------
def test_all_views_agree_today_with_future_payment(fin, auth_client):
    """A 600 fällig -20: 500 heute + 100 (+5) | B 300 fällig +10 | C 250 fällig -3 unbezahlt.
    offen: A 100 + B 300 + C 250 = 650 | überfällig: A 100 + C 250 = 350 | überfällige Positionen: 2."""
    a = fin.charge("600.00", d(-20))
    b = fin.charge("300.00", d(10))
    cc = fin.charge("250.00", d(-3))
    fin.pay("500.00", TODAY, (a, "500.00"))
    fin.pay("100.00", d(5), (a, "100.00"))
    put(fin)
    rows = {r["id"]: r for r in get_ok(auth_client, "/charges", lease_id=fin.lease.id)["items"]}
    assert (rows[a.id]["open_amount"], rows[b.id]["open_amount"], rows[cc.id]["open_amount"]) == ("100.00", "300.00", "250.00")
    k = kpis(auth_client)
    assert k["open_receivables"]["value"] == "650.00"
    assert k["overdue_receivables"]["value"] == "350.00" and k["overdue_payments"]["value"] == 2
    dun = get_ok(auth_client, "/dunning/overdue")
    assert {i["charge_id"]: i["open_amount"] for i in dun["items"]} == {a.id: "100.00", cc.id: "250.00"}
    row = next(r for r in get_ok(auth_client, "/tenants")["items"] if r.get("lease_id") == fin.lease.id)
    assert row["overdue_amount"] == "350.00" and row["payment_status"] == "arrears"
    # Gegenprobe Service
    pos = C.receivable_position(fin.w.db, TODAY)
    assert pos["open_total"] == D("650.00") and pos["overdue_count"] == 2


def test_all_views_agree_historical(fin, auth_client):
    """Stichtag -12: A 600 fällig -20 mit Zahlungen 200 (-15) und 400 (-5); B 300 fällig -30 unbezahlt.
    Am Stichtag -12: A offen 400 (nur 200 gebucht), B offen 300 -> offen 700, überfällig 700, Positionen 2."""
    a = fin.charge("600.00", d(-20))
    b = fin.charge("300.00", d(-30))
    fin.pay("200.00", d(-15), (a, "200.00"))
    fin.pay("400.00", d(-5), (a, "400.00"))
    put(fin)
    as_of = iso(-12)
    rows = {r["id"]: r for r in get_ok(auth_client, "/charges", lease_id=fin.lease.id, as_of=as_of)["items"]}
    assert (rows[a.id]["open_amount"], rows[b.id]["open_amount"]) == ("400.00", "300.00")
    assert rows[a.id]["status"] == "partial" and rows[b.id]["status"] == "open"
    k = kpis(auth_client, as_of=as_of)
    assert k["open_receivables"]["value"] == "700.00" and k["overdue_receivables"]["value"] == "700.00" and k["overdue_payments"]["value"] == 2
    dun = get_ok(auth_client, "/dunning/overdue", as_of=as_of)
    assert {i["charge_id"]: i["open_amount"] for i in dun["items"]} == {a.id: "400.00", b.id: "300.00"}


# ---------------------------------------------------------------------------------------------------------------------------------
# Review M2: POST /dunning/prepare lehnt Zukunfts-Stichtage ab (Ist-Auswertung, keine Prognose) und schreibt dabei nichts
# ---------------------------------------------------------------------------------------------------------------------------------
def test_dunning_prepare_future_as_of_is_422_and_writes_nothing(world, auth_client):
    r = auth_client.post(V + "/dunning/prepare", json={"as_of": iso(1)})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "as_of_in_future"
    assert auth_client.get(V + "/dunning/notices").json()["items"] == []


def test_dunning_prepare_today_and_past_still_allowed(world, auth_client):
    assert auth_client.post(V + "/dunning/prepare", json={"as_of": iso(0)}).status_code == 200
    assert auth_client.post(V + "/dunning/prepare", json={"as_of": iso(-30)}).status_code == 200
