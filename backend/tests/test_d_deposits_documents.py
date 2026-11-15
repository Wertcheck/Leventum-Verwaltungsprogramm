import io
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select

from leventum.models import AuditEvent, Charge, Payment
from leventum.services import deposits as DEP, documents as DOC, leases as L
from leventum.services.errors import ServiceError
from leventum.storage import LocalFileStore
from tests.helpers import World


@pytest.fixture
def w(app):
    w = World(app)
    w.main_l = w.activate_main()
    w.sub_l = w.sub([w.ru_unit(w.we2)], [w.tenant("Max Mustermann")], date(2026, 1, 1), None)
    yield w
    w.db.close()


def S(w, d): return DEP.summary(d, w.db.get(L.Lease, d.lease_id), date(2026, 6, 1))


def test_main_and_sub_deposits_are_independent(w):
    dm = DEP.ensure_deposit(w.db, None, w.main_l.id, agreed_amount=D("2550.00"), due_date=date(2026, 1, 1))
    ds = DEP.ensure_deposit(w.db, None, w.sub_l.id, agreed_amount=D("3450.00"), due_date=date(2026, 1, 1))
    DEP.add_transaction(w.db, None, ds.id, kind="paid", amount=D("3450.00"), transaction_date=date(2026, 1, 3))
    sm, ss = S(w, dm), S(w, ds)
    assert (ss["status"], ss["held"], ss["open"], ss["lease_kind"]) == ("paid", D("3450.00"), D("0.00"), "sub")
    assert (sm["status"], sm["held"], sm["open"], sm["lease_kind"]) == ("open", D("0.00"), D("2550.00"), "main")  # keine Verrechnung, kein Durchreichen
    assert "Leventum → Vermieter" in sm["direction_note"] and "Mieter → Leventum" in ss["direction_note"]
    assert DEP.ensure_deposit(w.db, None, w.sub_l.id, agreed_amount=D("3450.00")).id == ds.id  # je Vertrag genau eine Kaution


def test_agreed_amount_defaults_from_lease_and_partial_payments_and_overdue(w):
    w.sub_l.deposit_amount = D("1000.00")
    d = DEP.ensure_deposit(w.db, None, w.sub_l.id, due_date=date(2026, 2, 1))
    assert d.agreed_amount == D("1000.00")
    DEP.add_transaction(w.db, None, d.id, kind="paid", amount=D("400.00"), transaction_date=date(2026, 2, 5))
    s = S(w, d)
    assert (s["status"], s["paid"], s["open"], s["overdue"]) == ("partially_paid", D("400.00"), D("600.00"), True)
    with pytest.raises(ServiceError) as e:
        DEP.add_transaction(w.db, None, d.id, kind="paid", amount=D("700.00"), transaction_date=date(2026, 2, 6))
    assert e.value.code == "exceeds_open"
    DEP.add_transaction(w.db, None, d.id, kind="paid", amount=D("600.00"), transaction_date=date(2026, 3, 1))
    assert S(w, d)["status"] == "paid" and S(w, d)["overdue"] is False


def test_refund_partial_retention_with_reason_and_limits(w):
    d = DEP.ensure_deposit(w.db, None, w.sub_l.id, agreed_amount=D("1000.00"))
    DEP.add_transaction(w.db, None, d.id, kind="paid", amount=D("1000.00"), transaction_date=date(2026, 1, 5))
    with pytest.raises(ServiceError) as e:
        DEP.add_transaction(w.db, None, d.id, kind="retained", amount=D("150.00"), transaction_date=date(2026, 7, 1))
    assert e.value.code == "reason_required"
    DEP.add_transaction(w.db, None, d.id, kind="retained", amount=D("150.00"), transaction_date=date(2026, 7, 1), reason="Beschädigung Parkett (Beispiel)")
    DEP.add_transaction(w.db, None, d.id, kind="refunded", amount=D("300.00"), transaction_date=date(2026, 7, 5))
    s = S(w, d)
    assert (s["held"], s["refunded"], s["retained"], s["status"]) == (D("550.00"), D("300.00"), D("150.00"), "partially_refunded")
    with pytest.raises(ServiceError) as e:
        DEP.add_transaction(w.db, None, d.id, kind="refunded", amount=D("550.01"), transaction_date=date(2026, 7, 6))
    assert e.value.code == "exceeds_held"
    DEP.add_transaction(w.db, None, d.id, kind="refunded", amount=D("550.00"), transaction_date=date(2026, 7, 6))
    assert S(w, d)["status"] == "settled" and S(w, d)["held"] == D("0.00")


