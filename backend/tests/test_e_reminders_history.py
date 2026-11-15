import io
from datetime import date, datetime, timezone
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from leventum.models import Task
from leventum.services import (charges as C, communications as COM, deposits as DEP, documents as DOC, history as H, leases as L, payments as P,
                               reminders as REM, repairs as R, tasks as T, utility as U)
from leventum.storage import LocalFileStore
from tests.helpers import World


@pytest.fixture
def w(app):
    w = World(app)
    w.main_l = w.activate_main()
    w.tenant_p = w.tenant("Max Mustermann")
    w.sub_l = w.sub([w.ru_unit(w.we2)], [w.tenant_p], date(2026, 1, 1), None)
    yield w
    w.db.close()


def rem(w, today, typ=None):
    items = REM.compute(w.db, today)
    return [r for r in items if typ is None or r["type"] == typ]


def kinds(w, today):
    return {r["type"] for r in REM.compute(w.db, today)}


# ---- Fristen -------------------------------------------------------------------------------------------------------------------------------------------
def test_add_months_clamps_to_month_end():
    assert REM.add_months(date(2026, 5, 31), -3) == date(2026, 2, 28)
    assert REM.add_months(date(2026, 12, 31), -3) == date(2026, 9, 30)
    assert REM.add_months(date(2024, 3, 31), -1) == date(2024, 2, 29)
    assert REM.add_months(date(2026, 1, 15), -2) == date(2025, 11, 15)


def test_contract_end_reminder_window_and_severity(w):
    L.update_lease(w.db, None, w.sub_l.id, {"end_date": date(2026, 12, 31)})
    assert rem(w, date(2026, 9, 1), "contract_end") == []                       # 121 Tage vorher: noch nichts
    r = rem(w, date(2026, 10, 15), "contract_end")[0]                            # 77 Tage
    assert r["severity"] == "info" and r["entity_type"] == "lease" and r["entity_id"] == w.sub_l.id and r["due_date"] == date(2026, 12, 31)
    assert rem(w, date(2026, 12, 10), "contract_end")[0]["severity"] == "warning"  # 21 Tage
    assert rem(w, date(2027, 1, 2), "contract_end") == []                        # nach Ende nicht mehr
    L.terminate_lease(w.db, None, w.sub_l.id, terminated_on=date(2026, 3, 1), effective_on=date(2026, 6, 30))  # wirksames Ende zählt
    assert rem(w, date(2026, 6, 1), "contract_end")[0]["due_date"] == date(2026, 6, 30)


def test_notice_deadline_is_computed_from_stored_data_and_labelled_as_not_legal_advice(w):
    L.update_lease(w.db, None, w.sub_l.id, {"end_date": date(2026, 12, 31), "notice_period_months": 3})
    assert rem(w, date(2026, 6, 1), "notice_deadline") == []                      # Stichtag 30.9. liegt > 60 Tage entfernt
    r = rem(w, date(2026, 8, 15), "notice_deadline")[0]
    assert r["due_date"] == date(2026, 9, 30) and "keine Rechtsprüfung" in r["detail"] and "46 Tage" in r["detail"]
    late = rem(w, date(2026, 10, 5), "notice_deadline")[0]
    assert "verstrichen" in late["title"] and late["severity"] == "warning"
    L.terminate_lease(w.db, None, w.sub_l.id, terminated_on=date(2026, 8, 1), effective_on=date(2026, 12, 31))
    assert rem(w, date(2026, 10, 5), "notice_deadline") == []                    # bereits gekündigt → kein Hinweis
    L2 = w.sub([w.ru_unit(w.we1)], [w.tenant("Unbefristet Mieter")], date(2026, 1, 1), None)
    assert all(x["entity_id"] != L2.id for x in rem(w, date(2026, 8, 15), "notice_deadline"))  # ohne Enddatum/Frist: nie ein Stichtag


# ---- Zahlungen / Kaution / Reparaturen / Abrechnung ----------------------------------------------------------------------------------------------------------
def test_overdue_payment_reminder_respects_partial_and_full_payments(w):
    C.generate_charges(w.db, None, from_month=date(2026, 1, 1), through_month=date(2026, 1, 1), today=date(2026, 2, 1))
    today = date(2026, 2, 10)
    r = rem(w, today, "overdue_payment")
    assert len(r) == 1 and r[0]["severity"] == "critical" and r[0]["amount"] == D("1370.00") and r[0]["entity_id"] == w.sub_l.id  # Verbindlichkeiten (Hauptmiete) zählen nicht
    rent = w.db.scalars(select(C.Charge).where(C.Charge.lease_id == w.sub_l.id, C.Charge.charge_type == "base_rent")).one()
    P.create_payment(w.db, None, direction="in", booking_date=date(2026, 1, 5), amount=D("500.00"), allocations=[{"charge_id": rent.id, "amount": D("500.00")}])
    assert rem(w, today, "overdue_payment")[0]["amount"] == D("870.00")
    assert rem(w, date(2026, 1, 1), "overdue_payment") == []  # am Fälligkeitstag noch nicht überfällig


