import io
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from leventum.models import AuditEvent, Task
from leventum.services import communications as COM, documents as DOC, leases as L, repairs as R
from leventum.services.errors import ServiceError
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


@pytest.fixture
def store(settings):
    return LocalFileStore(settings.documents_path, 4096)


# ---- Kommunikation ------------------------------------------------------------------------------------------------------------------------------
def test_communication_requires_reference_and_valid_values(w):
    for kw in (dict(channel="email", direction="in", subject="x"), dict(channel="fax", direction="in", subject="x", party_id=1),
               dict(channel="email", direction="sideways", subject="x", party_id=1), dict(channel="email", direction="in", subject=" ", party_id=1),
               dict(channel="email", direction="in", subject="x", lease_id=999)):
        with pytest.raises(ServiceError):
            COM.create(w.db, None, **kw)


def test_communication_log_filters_and_chronological_order(w):
    t0 = datetime(2026, 2, 1, 10, tzinfo=timezone.utc)
    a = COM.create(w.db, w.user.id, channel="email", direction="in", subject="Frage zur Heizung", party_id=w.tenant_p.id, lease_id=w.sub_l.id, occurred_at=t0)
    b = COM.create(w.db, w.user.id, channel="phone", direction="out", subject="Rückruf", party_id=w.tenant_p.id, occurred_at=datetime(2026, 2, 2, tzinfo=timezone.utc))
    c = COM.create(w.db, w.user.id, channel="letter", direction="out", subject="Hausordnung", property_id=w.prop.id)
    assert [x.subject for x in COM.query(w.db, party_id=w.tenant_p.id)] == ["Rückruf", "Frage zur Heizung"]
    assert [x.id for x in COM.query(w.db, lease_id=w.sub_l.id)] == [a.id] and [x.id for x in COM.query(w.db, channel="letter")] == [c.id]
    assert b.created_by_user_id == w.user.id


def test_follow_up_task_inherits_references_and_nothing_is_sent(w):
    c = COM.create(w.db, None, channel="email", direction="in", subject="Wasserschaden", party_id=w.tenant_p.id, lease_id=w.sub_l.id,
                   follow_up={"title": "Rückruf Mieter", "due_date": date(2026, 3, 1), "priority": "high"})
    t = w.db.scalars(select(Task).where(Task.title == "Rückruf Mieter")).one()
    assert (t.party_id, t.lease_id, t.priority, t.due_date) == (w.tenant_p.id, w.sub_l.id, "high", date(2026, 3, 1))
    assert c.id and not hasattr(COM, "send") and not [n for n in dir(COM) if "send" in n.lower() or "smtp" in n.lower()]


def test_handover_protocol_rules_and_audit(w):
    h = COM.create_handover(w.db, w.user.id, lease_id=w.sub_l.id, kind="move_in", protocol_date=date(2026, 1, 1), unit_id=w.we2.id, keys_handed=3,
                            meter_readings="Strom 1234,5; Wasser 88,1", condition_notes="Wände weiß, keine Mängel", signed=True)
    assert h.signed and h.keys_handed == 3
    for kw in (dict(kind="umzug"), dict(kind="move_in", unit_id=999)):
        with pytest.raises(ServiceError):
            COM.create_handover(w.db, None, lease_id=w.sub_l.id, protocol_date=date(2026, 1, 1), **kw)
    other = __import__("leventum.services.master", fromlist=["x"]).create_property(w.db, None, {"name": "Fremd", "property_type": "wohnung"})
    fu = __import__("leventum.services.master", fromlist=["x"]).create_unit(w.db, None, other.id, {"unit_number": "9"})
    with pytest.raises(ServiceError):
        COM.create_handover(w.db, None, lease_id=w.sub_l.id, kind="move_out", protocol_date=date(2026, 6, 1), unit_id=fu.id)  # Einheit gehört nicht zum Vertrag
    draft = w.sub([w.ru_unit(w.we1)], [w.tenant("Kein Mieter")], date(2026, 1, 1), None, activate=False)
    L.cancel_lease(w.db, None, draft.id, "Absage")
    with pytest.raises(ServiceError):
        COM.create_handover(w.db, None, lease_id=draft.id, kind="move_in", protocol_date=date(2026, 1, 1))
    assert w.db.scalar(select(AuditEvent).where(AuditEvent.action == "handover.created")) is not None


# ---- Dokumente ---------------------------------------------------------------------------------------------------------------------------------------
def up(w, store, name="a.pdf", typ="sonstige", ent="lease", eid=None, data=b"%PDF-1.4 x"):
    return DOC.upload(w.db, store, w.user.id, stream=io.BytesIO(data), filename=name, doc_type=typ, entity_type=ent, entity_id=eid or w.sub_l.id)


