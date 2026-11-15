from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from leventum.models import AuditEvent, Charge, DunningNotice
from leventum.services import charges as C, dunning as DN, payments as P
from leventum.services.errors import ServiceError
from tests.helpers import World

JAN, FEB = date(2026, 1, 1), date(2026, 2, 1)


@pytest.fixture
def w(app):
    w = World(app)
    w.activate_main()
    w.sub_l = w.sub([w.ru_unit(w.we2)], [w.tenant("Max Mustermann")], JAN, None)
    C.generate_charges(w.db, None, from_month=JAN, through_month=FEB, today=date(2026, 2, 15))
    yield w
    w.db.close()


def rec(w, ctype="base_rent", month=JAN):
    return w.db.scalars(select(Charge).where(Charge.direction == "receivable", Charge.charge_type == ctype, Charge.period_start == month)).one()


def pay(w, charge, amount, day):
    return P.create_payment(w.db, None, direction="in", booking_date=day, amount=amount, allocations=[{"charge_id": charge.id, "amount": amount}])


def fix(n):  # Platzhalter für die Frist wie ein Mitarbeiter ersetzen
    n.body = n.body.replace("[Frist eintragen]", "30.03.2026")
    return n


def test_overdue_detection_considers_due_date_partial_and_full_payments(w):
    today = date(2026, 2, 10)
    ids = {(c["lease_id"], c["charge_type"], c["due_date"]): c for c in DN.candidates(w.db, today)}
    assert len(ids) == 4  # Miete + Nebenkosten für Januar und Februar (beide am 1. fällig, am 10.2. überfällig)
    assert {c["due_date"] for c in DN.candidates(w.db, today)} == {JAN, FEB}
    assert DN.candidates(w.db, date(2026, 1, 1)) == []  # am Fälligkeitstag noch nicht überfällig
    pay(w, rec(w), D("400.00"), date(2026, 1, 20))
    c = next(c for c in DN.candidates(w.db, today) if c["charge_type"] == "base_rent" and c["due_date"] == JAN)
    assert c["open_amount"] == D("750.00") and c["amount"] == D("1150.00")  # Teilzahlung berücksichtigt
    pay(w, rec(w), D("750.00"), date(2026, 1, 25))
    assert not [c for c in DN.candidates(w.db, today) if c["charge_type"] == "base_rent" and c["due_date"] == JAN]  # voll bezahlt
    pay(w, rec(w, "utility_prepayment"), D("220.00"), date(2026, 2, 12))
    assert [c for c in DN.candidates(w.db, date(2026, 2, 13)) if c["due_date"] == JAN] == []
    # Zahlung nach dem Stichtag zählt nicht für einen Stichtag davor
    assert any(c["charge_type"] == "utility_prepayment" for c in DN.candidates(w.db, date(2026, 2, 10)))


def test_payables_and_voided_charges_are_never_dunned(w):
    cands = DN.candidates(w.db, date(2026, 3, 1))
    assert all(c["lease_id"] == w.sub_l.id for c in cands)
    voided = rec(w)
    C.void_charge(w.db, None, voided.id, "Test")
    after = DN.candidates(w.db, date(2026, 3, 1))
    assert voided.id not in {c["charge_id"] for c in after} and len(after) == 3


def test_prepare_creates_draft_per_lease_and_level_without_sending_and_is_idempotent(w):
    today = date(2026, 2, 10)
    created = DN.prepare_notices(w.db, None, as_of=today)
    assert len(created) == 1 and created[0].level == 1 and created[0].status == "draft" and len(created[0].lines) == 4
    n = created[0]
    assert n.total_open == D("2740.00") and "Zahlungserinnerung" in n.body and "Max Mustermann" in n.body and "1.150,00 €" in n.body
    assert "Gebühr" not in n.body and "Zinsen" not in n.body.replace("Verzugszinsen", "")  # keine Gebühren/Zinsen im Schreiben
    assert "NICHT enthalten" in n.review_hint and "kein automatischer Versand" in n.review_hint
    assert DN.prepare_notices(w.db, None, as_of=today) == []  # keine doppelten Entwürfe
    assert n.sent_on is None and n.approved_at is None


def test_approval_requires_manual_step_and_resolved_placeholder(w):
    n = DN.prepare_notices(w.db, None, as_of=date(2026, 2, 10))[0]
    with pytest.raises(ServiceError) as e:
        DN.approve(w.db, None, n.id)
    assert e.value.code == "placeholder_unresolved" and n.status == "draft"
    with pytest.raises(ServiceError):
        DN.mark_sent(w.db, None, n.id, sent_on=date(2026, 2, 11), via="Brief")  # nicht freigegeben → kein "versandt"
    fix(n)
    DN.approve(w.db, None, n.id)
    assert n.status == "approved"
    DN.mark_sent(w.db, None, n.id, sent_on=date(2026, 2, 11), via="Brief")
    assert (n.status, n.sent_via) == ("sent", "Brief")
    with pytest.raises(ServiceError):
        DN.update_draft(w.db, None, n.id, body="x")
    with pytest.raises(ServiceError):
        DN.cancel(w.db, None, n.id, "zu spät")


