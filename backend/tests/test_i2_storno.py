"""Charakterisierungstests Storno/Gegenbuchung/Rücknahme von Zahlungen (Bestand, ADR 0002 A5/A6/F1).
Die Stornierungs- und Gegenbuchungslogik wird NICHT geändert (Vorgabe Eigentümer); keine künstliche Begrenzung offener Forderungen.
Alle Erwartungswerte sind von Hand relativ zu date.today() gerechnet (zeitstabil), nicht aus dem Code abgeleitet.

Modell (Handrechnung): offen(Stichtag) = Forderungsbetrag - Summe der Zuordnungen aller Zahlungen mit booking_date <= Stichtag.
Eine Zahlung ordnet +x zu, ihre Gegenbuchung -x (Buchungsdatum = Stornodatum, Standard heute).

Befunde, die in dieser Datei als Ist-Verhalten festgehalten (nicht als erwünscht bewertet) werden:
  F1  (bekannt, ADR 0002)   Storno mit Buchungsdatum vor der Originalzahlung -> offen > Forderungsbetrag.
  F1b (NEU im Test aufgefallen) Dieselbe Wirkung entsteht OHNE explizites Stornodatum, wenn die Originalzahlung in der Zukunft datiert ist
      (Standard-Stornodatum = heute < Buchungsdatum der Zahlung): heute offen = 2 x Forderung, obwohl `charge.open_amount` ohne Stichtag
      korrekt den Forderungsbetrag liefert (Abweichung Dashboard/Stichtag vs. Listen, vgl. A8).
  F1c (NEU im Test aufgefallen) Der Storno-Pfad hat keine Plausibilitätsprüfung des Buchungsdatums (weder >= Originalzahlung noch <= heute).
Der bestehende xfail(strict) zu F1 in test_k2_dashboard_kpis.py bleibt unberührt."""
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from leventum.models import AuditEvent, Payment, PaymentAllocation
from leventum.services import charges as C, payments as P
from leventum.services.errors import ServiceError
from tests.helpers import World

TODAY = date.today()


def d(n: int) -> date:
    return TODAY + timedelta(days=n)


@pytest.fixture
def world(app, auth_client):
    w = World(app)
    w.activate_main()
    w.db.commit()
    yield w
    w.db.close()


class Fin:
    def __init__(self, w):
        self.w = w
        self.db = w.db
        self.tenant = w.tenant("Storno Mieter")
        self.lease = w.sub([w.ru_room(w.room1)], [self.tenant], d(-400), None, nk_mode=None)
        self.n = 0
        self.charges = []

    def charge(self, amount, due):
        c = C.create_manual_charge(self.db, None, lease_id=self.lease.id, amount=D(amount), due_date=due, period_start=due,
                                   period_end=due + timedelta(days=29), note="Teststorno")
        self.charges.append(c)
        return c

    def pay(self, amount, booking, *allocs):
        self.n += 1
        return P.create_payment(self.db, None, direction="in", booking_date=booking, amount=D(amount), counterparty_party_id=self.tenant.id,
                                lease_id=self.lease.id, reference=f"S-{self.n}", allocations=[{"charge_id": c.id, "amount": D(a)} for c, a in allocs])

    def commit(self):
        self.db.commit()
        self.db.expire_all()

    def both(self, as_of):
        """receivable_position UND Summe/Anzahl aus open_amount(..., as_of) je Forderung; beide müssen übereinstimmen."""
        r = C.receivable_position(self.db, as_of)
        opens = {c.id: C.open_amount(self.db, c, as_of) for c in self.charges}
        total = sum((o for o in opens.values() if o > 0), D("0.00"))
        overdue = sum(1 for c in self.charges if opens[c.id] > 0 and c.due_date < as_of)
        assert r["open_total"] == total, (as_of, r["open_total"], opens)
        assert r["overdue_count"] == overdue, as_of
        return r, opens


@pytest.fixture
def fin(world):
    return Fin(world)


