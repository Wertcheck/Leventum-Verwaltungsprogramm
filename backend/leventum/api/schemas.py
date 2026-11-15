from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from leventum import domain

Amount = Annotated[Decimal, Field(ge=0, decimal_places=2, max_digits=14)]
Pos = Annotated[Decimal, Field(ge=0, decimal_places=2, max_digits=12)]


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PartyIn(In):
    kind: Literal["person", "company"]
    display_name: str | None = Field(None, max_length=200)
    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    company_name: str | None = Field(None, max_length=200)
    birth_date: date | None = None
    email: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=60)
    street: str | None = Field(None, max_length=200)
    postal_code: str | None = Field(None, max_length=20)
    city: str | None = Field(None, max_length=100)
    country: str = Field("DE", max_length=2)
    iban: str | None = Field(None, max_length=40)
    notes: str | None = None
    is_own_organization: bool = False
    roles: list[Literal["owner", "landlord", "tenant", "service_provider"]] = []


class PartyPatch(In):
    display_name: str | None = Field(None, max_length=200)
    first_name: str | None = None
    last_name: str | None = None
    company_name: str | None = None
    birth_date: date | None = None
    email: str | None = None
    phone: str | None = None
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    iban: str | None = None
    notes: str | None = None
    is_active: bool | None = None
    roles: list[Literal["owner", "landlord", "tenant", "service_provider"]] | None = None


class PropertyIn(In):
    name: str = Field(min_length=1, max_length=200)
    property_type: Literal["mehrfamilienhaus", "wohnung", "einfamilienhaus", "gewerbeeinheit", "sonstige"]
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    owner_party_id: int | None = None
    year_built: int | None = Field(None, ge=1000, le=2100)
    total_area: Pos | None = None
    heating_type: str | None = None
    equipment: str | None = None
    notes: str | None = None


class PropertyPatch(PropertyIn):
    name: str | None = Field(None, min_length=1, max_length=200)  # type: ignore[assignment]
    property_type: Literal["mehrfamilienhaus", "wohnung", "einfamilienhaus", "gewerbeeinheit", "sonstige"] | None = None  # type: ignore[assignment]
    is_active: bool | None = None


class UnitIn(In):
    unit_number: str = Field(min_length=1, max_length=40)
    floor: str | None = None
    living_area: Pos | None = None
    rooms_count: int | None = Field(None, ge=0)
    equipment: str | None = None
    manual_status: Literal["reserved", "renovation", "unavailable"] | None = None
    notes: str | None = None


class UnitPatch(In):
    floor: str | None = None
    living_area: Pos | None = None
    rooms_count: int | None = Field(None, ge=0)
    equipment: str | None = None
    manual_status: Literal["reserved", "renovation", "unavailable"] | None = None
    notes: str | None = None
    is_active: bool | None = None


class RoomIn(In):
    name: str = Field(min_length=1, max_length=80)
    area: Pos | None = None
    notes: str | None = None


class BedIn(In):
    label: str = Field(min_length=1, max_length=80)
    notes: str | None = None


class RentableIn(In):
    property_id: int
    unit_id: int | None = None
    room_id: int | None = None
    bed_id: int | None = None
    name: str | None = None


class LeasePartyIn(In):
    party_id: int
    role: Literal["lessor", "lessee", "co_lessee", "occupant", "guarantor"]


class LeaseIn(In):
    kind: Literal["main", "sub"]
    lease_type_id: int
    start_date: date
    end_date: date | None = None
    parties: list[LeasePartyIn]
    rentable_unit_ids: list[int]
    contract_number: str | None = None
    is_fixed_term: bool = False
    fixed_term_reason: str | None = None
    notice_period_months: int | None = Field(None, ge=0)
    notice_note: str | None = None
    subletting_permitted: bool | None = None
    deposit_amount: Amount | None = None
    payment_rhythm: Literal["monthly", "quarterly", "yearly", "on_demand"] = "monthly"
    payment_due_day: int = Field(1, ge=1, le=31)
    intended_use: str | None = Field(None, max_length=80)
    intended_use_note: str | None = None
    legal_basis_ref: str | None = None
    legal_basis_note: str | None = None
    parent_lease_id: int | None = None
    coverage_override_reason: str | None = None
    internal_notes: str | None = None