def test_stale_draft_cannot_be_approved_after_payment(w):
    n = fix(DN.prepare_notices(w.db, None, as_of=date(2026, 2, 10))[0])
    pay(w, rec(w), D("1150.00"), date(2026, 2, 11))  # Mieter zahlt, bevor die Mahnung freigegeben wird
    with pytest.raises(ServiceError) as e:
        DN.approve(w.db, None, n.id)
    assert e.value.code == "stale_draft" and e.value.details[0]["current_open"] == D("0.00") and n.status == "draft"
    DN.cancel(w.db, None, n.id, "veraltet")
    new = DN.prepare_notices(w.db, None, as_of=date(2026, 2, 12))
    assert len(new) == 1 and new[0].total_open == D("1590.00")  # 2740 − 1150


def test_level_progression_waiting_period_and_max_level(w):
    d0 = date(2026, 2, 10)
    n1 = fix(DN.prepare_notices(w.db, None, as_of=d0)[0])
    DN.approve(w.db, None, n1.id)
    assert {c["state"] for c in DN.candidates(w.db, d0)} == {"approved_not_sent"}  # freigegeben, aber Versand nicht dokumentiert
    assert DN.prepare_notices(w.db, None, as_of=d0) == []
    DN.mark_sent(w.db, None, n1.id, sent_on=d0, via="E-Mail")
    assert {c["state"] for c in DN.candidates(w.db, d0 + timedelta(days=3))} == {"waiting"}
    assert DN.prepare_notices(w.db, None, as_of=d0 + timedelta(days=3)) == []
    d1 = d0 + timedelta(days=DN.MIN_DAYS_BETWEEN_LEVELS)
    n2 = fix(DN.prepare_notices(w.db, None, as_of=d1)[0])
    assert n2.level == 2 and "Erste Mahnung" in n2.body
    DN.approve(w.db, None, n2.id)
    DN.mark_sent(w.db, None, n2.id, sent_on=d1, via="Brief")
    d2 = d1 + timedelta(days=7)
    n3 = fix(DN.prepare_notices(w.db, None, as_of=d2)[0])
    assert n3.level == 3 and "Zweite Mahnung" in n3.body
    DN.approve(w.db, None, n3.id)
    DN.mark_sent(w.db, None, n3.id, sent_on=d2, via="Brief")
    assert {c["state"] for c in DN.candidates(w.db, d2 + timedelta(days=60))} == {"max_level_reached"}
    assert DN.prepare_notices(w.db, None, as_of=d2 + timedelta(days=60)) == []  # es gibt keine 4. Stufe


def test_cancelled_draft_allows_new_draft_and_everything_is_logged(w):
    n = DN.prepare_notices(w.db, None, as_of=date(2026, 2, 10))[0]
    DN.cancel(w.db, None, n.id, "Mieter hat Ratenzahlung vereinbart")
    again = DN.prepare_notices(w.db, None, as_of=date(2026, 2, 10))
    assert len(again) == 1 and again[0].id != n.id
    actions = [a.action for a in w.db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "dunning_notice", AuditEvent.entity_id == str(n.id)))]
    assert actions == ["dunning.prepared", "dunning.cancelled"]


def test_partial_payment_changes_only_remaining_amount_in_next_draft(w):
    pay(w, rec(w), D("1000.00"), date(2026, 1, 15))
    n = DN.prepare_notices(w.db, None, as_of=date(2026, 2, 10))[0]
    line = next(l for l in n.lines if l.charge_id == rec(w).id)
    assert line.open_amount == D("150.00") and n.total_open == D("1740.00")


def test_regression_approved_but_unsent_notice_never_escalates(w):
    """Befund aus der Master-Review: Eine nur freigegebene Stufe-1-Erinnerung führte nach 7 Tagen zu einem Stufe-2-Entwurf."""
    n = fix(DN.prepare_notices(w.db, None, as_of=date(2026, 2, 10))[0])
    DN.approve(w.db, None, n.id)
    for later in (date(2026, 2, 20), date(2026, 3, 30), date(2027, 6, 1)):
        assert {(c["state"], c["proposed_level"]) for c in DN.candidates(w.db, later)} == {("approved_not_sent", 1)}
        assert DN.prepare_notices(w.db, None, as_of=later) == []
    DN.mark_sent(w.db, None, n.id, sent_on=date(2026, 2, 11), via="Brief")
    assert {(c["state"], c["proposed_level"]) for c in DN.candidates(w.db, date(2026, 2, 20))} == {("due", 2)}  # erst NACH dokumentiertem Versand


def test_summary_counts_are_consistent_with_states_and_positions_are_identifiable(w):
    cands = DN.candidates(w.db, date(2026, 2, 10))
    assert all({"charge_id", "charge_label", "period_start", "period_end", "charge_type", "due_date"} <= c.keys() for c in cands)
    labels = {(c["lease_id"], c["due_date"], c["charge_label"]) for c in cands}
    assert len(labels) == len(cands) == 4  # Kaltmiete und NK am selben Fälligkeitstag sind unterscheidbar
    sm = DN.summarize(cands)
    assert sm["total_positions"] == 4 and sm["by_state"]["due"]["positions"] == 4 and sm["by_state"]["draft_exists"]["positions"] == 0
    DN.prepare_notices(w.db, None, as_of=date(2026, 2, 10))
    sm = DN.summarize(DN.candidates(w.db, date(2026, 2, 10)))
    assert sm["by_state"]["due"]["positions"] == 0 and sm["by_state"]["draft_exists"]["positions"] == 4  # Entwürfe werden nicht erneut als neu vorbereitbar gezählt
    assert sum(v["positions"] for v in sm["by_state"].values()) == sm["total_positions"]
    assert sm["by_state"]["draft_exists"]["open_amount"] == D("2740.00") and sm["by_state"]["draft_exists"]["leases"] == 1