# ---------------------------------------------------------------------------------------------------------------------------------
# (1) Originalzahlung VOR Gegenbuchung. Forderung 600 fällig -30; Zahlung 600 bei -20; Storno bei -5.
#   <= -21: 600 | -20..-6: 0 | >= -5: 600. Überfällig, wenn offen und Fälligkeit -30 < Stichtag (hier immer erfüllt).
# ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("off,open_,overdue", [(-25, "600.00", 1), (-20, "0.00", 0), (-6, "0.00", 0), (-5, "600.00", 1), (0, "600.00", 1)])
def test_1_original_before_reversal_per_as_of(fin, off, open_, overdue):
    c = fin.charge("600.00", d(-30))
    p = fin.pay("600.00", d(-20), (c, "600.00"))
    P.reverse_payment(fin.db, None, p.id, reason="Fehlbuchung", booking_date=d(-5))
    fin.commit()
    r, opens = fin.both(d(off))
    assert r["open_total"] == D(open_) and r["overdue_count"] == overdue
    assert opens[c.id] == D(open_)


def test_1_open_amount_without_as_of_is_charge_amount_after_reversal(fin):
    c = fin.charge("600.00", d(-30))
    p = fin.pay("600.00", d(-20), (c, "600.00"))
    P.reverse_payment(fin.db, None, p.id, reason="Fehlbuchung", booking_date=d(-5))
    fin.commit()
    assert C.allocated(fin.db, c.id) == D("0.00") and C.open_amount(fin.db, c) == D("600.00")


# ---------------------------------------------------------------------------------------------------------------------------------
# (2) Gegenbuchung VOR Originalzahlung – Ist-Verhalten, fachlich ungeklärt (Befund F1), NICHT als erwünscht bewertet.
#   Forderung 600 fällig -30; Zahlung 600 bei -5; Storno bei -20.
#   <= -21: 600 | -20..-6: Storno (-600) wirkt, Original (+600) noch nicht -> 600 - (-600) = 1200 | >= -5: 600 - 0 = 600.
# ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("off,open_", [(-25, "600.00"), (-20, "1200.00"), (-10, "1200.00"), (-6, "1200.00"), (-5, "600.00"), (0, "600.00")])
def test_2_reversal_before_original_actual_behavior_f1(fin, off, open_):
    """Ist-Verhalten, fachlich ungeklärt (Befund F1): zwischen Storno- und Originaldatum ist offen > Forderungsbetrag (1200 bei Forderung 600)."""
    c = fin.charge("600.00", d(-30))
    p = fin.pay("600.00", d(-5), (c, "600.00"))
    P.reverse_payment(fin.db, None, p.id, reason="Fehlbuchung", booking_date=d(-20))  # F1c: keine Prüfung des Datums
    fin.commit()
    r, opens = fin.both(d(off))
    assert r["open_total"] == D(open_) and opens[c.id] == D(open_)
    if off in (-20, -10, -6):
        assert r["open_total"] > c.amount  # F1: Dokumentation des Befunds, kein Soll-Zustand


# ---------------------------------------------------------------------------------------------------------------------------------
# (3) Mehrfach-/Teilstorno
# ---------------------------------------------------------------------------------------------------------------------------------
def test_3_second_reversal_of_same_payment_rejected(fin):
    c = fin.charge("600.00", d(-30))
    p = fin.pay("600.00", d(-20), (c, "600.00"))
    P.reverse_payment(fin.db, None, p.id, reason="Fehlbuchung", booking_date=d(-5))
    fin.commit()
    with pytest.raises(ServiceError) as ei:
        P.reverse_payment(fin.db, None, p.id, reason="nochmal", booking_date=d(-4))
    assert ei.value.code == "already_reversed" and ei.value.status == 409
    fin.db.rollback()
    assert len(fin.db.scalars(select(Payment).where(Payment.reverses_payment_id == p.id)).all()) == 1
    assert C.open_amount(fin.db, c) == D("600.00")  # nichts doppelt storniert (kein offen 1200)


