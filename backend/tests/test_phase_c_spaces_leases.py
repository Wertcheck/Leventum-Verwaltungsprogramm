from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from leventum.models import RentableUnit
from leventum.services import leases as L, master as M
from leventum.services.errors import ServiceError
from tests.helpers import World


@pytest.fixture
def w(app):
    w = World(app)
    yield w
    w.db.close()


def codes(exc): return {e["code"] for e in exc.value.details["errors"]}


# ---- Raumhierarchie / Vermietungseinheit -------------------------------------------------------------------
def test_hierarchy_levels_and_rentable_unit_chain(w):
    ru = {k: getattr(w, f"ru_{k}")(v) if k != "prop" else w.ru_prop() for k, v in
          {"prop": None, "unit": w.we1, "room": w.room1, "bed": w.bed1}.items()}
    assert [ru[k].level for k in ("prop", "unit", "room", "bed")] == ["property", "unit", "room", "bed"]
    b = ru["bed"]
    assert (b.unit_id, b.room_id, b.bed_id) == (w.we1.id, w.room1.id, w.bed1.id)  # Ahnen mitgesetzt
    assert w.ru_bed(w.bed1).id == b.id  # idempotent
    assert M.space_label(w.db, b) == "Haus Bergmann · WE 1 · Zimmer 1 · Bett A"


def test_rentable_unit_rejects_inconsistent_hierarchy(w):
    other = M.create_room(w.db, None, w.we2.id, {"name": "X"})
    with pytest.raises(ServiceError):
        M.ensure_rentable_unit(w.db, None, property_id=w.prop.id, unit_id=w.we1.id, room_id=other.id)


def test_db_check_constraint_rejects_inconsistent_levels(w):
    w.db.commit()
    with pytest.raises(IntegrityError):
        w.db.execute(text("INSERT INTO rentable_unit (level, property_id, unit_id, is_active, created_at, updated_at) "
                          "VALUES ('room', 1, 1, 1, '2026-01-01', '2026-01-01')"))


def test_duplicate_unit_number_room_and_bed_rejected(w):
    with pytest.raises(ServiceError) as e:
        M.create_unit(w.db, None, w.prop.id, {"unit_number": "WE 1"})
    assert e.value.code == "duplicate"
    with pytest.raises(ServiceError):
        M.create_room(w.db, None, w.we1.id, {"name": "Zimmer 1"})
    with pytest.raises(ServiceError):
        M.create_bed(w.db, None, w.room1.id, {"label": "Bett A"})


# ---- Ganze Wohnung / Hauptmietvertrag auf Objektebene --------------------------------------------------------------
def test_whole_flat_sublease_under_property_level_main_lease(w):
    w.activate_main()
    t = w.tenant("Max Mustermann")
    sub = w.sub([w.ru_unit(w.we2)], [t], date(2026, 3, 1), None)
    assert sub.status == "active"
    assert [x for x in L.occupancy_on(w.db, w.ru_unit(w.we2), date(2026, 6, 1))] == [sub]
    assert L.occupancy_on(w.db, w.ru_unit(w.we1), date(2026, 6, 1)) == []  # andere WE leer
    assert L.occupancy_on(w.db, w.ru_unit(w.we2), date(2026, 2, 1)) == []  # vor Mietbeginn leer


def test_rent_to_rent_example_amounts_kept_on_separate_contracts(w):
    main = w.activate_main(rent=D("850.00"), nk=D("180.00"))
    sub = w.sub([w.ru_unit(w.we2)], [w.tenant("Max Mustermann")], date(2026, 1, 1), None, rent=D("1150.00"), nk=D("220.00"))
    day = date(2026, 5, 1)
    m, s = L.monthly_total(main, day), L.monthly_total(sub, day)
    assert (m["base_rent"], m["utility_amount"], m["total"]) == (D("850.00"), D("180.00"), D("1030.00"))
    assert (s["base_rent"], s["utility_amount"], s["total"]) == (D("1150.00"), D("220.00"), D("1370.00"))


def test_sublease_requires_main_lease_coverage(w):
    t = w.tenant("A B")
    with pytest.raises(L.LeaseValidationError) as e:  # kein Hauptmietvertrag
        w.sub([w.ru_unit(w.we1)], [t], date(2026, 1, 1), None)
    assert "not_covered" in codes(e)


