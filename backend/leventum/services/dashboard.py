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

# Implementierte Zähler: key -> Funktion(db) -> int. Wird in Phase C/E befüllt.
IMPLEMENTED: dict = {}


def build_dashboard(db: Session) -> dict:
    kpis = []
    for key, label, phase in KPI_DEFINITIONS:
        fn = IMPLEMENTED.get(key)
        if fn is None:
            kpis.append({"key": key, "label": label, "value": None, "available": False, "planned_phase": phase})
        else:
            kpis.append({"key": key, "label": label, "value": fn(db), "available": True, "planned_phase": phase})
    return {"kpis": kpis, "warnings": [], "tasks": []}