def test_3_reversal_cannot_be_reversed_and_no_partial_amount_api(fin):
    c = fin.charge("600.00", d(-30))
    p = fin.pay("600.00", d(-20), (c, "600.00"))
    rev = P.reverse_payment(fin.db, None, p.id, reason="Fehlbuchung", booking_date=d(-5))
    fin.commit()
    with pytest.raises(ServiceError) as ei:
        P.reverse_payment(fin.db, None, rev.id, reason="Storno des Stornos")
    assert ei.value.code == "invalid_state" and ei.value.status == 409
    import inspect
    assert "amount" not in inspect.signature(P.reverse_payment).parameters  # Teilbetrags-Storno existiert nicht (nur Vollstorno)


def test_3_reversal_needs_reason_and_existing_payment(fin):
    c = fin.charge("600.00", d(-30))
    p = fin.pay("600.00", d(-20), (c, "600.00"))
    with pytest.raises(ServiceError) as ei:
        P.reverse_payment(fin.db, None, p.id, reason="   ")
    assert ei.value.code == "invalid"
    with pytest.raises(ServiceError) as ei2:
        P.reverse_payment(fin.db, None, 999999, reason="x")
    assert ei2.value.status == 404


def test_3_reversed_payment_and_reversal_cannot_be_allocated_or_deallocated(fin):
    c = fin.charge("600.00", d(-30))
    p = fin.pay("600.00", d(-20), (c, "600.00"))
    rev = P.reverse_payment(fin.db, None, p.id, reason="Fehlbuchung", booking_date=d(-5))
    fin.commit()
    for call in (lambda: P.allocate(fin.db, None, p.id, charge_id=c.id, amount=D("1.00")),
                 lambda: P.allocate(fin.db, None, rev.id, charge_id=c.id, amount=D("1.00")),
                 lambda: P.deallocate(fin.db, None, p.id, charge_id=c.id, amount=D("1.00"), reason="x")):
        with pytest.raises(ServiceError) as ei:
            call()
        assert ei.value.code == "invalid_state" and ei.value.status == 409
        fin.db.rollback()
    assert C.allocated(fin.db, c.id) == D("0.00")


def test_3_reversing_unallocated_payment_creates_no_allocation_rows(fin):
    p = fin.pay("100.00", d(-3))
    rev = P.reverse_payment(fin.db, None, p.id, reason="Fehlbuchung", booking_date=d(-2))
    fin.commit()
    assert fin.db.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == rev.id)).all() == []
    assert P.unallocated(fin.db, fin.db.get(Payment, rev.id)) == D("-100.00")  # Ist: signierter Betrag der Gegenbuchung bleibt unzugeordnet


# ---------------------------------------------------------------------------------------------------------------------------------
# (4) Teilzahlungen und Gegenbuchungen
# ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("off,open_,overdue", [(-25, "600.00", 1), (-20, "400.00", 1), (-15, "200.00", 1), (-10, "0.00", 0),
                                               (-6, "0.00", 0), (-5, "200.00", 1), (0, "200.00", 1)])
def test_4_three_partial_payments_middle_reversed(fin, off, open_, overdue):
    """Forderung 600 fällig -30; Teilzahlungen 200 (-20), 200 (-15), 200 (-10); die mittlere wird bei -5 storniert.
    offen: -25: 600 | -20: 400 | -15: 200 | -10..-6: 0 | ab -5: 200 (nur 400 bleiben bezahlt)."""
    c = fin.charge("600.00", d(-30))
    fin.pay("200.00", d(-20), (c, "200.00"))
    p2 = fin.pay("200.00", d(-15), (c, "200.00"))
    fin.pay("200.00", d(-10), (c, "200.00"))
    P.reverse_payment(fin.db, None, p2.id, reason="Rückläufer", booking_date=d(-5))
    fin.commit()
    r, opens = fin.both(d(off))
    assert r["open_total"] == D(open_) and r["overdue_count"] == overdue and opens[c.id] == D(open_)


