"""Dashboard-Kennzahlen. Es werden ausschließlich real berechnete Werte geliefert.
Kennzahlen, deren Datenquelle noch nicht existiert (Phasen C–E), sind explizit `available=False`
und haben `value=None` – keine Platzhalter- oder Demo-Zahlen."""
from __future__ import annotations

from sqlalchemy.orm import Session

# (key, label, benötigte Phase)
KPI_DEFINITIONS = [
    ("properties", "Immobilien", "C"),
    ("units", "Wohneinheiten", "C"),
    ("active_main_leases", "Aktive Hauptmietverträge", "C"),
    ("active_subleases", "Aktive Untermietverträge", "C"),
    ("active_tenants", "Aktive Mieter", "C"),
    ("main_rent_obligations", "Monatliche Hauptmietverpflichtungen", "D"),
    ("sublease_receivables", "Monatliche Untermietforderungen", "D"),
    ("open_receivables", "Offene Mietforderungen", "D"),
    ("overdue_payments", "Überfällige Zahlungen", "D"),
    ("monthly_utility_costs", "Monatliche Betriebskosten", "D"),
    ("open_tasks", "Offene Aufgaben", "E"),
    ("upcoming_contract_ends", "Anstehende Vertragsenden", "C"),
]

from datetime import date, timedelta

from sqlalchemy import distinct, func, select

from leventum import domain
from leventum.models import Lease, LeaseParty, Property, Unit
from leventum.services.leases import OPEN_END, effective_end


def _running(db, kind):
    today = date.today()
    return [x for x in db.scalars(select(Lease).where(Lease.kind == kind, Lease.status.in_(domain.RUNNING_STATUS)))
            if x.start_date <= today <= (effective_end(x) or OPEN_END)]


def _active_tenants(db):
    ids = {p.party_id for lease in _running(db, "sub") for p in lease.parties if p.role in ("lessee", "co_lessee")}
    return len(ids)


def _upcoming_ends(db):
    today, horizon = date.today(), date.today() + timedelta(days=90)
    return sum(1 for lease in db.scalars(select(Lease).where(Lease.status.in_(domain.RUNNING_STATUS)))
               if (e := effective_end(lease)) is not None and today <= e <= horizon)


# Implementierte Zähler: key -> Funktion(db) -> int
IMPLEMENTED: dict = {
    "properties": lambda db: db.scalar(select(func.count()).select_from(Property).where(Property.is_active.is_(True))),
    "units": lambda db: db.scalar(select(func.count()).select_from(Unit).where(Unit.is_active.is_(True))),
    "active_main_leases": lambda db: len(_running(db, "main")),
    "active_subleases": lambda db: len(_running(db, "sub")),
    "active_tenants": _active_tenants,
    "upcoming_contract_ends": _upcoming_ends,
}


def build_dashboard(db: Session) -> dict:
    kpis = []
    for key, label, phase in KPI_DEFINITIONS:
        fn = IMPLEMENTED.get(key)
        if fn is None:
            kpis.append({"key": key, "label": label, "value": None, "available": False, "planned_phase": phase})
        else:
            kpis.append({"key": key, "label": label, "value": fn(db), "available": True, "planned_phase": phase})
    return {"kpis": kpis, "warnings": [], "tasks": []}