def test_coverage_period_and_permission_checks(w):
    w.activate_main(start=date(2026, 1, 1), end=date(2026, 12, 31))
    t = w.tenant("A B")
    with pytest.raises(L.LeaseValidationError) as e:  # Untermiete reicht über Hauptmietende
        w.sub([w.ru_unit(w.we1)], [t], date(2026, 6, 1), date(2027, 3, 31))
    assert "not_covered" in codes(e)
    with pytest.raises(L.LeaseValidationError):  # unbefristet unter befristetem Haupt
        w.sub([w.ru_unit(w.we1)], [t], date(2026, 6, 1), None)
    ok = w.sub([w.ru_unit(w.we1)], [t], date(2026, 6, 1), date(2026, 12, 31))
    assert ok.status == "active"


def test_subletting_not_permitted_or_unclear_blocks(w):
    w.activate_main(permitted=None)  # ungeklärt zählt NICHT als erlaubt
    with pytest.raises(L.LeaseValidationError) as e:
        w.sub([w.ru_unit(w.we1)], [w.tenant("A B")], date(2026, 1, 1), None)
    assert "subletting_not_permitted" in codes(e)


def test_coverage_override_needs_reason_is_downgraded_and_audited(w):
    w.activate_main(permitted=False)
    sub = w.sub([w.ru_unit(w.we1)], [w.tenant("A B")], date(2026, 1, 1), None, coverage_override_reason="Zustimmung des Eigentümers liegt mündlich vor, Nachweis folgt")
    assert sub.status == "active"
    from leventum.models import AuditEvent
    from sqlalchemy import select
    ev = w.db.scalars(select(AuditEvent).where(AuditEvent.action == "lease.activated", AuditEvent.entity_id == str(sub.id))).one()
    assert "Zustimmung" in ev.details["coverage_override_reason"] and "subletting_not_permitted" in ev.details["warnings"]


def test_main_lease_on_units_only_does_not_cover_other_unit(w):
    w.activate_main(rus=[w.ru_unit(w.we1)])
    with pytest.raises(L.LeaseValidationError):
        w.sub([w.ru_unit(w.we2)], [w.tenant("A B")], date(2026, 1, 1), None)
    assert w.sub([w.ru_room(w.room1)], [w.tenant("C D")], date(2026, 1, 1), None).status == "active"  # Zimmer in WE1 gedeckt


# ---- Zimmer / Betten / mehrere Untermietverträge je Wohneinheit ----------------------------------------------------------
def test_two_rooms_in_one_flat_to_different_subtenants(w):
    w.activate_main()
    a, b = w.tenant("Anna Eins"), w.tenant("Bernd Zwei")
    s1 = w.sub([w.ru_room(w.room1)], [a], date(2026, 1, 1), None, type_code="zimmer", rent=D("450.00"), nk=D("60.00"))
    s2 = w.sub([w.ru_room(w.room2)], [b], date(2026, 1, 1), None, type_code="zimmer", rent=D("400.00"), nk=D("50.00"))
    occ = L.occupancy_on(w.db, w.ru_unit(w.we1), date(2026, 2, 1))  # Wohneinheit gilt als belegt
    assert {x.id for x in occ} == {s1.id, s2.id}


def test_whole_flat_conflicts_with_room_lease_and_vice_versa(w):
    w.activate_main()
    w.sub([w.ru_room(w.room1)], [w.tenant("A B")], date(2026, 1, 1), None)
    with pytest.raises(L.LeaseValidationError) as e:
        w.sub([w.ru_unit(w.we1)], [w.tenant("C D")], date(2026, 6, 1), None)
    assert "sub_overlap" in codes(e)
    w2 = w.sub([w.ru_unit(w.we2)], [w.tenant("E F")], date(2026, 1, 1), None)
    with pytest.raises(L.LeaseValidationError):  # umgekehrt: Zimmer in vermieteter WE
        w.sub([w.ru_room(M.create_room(w.db, None, w.we2.id, {"name": "Z"}))], [w.tenant("G H")], date(2026, 2, 1), None)
    assert w2.status == "active"


def test_bed_wise_two_beds_same_room_and_conflicts(w):
    w.activate_main()
    s1 = w.sub([w.ru_bed(w.bed1)], [w.tenant("A B")], date(2026, 1, 1), date(2026, 6, 30), type_code="bett", rent=D("300.00"), nk=D("40.00"))
    s2 = w.sub([w.ru_bed(w.bed2)], [w.tenant("C D")], date(2026, 1, 1), date(2026, 6, 30), type_code="bett", rent=D("300.00"), nk=D("40.00"))
    with pytest.raises(L.LeaseValidationError) as e:  # selbes Bett, überlappend
        w.sub([w.ru_bed(w.bed1)], [w.tenant("E F")], date(2026, 6, 1), date(2026, 8, 31), type_code="bett")
    assert "sub_overlap" in codes(e)
    with pytest.raises(L.LeaseValidationError):  # ganzes Zimmer, obwohl Betten belegt
        w.sub([w.ru_room(w.room1)], [w.tenant("G H")], date(2026, 3, 1), None)
    nxt = w.sub([w.ru_bed(w.bed1)], [w.tenant("E F")], date(2026, 7, 1), None, type_code="bett")  # Folgemieter ohne Überschneidung
    assert nxt.status == "active" and s2.status == "active" and s1.status == "active"