def test_deposit_overdue_reminder(w):
    d = DEP.ensure_deposit(w.db, None, w.sub_l.id, agreed_amount=D("1000.00"), due_date=date(2026, 1, 15))
    assert [r["entity_id"] for r in rem(w, date(2026, 2, 1), "deposit_overdue")] == [d.id]
    DEP.add_transaction(w.db, None, d.id, kind="paid", amount=D("1000.00"), transaction_date=date(2026, 1, 20))
    assert rem(w, date(2026, 2, 1), "deposit_overdue") == []


def test_repair_reminders_upcoming_overdue_urgent_and_closed_excluded(w):
    today = date(2026, 3, 15)
    mk = lambda title, **kw: R.create_repair(w.db, None, property_id=w.prop.id, title=title, reported_on=today, **kw)
    soon = mk("Termin bald", scheduled_for=date(2026, 3, 18))
    far = mk("Termin fern", scheduled_for=date(2026, 4, 30))
    late = mk("Termin verpasst", scheduled_for=date(2026, 3, 10))
    urgent = mk("Wasser läuft", priority="urgent")
    done = mk("Erledigt", scheduled_for=date(2026, 3, 1))
    R.set_status(w.db, None, done.id, "done")
    by = {r["entity_id"]: r for r in REM.compute(w.db, today) if r["entity_type"] == "repair"}
    assert by[soon.id]["type"] == "repair_upcoming" and by[late.id]["type"] == "repair_overdue" and by[urgent.id]["type"] == "repair_urgent"
    assert far.id not in by and done.id not in by
    assert by[late.id]["severity"] == "critical" and by[soon.id]["severity"] == "info"


def test_utility_statement_reminder_for_previous_year_until_recorded(w):
    main = w.main_l  # läuft seit 2025-01-01 mit NK-Vorauszahlung → für 2025 wird eine Abrechnung erwartet
    r = rem(w, date(2026, 2, 1), "utility_statement_due")
    assert len(r) == 1 and r[0]["entity_id"] == main.id and "2025" in r[0]["title"] and "Fristen sind rechtlich zu prüfen" in r[0]["detail"]
    U.create_statement(w.db, None, main_lease_id=main.id, period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), unit_ids=[w.we1.id])
    assert rem(w, date(2026, 2, 1), "utility_statement_due") == []
    assert rem(w, date(2025, 6, 1), "utility_statement_due") == []  # für das laufende Jahr noch keine Abrechnung fällig
    flat = w.main(nk_mode="flat_rate", nk=D("100.00"))
    L.activate_lease(w.db, None, flat.id)
    assert all(x["entity_id"] != flat.id for x in rem(w, date(2026, 2, 1), "utility_statement_due"))  # Pauschale: keine Abrechnung erwartet


def test_missing_document_reminder_resolves_after_upload(w, settings):
    r = {x["doc_type"] for x in rem(w, date(2026, 2, 1), "missing_document") if x["entity_id"] == w.sub_l.id}
    assert r == {"mietvertrag", "uebergabeprotokoll"}
    store = LocalFileStore(settings.documents_path, 4096)
    DOC.upload(w.db, store, None, stream=io.BytesIO(b"%PDF-1"), filename="mv.pdf", doc_type="mietvertrag", entity_type="lease", entity_id=w.sub_l.id)
    r = {x["doc_type"] for x in rem(w, date(2026, 2, 1), "missing_document") if x["entity_id"] == w.sub_l.id}
    assert r == {"uebergabeprotokoll"}
    assert [x["severity"] for x in rem(w, date(2026, 2, 1), "missing_document") if x["doc_type"] == "uebergabeprotokoll"][0] == "info"


