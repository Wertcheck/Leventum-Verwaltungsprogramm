"""Finanzen (Phase D): Sollstellungen, Zahlungen, Rechnungen, Kautionen, Mahnwesen, Bankimport, Dokumente."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from leventum.db.base import Area, Base, Money, utcnow
from leventum.models.master import Timestamps


class Charge(Base, Timestamps):
    """Sollstellung (Forderung gegen Untermieter / Verbindlichkeit gegenüber Vermieter). Nie löschen, nur stornieren."""
    __tablename__ = "charge"
    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"), CheckConstraint("period_end >= period_start", name="period_ordered"))
    id: Mapped[int] = mapped_column(primary_key=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("lease.id"), index=True)
    direction: Mapped[str] = mapped_column(String(10))
    charge_type: Mapped[str] = mapped_column(String(30))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[object] = mapped_column(Money)
    # Duplikatschutz: gesetzt solange aktiv, NULL nach Storno (mehrere NULLs sind in SQLite und PostgreSQL erlaubt)
    dedupe_key: Mapped[str | None] = mapped_column(String(120), unique=True)
    source: Mapped[str] = mapped_column(String(15), default="generated")
    note: Mapped[str | None] = mapped_column(Text)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    void_reason: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))


class Invoice(Base, Timestamps):
    """Rechnung / objektbezogene Kosten (Eingangsrechnung)."""
    __tablename__ = "invoice"
    __table_args__ = (UniqueConstraint("supplier_party_id", "invoice_number"), CheckConstraint("amount > 0", name="amount_positive"))
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_party_id: Mapped[int | None] = mapped_column(ForeignKey("party.id"))
    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("unit.id"))
    cost_type_id: Mapped[int | None] = mapped_column(ForeignKey("cost_type.id"))
    invoice_number: Mapped[str | None] = mapped_column(String(80))
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[object] = mapped_column(Money)
    description: Mapped[str | None] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(Text)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))


class Payment(Base):
    """Tatsächlicher Zahlungsfluss. UNVERÄNDERLICH: Korrektur nur per Gegenbuchung (is_reversal)."""
    __tablename__ = "payment"
    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    direction: Mapped[str] = mapped_column(String(3))
    booking_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[object] = mapped_column(Money)
    is_reversal: Mapped[bool] = mapped_column(Boolean, default=False)
    reverses_payment_id: Mapped[int | None] = mapped_column(ForeignKey("payment.id"), unique=True)
    counterparty_party_id: Mapped[int | None] = mapped_column(ForeignKey("party.id"))
    lease_id: Mapped[int | None] = mapped_column(ForeignKey("lease.id"))
    property_id: Mapped[int | None] = mapped_column(ForeignKey("property.id"))
    method: Mapped[str] = mapped_column(String(20), default="bank_transfer")
    reference: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(15), default="manual")
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentAllocation(Base):
    """Zuordnung (vorzeichenbehaftet, append-only): + ordnet zu, − nimmt eine Zuordnung zurück."""
    __tablename__ = "payment_allocation"
    __table_args__ = (CheckConstraint("(charge_id IS NOT NULL AND invoice_id IS NULL) OR (charge_id IS NULL AND invoice_id IS NOT NULL)", name="one_target"),
                      CheckConstraint("amount <> 0", name="amount_nonzero"))
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payment.id"), index=True)
    charge_id: Mapped[int | None] = mapped_column(ForeignKey("charge.id"), index=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoice.id"), index=True)
    amount: Mapped[object] = mapped_column(Money)
    reason: Mapped[str | None] = mapped_column(String(300))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Deposit(Base, Timestamps):
    """Kaution je Vertrag. Hauptmiete: Leventum → Vermieter. Untermiete: Mieter → Leventum. Vollständig getrennt von Payment/Charge."""
    __tablename__ = "deposit"
    id: Mapped[int] = mapped_column(primary_key=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("lease.id"), unique=True)
    agreed_amount: Mapped[object] = mapped_column(Money)
    due_date: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    transactions: Mapped[list["DepositTransaction"]] = relationship(cascade="all, delete-orphan", order_by="DepositTransaction.id")


class DepositTransaction(Base):
    __tablename__ = "deposit_transaction"
    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    deposit_id: Mapped[int] = mapped_column(ForeignKey("deposit.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # paid | refunded | retained
    amount: Mapped[object] = mapped_column(Money)
    transaction_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    bank_transaction_id: Mapped[int | None] = mapped_column(ForeignKey("bank_transaction.id"), unique=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Document(Base):
    __tablename__ = "document"
    id: Mapped[int] = mapped_column(primary_key=True)
    storage_key: Mapped[str] = mapped_column(String(200), unique=True)
    original_name: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    doc_type: Mapped[str] = mapped_column(String(40), default="sonstige")
    uploaded_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    links: Mapped[list["DocumentLink"]] = relationship(cascade="all, delete-orphan")


class DocumentLink(Base):
    """Polymorphe Zuordnung (kein DB-Fremdschlüssel); Typ per Allowlist im Service geprüft."""
    __tablename__ = "document_link"
    __table_args__ = (UniqueConstraint("document_id", "entity_type", "entity_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("document.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(30), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)


class DunningNotice(Base):
    __tablename__ = "dunning_notice"
    __table_args__ = (CheckConstraint("level BETWEEN 1 AND 3", name="level_range"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("lease.id"), index=True)
    level: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="draft", index=True)
    as_of_date: Mapped[date] = mapped_column(Date)
    recipient_name: Mapped[str] = mapped_column(String(300))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    review_hint: Mapped[str | None] = mapped_column(Text)
    total_open: Mapped[object] = mapped_column(Money)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_on: Mapped[date | None] = mapped_column(Date)
    sent_via: Mapped[str | None] = mapped_column(String(40))
    sent_marked_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    lines: Mapped[list["DunningLine"]] = relationship(cascade="all, delete-orphan", order_by="DunningLine.id")


class DunningLine(Base):
    __tablename__ = "dunning_line"
    id: Mapped[int] = mapped_column(primary_key=True)
    notice_id: Mapped[int] = mapped_column(ForeignKey("dunning_notice.id"), index=True)
    charge_id: Mapped[int] = mapped_column(ForeignKey("charge.id"), index=True)
    open_amount: Mapped[object] = mapped_column(Money)  # Stand bei Erstellung
    due_date: Mapped[date] = mapped_column(Date)


class BankAccount(Base):
    __tablename__ = "bank_account"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    iban: Mapped[str | None] = mapped_column(String(40))  # nur Kontokennung, KEINE Zugangsdaten
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class BankImport(Base):
    __tablename__ = "bank_import"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("bank_account.id"), index=True)
    format: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    imported_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    total_rows: Mapped[int] = mapped_column(Integer)
    new_rows: Mapped[int] = mapped_column(Integer)
    duplicate_rows: Mapped[int] = mapped_column(Integer)


class BankTransaction(Base):
    __tablename__ = "bank_transaction"
    __table_args__ = (UniqueConstraint("account_id", "fingerprint"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("bank_account.id"), index=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("bank_import.id"), index=True)
    booking_date: Mapped[date] = mapped_column(Date, index=True)
    value_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[object] = mapped_column(Money)  # vorzeichenbehaftet: + Eingang, − Ausgang
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    counterparty_name: Mapped[str | None] = mapped_column(String(300))
    counterparty_iban: Mapped[str | None] = mapped_column(String(40))
    reference: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(120))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)
    ignore_reason: Mapped[str | None] = mapped_column(Text)
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payment.id"), unique=True)
    confirmed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict | None] = mapped_column(JSON)


class LeaseAllocationWeight(Base):
    """Individuelle Gewichte (Wohneinheiten) für die Verteilung einer Hauptmiete (allocation_method = custom)."""
    __tablename__ = "lease_allocation_weight"
    __table_args__ = (UniqueConstraint("lease_id", "unit_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("lease.id"), index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("unit.id"))
    weight: Mapped[object] = mapped_column(Area)
