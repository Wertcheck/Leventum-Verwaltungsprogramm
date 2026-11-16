"""Äquivalenz- und Skalierungstests zur N+1-Optimierung von `economics.Engine._open` (ADR 0002 Befund B).

Die Referenzimplementierung (`RefEngine`) enthält den ALTEN Algorithmus unverändert: je Forderung `charges.open_amount(db, c, as_of)`,
je Rechnung `payments.invoice_allocated(db, id, as_of)`, je Zahlung eine Zuordnungsabfrage. Die neue Engine (gruppierte Abfragen) muss
auf denselben Daten BITGLEICHE Berichte liefern (Vergleich über `repr`, d. h. inkl. Decimal-Exponent, Reihenfolge der Warnungen).
Zusätzlich Handrechnungen (zeitstabil relativ zu date.today()) und eine Begrenzung der Statementzahl (nicht der Laufzeit)."""
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import event, select

from leventum.models import Charge, Invoice, Lease, Payment, PaymentAllocation
from leventum.services import charges as C, economics as E, payments as P
from leventum.services.economics import ZERO
from leventum.services.utility import q
from tests.helpers import World

TODAY = date.today()


def d(n: int) -> date:
    return TODAY + timedelta(days=n)


def month_start(offset: int) -> date:
    m = TODAY.month - 1 + offset
    return date(TODAY.year + m // 12, m % 12 + 1, 1)


def month_end(offset: int) -> date:
    return month_start(offset + 1) - timedelta(days=1)


class RefEngine(E.Engine):
    """Alter Algorithmus (Stand vor der Optimierung), nur `_open` und `_ist` überschrieben."""

    def _open(self, as_of, prefix=""):
        for c in self.db.scalars(select(Charge).where(Charge.voided_at.is_(None), Charge.due_date <= as_of)):
            o = C.open_amount(self.db, c, as_of)
            if o <= 0:
                continue
            lease = self.db.get(Lease, c.lease_id)
            base = "receivables" if c.direction == "receivable" else "payables"
            self._add(lease, f"{prefix}open_{base}", o)
            if c.due_date < as_of:
                self._add(lease, f"{prefix}overdue_{base}", o)
        for inv in self.db.scalars(select(Invoice).where(Invoice.voided_at.is_(None), Invoice.invoice_date <= as_of)):
            o = q(inv.amount - P.invoice_allocated(self.db, inv.id, as_of))
            if o > 0:
                self._attach_invoice(inv, f"{prefix}open_invoices", o)

    def _ist(self):
        pays = list(self.db.scalars(select(Payment).where(Payment.booking_date >= self.start, Payment.booking_date <= self.end)))
        for p in pays:
            allocs = list(self.db.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == p.id)))
            for a in allocs:
                if a.charge_id:
                    c = self.db.get(Charge, a.charge_id)
                    lease = self.db.get(Lease, c.lease_id)
                    self._add(lease, "ist_in_receivables" if c.direction == "receivable" else "ist_out_payables", a.amount)
                else:
                    inv = self.db.get(Invoice, a.invoice_id)
                    self._attach_invoice(inv, "ist_out_invoices", a.amount)
            rest = q(P.signed(p) - sum((a.amount for a in allocs), D(0)))
            if rest:
                metric = "ist_in_other" if p.direction == "in" else "ist_out_other"
                (self.prop[p.property_id] if p.property_id else self.port)[metric] += rest


@pytest.fixture
def world(app, auth_client):
    w = World(app)
    w.main_lease = w.activate_main()
    w.db.commit()
    yield w
    w.db.close()