def test_4_reversal_of_payment_with_partly_deallocated_allocation_reverses_only_net(fin):
    """Zahlung 600 auf Forderung 600, davon 200 zurückgenommen (Rücknahme-Zeile -200). Storno schreibt nur die Netto-Zuordnung (-400) zurück."""
    c = fin.charge("600.00", d(-30))
    p = fin.pay("600.00", d(-20), (c, "600.00"))
    P.deallocate(fin.db, None, p.id, charge_id=c.id, amount=D("200.00"), reason="Teilkorrektur")
    rev = P.reverse_payment(fin.db, None, p.id, reason="Fehlbuchung", booking_date=d(-5))
    fin.commit()
    rows = fin.db.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == rev.id)).all()
    assert [r.amount for r in rows] == [D("-400.00")]
    assert C.allocated(fin.db, c.id) == D("0.00") and C.open_amount(fin.db, c) == D("600.00")
    r, _ = fin.both(TODAY)
    assert r["open_total"] == D("600.00")


@pytest.mark.parametrize("off,open_,overdue", [(-21, "600.00", 2), (-20, "100.00", 0), (-9, "100.00", 1), (-6, "100.00", 1), (-5, "600.00", 3), (0, "600.00", 3)])
def test_4_payment_spread_over_charges_with_reversal(fin, off, open_, overdue):
    """A 300 (fällig -30), B 200 (fällig -25), C 100 (fällig -10). Zahlung 500 bei -20: 300 -> A, 200 -> B. Storno bei -5 hebt beide Zuordnungen auf.
    -21: 600 offen, überfällig A,B = 2 | -20..-6: nur C offen = 100 (überfällig erst ab -9: C fällig -10 < Stichtag) | ab -5: 600, überfällig A,B,C = 3."""
    a, b, c = fin.charge("300.00", d(-30)), fin.charge("200.00", d(-25)), fin.charge("100.00", d(-10))
    p = fin.pay("500.00", d(-20), (a, "300.00"), (b, "200.00"))
    P.reverse_payment(fin.db, None, p.id, reason="Fehlbuchung", booking_date=d(-5))
    fin.commit()
    r, opens = fin.both(d(off))
    assert r["open_total"] == D(open_) and r["overdue_count"] == overdue
    assert sum(len(v) for v in r["overdue_by_lease"].values()) == overdue


def test_4_spread_reversal_writes_one_negative_allocation_per_charge(fin):
    a, b = fin.charge("300.00", d(-30)), fin.charge("200.00", d(-25))
    p = fin.pay("500.00", d(-20), (a, "300.00"), (b, "200.00"))
    rev = P.reverse_payment(fin.db, None, p.id, reason="Fehlbuchung", booking_date=d(-5))
    fin.commit()
    rows = fin.db.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == rev.id)).all()
    assert sorted((r.charge_id, r.amount) for r in rows) == sorted([(a.id, D("-300.00")), (b.id, D("-200.00"))])
    assert all(r.reason == "Storno" for r in rows)


# ---------------------------------------------------------------------------------------------------------------------------------
# (5) Storno einer heute zukünftig datierten Zahlung
# ---------------------------------------------------------------------------------------------------------------------------------
def test_5_reverse_future_dated_payment_default_date_f1b(fin):
    """Ist-Verhalten, fachlich ungeklärt (Befund F1b, NEU): Forderung 600 (fällig -30), Zahlung 600 mit Buchungsdatum +10, Storno ohne Datum (= heute).
    Heute wirkt nur das Storno (-600), die Originalzahlung (+10) noch nicht -> dashboardrelevante Position heute = 1200 (> Forderung),
    während open_amount ohne Stichtag (Netto aller Zuordnungen) 600 liefert. Ab +10: 600."""
    c = fin.charge("600.00", d(-30))
    p = fin.pay("600.00", d(10), (c, "600.00"))
    rev = P.reverse_payment(fin.db, None, p.id, reason="Fehlbuchung")  # Standarddatum = heute
    fin.commit()
    assert rev.booking_date == TODAY
    r, opens = fin.both(TODAY)
    assert r["open_total"] == D("1200.00") and opens[c.id] == D("1200.00")  # F1b
    assert C.open_amount(fin.db, c) == D("600.00")  # ohne Stichtag: Netto
    assert fin.both(d(-1))[0]["open_total"] == D("600.00")  # vor Storno und Zahlung
    assert fin.both(d(10))[0]["open_total"] == D("600.00")  # Zahlung und Storno beide wirksam


