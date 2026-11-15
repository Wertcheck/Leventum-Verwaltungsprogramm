"""Master-Review P1: Dokument-Integrität, endgültige Löschung, Datenintegrität, Objektzusammenfassung."""
import hashlib
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from leventum.models import AppUser, AuditEvent, Document, Role
from leventum.security.passwords import hash_password
from leventum.services import documents as DOC, integrity, master as M, payments as P
from leventum.services.errors import ServiceError
from leventum.storage import LocalFileStore
from tests.conftest import PW
from tests.helpers import World

V = "/api/v1"


@pytest.fixture
def w(app):
    w = World(app)
    yield w
    w.db.close()


@pytest.fixture
def store(settings):
    return LocalFileStore(settings.documents_path, 8192)


def up(w, store, data=b"%PDF-1.4 Inhalt", name="a.pdf"):
    return DOC.upload(w.db, store, w.user.id, stream=io.BytesIO(data), filename=name, doc_type="sonstige", entity_type="property", entity_id=w.prop.id)


# ---- Speicherung / Integrität ---------------------------------------------------------------------------------------------------------------
def test_upload_stores_exact_bytes_size_and_hash_and_roundtrips(w, store):
    data = b"%PDF-1.4 " + bytes(range(256)) * 10
    d = up(w, store, data)
    assert d.size == len(data) and d.sha256 == hashlib.sha256(data).hexdigest()
    with store.open(d.storage_key) as fh:
        assert fh.read() == data  # tatsächliche Bytes, nicht nur eine Datenbankreferenz
    assert DOC.verify(store, d) == {"ok": True, "problem": None, "message": "Datei vorhanden und unverändert."}


def test_verify_detects_missing_truncated_modified_and_unreadable_files(w, store, settings):
    d = up(w, store, b"%PDF-1.4 original")
    path = settings.documents_path / d.storage_key
    path.write_bytes(b"%PDF-1.4 manipula")  # gleiche Länge (17 Byte), anderer Inhalt
    assert DOC.verify(store, d)["problem"] == "hash_mismatch"
    path.write_bytes(b"%PDF")
    assert DOC.verify(store, d)["problem"] == "size_mismatch"
    path.unlink()
    assert DOC.verify(store, d)["problem"] == "missing"
    d2 = up(w, store, b"%PDF-1.4 zweite")
    (settings.documents_path / d2.storage_key).unlink()
    (settings.documents_path / d2.storage_key).mkdir()  # Verzeichnis statt Datei → nicht lesbar
    assert DOC.verify(store, d2)["problem"] in ("unreadable", "missing")
    bad = {p["document_id"] for p in DOC.verify_all(w.db, store)}
    assert {d.id, d2.id} <= bad


# ---- Löschen / Aufbewahrung / endgültige Entfernung ------------------------------------------------------------------------------------------
def test_purge_rules_deleted_first_retention_reason_audit_and_file_removed(w, store, settings):
    d = up(w, store)
    with pytest.raises(ServiceError) as e:
        DOC.purge(w.db, store, w.user.id, d.id, "Frist abgelaufen", 3650)
    assert e.value.code == "not_deleted"
    DOC.soft_delete(w.db, w.user.id, d.id, "falsch hochgeladen")
    assert store.exists(d.storage_key)  # Weichlöschung entfernt die Datei NICHT
    with pytest.raises(ServiceError) as e:
        DOC.purge(w.db, store, w.user.id, d.id, "zu früh", 3650)
    assert e.value.code == "retention_period" and store.exists(d.storage_key)
    d.uploaded_at = datetime.now(timezone.utc) - timedelta(days=3651)
    with pytest.raises(ServiceError):
        DOC.purge(w.db, store, w.user.id, d.id, "  ", 3650)
    DOC.purge(w.db, store, w.user.id, d.id, "Aufbewahrungsfrist abgelaufen", 3650)
    assert d.purged_at is not None and not store.exists(d.storage_key) and d.sha256  # Datei weg, Nachweis (Hash) bleibt
    ev = w.db.scalars(select(AuditEvent).where(AuditEvent.action == "document.purged")).one()
    assert ev.details["sha256"] == d.sha256 and ev.details["reason"] == "Aufbewahrungsfrist abgelaufen"
    with pytest.raises(ServiceError) as e:
        DOC.purge(w.db, store, w.user.id, d.id, "nochmal", 3650)
    assert e.value.code == "already_purged"
    assert DOC.verify(store, d)["problem"] == "purged"