class Data:
    """Erfundene Szenarien; alle Daten relativ zu heute. Sub A (Zimmer 1), Sub B (Zimmer 2), Sub C (WE 2), Hauptmietvertrag."""

    def __init__(self, w):
        self.w, self.db, self.n = w, w.db, 0
        self.ta, self.tb, self.tc = w.tenant("Anna Alpha"), w.tenant("Bert Beta"), w.tenant("Cora Gamma")
        self.sa = w.sub([w.ru_room(w.room1)], [self.ta], d(-400), None, nk_mode=None)
        self.sb = w.sub([w.ru_room(w.room2)], [self.tb], d(-400), None, nk_mode=None)
        self.sc = w.sub([w.ru_unit(w.we2)], [self.tc], d(-400), None, nk_mode=None)
        self.main = w.main_lease

    def charge(self, lease, amount, due):
        return C.create_manual_charge(self.db, None, lease_id=lease.id, amount=D(amount), due_date=due, period_start=due, period_end=due + timedelta(days=29), note="Test")

    def pay(self, lease, amount, booking, *allocs, direction="in", **kw):
        self.n += 1
        return P.create_payment(self.db, None, direction=direction, booking_date=booking, amount=D(amount), lease_id=lease.id, reference=f"P-{self.n}",
                                allocations=[({"charge_id": t.id, "amount": D(a)} if isinstance(t, Charge) else {"invoice_id": t.id, "amount": D(a)}) for t, a in allocs], **kw)

    def build(self):
        w = self.w
        # Sub A
        c1 = self.charge(self.sa, "600.00", d(-30)); self.pay(self.sa, "250.00", d(-20), (c1, "250.00"))                      # Teilzahlung
        c2 = self.charge(self.sa, "900.00", d(-50))                                                                           # mehrere Zahlungen
        for amt, off in (("300.00", -40), ("300.00", -30), ("100.00", -3)):
            self.pay(self.sa, amt, d(off), (c2, amt))
        c3 = self.charge(self.sa, "500.00", d(-45)); self.pay(self.sa, "500.00", d(-44), (c3, "500.00"))                      # vollständig
        c4 = self.charge(self.sa, "700.00", d(-20)); self.pay(self.sa, "700.00", d(15), (c4, "700.00"))                       # Zukunftszahlung
        c5 = self.charge(self.sa, "600.00", d(-30)); p5 = self.pay(self.sa, "600.00", d(-20), (c5, "600.00"))                 # Storno nach Original
        P.reverse_payment(self.db, None, p5.id, reason="Fehlbuchung", booking_date=d(-5))
        c8 = self.charge(self.sa, "800.00", d(20)); self.pay(self.sa, "100.00", d(-1), (c8, "100.00"))                        # nicht fällig, Teilzahlung
        c9 = self.charge(self.sa, "450.00", d(0))                                                                             # fällig genau heute
        # Sub B: F1 (Storno VOR Originalzahlung) + storniert (voided)
        c6 = self.charge(self.sb, "600.00", d(-30)); p6 = self.pay(self.sb, "600.00", d(-5), (c6, "600.00"))
        P.reverse_payment(self.db, None, p6.id, reason="Fehlbuchung", booking_date=d(-20))
        c7 = self.charge(self.sb, "400.00", d(-30)); C.void_charge(self.db, None, c7.id, "Testweise storniert")
        # Sub C
        self.charge(self.sc, "300.00", d(-10))
        c11 = self.charge(self.sc, "200.00", d(-70)); p11 = self.pay(self.sc, "200.00", d(-60), (c11, "200.00"))               # Rücknahme der Zuordnung
        P.deallocate(self.db, None, p11.id, charge_id=c11.id, amount=D("50.00"), reason="Teilkorrektur")
        # Hauptmiete (Verbindlichkeiten)
        m1 = self.charge(self.main, "3000.00", d(-30)); self.pay(self.main, "1000.00", d(-20), (m1, "1000.00"), direction="out")
        self.charge(self.main, "3000.00", d(5))
        m3 = self.charge(self.main, "2000.00", d(-60)); self.pay(self.main, "2000.00", d(-55), (m3, "2000.00"), direction="out")
        # ohne Zuordnung
        self.pay(self.sa, "120.00", d(-2))
        self.pay(self.main, "50.00", d(-2), direction="out")
        # Rechnungen
        p = w.prop
        i1 = P.create_invoice(self.db, None, property_id=p.id, unit_id=w.we1.id, invoice_number="R1", amount=D("238.00"), invoice_date=d(-60))
        self.pay(self.main, "100.00", d(-50), (i1, "100.00"), direction="out")
        i2 = P.create_invoice(self.db, None, property_id=p.id, invoice_number="R2", amount=D("100.00"), invoice_date=d(-10))      # ohne Wohneinheit
        self.pay(self.main, "100.00", d(-9), (i2, "100.00"), direction="out")
        P.create_invoice(self.db, None, property_id=p.id, unit_id=w.we2.id, invoice_number="R3", amount=D("500.00"), invoice_date=d(10))  # Zukunft
        i4 = P.create_invoice(self.db, None, property_id=p.id, unit_id=w.we2.id, invoice_number="R4", amount=D("200.00"), invoice_date=d(-5))
        self.pay(self.main, "200.00", d(20), (i4, "200.00"), direction="out")                                                    # Zukunftszahlung
        i5 = P.create_invoice(self.db, None, property_id=p.id, invoice_number="R5", amount=D("77.00"), invoice_date=d(-40))
        P.void_invoice(self.db, None, i5.id, "Testweise storniert")
        self.db.commit()
        self.db.expire_all()