class LeasePatch(In):
    lease_type_id: int | None = None
    contract_number: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_fixed_term: bool | None = None
    fixed_term_reason: str | None = None
    notice_period_months: int | None = Field(None, ge=0)
    notice_note: str | None = None
    subletting_permitted: bool | None = None
    deposit_amount: Amount | None = None
    payment_rhythm: Literal["monthly", "quarterly", "yearly", "on_demand"] | None = None
    payment_due_day: int | None = Field(None, ge=1, le=31)
    intended_use: str | None = None
    intended_use_note: str | None = None
    coverage_override_reason: str | None = None
    internal_notes: str | None = None


class TermIn(In):
    valid_from: date
    valid_to: date | None = None
    base_rent: Amount
    other_charges: Amount = Decimal(0)
    rent_period: Literal["month", "day"] = "month"
    note: str | None = None


class UtilityAgreementIn(In):
    valid_from: date
    valid_to: date | None = None
    mode: Literal["flat_rate", "prepayment", "included", "individual", "none"]
    monthly_amount: Amount | None = None
    settlement_agreed: bool | None = None
    description: str | None = None
    legal_note: str | None = None


class NoteIn(In):
    kind: Literal["note", "review", "hint"] = "note"
    text: str = Field(min_length=1)


class LegalReviewIn(In):
    status: Literal["not_reviewed", "in_review", "reviewed"]
    basis_ref: str | None = Field(None, max_length=200)
    basis_note: str | None = None


class TerminateIn(In):
    terminated_on: date
    effective_on: date


class CancelIn(In):
    reason: str = Field(min_length=1)


class StatementIn(In):
    main_lease_id: int
    period_start: date
    period_end: date
    unit_ids: list[int]
    statement_date: date | None = None
    received_on: date | None = None
    stated_balance: Annotated[Decimal, Field(decimal_places=2, max_digits=14)] | None = None
    notes: str | None = None


class LineIn(In):
    cost_type_id: int
    amount: Annotated[Decimal, Field(decimal_places=2, max_digits=14)]
    allocation_key: Literal["area", "equal", "persons", "consumption", "custom", "none"] = "none"
    allocable_status: Literal["unreviewed", "allocable", "not_allocable"] = "unreviewed"
    description: str | None = Field(None, max_length=300)
    note: str | None = None
    weights: dict[int, Pos] | None = None


class PrepaymentIn(In):
    amount: Amount
    source: Literal["agreed_calculated", "statement", "manual"]


class StatusIn(In):
    status: Literal["draft", "captured", "reviewed"]


# --- Phase D ---
class ChargeGenerateIn(In):
    from_month: date
    through_month: date
    lease_id: int | None = None


class ChargeManualIn(In):
    lease_id: int
    amount: Annotated[Decimal, Field(gt=0, decimal_places=2, max_digits=14)]
    due_date: date
    period_start: date
    period_end: date
    note: str = Field(min_length=1)


class VoidIn(In):
    reason: str = Field(min_length=1)


class AllocationIn(In):
    charge_id: int | None = None
    invoice_id: int | None = None
    amount: Annotated[Decimal, Field(gt=0, decimal_places=2, max_digits=14)]


class PaymentIn(In):
    direction: Literal["in", "out"]
    booking_date: date
    amount: Annotated[Decimal, Field(gt=0, decimal_places=2, max_digits=14)]
    counterparty_party_id: int | None = None
    lease_id: int | None = None
    property_id: int | None = None
    method: Literal["bank_transfer", "cash", "direct_debit", "other"] = "bank_transfer"
    reference: str | None = None
    note: str | None = None
    allocations: list[AllocationIn] = []
    accept_possible_duplicate: bool = False


class DeallocIn(AllocationIn):
    reason: str = Field(min_length=1)


class ReverseIn(In):
    reason: str = Field(min_length=1)
    booking_date: date | None = None


class InvoiceIn(In):
    property_id: int
    amount: Annotated[Decimal, Field(gt=0, decimal_places=2, max_digits=14)]
    invoice_date: date
    supplier_party_id: int | None = None
    unit_id: int | None = None
    repair_id: int | None = None
    cost_type_id: int | None = None
    invoice_number: str | None = Field(None, max_length=80)
    due_date: date | None = None
    description: str | None = Field(None, max_length=300)
    notes: str | None = None


class DepositIn(In):
    lease_id: int
    agreed_amount: Amount | None = None
    due_date: date | None = None
    note: str | None = None