# ---- API: Download-Prüfung, Rechte -----------------------------------------------------------------------------------------------------------------
@pytest.fixture
def uploaded(auth_client, settings):
    c = auth_client
    prop = c.post(V + "/properties", json={"name": "H", "property_type": "wohnung"}).json()
    r = c.post(V + "/documents", data={"entity_type": "property", "entity_id": prop["id"], "doc_type": "sonstige"}, files={"file": ("Beleg.pdf", b"%PDF-1.4 echter Inhalt", "application/pdf")})
    assert r.status_code == 201
    return c, r.json(), settings


def test_download_verifies_integrity_and_reports_missing_or_corrupt(uploaded, app):
    c, doc, settings = uploaded
    ok = c.get(V + f"/documents/{doc['id']}/download")
    assert ok.status_code == 200 and ok.content == b"%PDF-1.4 echter Inhalt" and c.get(V + f"/documents/{doc['id']}/verify").json()["ok"] is True
    with app.state.session_factory() as db:
        key = db.scalar(select(Document.storage_key))
    path = settings.documents_path / key
    path.write_bytes(b"%PDF-1.4 FALSCHER Inhalt")
    r = c.get(V + f"/documents/{doc['id']}/download")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "file_corrupt"  # beschädigte Datei wird NICHT ausgeliefert
    assert c.get(V + "/documents/verify-all").json()["ok"] is False
    assert c.get(V + "/system/integrity").json()["documents"]["ok"] is False
    path.unlink()
    r = c.get(V + f"/documents/{doc['id']}/download")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "file_missing"
    with app.state.session_factory() as db:
        assert db.scalars(select(AuditEvent).where(AuditEvent.action == "document.integrity_failed")).all()  # protokolliert


def test_purge_endpoint_requires_admin_confirmation_and_retention(uploaded, app):
    c, doc, settings = uploaded
    assert c.post(V + f"/documents/{doc['id']}/purge", json={"reason": "x", "confirm": False}).status_code in (400, 422)
    assert c.post(V + f"/documents/{doc['id']}/purge", json={"reason": "x", "confirm": True}).status_code == 409  # nicht gelöscht
    c.post(V + f"/documents/{doc['id']}/delete", json={"reason": "falsch"})
    assert c.post(V + f"/documents/{doc['id']}/purge", json={"reason": "x", "confirm": True}).json()["detail"]["code"] == "retention_period"
    with app.state.session_factory() as db:
        db.add(AppUser(username="verw", display_name="V", password_hash=hash_password(PW), role_id=db.scalar(select(Role.id).where(Role.code == "verwaltung"))))
        d = db.scalar(select(Document)); d.uploaded_at = datetime.now(timezone.utc) - timedelta(days=4000)
        db.commit()
    other = TestClient(app, headers={"X-Leventum-Client": "1"})
    other.post(V + "/auth/login", json={"username": "verw", "password": PW})
    assert other.post(V + f"/documents/{doc['id']}/purge", json={"reason": "x", "confirm": True}).status_code == 403  # nur Administrator
    ok = c.post(V + f"/documents/{doc['id']}/purge", json={"reason": "Frist abgelaufen", "confirm": True})
    assert ok.status_code == 200 and ok.json()["purged_at"]
    assert c.get(V + f"/documents/{doc['id']}/download").status_code == 404


# ---- Datenintegrität -----------------------------------------------------------------------------------------------------------------------------------
def test_integrity_check_is_clean_for_valid_data_and_finds_injected_faults(w):
    w.activate_main()
    w.sub([w.ru_bed(w.bed1)], [w.tenant("A B")], date(2026, 1, 1), None, type_code="bett")
    assert integrity.check(w.db)["ok"] is True
    w.db.commit()
    # Fehler am Service vorbei einschleusen
    w.db.execute(text("UPDATE rentable_unit SET space_key = 'FALSCH' WHERE id = 1"))
    w.db.execute(text("UPDATE room SET unit_id = 2 WHERE id = 1"))  # Zimmer wandert in andere Wohneinheit → Eltern-Kette der Betten-Einheit stimmt nicht mehr
    w.db.commit()
    w.db.expire_all()  # direktes SQL umgeht den Sitzungscache
    codes = {f["code"] for f in integrity.check(w.db)["findings"]}
    assert {"space_key_mismatch", "bad_parent_chain"} <= codes