def test_one_lease_multiple_rooms_and_multiple_tenants_and_occupants(w):
    """Firma mietet 2 Zimmer für 3 Monteure (Mieter ≠ Bewohner)."""
    w.activate_main()
    firma = M.create_party(w.db, None, {"kind": "company", "company_name": "Bau GmbH"}, ["tenant"])
    workers = [w.tenant(n) for n in ("Jan Arbeiter", "Piotr Arbeiter", "Karl Arbeiter")]
    lease = L.create_lease(w.db, None, kind="sub", lease_type_id=w.t["monteurwohnung"], start_date=date(2026, 1, 1), end_date=date(2026, 3, 31),
                           is_fixed_term=True, intended_use="monteur",
                           parties=[{"party_id": w.own.id, "role": "lessor"}, {"party_id": firma.id, "role": "lessee"}] +
                                   [{"party_id": x.id, "role": "occupant"} for x in workers],
                           rentable_unit_ids=[w.ru_room(w.room1).id, w.ru_room(w.room2).id])
    L.activate_lease(w.db, None, lease.id)
    assert len(lease.items) == 2 and len([p for p in lease.parties if p.role == "occupant"]) == 3


def test_sequential_subleases_on_same_unit_are_fine(w):
    w.activate_main()
    w.sub([w.ru_unit(w.we1)], [w.tenant("A B")], date(2026, 1, 1), date(2026, 3, 31))
    w.sub([w.ru_unit(w.we1)], [w.tenant("C D")], date(2026, 4, 1), None)  # direkt anschließend
    with pytest.raises(L.LeaseValidationError):
        w.sub([w.ru_unit(w.we1)], [w.tenant("E F")], date(2026, 3, 31), date(2026, 4, 5))  # 1 Tag Überlappung


def test_terminated_lease_frees_space_after_effective_date(w):
    w.activate_main()
    s = w.sub([w.ru_unit(w.we1)], [w.tenant("A B")], date(2026, 1, 1), None)
    L.terminate_lease(w.db, None, s.id, terminated_on=date(2026, 3, 1), effective_on=date(2026, 5, 31))
    with pytest.raises(L.LeaseValidationError):
        w.sub([w.ru_unit(w.we1)], [w.tenant("C D")], date(2026, 5, 1), None)
    assert w.sub([w.ru_unit(w.we1)], [w.tenant("C D")], date(2026, 6, 1), None).status == "active"


def test_draft_does_not_block_and_cancelled_draft_needs_reason(w):
    w.activate_main()
    d = w.sub([w.ru_unit(w.we1)], [w.tenant("A B")], date(2026, 1, 1), None, activate=False)
    assert w.sub([w.ru_unit(w.we1)], [w.tenant("C D")], date(2026, 1, 1), None).status == "active"
    with pytest.raises(L.LeaseValidationError):  # beim Aktivieren des Entwurfs greift die Prüfung
        L.activate_lease(w.db, None, d.id)
    with pytest.raises(ServiceError):
        L.cancel_lease(w.db, None, d.id, "  ")
    assert L.cancel_lease(w.db, None, d.id, "Interessent abgesprungen").status == "cancelled"


def test_main_overlap_is_warning_not_error(w):
    w.activate_main(start=date(2025, 1, 1))
    second = w.main(rus=[w.ru_unit(w.we1)], start=date(2025, 6, 1))
    v = L.validate_lease(w.db, second)
    assert not v.errors and any(x["code"] == "main_overlap" for x in v.warnings)


def test_party_roles_enforced_for_leventum_position(w):
    bad = L.create_lease(w.db, None, kind="main", lease_type_id=w.t["hauptmiete"], start_date=date(2026, 1, 1), end_date=None,
                         parties=[{"party_id": w.owner.id, "role": "lessor"}, {"party_id": w.tenant("A B").id, "role": "lessee"}],
                         rentable_unit_ids=[w.ru_prop().id])
    with pytest.raises(L.LeaseValidationError) as e:
        L.activate_lease(w.db, None, bad.id)
    assert "main_lessee_not_own" in codes(e)
    with pytest.raises(ServiceError):  # Vertragsart nur für Untermiete
        L.create_lease(w.db, None, kind="main", lease_type_id=w.t["zimmer"], start_date=date(2026, 1, 1), end_date=None, parties=[], rentable_unit_ids=[1])


