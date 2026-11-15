"""Operative Verwaltung (Phase E): Aufgaben, Reparaturen, Kommunikation, Übergabeprotokolle."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from leventum.db.base import Base, Money, utcnow
from leventum.models.master import Timestamps


class Task(Base, Timestamps):
    __tablename__ = "task"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    status: Mapped[str] = mapped_column(String(15), default="open", index=True)
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    assignee_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    party_id: Mapped[int | None] = mapped_column(ForeignKey("party.id"), index=True)
    property_id: Mapped[int | None] = mapped_column(ForeignKey("property.id"), index=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("unit.id"))
    lease_id: Mapped[int | None] = mapped_column(ForeignKey("lease.id"), index=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoice.id"))
    repair_id: Mapped[int | None] = mapped_column(ForeignKey("repair.id"), index=True)
    source: Mapped[str] = mapped_column(String(15), default="manual")  # manual | reminder
    dedupe_key: Mapped[str | None] = mapped_column(String(160), unique=True)  # aus Erinnerungen erzeugte Aufgaben
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))


class Repair(Base, Timestamps):
    __tablename__ = "repair"
    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("unit.id"))
    lease_id: Mapped[int | None] = mapped_column(ForeignKey("lease.id"))
    reported_by_party_id: Mapped[int | None] = mapped_column(ForeignKey("party.id"))
    contractor_party_id: Mapped[int | None] = mapped_column(ForeignKey("party.id"))
    reported_on: Mapped[date] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(20), default="sonstige")
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    status: Mapped[str] = mapped_column(String(15), default="reported", index=True)
    cost_estimate: Mapped[object | None] = mapped_column(Money)
    scheduled_for: Mapped[date | None] = mapped_column(Date)
    completed_on: Mapped[date | None] = mapped_column(Date)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))


class RepairEvent(Base):
    """Verlauf eines Reparaturvorgangs (append-only)."""
    __tablename__ = "repair_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    repair_id: Mapped[int] = mapped_column(ForeignKey("repair.id"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    kind: Mapped[str] = mapped_column(String(20))  # reported | status | note | estimate | contractor | invoice | scheduled
    text: Mapped[str] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))


class Communication(Base):
    """Protokollierter Kommunikationsvorgang. Die Software versendet nichts. Unveränderlich."""
    __tablename__ = "communication"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(15))
    direction: Mapped[str] = mapped_column(String(3))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str | None] = mapped_column(Text)
    party_id: Mapped[int | None] = mapped_column(ForeignKey("party.id"), index=True)
    lease_id: Mapped[int | None] = mapped_column(ForeignKey("lease.id"), index=True)
    property_id: Mapped[int | None] = mapped_column(ForeignKey("property.id"))
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("unit.id"))
    repair_id: Mapped[int | None] = mapped_column(ForeignKey("repair.id"))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HandoverProtocol(Base):
    __tablename__ = "handover_protocol"
    id: Mapped[int] = mapped_column(primary_key=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("lease.id"), index=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("unit.id"))
    kind: Mapped[str] = mapped_column(String(10))
    protocol_date: Mapped[date] = mapped_column(Date)
    keys_handed: Mapped[int | None] = mapped_column(Integer)
    meter_readings: Mapped[str | None] = mapped_column(Text)
    condition_notes: Mapped[str | None] = mapped_column(Text)
    attendees: Mapped[str | None] = mapped_column(Text)
    signed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
