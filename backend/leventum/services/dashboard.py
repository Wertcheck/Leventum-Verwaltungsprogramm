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
    ("overdue_tasks", "Überfällige Aufgaben", "E"),
    ("open_repairs", "Offene Reparaturen", "E"),
    ("physical_vacancy", "Physischer Leerstand (unbelegte Betten/Zimmer/Einheiten)", "D"),
    ("economic_vacancy_cost", "Wirtschaftlicher Leerstand (Kosten, laufender Monat)", "D"),
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


def _fig(db):
    from leventum.services.economics import current_month_figures
    return current_month_figures(db)


# Implementierte Kennzahlen: key -> (Funktion(db) -> Wert, Format). Geld als String-Dezimal.
IMPLEMENTED_MONEY: dict = {
    "main_rent_obligations": lambda db: _fig(db)["main_total"],
    "sublease_receivables": lambda db: _fig(db)["sub_total"],
    "open_receivables": lambda db: _fig(db)["open_receivables"],
    "monthly_utility_costs": lambda db: _fig(db)["main_utility"],
    "economic_vacancy_cost": lambda db: _fig(db)["economic_vacancy_cost"],
}
def _open_tasks(db):
    from leventum import domain as d
    from leventum.models import Task
    return db.scalar(select(func.count()).select_from(Task).where(Task.status.in_(d.TASK_OPEN)))


def _overdue_tasks(db):
    from leventum.models import Task
    from leventum.services.tasks import query
    return len(query(db, overdue=True))


def _open_repairs(db):
    from leventum import domain as d
    from leventum.models import Repair
    return db.scalar(select(func.count()).select_from(Repair).where(Repair.status.in_(d.REPAIR_OPEN)))


IMPLEMENTED: dict = {
    "open_tasks": _open_tasks, "overdue_tasks": _overdue_tasks, "open_repairs": _open_repairs,
    "overdue_payments": lambda db: _fig(db)["overdue_count"],
    "physical_vacancy": lambda db: _fig(db)["vacant_leaves"],
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
        if key in IMPLEMENTED_MONEY:
            kpis.append({"key": key, "label": label, "value": format(IMPLEMENTED_MONEY[key](db), "f"), "format": "eur", "available": True, "planned_phase": phase})
        elif fn is None:
            kpis.append({"key": key, "label": label, "value": None, "available": False, "planned_phase": phase})
        else:
            kpis.append({"key": key, "label": label, "value": fn(db), "available": True, "planned_phase": phase})
    from leventum.api.master import js
    from leventum.services import reminders as rem, tasks as tk
    from leventum.api.master import ser
    return {"kpis": kpis, "warnings": js(rem.compute(db)[:8]),
            "tasks": [{**ser(t), "overdue": tk.is_overdue(t)} for t in tk.query(db, open_only=True)[:5]]}