def test_5_reverse_future_dated_payment_with_future_reversal_date(fin):
    """Storno mit Buchungsdatum +10 (gleich Original): heute offen 600 (keine der beiden Buchungen wirkt), ab +10 ebenfalls 600."""
    c = fin.charge("600.00", d(-30))
    p = fin.pay("600.00", d(10), (c, "600.00"))
    P.reverse_payment(fin.db, None, p.id, reason="Fehlbuchung", booking_date=d(10))
    fin.commit()
    for off in (0, 9, 10):
        assert fin.both(d(off))[0]["open_total"] == D("600.00"), off


def test_5_future_dated_payment_unreversed_does_not_reduce_today_but_open_amount_does(fin):
    """Kontrolle (A8): Stichtagssicht heute 600, open_amount ohne Stichtag 0."""
    c = fin.charge("600.00", d(-30))
    fin.pay("600.00", d(10), (c, "600.00"))
    fin.commit()
    assert fin.both(TODAY)[1][c.id] == D("600.00") and C.open_amount(fin.db, c) == D("0.00")


# ---------------------------------------------------------------------------------------------------------------------------------
# (6) Unveränderlichkeit und Audit
# ---------------------------------------------------------------------------------------------------------------------------------
def test_6_original_and_allocations_unchanged_reversal_is_own_row(fin):
    c = fin.charge("600.00", d(-30))
    p = fin.pay("600.00", d(-20), (c, "600.00"))
    fin.commit()
    pid, cid = p.id, c.id
    before_p = (p.amount, p.booking_date, p.is_reversal, p.reverses_payment_id, p.reference)
    orig_alloc = [(a.id, a.amount, a.charge_id) for a in fin.db.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == pid))]
    rev = P.reverse_payment(fin.db, None, pid, reason="Fehlbuchung", booking_date=d(-5))
    fin.commit()
    p = fin.db.get(Payment, pid)
    assert (p.amount, p.booking_date, p.is_reversal, p.reverses_payment_id, p.reference) == before_p
    assert [(a.id, a.amount, a.charge_id) for a in fin.db.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == pid))] == orig_alloc
    rev = fin.db.get(Payment, rev.id)
    assert rev.id != pid and rev.is_reversal is True and rev.reverses_payment_id == pid
    assert rev.amount == D("600.00") and rev.booking_date == d(-5) and P.signed(rev) == D("-600.00")  # Betrag positiv (CHECK), Vorzeichen via is_reversal
    assert rev.reference == "Storno zu Zahlung %d: Fehlbuchung" % pid
    ra = fin.db.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == rev.id)).all()
    assert [(a.charge_id, a.amount, a.reason) for a in ra] == [(cid, D("-600.00"), "Storno")]
    assert P.is_reversed(fin.db, p) and P.payment_view(fin.db, p)["reversed"] is True
    assert P.unallocated(fin.db, p) == D("0.00") and P.unallocated(fin.db, rev) == D("0.00")