def test_reminders_are_sorted_stable_and_have_unique_keys(w):
    C.generate_charges(w.db, None, from_month=date(2026, 1, 1), through_month=date(2026, 1, 1), today=date(2026, 2, 1))
    R.create_repair(w.db, None, property_id=w.prop.id, title="x", reported_on=date(2026, 2, 1), scheduled_for=date(2026, 2, 12))
    a, b = REM.compute(w.db, date(2026, 2, 10)), REM.compute(w.db, date(2026, 2, 10))
    assert a == b and len({r["key"] for r in a}) == len(a)
    sev = [REM.SEV_ORDER[r["severity"]] for r in a]
    assert sev == sorted(sev) and a[0]["severity"] == "critical"


def test_no_reminder_for_inactive_or_cancelled_contracts(w):
    L.update_lease(w.db, None, w.sub_l.id, {"end_date": date(2026, 3, 1)})
    draft = w.sub([w.ru_unit(w.we1)], [w.tenant("Entwurf Mieter")], date(2026, 1, 1), date(2026, 3, 1), activate=False)
    assert all(r["entity_id"] != draft.id for r in rem(w, date(2026, 2, 15)))  # Entwürfe lösen nichts aus
    L.cancel_lease(w.db, None, draft.id, "storniert")
    assert all(r["entity_id"] != draft.id for r in rem(w, date(2026, 2, 15)))


# ---- Historie -------------------------------------------------------------------------------------------------------------------------------------------
def test_party_timeline_merges_sources_orders_and_excludes_others(w):
    other = w.tenant("Fremder Mieter")
    rep = R.create_repair(w.db, w.user.id, property_id=w.prop.id, title="Heizung", reported_on=date(2026, 2, 1), lease_id=w.sub_l.id, reported_by_party_id=w.tenant_p.id)
    R.set_status(w.db, w.user.id, rep.id, "in_progress")
    COM.create(w.db, w.user.id, channel="email", direction="in", subject="Frage zur Nebenkostenabrechnung", party_id=w.tenant_p.id, occurred_at=datetime(2026, 2, 5, tzinfo=timezone.utc))
    COM.create(w.db, w.user.id, channel="email", direction="in", subject="NUR FÜR FREMDEN", party_id=other.id)
    T.create_task(w.db, w.user.id, title="Antwort vorbereiten", party_id=w.tenant_p.id)
    T.create_task(w.db, w.user.id, title="Fremde Aufgabe", party_id=other.id)
    DEP.add_transaction(w.db, w.user.id, DEP.ensure_deposit(w.db, w.user.id, w.sub_l.id, agreed_amount=D("100.00")).id, kind="paid", amount=D("100.00"), transaction_date=date(2026, 1, 5))
    tl = H.party_timeline(w.db, w.tenant_p.id)
    text = " | ".join(i["summary"] for i in tl)
    for needle in ("Partei angelegt: Max Mustermann", "Untermietvertrag", "Reparatur #", "Frage zur Nebenkostenabrechnung", "Aufgabe erstellt: Antwort vorbereiten", "Kaution vereinbart", "Kautionsbuchung: paid"):
        assert needle in text, needle
    assert "NUR FÜR FREMDEN" not in text and "Fremde Aufgabe" not in text and "Fremder Mieter" not in text
    ats = [i["at"] for i in tl]
    assert ats == sorted(ats, reverse=True) and {i["source"] for i in tl} == {"audit", "communication", "repair"}
    assert any(i["actor"] == "Tester" for i in tl)  # Wer hat es getan


def test_entity_timelines_for_lease_property_and_repair(w):
    COM.create(w.db, w.user.id, channel="phone", direction="in", subject="Anruf Vertrag", lease_id=w.sub_l.id)
    COM.create(w.db, w.user.id, channel="letter", direction="out", subject="Brief Objekt", property_id=w.prop.id)
    rep = R.create_repair(w.db, w.user.id, property_id=w.prop.id, title="Fenster", reported_on=date(2026, 2, 1))
    R.add_note(w.db, w.user.id, rep.id, "Glaser kommt")
    assert any("Anruf Vertrag" in i["summary"] for i in H.entity_timeline(w.db, "lease", w.sub_l.id))
    assert not any("Brief Objekt" in i["summary"] for i in H.entity_timeline(w.db, "lease", w.sub_l.id))
    assert any("Brief Objekt" in i["summary"] for i in H.entity_timeline(w.db, "property", w.prop.id))
    rt = H.entity_timeline(w.db, "repair", rep.id)
    assert any("Glaser kommt" in i["summary"] for i in rt) and any("gemeldet" in i["summary"].lower() or "Gemeldet" in i["summary"] for i in rt)
