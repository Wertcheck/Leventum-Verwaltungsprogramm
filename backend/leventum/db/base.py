from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, MetaData
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

# Benannte Constraints: Voraussetzung für Alembic-Batch-Migrationen auf SQLite.
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class Money(TypeDecorator):
    """Decimal mit 2 Nachkommastellen, gespeichert als BIGINT (Cent). Kein float, DB-unabhängig."""

    impl = BigInteger
    cache_ok = True
    SCALE = 100

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        d = Decimal(str(value)) if not isinstance(value, Decimal) else value
        scaled = d * self.SCALE
        if scaled != scaled.to_integral_value():
            raise ValueError(f"Betrag {value} hat mehr als 2 Nachkommastellen")
        return int(scaled)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return (Decimal(int(value)) / self.SCALE).quantize(Decimal("0.01"))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