def test_integrity_detects_overlapping_subleases_and_over_allocations(w):
    from leventum.models import Charge, Lease, LeaseItem, PaymentAllocation
    w.activate_main()
    a = w.sub([w.ru_unit(w.we2)], [w.tenant("A B")], date(2026, 1, 1), None)
    b = w.sub([w.ru_unit(w.we1)], [w.tenant("C D")], date(2026, 1, 1), None)
    b.items[0].rentable_unit = a.items[0].rentable_unit  # am Service vorbei auf dieselbe Einheit
    w.db.flush()
    c = Charge(lease_id=a.id, direction="receivable", charge_type="base_rent", period_start=date(2026, 1, 1), period_end=date(2026, 1, 31), due_date=date(2026, 1, 1), amount=D("100.00"), dedupe_key="x")
    w.db.add(c); w.db.flush()
    pay = P.create_payment(w.db, None, direction="in", booking_date=date(2026, 1, 2), amount=D("500.00"))
    w.db.add(PaymentAllocation(payment_id=pay.id, charge_id=c.id, amount=D("300.00")))  # über Betrag der Sollstellung
    w.db.flush()
    codes = {f["code"] for f in integrity.check(w.db)["findings"]}
    assert {"overlapping_subleases", "charge_over_allocated"} <= codes


def test_property_summary_distinguishes_existing_rooms_from_created_rentable_units(w):
    w.ru_unit(w.we1); w.ru_room(w.room2); w.ru_bed(w.bed1)
    from tests.test_d_api import V as _V  # noqa
    s = {"units": 2, "rooms": 2, "beds": 2}
    from leventum.api.master import properties_get
    out = properties_get(w.prop.id, db=w.db)["summary"]
    assert (out["units"], out["rooms"], out["beds"]) == (2, 2, 2)
    assert out["rentable"]["unit"] == {"created": 1, "possible": 2} and out["rentable"]["room"] == {"created": 1, "possible": 2}
    assert out["rentable"]["bed"] == {"created": 1, "possible": 2} and out["rentable"]["property"] == {"created": 0, "possible": 1}


# ---- Zentrale Definitionen: laufender Vertrag, Phase, aktiver Mieter (Befund B2) ---------------------------------------------------------------
def test_phase_and_is_running_cover_all_states(w):
    from leventum.services import leases as L
    w.activate_main()
    today = date(2026, 6, 15)
    mk = lambda s, e, tn: w.sub([w.ru_unit(w.we2)], [w.tenant(tn)], s, e, activate=False)
    future = mk(date(2026, 9, 1), None, "Zu Kunft"); L.activate_lease(w.db, None, future.id)
    assert L.phase(future, today) == "upcoming" and not L.is_running(future, today) and L.is_running(future, date(2026, 9, 1))
    cur = w.sub([w.ru_unit(w.we1)], [w.tenant("Ak Tiv")], date(2026, 1, 1), None)
    assert L.phase(cur, today) == "active" and L.is_running(cur, today)
    L.terminate_lease(w.db, None, cur.id, terminated_on=date(2026, 5, 1), effective_on=date(2026, 8, 31))
    assert L.phase(cur, today) == "notice" and L.is_running(cur, today)  # gekündigt, aber noch laufend
    assert L.phase(cur, date(2026, 9, 1)) == "ended" and not L.is_running(cur, date(2026, 9, 1))
    drafts = w.sub([w.ru_unit(w.we1)], [w.tenant("Ent Wurf")], date(2027, 1, 1), None, activate=False)
    assert L.phase(drafts, today) == "draft" and not L.is_running(drafts, today)
    L.cancel_lease(w.db, None, drafts.id, "storniert")
    assert L.phase(drafts, today) == "cancelled"


def test_dashboard_counts_follow_central_definitions_and_explain_notice(w, app):
    from leventum.services import dashboard as D, leases as L
    w.activate_main()
    keller = w.tenant("Thomas Keller")
    s1 = w.sub([w.ru_unit(w.we1)], [w.tenant("Anna Aktiv")], date(2026, 1, 1), None)
    s2 = w.sub([w.ru_unit(w.we2)], [keller], date(2026, 1, 1), None)
    L.terminate_lease(w.db, None, s2.id, terminated_on=date(2026, 10, 20), effective_on=date.today().replace(year=date.today().year + 1))
    w.tenant("Lisa Ohne Vertrag")  # Person ohne Vertrag
    only_ended = w.tenant("Egon Ehemalig")
    w.db.commit()
    d = D.build_dashboard(w.db)
    k = {x["key"]: x for x in d["kpis"]}
    assert k["active_subleases"]["value"] == 2 and k["active_subleases"]["hint"] == "davon 1 in Kündigung"
    assert k["active_tenants"]["value"] == 2 and k["active_tenants"]["hint"] == "davon 1 in Kündigung"  # Lisa und Egon zählen nicht
    assert all(x["definition"] for x in d["kpis"]) and "laufenden Untermietvertrag" in k["active_tenants"]["definition"]
    assert only_ended.id and s1.id
