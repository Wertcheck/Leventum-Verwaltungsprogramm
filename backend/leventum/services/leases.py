"""Vertragsverwaltung (Haupt- und Untermietverträge).
Grundsatz: Die Software dokumentiert und prüft Konsistenz (Überschneidung, Deckung), sie trifft KEINE rechtliche
Einordnung. Rechtliche Felder werden nie automatisch gesetzt."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from leventum import domain
from leventum.models import Lease, LeaseItem, LeaseNote, LeaseParty, LeaseTerm, LeaseType, Party, RentableUnit, UtilityAgreement
from leventum.services import audit
from leventum.services.errors import NotFound, ServiceError
from leventum.services.master import chain, get_or_404, own_organization, spatially_related, space_label

OPEN_END = date.max


def effective_end(lease: Lease) -> date | None:
    return lease.termination_effective_on or lease.end_date


def _span(lease: Lease) -> tuple[date, date]:
    return lease.start_date, effective_end(lease) or OPEN_END


def is_running(lease: Lease, day: date | None = None) -> bool:
    """ZENTRALE Definition „laufender Vertrag“: Status aktiv oder gekündigt UND Tag zwischen Beginn und wirksamem Ende.
    Gekündigte Verträge laufen bis zum wirksamen Ende weiter (die Kündigung ist ein Zusatzmerkmal, kein Ende)."""
    day = day or date.today()
    return lease.status in domain.RUNNING_STATUS and lease.start_date <= day <= (effective_end(lease) or OPEN_END)


def phase(lease: Lease, today: date | None = None) -> str:
    """Anzeigephase eines Vertrags: draft | cancelled | upcoming | active | notice | ended."""
    today = today or date.today()
    if lease.status in ("draft", "cancelled"):
        return lease.status
    end = effective_end(lease)
    if lease.status == "ended" or (end is not None and end < today):
        return "ended"
    if lease.start_date > today:
        return "upcoming"
    return "notice" if lease.status == "terminated" else "active"


def overlaps(a: tuple[date, date], b: tuple[date, date]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


@dataclass
class Validation:
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    hints: list[dict] = field(default_factory=list)

    def err(self, code, msg, **d): self.errors.append({"code": code, "message": msg, **d})
    def warn(self, code, msg, **d): self.warnings.append({"code": code, "message": msg, **d})
    def hint(self, code, msg, **d): self.hints.append({"code": code, "message": msg, **d})

    def as_dict(self):
        return {"errors": self.errors, "warnings": self.warnings, "hints": self.hints}


def _party_ids(lease: Lease, *roles: str) -> list[int]:
    return [lp.party_id for lp in lease.parties if lp.role in roles]


# --- Anlegen ---------------------------------------------------------------------------------------
def create_lease(db: Session, actor_id: int | None, *, kind: str, lease_type_id: int, start_date: date,
                 end_date: date | None, parties: list[dict], rentable_unit_ids: list[int], **fields) -> Lease:
    if kind not in domain.LEASE_KINDS:
        raise ServiceError("invalid", "Ungültige Vertragsart (main/sub).")
    lt = get_or_404(db, LeaseType, lease_type_id, "Vertragsart")
    if lt.applies_to not in ("both", kind):
        raise ServiceError("invalid", f"Vertragsart {lt.name!r} ist für {kind}-Verträge nicht vorgesehen.")
    if end_date is not None and end_date < start_date:
        raise ServiceError("invalid", "Vertragsende liegt vor dem Vertragsbeginn.")
    for k, allowed in (("payment_rhythm", domain.PAYMENT_RHYTHMS),):
        if k in fields and fields[k] not in allowed:
            raise ServiceError("invalid", f"Ungültiger Wert für {k}.")
    if not rentable_unit_ids:
        raise ServiceError("invalid", "Mindestens ein Mietgegenstand (Vermietungseinheit) ist erforderlich.")
    if kind == "sub":
        fields.pop("subletting_permitted", None)
    lease = Lease(kind=kind, lease_type_id=lt.id, start_date=start_date, end_date=end_date, status="draft", **fields)
    for p in parties:
        if p["role"] not in domain.LEASE_PARTY_ROLES:
            raise ServiceError("invalid", f"Ungültige Vertragspartei-Rolle {p['role']!r}.")
        get_or_404(db, Party, p["party_id"], "Partei")
        lease.parties.append(LeaseParty(party_id=p["party_id"], role=p["role"]))
    for rid in dict.fromkeys(rentable_unit_ids):
        get_or_404(db, RentableUnit, rid, "Vermietungseinheit")
        lease.items.append(LeaseItem(rentable_unit_id=rid))
    if fields.get("parent_lease_id"):
        parent = get_or_404(db, Lease, fields["parent_lease_id"], "Hauptmietvertrag")
        if parent.kind != "main" or kind != "sub":
            raise ServiceError("invalid", "parent_lease_id muss ein Hauptmietvertrag sein und nur bei Untermietverträgen stehen.")
    db.add(lease)
    db.flush()
    audit.record(db, "lease.created", actor_user_id=actor_id, entity_type="lease", entity_id=lease.id,
                 summary=f"{'Hauptmietvertrag' if kind == 'main' else 'Untermietvertrag'} als Entwurf angelegt")
    return lease


def update_lease(db: Session, actor_id: int | None, lease_id: int, data: dict) -> Lease:
    lease = get_or_404(db, Lease, lease_id, "Vertrag")
    forbidden = {"kind", "status", "legal_review_status", "legal_reviewed_by_user_id", "legal_reviewed_at"} & data.keys()
    if forbidden:
        raise ServiceError("invalid", f"Felder nicht direkt änderbar: {sorted(forbidden)}")
    if lease.status in ("ended", "cancelled"):
        raise ServiceError("locked", "Beendete oder stornierte Verträge sind nicht änderbar.", 409)
    for k, v in data.items():
        setattr(lease, k, v)
    if lease.end_date is not None and lease.end_date < lease.start_date:
        raise ServiceError("invalid", "Vertragsende liegt vor dem Vertragsbeginn.")
    audit.record(db, "lease.updated", actor_user_id=actor_id, entity_type="lease", entity_id=lease.id,
                 summary="Vertrag geändert", details={"fields": sorted(data)})
    db.flush()
    return lease


# --- Konditionen (versioniert) ---------------------------------------------------------------------
def _append_versioned(db, lease, model, new, label):
    """Neue Version anhängen. Eine offene Vorversion wird am Vortag beendet; Überlappungen werden abgelehnt."""
    existing = list(getattr(lease, label))
    for e in existing:
        if overlaps((e.valid_from, e.valid_to or OPEN_END), (new.valid_from, new.valid_to or OPEN_END)):
            if e.valid_to is None and e.valid_from < new.valid_from:
                e.valid_to = new.valid_from - timedelta(days=1)
            else:
                raise ServiceError("overlap", "Der Gültigkeitszeitraum überschneidet sich mit einer vorhandenen Version.", 409)
    getattr(lease, label).append(new)


def add_term(db: Session, actor_id: int | None, lease_id: int, *, valid_from: date, valid_to: date | None,
             base_rent, other_charges=0, rent_period: str = "month", note: str | None = None) -> LeaseTerm:
    lease = get_or_404(db, Lease, lease_id, "Vertrag")
    if rent_period not in domain.RENT_PERIODS:
        raise ServiceError("invalid", "Ungültige Mietperiode.")
    if base_rent < 0 or other_charges < 0:
        raise ServiceError("invalid", "Beträge dürfen nicht negativ sein.")
    t = LeaseTerm(valid_from=valid_from, valid_to=valid_to, base_rent=base_rent, other_charges=other_charges,
                  rent_period=rent_period, note=note)
    _append_versioned(db, lease, LeaseTerm, t, "terms")
    db.flush()
    audit.record(db, "lease.term_added", actor_user_id=actor_id, entity_type="lease", entity_id=lease.id,
                 summary="Mietkonditionen ergänzt", details={"valid_from": str(valid_from), "base_rent": str(base_rent)})
    return t


def add_utility_agreement(db: Session, actor_id: int | None, lease_id: int, *, valid_from: date, valid_to: date | None,
                          mode: str, monthly_amount=None, settlement_agreed: bool | None = None,
                          description: str | None = None, legal_note: str | None = None) -> UtilityAgreement:
    """Nebenkostenvereinbarung. Die Abrechnungsfähigkeit wird NICHT aus dem Betrag geraten:
    prepayment → Abrechnung vereinbart; flat_rate/included/none → keine Abrechnung; individual → nur wenn ausdrücklich gesetzt."""
    lease = get_or_404(db, Lease, lease_id, "Vertrag")
    if mode not in domain.UTILITY_MODES:
        raise ServiceError("invalid", "Ungültiger Nebenkostenmodus.")
    if mode in ("flat_rate", "prepayment"):
        if monthly_amount is None or monthly_amount < 0:
            raise ServiceError("invalid", "Für Pauschale/Vorauszahlung ist ein monatlicher Betrag (≥ 0) erforderlich.")
    elif monthly_amount not in (None, 0):
        raise ServiceError("invalid", "Bei 'enthalten', 'individuell' oder 'keine' darf kein separater Monatsbetrag stehen.")
    if mode == "prepayment":
        settlement_agreed = True
    elif mode in ("flat_rate", "included", "none"):
        if settlement_agreed:
            raise ServiceError("invalid", "Bei Pauschale/enthalten/keine kann keine Abrechnung vereinbart sein "
                                          "(andernfalls Modus 'Vorauszahlung' oder 'individuell' wählen).")
        settlement_agreed = False
    elif mode == "individual" and not description:
        raise ServiceError("invalid", "Bei individueller Vereinbarung ist eine Beschreibung erforderlich.")
    a = UtilityAgreement(valid_from=valid_from, valid_to=valid_to, mode=mode, monthly_amount=monthly_amount,
                         settlement_agreed=settlement_agreed, description=description, legal_note=legal_note)
    _append_versioned(db, lease, UtilityAgreement, a, "utility_agreements")
    db.flush()
    audit.record(db, "lease.utility_agreement_added", actor_user_id=actor_id, entity_type="lease", entity_id=lease.id,
                 summary=f"Nebenkostenvereinbarung ({mode})", details={"valid_from": str(valid_from)})
    return a


def add_note(db: Session, actor_id: int | None, lease_id: int, kind: str, text: str) -> LeaseNote:
    get_or_404(db, Lease, lease_id, "Vertrag")
    if kind not in domain.NOTE_KINDS or not text.strip():
        raise ServiceError("invalid", "Ungültiger Vermerk.")
    n = LeaseNote(lease_id=lease_id, kind=kind, text=text.strip(), created_by_user_id=actor_id)
    db.add(n)
    db.flush()
    audit.record(db, "lease.note_added", actor_user_id=actor_id, entity_type="lease", entity_id=lease_id, summary=f"Vermerk ({kind})")
    return n


def set_legal_review(db: Session, actor_id: int | None, lease_id: int, status: str, *, basis_ref: str | None,
                     basis_note: str | None) -> Lease:
    """Ausschließlich manuelle Dokumentation einer Rechtsprüfung. Die Software prüft nichts rechtlich."""
    lease = get_or_404(db, Lease, lease_id, "Vertrag")
    if status not in domain.LEGAL_REVIEW:
        raise ServiceError("invalid", "Ungültiger Prüfstatus.")
    lease.legal_review_status = status
    lease.legal_basis_ref = basis_ref
    lease.legal_basis_note = basis_note
    if status == "reviewed":
        lease.legal_reviewed_by_user_id = actor_id
        lease.legal_reviewed_at = datetime.now(timezone.utc)
    else:
        lease.legal_reviewed_by_user_id = None
        lease.legal_reviewed_at = None
    audit.record(db, "lease.legal_review", actor_user_id=actor_id, entity_type="lease", entity_id=lease.id,
                 summary=f"Rechtlicher Prüfstatus: {status}", details={"basis_ref": basis_ref})
    db.flush()
    return lease


# --- Validierung -----------------------------------------------------------------------------------
def _other_running(db, kind, exclude_id):
    return db.scalars(select(Lease).where(Lease.kind == kind, Lease.status.in_(domain.RUNNING_STATUS), Lease.id != exclude_id)).all()


def validate_lease(db: Session, lease: Lease) -> Validation:
    v = Validation()
    own = own_organization(db)
    lessors, lessees = _party_ids(lease, "lessor"), _party_ids(lease, "lessee", "co_lessee")
    if not lessors:
        v.err("no_lessor", "Es fehlt ein Vermieter (Vertragspartei mit Rolle 'lessor').")
    if not lessees:
        v.err("no_lessee", "Es fehlt ein Mieter (Rolle 'lessee').")
    if own is None:
        v.err("no_own_organization", "Es ist keine eigene Organisation (Leventum) als Partei angelegt.")
    elif lease.kind == "main" and lessees and own.id not in _party_ids(lease, "lessee"):
        v.err("main_lessee_not_own", "Beim Hauptmietvertrag muss Leventum Mieter sein.")
    elif lease.kind == "sub" and lessors and own.id not in lessors:
        v.err("sub_lessor_not_own", "Beim Untermietvertrag muss Leventum Vermieter sein.")
    if lease.is_fixed_term and lease.end_date is None:
        v.err("fixed_term_no_end", "Befristeter Vertrag ohne Vertragsende.")
    if lease.is_fixed_term and not (lease.fixed_term_reason or "").strip() and lease.lease_type.requires_fixed_term_reason:
        v.hint("fixed_term_reason_missing", "Für diese Vertragsart ist ein Befristungsgrund vorgesehen, aber nicht dokumentiert.")
    if not lease.terms:
        v.warn("no_terms", "Keine Mietkonditionen erfasst.")
    if not lease.utility_agreements:
        v.warn("no_utility_agreement", "Keine Nebenkostenvereinbarung erfasst.")
    if lease.legal_review_status != "reviewed":
        v.hint("legal_not_reviewed", "Rechtliche Einordnung nicht als geprüft dokumentiert (keine automatische Einordnung durch die Software).")

    span = _span(lease)
    mine = [i.rentable_unit for i in lease.items]
    if lease.kind == "sub":
        _check_sub_conflicts(db, lease, mine, span, v)
        _check_coverage(db, lease, mine, span, v)
    else:
        for other in _other_running(db, "main", lease.id):
            if overlaps(span, _span(other)):
                for i in other.items:
                    for m in mine:
                        if spatially_related(m, i.rentable_unit):
                            v.warn("main_overlap", f"Überschneidung mit Hauptmietvertrag {other.id} ({space_label(db, m)}).",
                                   other_lease_id=other.id)
    return v


def _check_sub_conflicts(db, lease, mine, span, v):
    for other in _other_running(db, "sub", lease.id):
        if not overlaps(span, _span(other)):
            continue
        for i in other.items:
            for m in mine:
                if spatially_related(m, i.rentable_unit):
                    v.err("sub_overlap", f"{space_label(db, m)} ist im Zeitraum bereits durch Untermietvertrag {other.id} "
                                         f"belegt ({space_label(db, i.rentable_unit)}).", other_lease_id=other.id)


def _check_coverage(db, lease, mine, span, v):
    mains = _other_running(db, "main", lease.id)
    report = v.warn if lease.coverage_override_reason else v.err
    for m in mine:
        def covering(only_permitted):
            out = []
            for ml in mains:
                if only_permitted and ml.subletting_permitted is not True:
                    continue
                if any(chain(i.rentable_unit) == chain(m)[:len(chain(i.rentable_unit))] for i in ml.items):
                    out.append(_span(ml))
            return out
        if _covers(covering(True), span):
            continue
        if _covers(covering(False), span):
            report("subletting_not_permitted", f"{space_label(db, m)}: Untervermietung im Hauptmietvertrag nicht (ausdrücklich) erlaubt.")
        else:
            report("not_covered", f"{space_label(db, m)}: Zeitraum ist nicht vollständig durch einen laufenden Hauptmietvertrag gedeckt.")


def _covers(spans: list[tuple[date, date]], target: tuple[date, date]) -> bool:
    cur = target[0]
    for s, e in sorted(spans):
        if s > cur:
            break
        if e >= cur:
            if e >= target[1]:
                return True
            cur = e + timedelta(days=1)
    return False


# --- Statuswechsel ---------------------------------------------------------------------------------
class LeaseValidationError(ServiceError):
    def __init__(self, v: Validation):
        super().__init__("validation_failed", "Der Vertrag kann nicht aktiviert werden.", 422, v.as_dict())


def activate_lease(db: Session, actor_id: int | None, lease_id: int) -> tuple[Lease, Validation]:
    lease = get_or_404(db, Lease, lease_id, "Vertrag")
    if lease.status != "draft":
        raise ServiceError("invalid_state", "Nur Entwürfe können aktiviert werden.", 409)
    v = validate_lease(db, lease)
    if v.errors:
        raise LeaseValidationError(v)
    lease.status = "active"
    details = {"warnings": [w["code"] for w in v.warnings]}
    if lease.coverage_override_reason:
        details["coverage_override_reason"] = lease.coverage_override_reason
    audit.record(db, "lease.activated", actor_user_id=actor_id, entity_type="lease", entity_id=lease.id,
                 summary="Vertrag aktiviert", details=details)
    db.flush()
    return lease, v


def terminate_lease(db: Session, actor_id: int | None, lease_id: int, *, terminated_on: date, effective_on: date) -> Lease:
    lease = get_or_404(db, Lease, lease_id, "Vertrag")
    if lease.status != "active":
        raise ServiceError("invalid_state", "Nur aktive Verträge können gekündigt werden.", 409)
    if effective_on < lease.start_date or effective_on < terminated_on:
        raise ServiceError("invalid", "Das Beendigungsdatum ist unplausibel.")
    lease.status = "terminated"
    lease.terminated_on, lease.termination_effective_on = terminated_on, effective_on
    audit.record(db, "lease.terminated", actor_user_id=actor_id, entity_type="lease", entity_id=lease.id,
                 summary="Kündigung erfasst", details={"effective_on": str(effective_on)})
    db.flush()
    return lease


def cancel_lease(db: Session, actor_id: int | None, lease_id: int, reason: str) -> Lease:
    lease = get_or_404(db, Lease, lease_id, "Vertrag")
    if lease.status != "draft" or not reason.strip():
        raise ServiceError("invalid_state", "Nur Entwürfe können (mit Begründung) storniert werden.", 409)
    lease.status = "cancelled"
    audit.record(db, "lease.cancelled", actor_user_id=actor_id, entity_type="lease", entity_id=lease.id,
                 summary="Entwurf storniert", details={"reason": reason})
    db.flush()
    return lease


def close_expired(db: Session, actor_id: int | None, today: date) -> int:
    """Setzt laufende Verträge mit abgelaufenem Ende auf 'ended'. Wird vom Aufrufer (App-Start) ausgelöst."""
    n = 0
    for lease in db.scalars(select(Lease).where(Lease.status.in_(domain.RUNNING_STATUS))):
        e = effective_end(lease)
        if e is not None and e < today:
            lease.status = "ended"
            audit.record(db, "lease.ended", actor_user_id=actor_id, entity_type="lease", entity_id=lease.id, summary="Vertrag ausgelaufen")
            n += 1
    db.flush()
    return n


# --- Abfragen --------------------------------------------------------------------------------------
def term_on(lease: Lease, day: date) -> LeaseTerm | None:
    return next((t for t in lease.terms if t.valid_from <= day <= (t.valid_to or OPEN_END)), None)


def utility_on(lease: Lease, day: date) -> UtilityAgreement | None:
    return next((a for a in lease.utility_agreements if a.valid_from <= day <= (a.valid_to or OPEN_END)), None)


def occupancy_on(db: Session, ru: RentableUnit, day: date) -> list[Lease]:
    """Laufende Untermietverträge, die diese Vermietungseinheit (oder eine darüber-/darunterliegende) am Tag belegen."""
    out = []
    for lease in db.scalars(select(Lease).where(Lease.kind == "sub", Lease.status.in_(domain.RUNNING_STATUS))):
        s, e = _span(lease)
        if s <= day <= e and any(spatially_related(ru, i.rentable_unit) for i in lease.items):
            out.append(lease)
    return out


def monthly_total(lease: Lease, day: date) -> dict:
    """Monatliche Soll-Gesamtmiete laut Vertragsdaten. Pauschale/Vorauszahlung werden getrennt ausgewiesen;
    'enthalten' addiert nichts (steckt in der Kaltmiete). Tagesbasierte Mieten werden NICHT hochgerechnet."""
    t, a = term_on(lease, day), utility_on(lease, day)
    if t is None:
        return {"available": False}
    if t.rent_period != "month":
        return {"available": False, "reason": "Tagesbasierte Miete – keine Monatsumrechnung implementiert."}
    util = a.monthly_amount if a and a.mode in ("flat_rate", "prepayment") and a.monthly_amount is not None else Decimal("0.00")
    return {"available": True, "base_rent": t.base_rent, "other_charges": t.other_charges, "utility_mode": a.mode if a else None,
            "utility_amount": util, "total": t.base_rent + t.other_charges + util}
