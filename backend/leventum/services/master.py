"""Stammdaten: Parteien, Objekte, Wohneinheiten, Zimmer, Betten, Vermietungseinheiten."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from leventum import domain
from leventum.models import Bed, Party, PartyRole, Property, RentableUnit, Room, Unit
from leventum.services import audit
from leventum.services.errors import NotFound, ServiceError


def get_or_404(db: Session, model, id_: int, label: str):
    obj = db.get(model, id_)
    if obj is None:
        raise NotFound(label)
    return obj


def _check(value, allowed, field):
    if value not in allowed:
        raise ServiceError("invalid", f"Ungültiger Wert für {field}: {value!r}.")


# --- Parteien ----------------------------------------------------------------------------------
def _display_name(d: dict) -> str:
    if d.get("display_name"):
        return d["display_name"].strip()
    if d.get("kind") == "company":
        return (d.get("company_name") or "").strip()
    return f"{(d.get('first_name') or '').strip()} {(d.get('last_name') or '').strip()}".strip()


def create_party(db: Session, actor_id: int | None, data: dict, roles: list[str]) -> Party:
    _check(data.get("kind"), domain.PARTY_KINDS, "kind")
    for r in roles:
        _check(r, domain.PARTY_ROLES, "role")
    if data.get("is_own_organization") and data["kind"] != "company":
        raise ServiceError("invalid", "Die eigene Organisation muss eine Firma sein.")
    data = {**data, "display_name": _display_name(data)}
    if not data["display_name"]:
        raise ServiceError("invalid", "Name fehlt.")
    p = Party(**data)
    p.roles = [PartyRole(role=r) for r in dict.fromkeys(roles)]
    db.add(p)
    db.flush()
    audit.record(db, "party.created", actor_user_id=actor_id, entity_type="party", entity_id=p.id,
                 summary=f"Partei angelegt: {p.display_name}", details={"roles": roles})
    return p


def update_party(db: Session, actor_id: int | None, party_id: int, data: dict, roles: list[str] | None = None) -> Party:
    p = get_or_404(db, Party, party_id, "Partei")
    changed = {k: v for k, v in data.items() if getattr(p, k) != v}
    for k, v in changed.items():
        setattr(p, k, v)
    if "display_name" not in data and ({"first_name", "last_name", "company_name"} & changed.keys()):
        p.display_name = _display_name({"kind": p.kind, "first_name": p.first_name, "last_name": p.last_name,
                                        "company_name": p.company_name}) or p.display_name
    if roles is not None:
        for r in roles:
            _check(r, domain.PARTY_ROLES, "role")
        p.roles = [PartyRole(role=r) for r in dict.fromkeys(roles)]
        changed["roles"] = roles
    audit.record(db, "party.updated", actor_user_id=actor_id, entity_type="party", entity_id=p.id,
                 summary=f"Partei geändert: {p.display_name}", details={"fields": sorted(changed)})
    db.flush()
    return p


def own_organization(db: Session) -> Party | None:
    return db.scalar(select(Party).where(Party.is_own_organization.is_(True), Party.is_active.is_(True)).order_by(Party.id))


# --- Objekte / Raumhierarchie --------------------------------------------------------------------
def create_property(db: Session, actor_id: int | None, data: dict) -> Property:
    _check(data.get("property_type"), domain.PROPERTY_TYPES, "property_type")
    owner_id = data.get("owner_party_id")
    if owner_id is not None:
        owner = get_or_404(db, Party, owner_id, "Eigentümer")
        if "owner" not in {r.role for r in owner.roles}:
            owner.roles.append(PartyRole(role="owner"))
    p = Property(**data)
    db.add(p)
    db.flush()
    audit.record(db, "property.created", actor_user_id=actor_id, entity_type="property", entity_id=p.id,
                 summary=f"Objekt angelegt: {p.name}")
    return p


def update_property(db: Session, actor_id: int | None, property_id: int, data: dict) -> Property:
    p = get_or_404(db, Property, property_id, "Objekt")
    if "property_type" in data:
        _check(data["property_type"], domain.PROPERTY_TYPES, "property_type")
    if data.get("owner_party_id") is not None:
        get_or_404(db, Party, data["owner_party_id"], "Eigentümer")
    for k, v in data.items():
        setattr(p, k, v)
    audit.record(db, "property.updated", actor_user_id=actor_id, entity_type="property", entity_id=p.id,
                 summary=f"Objekt geändert: {p.name}", details={"fields": sorted(data)})
    db.flush()
    return p


def _dup(db, model, **flt):
    return db.scalar(select(model).filter_by(**flt)) is not None


def create_unit(db: Session, actor_id: int | None, property_id: int, data: dict) -> Unit:
    get_or_404(db, Property, property_id, "Objekt")
    if data.get("manual_status") is not None:
        _check(data["manual_status"], domain.UNIT_MANUAL_STATUS, "manual_status")
    if _dup(db, Unit, property_id=property_id, unit_number=data["unit_number"]):
        raise ServiceError("duplicate", f"Wohneinheit {data['unit_number']!r} existiert in diesem Objekt bereits.", 409)
    u = Unit(property_id=property_id, **data)
    db.add(u)
    db.flush()
    audit.record(db, "unit.created", actor_user_id=actor_id, entity_type="unit", entity_id=u.id,
                 summary=f"Wohneinheit angelegt: {u.unit_number}")
    return u


def update_unit(db: Session, actor_id: int | None, unit_id: int, data: dict) -> Unit:
    u = get_or_404(db, Unit, unit_id, "Wohneinheit")
    if data.get("manual_status") is not None:
        _check(data["manual_status"], domain.UNIT_MANUAL_STATUS, "manual_status")
    for k, v in data.items():
        setattr(u, k, v)
    audit.record(db, "unit.updated", actor_user_id=actor_id, entity_type="unit", entity_id=u.id,
                 summary=f"Wohneinheit geändert: {u.unit_number}", details={"fields": sorted(data)})
    db.flush()
    return u


def create_room(db: Session, actor_id: int | None, unit_id: int, data: dict) -> Room:
    get_or_404(db, Unit, unit_id, "Wohneinheit")
    if _dup(db, Room, unit_id=unit_id, name=data["name"]):
        raise ServiceError("duplicate", f"Zimmer {data['name']!r} existiert in dieser Wohneinheit bereits.", 409)
    r = Room(unit_id=unit_id, **data)
    db.add(r)
    db.flush()
    audit.record(db, "room.created", actor_user_id=actor_id, entity_type="room", entity_id=r.id, summary=f"Zimmer angelegt: {r.name}")
    return r


def create_bed(db: Session, actor_id: int | None, room_id: int, data: dict) -> Bed:
    get_or_404(db, Room, room_id, "Zimmer")
    if _dup(db, Bed, room_id=room_id, label=data["label"]):
        raise ServiceError("duplicate", f"Bett {data['label']!r} existiert in diesem Zimmer bereits.", 409)
    b = Bed(room_id=room_id, **data)
    db.add(b)
    db.flush()
    audit.record(db, "bed.created", actor_user_id=actor_id, entity_type="bed", entity_id=b.id, summary=f"Bett angelegt: {b.label}")
    return b


def ensure_rentable_unit(db: Session, actor_id: int | None, *, property_id: int, unit_id: int | None = None,
                         room_id: int | None = None, bed_id: int | None = None, name: str | None = None) -> RentableUnit:
    """Legt die Vermietungseinheit für genau eine Ebene an (oder liefert die vorhandene). Die Ebene ergibt sich aus der
    tiefsten angegebenen ID; übergeordnete IDs werden aus der Hierarchie abgeleitet und auf Konsistenz geprüft."""
    prop = get_or_404(db, Property, property_id, "Objekt")
    bed = room = unit = None
    if bed_id is not None:
        bed = get_or_404(db, Bed, bed_id, "Bett")
        room = db.get(Room, bed.room_id)
        if room_id not in (None, room.id):
            raise ServiceError("invalid", "Bett gehört nicht zum angegebenen Zimmer.")
        room_id = room.id
    if room_id is not None:
        room = room or get_or_404(db, Room, room_id, "Zimmer")
        unit = db.get(Unit, room.unit_id)
        if unit_id not in (None, unit.id):
            raise ServiceError("invalid", "Zimmer gehört nicht zur angegebenen Wohneinheit.")
        unit_id = unit.id
    if unit_id is not None:
        unit = unit or get_or_404(db, Unit, unit_id, "Wohneinheit")
        if unit.property_id != prop.id:
            raise ServiceError("invalid", "Wohneinheit gehört nicht zum angegebenen Objekt.")
    level = "bed" if bed else "room" if room else "unit" if unit else "property"
    existing = db.scalar(select(RentableUnit).where(
        RentableUnit.property_id == property_id, RentableUnit.level == level,
        RentableUnit.unit_id.is_(None) if unit_id is None else RentableUnit.unit_id == unit_id,
        RentableUnit.room_id.is_(None) if room_id is None else RentableUnit.room_id == room_id,
        RentableUnit.bed_id.is_(None) if bed_id is None else RentableUnit.bed_id == bed_id))
    if existing:
        return existing
    ru = RentableUnit(level=level, property_id=property_id, unit_id=unit_id, room_id=room_id,
                      bed_id=bed.id if bed else None, name=name)
    db.add(ru)
    db.flush()
    audit.record(db, "rentable_unit.created", actor_user_id=actor_id, entity_type="rentable_unit", entity_id=ru.id,
                 summary=f"Vermietungseinheit angelegt ({level})")
    return ru


def chain(ru: RentableUnit) -> tuple:
    """Pfad Objekt → … → Ebene der Vermietungseinheit. Zwei Einheiten überschneiden sich räumlich genau dann,
    wenn der Pfad der einen ein Präfix des Pfads der anderen ist (gleich, übergeordnet oder untergeordnet)."""
    parts = [("P", ru.property_id)]
    for tag, v in (("U", ru.unit_id), ("R", ru.room_id), ("B", ru.bed_id)):
        if v is not None:
            parts.append((tag, v))
    return tuple(parts)


def spatially_related(a: RentableUnit, b: RentableUnit) -> bool:
    ca, cb = chain(a), chain(b)
    n = min(len(ca), len(cb))
    return ca[:n] == cb[:n]


def prefixed(prefix: str, value: str) -> str:
    """'WE' + '03' → 'WE 03', aber 'WE' + 'WE 03' bleibt 'WE 03' (keine Doppelung, wenn die Bezeichnung das Präfix schon enthält)."""
    return value if value.strip().lower().startswith(prefix.lower()) else f"{prefix} {value}"


def space_label(db: Session, ru: RentableUnit) -> str:
    parts = [db.get(Property, ru.property_id).name]
    if ru.unit_id:
        parts.append(prefixed("WE", db.get(Unit, ru.unit_id).unit_number))
    if ru.room_id:
        parts.append(prefixed("Zimmer", db.get(Room, ru.room_id).name))
    if ru.bed_id:
        parts.append(prefixed("Bett", db.get(Bed, ru.bed_id).label))
    return " · ".join(parts)


def lease_title(db: Session, lease) -> str:
    """Sprechende Bezeichnung für Listen: Mieter bzw. Vermieter + Mietgegenstand (statt nur '#4')."""
    roles = ("lessee", "co_lessee") if lease.kind == "sub" else ("lessor",)
    names = ", ".join(p.party.display_name for p in lease.parties if p.role in roles) or "–"
    spaces = [space_label(db, i.rentable_unit) for i in lease.items]
    where = spaces[0] + (f" (+{len(spaces) - 1})" if len(spaces) > 1 else "") if spaces else ""
    return f"{names} · {where}" if where else names