# (Beginn, Ende, "heute" der Engine): Gegenwart, Vergangenheit, Zukunft (Prognose, beide _open-Aufrufe), historische Stichtage
PERIODS = [
    ("aktueller_monat", month_start(0), month_end(0), TODAY),
    ("vergangener_zeitraum", month_start(-3), month_end(-2), TODAY),
    ("zukunft_prognose", month_start(0), month_end(2), TODAY),
    ("mehrjahr_prognose", month_start(-14), month_end(3), TODAY),
    ("historisch_minus10", month_start(0), month_end(1), d(-10)),
    ("historisch_minus25", month_start(-1), month_end(0), d(-25)),
    ("historisch_minus45", month_start(-2), month_end(0), d(-45)),
    ("historisch_minus65", month_start(-3), month_end(-1), d(-65)),
    ("stichtag_gleich_periodenende", month_start(-1), month_end(-1), month_end(-1)),
]


@pytest.fixture
def data(world):
    x = Data(world)
    x.build()
    return x


@pytest.mark.parametrize("name,start,end,today", PERIODS, ids=[p[0] for p in PERIODS])
def test_new_engine_is_bit_identical_to_reference(data, name, start, end, today):
    db, w = data.db, data.w
    new, ref = E.Engine(db, start, end, today), RefEngine(db, start, end, today)
    for scope, id_ in (("portfolio", None), ("property", w.prop.id), ("unit", w.we1.id), ("unit", w.we2.id)):
        assert repr(new.report(scope, id_)) == repr(ref.report(scope, id_)), (name, scope)
    assert new.warnings == ref.warnings
    assert repr(dict(new.port)) == repr(dict(ref.port))
    assert {k: repr(dict(v)) for k, v in new.leaf.items()} == {k: repr(dict(v)) for k, v in ref.leaf.items()}
    assert {k: repr(dict(v)) for k, v in new.prop.items()} == {k: repr(dict(v)) for k, v in ref.prop.items()}


def _offen(rep):
    o = rep["offen_zum_stichtag"]
    return o["receivables"], o["receivables_overdue"], o["payables"], o["payables_overdue"], o["invoices"]


def test_hand_calculated_values_today(data):
    """Stichtag heute (Handrechnung, siehe Szenarien in Data.build). Forderungen (fällig <= heute, Zahlungen bis heute):
    350 (Teilzahlung) + 200 (900 - 700) + 0 (voll) + 700 (Zukunftszahlung wirkt nicht) + 600 (Storno nach Original) + 600 (F1: beide Buchungen wirken heute -> 600)
    + 450 (fällig heute, nicht überfällig) + 300 + 50 (200 bezahlt, 50 zurückgenommen -> 50 offen) = 3250; überfällig (Fälligkeit < heute) = 2800.
    Verbindlichkeiten: 3000 - 1000 = 2000 (die 3000 fällig +5 zählt nicht, 2000 voll bezahlt). Rechnungen: 138 (R1) + 0 (R2) + 200 (R4, Zahlung +20 wirkt nicht) = 338."""
    rep = E.Engine(data.db, month_start(0), month_end(0), TODAY).report("portfolio")
    assert _offen(rep) == (D("3250.00"), D("2800.00"), D("2000.00"), D("2000.00"), D("338.00"))
    assert rep["prognose_periodenende"] is not None or month_end(0) <= TODAY


def test_hand_calculated_values_f1_window_must_stay_1200(data):
    """Stichtag heute-10: Forderung F1 (600, Storno bei -20 wirkt, Original bei -5 noch nicht) = 1200 (Ist-Verhalten, Befund F1, unverändert).
    Übrige: 350 (Teilzahlung bei -20) + 300 (900 - 300 - 300) + 0 + 700 + 0 (Original -20 wirkt, Storno -5 noch nicht) + 1200 (F1) + 300 (fällig -10, nicht überfällig)
    + 50 (Sub C: 200 bezahlt -60, Rücknahme 50 wirkt rückwirkend) = 2900; überfällig = 2900 - 300 = 2600.
    Verbindlichkeiten 2000/2000 (3000 - 1000; 3000 fällig +5 nicht). Rechnungen: R1 138 + R2 100 (Zahlung bei -9 wirkt noch nicht) = 238."""
    rep = E.Engine(data.db, month_start(0), month_end(1), d(-10)).report("portfolio")
    assert _offen(rep) == (D("2900.00"), D("2600.00"), D("2000.00"), D("2000.00"), D("238.00"))
    f1 = [c for c in data.db.scalars(select(Charge).where(Charge.lease_id == data.sb.id, Charge.voided_at.is_(None)))]
    assert len(f1) == 1 and C.open_amount(data.db, f1[0], d(-10)) == D("1200.00")


