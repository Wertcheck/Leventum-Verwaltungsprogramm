"""Stammdaten (Parteien, Objekte, Raumhierarchie), Verträge, Nebenkosten – Phase C."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from leventum.db.base import Area, Base, Money, utcnow


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Party(Base, Timestamps):
    __tablename__ = "party"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))
    display_name: Mapped[str] = mapped_column(String(200), index=True)
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    company_name: Mapped[str | None] = mapped_column(String(200))
    birth_date: Mapped[date | None] = mapped_column(Date)  # nur falls erforderlich
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(60))
    street: Mapped[str | None] = mapped_column(String(200))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    city: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(2), default="DE")
    iban: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)
    is_own_organization: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    roles: Mapped[list["PartyRole"]] = relationship(cascade="all, delete-orphan")


class PartyRole(Base):
    __tablename__ = "party_role"
    party_id: Mapped[int] = mapped_column(ForeignKey("party.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(30), primary_key=True)


class Property(Base, Timestamps):
    __tablename__ = "property"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    street: Mapped[str | None] = mapped_column(String(200))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    city: Mapped[str | None] = mapped_column(String(100))
    property_type: Mapped[str] = mapped_column(String(30))
    owner_party_id: Mapped[int | None] = mapped_column(ForeignKey("party.id"))
    year_built: Mapped[int | None] = mapped_column(Integer)
    total_area: Mapped[object | None] = mapped_column(Area)
    heating_type: Mapped[str | None] = mapped_column(String(100))
    equipment: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Unit(Base, Timestamps):
    """Wohneinheit. Kann ganz oder zimmer-/bettenweise vermietet werden (siehe RentableUnit)."""
    __tablename__ = "unit"
    __table_args__ = (UniqueConstraint("property_id", "unit_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    unit_number: Mapped[str] = mapped_column(String(40))
    floor: Mapped[str | None] = mapped_column(String(20))
    living_area: Mapped[object | None] = mapped_column(Area)
    rooms_count: Mapped[int | None] = mapped_column(Integer)
    equipment: Mapped[str | None] = mapped_column(Text)
    manual_status: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Room(Base, Timestamps):
    __tablename__ = "room"
    __table_args__ = (UniqueConstraint("unit_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("unit.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    area: Mapped[object | None] = mapped_column(Area)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Bed(Base, Timestamps):
    """Bett / Schlafplatz."""
    __tablename__ = "bed"
    __table_args__ = (UniqueConstraint("room_id", "label"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("room.id"), index=True)
    label: Mapped[str] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class RentableUnit(Base, Timestamps):
    """Vermietungseinheit: die tatsächlich vermietbare Einheit. Zeigt auf genau eine Ebene der Raumhierarchie.
    Übergeordnete Ebenen sind immer mitgesetzt (Bett → Zimmer → Wohneinheit → Objekt), damit Überschneidungen
    zwischen Ebenen (ganze Wohnung vs. Zimmer darin) prüfbar sind."""
    __tablename__ = "rentable_unit"
    __table_args__ = (
        CheckConstraint(
            "(level = 'property' AND unit_id IS NULL AND room_id IS NULL AND bed_id IS NULL)"
            " OR (level = 'unit' AND unit_id IS NOT NULL AND room_id IS NULL AND bed_id IS NULL)"
            " OR (level = 'room' AND unit_id IS NOT NULL AND room_id IS NOT NULL AND bed_id IS NULL)"
            " OR (level = 'bed' AND unit_id IS NOT NULL AND room_id IS NOT NULL AND bed_id IS NOT NULL)",
            name="level_consistent"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(10))
    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("unit.id"), index=True)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("room.id"))
    bed_id: Mapped[int | None] = mapped_column(ForeignKey("bed.id"))
    name: Mapped[str | None] = mapped_column(String(200))
    # Eindeutiger Raumschlüssel (z. B. "P1/U2/R3/B4"): ein UNIQUE über NULL-Spalten wirkt nicht, dieser Schlüssel verhindert Doppelungen portabel.
    space_key: Mapped[str] = mapped_column(String(60), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class LeaseType(Base):
    """Konfigurierbare Vertragsart. Der Name enthält ausdrücklich KEINE rechtliche Einordnung."""
    __tablename__ = "lease_type"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    applies_to: Mapped[str] = mapped_column(String(10), default="both")  # main | sub | both
    requires_fixed_term_reason: Mapped[bool] = mapped_column(Boolean, default=False)  # nur Hinweis, kein Zwang
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Lease(Base, Timestamps):
    __tablename__ = "lease"
    __table_args__ = (
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="dates_ordered"),
        CheckConstraint("payment_due_day BETWEEN 1 AND 31", name="due_day_range"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), index=True)  # main | sub
    lease_type_id: Mapped[int] = mapped_column(ForeignKey("lease_type.id"))
    contract_number: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(15), default="draft", index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_fixed_term: Mapped[bool] = mapped_column(Boolean, default=False)
    fixed_term_reason: Mapped[str | None] = mapped_column(Text)  # Befristungsgrund, Freitext
    notice_period_months: Mapped[int | None] = mapped_column(Integer)
    notice_note: Mapped[str | None] = mapped_column(Text)
    terminated_on: Mapped[date | None] = mapped_column(Date)
    termination_effective_on: Mapped[date | None] = mapped_column(Date)
    subletting_permitted: Mapped[bool | None] = mapped_column(Boolean)  # nur main; None = ungeklärt
    deposit_amount: Mapped[object | None] = mapped_column(Money)
    payment_rhythm: Mapped[str] = mapped_column(String(15), default="monthly")
    payment_due_day: Mapped[int] = mapped_column(Integer, default=1)
    intended_use: Mapped[str | None] = mapped_column(String(80))  # vereinbarte Nutzung
    intended_use_note: Mapped[str | None] = mapped_column(Text)
    legal_basis_ref: Mapped[str | None] = mapped_column(String(200))  # z. B. "§ 549 BGB" – nur Dokumentation
    legal_basis_note: Mapped[str | None] = mapped_column(Text)
    legal_review_status: Mapped[str] = mapped_column(String(15), default="not_reviewed")
    legal_reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    legal_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parent_lease_id: Mapped[int | None] = mapped_column(ForeignKey("lease.id"))  # optionaler Verweis Unter→Haupt
    coverage_override_reason: Mapped[str | None] = mapped_column(Text)
    allocation_method: Mapped[str] = mapped_column(String(10), default="area", server_default="area")  # Verteilung der Hauptmiete auf Wohneinheiten
    internal_notes: Mapped[str | None] = mapped_column(Text)
    lease_type: Mapped[LeaseType] = relationship()
    parties: Mapped[list["LeaseParty"]] = relationship(cascade="all, delete-orphan")
    items: Mapped[list["LeaseItem"]] = relationship(cascade="all, delete-orphan")
    terms: Mapped[list["LeaseTerm"]] = relationship(cascade="all, delete-orphan", order_by="LeaseTerm.valid_from")
    utility_agreements: Mapped[list["UtilityAgreement"]] = relationship(
        cascade="all, delete-orphan", order_by="UtilityAgreement.valid_from")


class LeaseParty(Base):
    """Vertragsparteien: mehrere Mieter (Mitmieter), Bewohner, Bürgen sind möglich."""
    __tablename__ = "lease_party"
    __table_args__ = (UniqueConstraint("lease_id", "party_id", "role"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("lease.id"), index=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("party.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    party: Mapped[Party] = relationship()


class LeaseItem(Base):
    """Mietgegenstand: welche Vermietungseinheit(en) der Vertrag umfasst."""
    __tablename__ = "lease_item"
    __table_args__ = (UniqueConstraint("lease_id", "rentable_unit_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("lease.id"), index=True)
    rentable_unit_id: Mapped[int] = mapped_column(ForeignKey("rentable_unit.id"), index=True)
    rentable_unit: Mapped[RentableUnit] = relationship()


class LeaseTerm(Base):
    """Versionierte Mietkonditionen (Kaltmiete etc.). Änderungen = neue Zeile."""
    __tablename__ = "lease_term"
    __table_args__ = (CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="dates_ordered"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("lease.id"), index=True)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    rent_period: Mapped[str] = mapped_column(String(10), default="month")  # month | day
    base_rent: Mapped[object] = mapped_column(Money)
    other_charges: Mapped[object] = mapped_column(Money, default=0)  # z. B. Möblierungszuschlag
    note: Mapped[str | None] = mapped_column(Text)


class UtilityAgreement(Base):
    """Nebenkostenvereinbarung (getrennt von der Miete, versioniert, je Vertrag). Gilt für Ebene A (Hauptmiete)
    und Ebene B (Untermiete). Eine Pauschale ist KEINE abrechenbare Vorauszahlung."""
    __tablename__ = "utility_agreement"
    __table_args__ = (CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="dates_ordered"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("lease.id"), index=True)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    mode: Mapped[str] = mapped_column(String(15))  # flat_rate | prepayment | included | individual | none
    monthly_amount: Mapped[object | None] = mapped_column(Money)
    settlement_agreed: Mapped[bool | None] = mapped_column(Boolean)  # Abrechnung vertraglich vereinbart? None = ungeklärt
    description: Mapped[str | None] = mapped_column(Text)
    legal_note: Mapped[str | None] = mapped_column(Text)


class LeaseNote(Base):
    """Interne Hinweise und Prüfvermerke. Append-only."""
    __tablename__ = "lease_note"
    id: Mapped[int] = mapped_column(primary_key=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("lease.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CostType(Base):
    __tablename__ = "cost_type"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class UtilityStatement(Base, Timestamps):
    """Nebenkostenabrechnung. level='upstream': Eingang vom Vermieter an Leventum (Ebene A).
    level='downstream' (Leventum → Untermieter) ist für Phase D reserviert und noch nicht nutzbar."""
    __tablename__ = "utility_statement"
    __table_args__ = (CheckConstraint("period_end >= period_start", name="period_ordered"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(12), default="upstream")
    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    main_lease_id: Mapped[int] = mapped_column(ForeignKey("lease.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    statement_date: Mapped[date | None] = mapped_column(Date)
    received_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="draft")
    stated_balance: Mapped[object | None] = mapped_column(Money)  # vom Vermieter ausgewiesen (+ = Nachzahlung, − = Guthaben)
    prepayments_amount: Mapped[object | None] = mapped_column(Money)
    prepayments_source: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)
    allocation_snapshot: Mapped[dict | None] = mapped_column(JSON)  # eingefrorene Verteilung (Flächen, Gewichte, Anteile) ab Status "reviewed"
    lines: Mapped[list["UtilityStatementLine"]] = relationship(cascade="all, delete-orphan", order_by="UtilityStatementLine.id")
    units: Mapped[list["UtilityStatementUnit"]] = relationship(cascade="all, delete-orphan")


class UtilityStatementUnit(Base):
    __tablename__ = "utility_statement_unit"
    __table_args__ = (UniqueConstraint("statement_id", "unit_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(ForeignKey("utility_statement.id"), index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("unit.id"))


class UtilityStatementLine(Base):
    __tablename__ = "utility_statement_line"
    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(ForeignKey("utility_statement.id"), index=True)
    cost_type_id: Mapped[int] = mapped_column(ForeignKey("cost_type.id"))
    description: Mapped[str | None] = mapped_column(String(300))
    amount: Mapped[object] = mapped_column(Money)
    allocation_key: Mapped[str] = mapped_column(String(15), default="none")
    allocable_status: Mapped[str] = mapped_column(String(15), default="unreviewed")
    note: Mapped[str | None] = mapped_column(Text)
    cost_type: Mapped[CostType] = relationship()
    weights: Mapped[list["UtilityLineWeight"]] = relationship(cascade="all, delete-orphan")


class UtilityLineWeight(Base):
    """Gewichte für Schlüssel persons / consumption / custom (Wohnfläche und gleichmäßig kommen aus den Stammdaten)."""
    __tablename__ = "utility_line_weight"
    __table_args__ = (UniqueConstraint("line_id", "unit_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("utility_statement_line.id"), index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("unit.id"))
    weight: Mapped[object] = mapped_column(Area)