def test_6_audit_event_written_for_reversal(fin):
    c = fin.charge("600.00", d(-30))
    p = fin.pay("600.00", d(-20), (c, "600.00"))
    rev = P.reverse_payment(fin.db, None, p.id, reason="Fehlbuchung", booking_date=d(-5))
    fin.commit()
    ev = fin.db.scalars(select(AuditEvent).where(AuditEvent.action == "payment.reversed")).all()
    assert len(ev) == 1 and ev[0].entity_type == "payment" and str(ev[0].entity_id) == str(p.id)
    assert ev[0].details["reversal_id"] == rev.id and ev[0].details["reason"] == "Fehlbuchung"
    assert fin.db.scalars(select(AuditEvent).where(AuditEvent.action == "payment.created")).all()  # Erfassung ebenfalls protokolliert


# ---------------------------------------------------------------------------------------------------------------------------------
# (7) Rücknahme (deallocate) vs. Storno (reverse) und historische Stichtage (ADR A6a)
# ---------------------------------------------------------------------------------------------------------------------------------
def test_7_deallocate_acts_retroactively_reverse_acts_from_own_date(fin):
    """Dokumentierte Charakterisierung (A6a, bekannte Einschränkung, NICHT behoben): die Rücknahme-Zeile gehört zur Originalzahlung und wirkt
    daher ab deren Buchungsdatum (-30) -> der historische Stichtag -20 ändert sich von 0 auf 600. Das Storno wirkt dagegen erst ab seinem
    eigenen Buchungsdatum (A5): Stichtag -20 bleibt 0, erst ab -5 wieder 600."""
    c1, c2 = fin.charge("600.00", d(-40)), fin.charge("600.00", d(-40))
    p1 = fin.pay("600.00", d(-30), (c1, "600.00"))
    p2 = fin.pay("600.00", d(-30), (c2, "600.00"))
    fin.commit()
    assert C.open_amount(fin.db, c1, d(-20)) == D("0.00") and C.open_amount(fin.db, c2, d(-20)) == D("0.00")
    P.deallocate(fin.db, None, p1.id, charge_id=c1.id, amount=D("600.00"), reason="Fehlzuordnung")
    P.reverse_payment(fin.db, None, p2.id, reason="Fehlbuchung", booking_date=d(-5))
    fin.commit()
    # Rücknahme: rückwirkend (Einschränkung A6a)
    assert C.open_amount(fin.db, c1, d(-20)) == D("600.00") and C.open_amount(fin.db, c1, d(-31)) == D("600.00")
    # Storno: historischer Stand bleibt erhalten, Wirkung ab -5
    assert C.open_amount(fin.db, c2, d(-20)) == D("0.00") and C.open_amount(fin.db, c2, d(-6)) == D("0.00")
    assert C.open_amount(fin.db, c2, d(-5)) == D("600.00") and C.open_amount(fin.db, c2) == D("600.00")
    # heute sind beide wieder voll offen, Zahlungs-Zustand unterscheidet sich:
    assert C.open_amount(fin.db, c1) == D("600.00")
    assert P.unallocated(fin.db, fin.db.get(Payment, p1.id)) == D("600.00") and not P.is_reversed(fin.db, fin.db.get(Payment, p1.id))  # Rücknahme: Zahlung bleibt frei zuordenbar
    assert P.is_reversed(fin.db, fin.db.get(Payment, p2.id))  # Storno: Zahlung endgültig storniert
    r, _ = fin.both(TODAY)
    assert r["open_total"] == D("1200.00")
    r, _ = fin.both(d(-20))
    assert r["open_total"] == D("600.00")  # nur c1 (rückwirkend), c2 noch bezahlt


def test_7_deallocated_payment_can_be_reallocated_reversed_cannot(fin):
    c = fin.charge("600.00", d(-40))
    p = fin.pay("600.00", d(-30), (c, "600.00"))
    P.deallocate(fin.db, None, p.id, charge_id=c.id, amount=D("600.00"), reason="Fehlzuordnung")
    P.allocate(fin.db, None, p.id, charge_id=c.id, amount=D("600.00"))
    fin.commit()
    assert C.open_amount(fin.db, c) == D("0.00")
    assert [a.amount for a in fin.db.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == p.id).order_by(PaymentAllocation.id))] == [D("600.00"), D("-600.00"), D("600.00")]