def test_forecast_fields_identical_and_present(data):
    new = E.Engine(data.db, month_start(0), month_end(2), TODAY).report("portfolio")
    ref = RefEngine(data.db, month_start(0), month_end(2), TODAY).report("portfolio")
    assert new["prognose_periodenende"] is not None and repr(new["prognose_periodenende"]) == repr(ref["prognose_periodenende"])
    assert new["prognose_periodenende"]["receivables_open_if_no_further_payments"] > 0


def test_allocated_by_charge_matches_allocated_for_every_charge_and_date(data):
    charges = list(data.db.scalars(select(Charge)))
    ids = [c.id for c in charges]
    for as_of in (None, d(-70), d(-60), d(-45), d(-20), d(-5), d(0), d(15), d(30)):
        grouped = C.allocated_by_charge(data.db, None, as_of)
        subset = C.allocated_by_charge(data.db, ids, as_of)
        for c in charges:
            exp = C.allocated(data.db, c.id, as_of)
            assert repr(grouped.get(c.id, ZERO)) == repr(exp) == repr(subset.get(c.id, ZERO)), (c.id, as_of)
    assert C.allocated_by_charge(data.db, [], None) == {}


def test_allocated_by_invoice_matches_invoice_allocated(data):
    invs = list(data.db.scalars(select(Invoice)))
    for as_of in (None, d(-50), d(-9), d(0), d(20)):
        grouped = C.allocated_by_invoice(data.db, None, as_of)
        for i in invs:
            assert repr(grouped.get(i.id, ZERO)) == repr(P.invoice_allocated(data.db, i.id, as_of)), (i.id, as_of)


def test_ist_values_unchanged_for_period_with_payments(data):
    rep_n = E.Engine(data.db, month_start(-3), month_end(1), TODAY).report("portfolio")
    rep_r = RefEngine(data.db, month_start(-3), month_end(1), TODAY).report("portfolio")
    assert repr(rep_n["ist"]) == repr(rep_r["ist"]) and rep_n["ist"]["in_total"] != 0


# ---------------------------------------------------------------------------------------------------------------------------------
# Skalierung: Statementzahl darf nicht linear mit der Forderungszahl wachsen (KEIN Laufzeittest)
# ---------------------------------------------------------------------------------------------------------------------------------
class Counter:
    def __init__(self, engine):
        self.engine, self.n = engine, 0

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._cb)
        return self

    def __exit__(self, *a):
        event.remove(self.engine, "before_cursor_execute", self._cb)

    def _cb(self, *a, **k):
        self.n += 1


def _statements(app, start, end, today):
    db = app.state.session_factory()   # frische Session: leerer Identity-Map-Cache wie im echten Aufruf
    try:
        with Counter(db.get_bind()) as c:
            E.Engine(db, start, end, today).report("portfolio")
        return c.n
    finally:
        db.close()


def test_statement_count_does_not_grow_with_charges(app, data):
    """Engine(...).report bei 30 vs. 100 Forderungen (alle überfällig bzw. teilbezahlt, Verträge unverändert).
    Alt: je Forderung >= 1 Statement je _open-Aufruf (2 Aufrufe bei Prognose) -> Differenz (70 Forderungen) >= 70.
    Neu: Anzahl hängt nur von Struktur/Verträgen/Zahlungen im Zeitraum ab -> Obergrenze der Differenz 5 (Reserve für nachgeladene Verträge/Batches,
    keinerlei Abhängigkeit je Forderung), Gesamtobergrenze 120 (aktuell deutlich darunter; zählt Struktur-/Soll-Abfragen)."""
    leases = [data.sa, data.sb, data.sc]
    start, end = month_start(0), month_end(2)   # Prognose -> beide _open-Aufrufe

    def add(k0, k1):
        for k in range(k0, k1):
            lease = leases[k % 3]
            c = data.charge(lease, f"{100 + k}.00", d(-(k % 90) - 1))
            if k % 3 == 0:
                data.pay(lease, "10.00", d(-(k % 90)), (c, "10.00"))
        data.db.commit()

    base = sum(1 for _ in data.db.scalars(select(Charge).where(Charge.voided_at.is_(None))))
    add(0, 30 - base if base < 30 else 0)
    n30 = _statements(app, start, end, TODAY)
    c30 = len(list(data.db.scalars(select(Charge).where(Charge.voided_at.is_(None)))))
    add(100, 100 + (100 - c30))
    n100 = _statements(app, start, end, TODAY)
    c100 = len(list(data.db.scalars(select(Charge).where(Charge.voided_at.is_(None)))))
    assert c30 >= 30 and c100 >= 100 and c100 - c30 >= 60
    assert n100 - n30 <= 5, (c30, n30, c100, n100)
    assert n100 <= 120, n100