class DepositTxIn(In):
    kind: Literal["paid", "refunded", "retained"]
    amount: Annotated[Decimal, Field(gt=0, decimal_places=2, max_digits=14)]
    transaction_date: date
    reason: str | None = None
    note: str | None = None


class DunningPrepareIn(In):
    as_of: date | None = None
    lease_id: int | None = None
    grace_days: int = Field(0, ge=0, le=60)


class DunningEditIn(In):
    subject: str | None = Field(None, max_length=300)
    body: str | None = None


class SentIn(In):
    sent_on: date
    via: str = Field(min_length=1, max_length=40)


class BankAccountIn(In):
    name: str = Field(min_length=1, max_length=120)
    iban: str | None = Field(None, max_length=40)


class ConfirmIn(In):
    confirm: Literal[True]  # ausdrückliche manuelle Bestätigung
    kind: Literal["payment", "deposit"] = "payment"
    allocations: list[AllocationIn] = []
    counterparty_party_id: int | None = None
    lease_id: int | None = None
    property_id: int | None = None
    note: str | None = None
    accept_possible_duplicate: bool = False
    deposit_id: int | None = None
    deposit_kind: Literal["paid", "refunded"] | None = None
    reason: str | None = None


class ReasonIn(In):
    reason: str = Field(min_length=1)


class LeaseAllocationIn(In):
    method: Literal["area", "equal", "custom"]
    weights: dict[int, Pos] = {}


# --- Phase E ---
Prio = Literal["low", "normal", "high", "urgent"]


class TaskIn(In):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    priority: Prio = "normal"
    due_date: date | None = None
    assignee_user_id: int | None = None
    party_id: int | None = None
    property_id: int | None = None
    unit_id: int | None = None
    lease_id: int | None = None
    invoice_id: int | None = None
    repair_id: int | None = None


class TaskPatch(In):
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    priority: Prio | None = None
    due_date: date | None = None
    assignee_user_id: int | None = None
    party_id: int | None = None
    property_id: int | None = None
    unit_id: int | None = None
    lease_id: int | None = None
    invoice_id: int | None = None
    repair_id: int | None = None


class TaskStatusIn(In):
    status: Literal["open", "in_progress", "waiting", "done", "cancelled"]
    note: str | None = None


class ReminderTaskIn(In):
    key: str = Field(min_length=1, max_length=160)
    due_date: date | None = None


Category = Literal["heizung", "wasserschaden", "elektrik", "sanitaer", "fenster", "tuerschloss", "instandhaltung", "sonstige"]


class RepairIn(In):
    property_id: int
    title: str = Field(min_length=1, max_length=200)
    reported_on: date
    description: str | None = None
    category: Category = "sonstige"
    priority: Prio = "normal"
    unit_id: int | None = None
    lease_id: int | None = None
    reported_by_party_id: int | None = None
    contractor_party_id: int | None = None
    cost_estimate: Amount | None = None
    scheduled_for: date | None = None


class RepairPatch(In):
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    category: Category | None = None
    priority: Prio | None = None
    unit_id: int | None = None
    lease_id: int | None = None
    contractor_party_id: int | None = None
    cost_estimate: Amount | None = None
    scheduled_for: date | None = None


class RepairStatusIn(In):
    status: Literal["reported", "scheduled", "in_progress", "waiting", "done", "cancelled"]
    note: str | None = None
    on: date | None = None


class NoteTextIn(In):
    text: str = Field(min_length=1)


class InvoiceLinkIn(In):
    invoice_id: int


class FollowUpIn(In):
    title: str = Field(min_length=1, max_length=200)
    due_date: date | None = None
    priority: Prio = "normal"


class CommunicationIn(In):
    channel: Literal["email", "phone", "letter", "in_person", "messenger", "other"]
    direction: Literal["in", "out"]
    subject: str = Field(min_length=1, max_length=300)
    body: str | None = None
    occurred_at: datetime | None = None
    party_id: int | None = None
    lease_id: int | None = None
    property_id: int | None = None
    unit_id: int | None = None
    repair_id: int | None = None
    follow_up: FollowUpIn | None = None


class HandoverIn(In):
    lease_id: int
    kind: Literal["move_in", "move_out"]
    protocol_date: date
    unit_id: int | None = None
    keys_handed: int | None = Field(None, ge=0)
    meter_readings: str | None = None
    condition_notes: str | None = None
    attendees: str | None = None
    signed: bool = False


class DocLinkIn(In):
    entity_type: str
    entity_id: int