# ---- Rechtliche Einordnung: nie automatisch -----------------------------------------------------------------------------------
def test_no_automatic_legal_classification_for_fixed_term_monteur_or_boardinghouse(w):
    w.activate_main()
    for code in ("monteurwohnung", "boardinghouse", "wohnraum_befristet"):
        s = w.sub([w.ru_unit(w.we2)], [w.tenant("A B")], date(2026, 1, 1), date(2026, 2, 28), type_code=code, is_fixed_term=True, activate=False)
        assert s.legal_basis_ref is None and s.legal_review_status == "not_reviewed" and s.legal_reviewed_at is None
        v = L.validate_lease(w.db, s)
        assert any(h["code"] == "legal_not_reviewed" for h in v.hints)
        w.db.delete(s)
        w.db.flush()


def test_fixed_term_reason_hint_only_where_type_requires_it(w):
    w.activate_main()
    a = w.sub([w.ru_unit(w.we2)], [w.tenant("A B")], date(2026, 1, 1), date(2026, 2, 28), type_code="wohnraum_befristet", is_fixed_term=True, activate=False)
    assert any(h["code"] == "fixed_term_reason_missing" for h in L.validate_lease(w.db, a).hints)
    L.update_lease(w.db, None, a.id, {"fixed_term_reason": "Eigenbedarf ab März (Beispieltext, nicht geprüft)"})
    assert not any(h["code"] == "fixed_term_reason_missing" for h in L.validate_lease(w.db, a).hints)
    w.db.delete(a); w.db.flush()
    b = w.sub([w.ru_unit(w.we2)], [w.tenant("C D")], date(2026, 1, 1), date(2026, 2, 28), type_code="monteurwohnung", is_fixed_term=True, activate=False)
    assert not any(h["code"] == "fixed_term_reason_missing" for h in L.validate_lease(w.db, b).hints)


def test_fixed_term_without_end_is_error(w):
    w.activate_main()
    s = w.sub([w.ru_unit(w.we2)], [w.tenant("A B")], date(2026, 1, 1), None, is_fixed_term=True, activate=False)
    assert "fixed_term_no_end" in {e["code"] for e in L.validate_lease(w.db, s).errors}


def test_legal_review_is_manual_documented_and_audited(w):
    w.activate_main()
    s = w.sub([w.ru_unit(w.we2)], [w.tenant("A B")], date(2026, 1, 1), None)
    L.set_legal_review(w.db, w.user.id, s.id, "reviewed", basis_ref="§ 549 BGB", basis_note="Prüfung durch Rechtsanwalt am 01.02.2026 (Beispiel)")
    assert (s.legal_review_status, s.legal_basis_ref, s.legal_reviewed_by_user_id) == ("reviewed", "§ 549 BGB", w.user.id)
    assert not any(h["code"] == "legal_not_reviewed" for h in L.validate_lease(w.db, s).hints)
    with pytest.raises(ServiceError):  # Direktes Setzen über update_lease ist verboten
        L.update_lease(w.db, None, s.id, {"legal_review_status": "reviewed"})
    n = L.add_note(w.db, None, s.id, "review", "Rückfrage an Kanzlei offen")
    assert n.kind == "review"


# ---- Versionierung ------------------------------------------------------------------------------------------------------------
def test_terms_and_agreements_are_versioned_without_overwrite(w):
    lease = w.activate_main(start=date(2025, 1, 1))
    L.add_term(w.db, None, lease.id, valid_from=date(2026, 1, 1), valid_to=None, base_rent=D("900.00"))
    assert [(t.valid_from, t.valid_to, t.base_rent) for t in lease.terms] == [
        (date(2025, 1, 1), date(2025, 12, 31), D("850.00")), (date(2026, 1, 1), None, D("900.00"))]
    assert L.term_on(lease, date(2025, 6, 1)).base_rent == D("850.00") and L.term_on(lease, date(2026, 6, 1)).base_rent == D("900.00")
    with pytest.raises(ServiceError) as e:
        L.add_term(w.db, None, lease.id, valid_from=date(2025, 6, 1), valid_to=date(2025, 7, 1), base_rent=D("1.00"))
    assert e.value.code == "overlap"