def test_void_transaction_keeps_history_and_prevents_negative_held(w):
    d = DEP.ensure_deposit(w.db, None, w.sub_l.id, agreed_amount=D("500.00"))
    paid = DEP.add_transaction(w.db, None, d.id, kind="paid", amount=D("500.00"), transaction_date=date(2026, 1, 5))
    DEP.add_transaction(w.db, None, d.id, kind="refunded", amount=D("100.00"), transaction_date=date(2026, 7, 5))
    with pytest.raises(ServiceError) as e:
        DEP.void_transaction(w.db, None, paid.id, "Falsch gebucht")
    assert e.value.code == "would_underflow" and paid.voided_at is None
    refund = d.transactions[1]
    DEP.void_transaction(w.db, None, refund.id, "Fehlbuchung")
    assert S(w, d)["refunded"] == D("0.00") and len(d.transactions) == 2  # Zeile bleibt erhalten
    assert w.db.scalar(select(AuditEvent).where(AuditEvent.action == "deposit.transaction_voided")) is not None


def test_deposits_are_outside_charges_payments_and_economics(w):
    from leventum.services import economics as E
    d = DEP.ensure_deposit(w.db, None, w.sub_l.id, agreed_amount=D("3450.00"))
    DEP.add_transaction(w.db, None, d.id, kind="paid", amount=D("3450.00"), transaction_date=date(2026, 1, 5))
    dm = DEP.ensure_deposit(w.db, None, w.main_l.id, agreed_amount=D("2550.00"))
    DEP.add_transaction(w.db, None, dm.id, kind="paid", amount=D("2550.00"), transaction_date=date(2026, 1, 5))
    assert w.db.scalar(select(func.count()).select_from(Payment)) == 0 and w.db.scalar(select(func.count()).select_from(Charge)) == 0
    r = E.Engine(w.db, date(2026, 1, 1), date(2026, 1, 31)).report("portfolio")
    assert r["ist"]["in_total"] == D("0.00") and r["ist"]["out_total"] == D("0.00")  # Kautionszahlungen sind kein Ist-Zahlungsfluss
    assert r["deposits"].startswith("ausgeschlossen")


def test_deposit_validation(w):
    with pytest.raises(ServiceError):
        DEP.ensure_deposit(w.db, None, w.sub_l.id)  # kein Betrag, Vertrag ohne deposit_amount
    d = DEP.ensure_deposit(w.db, None, w.sub_l.id, agreed_amount=D("100.00"))
    DEP.add_transaction(w.db, None, d.id, kind="paid", amount=D("100.00"), transaction_date=date(2026, 1, 5))
    with pytest.raises(ServiceError):
        DEP.ensure_deposit(w.db, None, w.sub_l.id, agreed_amount=D("50.00"))  # unter bereits gezahltem Betrag
    with pytest.raises(ServiceError):
        DEP.add_transaction(w.db, None, d.id, kind="paid", amount=D("0.00"), transaction_date=date(2026, 1, 5))


def test_documents_are_validated_linked_and_stored_outside_db(w, settings):
    store = LocalFileStore(settings.documents_path, 1024)
    d = DEP.ensure_deposit(w.db, None, w.sub_l.id, agreed_amount=D("100.00"))
    doc = DOC.upload(w.db, store, None, stream=io.BytesIO(b"%PDF-1.4 beleg"), filename="Kautionsbeleg.pdf", doc_type="kaution", entity_type="deposit", entity_id=d.id)
    assert DOC.for_entity(w.db, "deposit", d.id) == [doc] and doc.storage_key != "Kautionsbeleg.pdf" and store.exists(doc.storage_key)
    for kw in (dict(filename="x.exe", stream=io.BytesIO(b"MZ")), dict(filename="x.pdf", stream=io.BytesIO(b"kein pdf"))):
        with pytest.raises(ServiceError) as e:
            DOC.upload(w.db, store, None, doc_type="kaution", entity_type="deposit", entity_id=d.id, **kw)
        assert e.value.code == "invalid_file"
    with pytest.raises(ServiceError):
        DOC.upload(w.db, store, None, stream=io.BytesIO(b"%PDF-1"), filename="a.pdf", doc_type="kaution", entity_type="deposit", entity_id=999)
    with pytest.raises(ServiceError):
        DOC.upload(w.db, store, None, stream=io.BytesIO(b"%PDF-1"), filename="a.pdf", doc_type="kaution", entity_type="secrets", entity_id=1)
