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
    ("physical_vacancy", "Physischer Leerstand", "D"),
    ("economic_vacancy_cost", "Wirtschaftlicher Leerstand (Monat)", "D"),
    ("upcoming_contract_ends", "Anstehende Vertragsenden", "C"),
]

from datetime import date, timedelta

from sqlalchemy import distinct, func, select

from leventum import domain
from leventum.models import Lease, LeaseParty, Property, Unit
from leventum.services.leases import effective_end, is_running, phase


def _running(db, kind):
    return [x for x in db.scalars(select(Lease).where(Lease.kind == kind, Lease.status.in_(domain.RUNNING_STATUS))) if is_running(x)]


def _active_tenants(db):
    """Aktiver Mieter = Person/Firma mit mindestens einem LAUFENDEN Untermietvertrag als Mieter/Mitmieter (Bewohner, Bürgen und Personen ohne Vertrag zählen nicht)."""
    ids = {p.party_id for lease in _running(db, "sub") for p in lease.parties if p.role in ("lessee", "co_lessee")}
    return len(ids)


def _upcoming_ends(db):
    today, horizon = date.today(), date.today() + timedelta(days=90)
    return sum(1 for lease in db.scalars(select(Lease).where(Lease.status.in_(domain.RUNNING_STATUS)))
               if (e := effective_end(lease)) is not None and today <= e <= horizon)


def _fig(db):
    """Die Monatsauswertung ist aufwendig und wird je Dashboard-Aufruf (= je Session) nur einmal berechnet."""
    from leventum.services.economics import current_month_figures
    if "_fig" not in db.info:
        db.info["_fig"] = current_month_figures(db)
    return db.info["_fig"]


# Zentrale, sichtbare Definitionen (Tooltip/Dokumentation) – jede Kennzahl hat genau EINE Berechnungsquelle.
DEFINITIONS = {
    "properties": "Aktive Objekte (nicht deaktiviert).",
    "units": "Aktive Wohneinheiten aktiver Objekte.",
    "active_main_leases": "Hauptmietverträge mit Status aktiv/gekündigt, die heute laufen (Beginn ≤ heute ≤ wirksames Ende).",
    "active_subleases": "Untermietverträge mit Status aktiv/gekündigt, die heute laufen. Gekündigte Verträge laufen bis zum wirksamen Ende weiter und zählen mit (davon-Angabe).",
    "active_tenants": "Verschiedene Personen/Firmen mit mindestens einem laufenden Untermietvertrag als Mieter oder Mitmieter. Personen ohne laufenden Vertrag, Bewohner und Bürgen zählen nicht.",
    "main_rent_obligations": "Soll der Hauptmieten (Kalt + Nebenkosten) für den laufenden Monat, tagesanteilig laut Vertragskonditionen (aus der zentralen Soll-Berechnung).",
    "sublease_receivables": "Soll der Untermieten (Kalt + Nebenkosten) für den laufenden Monat, tagesanteilig laut Vertragskonditionen.",
    "open_receivables": "Summe aller offenen Forderungen gegen Untermieter (Sollstellungen abzüglich zugeordneter Zahlungen), unabhängig von der Fälligkeit.",
    "overdue_payments": "Anzahl offener Forderungspositionen (Sollstellungen), deren Fälligkeit vor heute liegt – nach Teilzahlungen.",
    "monthly_utility_costs": "Nebenkosten-Soll der Hauptmieten (Vorauszahlung + Pauschale) für den laufenden Monat.",
    "open_tasks": "Aufgaben mit Status offen, in Bearbeitung oder wartet.",
    "overdue_tasks": "Offene Aufgaben mit Fälligkeit vor heute.",
    "open_repairs": "Reparaturen mit Status gemeldet, terminiert, in Arbeit oder wartet.",
    "physical_vacancy": "Anzahl heute unbelegter kleinster Einheiten (Bett, Zimmer ohne Betten, Wohneinheit ohne Zimmer) ohne laufenden Untermietvertrag.",
    "economic_vacancy_cost": "Hauptmiete-Soll (Kalt+NK) des laufenden Monats an Tagen mit Mietverpflichtung, aber ohne laufenden Untermietvertrag (Teil der Hauptmietkosten).",
    "upcoming_contract_ends": "Laufende Verträge, deren wirksames Ende in den nächsten 90 Tagen liegt.",
}


def _hint(db, key):
    if key in ("active_subleases", "active_tenants"):
        running = _running(db, "sub")
        if key == "active_subleases":
            n = sum(1 for x in running if x.status == "terminated")
        else:  # Mieter, deren sämtliche laufenden Verträge gekündigt sind
            by: dict[int, list[bool]] = {}
            for x in running:
                for p in x.parties:
                    if p.role in ("lessee", "co_lessee"):
                        by.setdefault(p.party_id, []).append(x.status == "terminated")
            n = sum(1 for flags in by.values() if all(flags))
        return f"davon {n} in Kündigung" if n else None
    return None


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
    for k in kpis:
        k["definition"] = DEFINITIONS[k["key"]]
        k["hint"] = _hint(db, k["key"])
    from leventum.api.master import js
    from leventum.services import reminders as rem, tasks as tk
    from leventum.api.master import ser
    return {"kpis": kpis, "warnings": js(rem.compute(db)[:8]),
            "tasks": [{**ser(t), "overdue": tk.is_overdue(t)} for t in tk.query(db, open_only=True)[:5]]}