def test_documents_for_all_entity_types_and_search(w, store):
    rep = R.create_repair(w.db, None, property_id=w.prop.id, title="x", reported_on=date(2026, 1, 1))
    task = __import__("leventum.services.tasks", fromlist=["x"]).create_task(w.db, None, title="t")
    comm = COM.create(w.db, None, channel="email", direction="in", subject="s", party_id=w.tenant_p.id)
    ho = COM.create_handover(w.db, None, lease_id=w.sub_l.id, kind="move_in", protocol_date=date(2026, 1, 1))
    for ent, eid in (("repair", rep.id), ("task", task.id), ("communication", comm.id), ("handover_protocol", ho.id), ("party", w.tenant_p.id), ("property", w.prop.id), ("unit", w.we1.id)):
        d = up(w, store, f"{ent}.pdf", "sonstige", ent, eid)
        assert DOC.for_entity(w.db, ent, eid) == [d]
    up(w, store, "Mietvertrag Müller.pdf", "mietvertrag")
    up(w, store, "Rechnung Sanitär.pdf", "rechnung")
    assert [d.original_name for d in DOC.query(w.db, q="müller")] == ["Mietvertrag Müller.pdf"]
    assert [d.original_name for d in DOC.query(w.db, doc_type="rechnung")] == ["Rechnung Sanitär.pdf"]
    assert len(DOC.query(w.db, entity_type="lease", entity_id=w.sub_l.id)) == 2 and len(DOC.query(w.db, entity_type="lease", entity_id=999)) == 0


def test_document_can_be_linked_to_additional_entities_once(w, store):
    d = up(w, store, "Mietvertrag.pdf", "mietvertrag")
    DOC.add_link(w.db, None, d.id, "party", w.tenant_p.id)
    DOC.add_link(w.db, None, d.id, "party", w.tenant_p.id)  # idempotent
    assert len(d.links) == 2 and DOC.for_entity(w.db, "party", w.tenant_p.id) == [d]
    with pytest.raises(ServiceError):
        DOC.add_link(w.db, None, d.id, "geheim", 1)
    with pytest.raises(ServiceError):
        DOC.add_link(w.db, None, d.id, "party", 999)


def test_soft_delete_hides_keeps_file_logs_reason_and_is_final(w, store):
    d = up(w, store, "Mietvertrag.pdf", "mietvertrag")
    with pytest.raises(ServiceError):
        DOC.soft_delete(w.db, None, d.id, " ")
    DOC.soft_delete(w.db, w.user.id, d.id, "Versehentlich hochgeladen")
    assert DOC.for_entity(w.db, "lease", w.sub_l.id) == [] and DOC.query(w.db) == [] and DOC.query(w.db, include_deleted=True) == [d]
    assert store.exists(d.storage_key)  # Datei bleibt (Aufbewahrungsfristen offen, Backup enthält sie)
    ev = w.db.scalars(select(AuditEvent).where(AuditEvent.action == "document.deleted")).one()
    assert ev.details["reason"] == "Versehentlich hochgeladen" and ev.actor_user_id == w.user.id
    with pytest.raises(ServiceError):
        DOC.soft_delete(w.db, None, d.id, "nochmal")
    with pytest.raises(ServiceError):
        DOC.add_link(w.db, None, d.id, "party", w.tenant_p.id)  # gelöschte Dokumente werden nicht mehr verknüpft


def test_missing_documents_checklist(w, store):
    assert DOC.missing_for_lease(w.db, w.sub_l) == ["mietvertrag", "uebergabeprotokoll"] and DOC.missing_for_lease(w.db, w.main_l) == ["mietvertrag"]
    contract = up(w, store, "mv.pdf", "mietvertrag")
    assert DOC.missing_for_lease(w.db, w.sub_l) == ["uebergabeprotokoll"]
    COM.create_handover(w.db, None, lease_id=w.sub_l.id, kind="move_in", protocol_date=date(2026, 1, 1))  # Protokolleintrag zählt
    assert DOC.missing_for_lease(w.db, w.sub_l) == []
    DOC.soft_delete(w.db, None, contract.id, "falsche Datei")
    assert DOC.missing_for_lease(w.db, w.sub_l) == ["mietvertrag"]  # gelöschtes Dokument zählt nicht mehr
    up(w, store, "ueb.pdf", "uebergabeprotokoll", "lease", w.main_l.id)  # an anderem Vertrag: zählt nicht
    assert "mietvertrag" in DOC.missing_for_lease(w.db, w.sub_l)
