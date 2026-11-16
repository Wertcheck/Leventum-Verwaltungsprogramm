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
    ("overdue_receivables", "Überfällige Mietforderungen", "D"),
    ("overdue_payments", "Überfällige Zahlungen", "D"),
    ("monthly_utility_costs", "Monatliche Betriebskosten", "D"),
    ("open_tasks", "Offene Aufgaben", "E"),
    ("overdue_tasks", "Überfällige Aufgaben", "E"),
    ("open_repairs", "Offene Reparaturen", "E"),
    ("physical_vacancy", "Physischer Leerstand", "D"),
    ("economic_vacancy_cost", "Wirtschaftlicher Leerstand (Monat)", "D"),
    ("upcoming_contract_ends", "Anstehende Vertragsenden", "C"),
    ("upcoming_main_lease_ends", "Anstehende Hauptmietvertragsenden", "C"),
    ("upcoming_sublease_ends", "Anstehende Untermietvertragsenden", "C"),
]

from datetime import date

from sqlalchemy import func, select

from leventum import domain
from leventum.models import Lease, Property, Unit
from leventum.services import stichtag as ST
from leventum.services.charges import receivable_position
from leventum.services.leases import is_running, upcoming_ends


def _running(db, kind, as_of=None):
    return [x for x in db.scalars(select(Lease).where(Lease.kind == kind, Lease.status.in_(domain.RUNNING_STATUS))) if is_running(x, as_of)]


def _active_tenants(db, as_of=None):
    """Aktiver Mieter = Person/Firma mit mindestens einem LAUFENDEN Untermietvertrag als Mieter/Mitmieter (Bewohner, Bürgen und Personen ohne Vertrag zählen nicht)."""
    ids = {p.party_id for lease in _running(db, "sub", as_of) for p in lease.parties if p.role in ("lessee", "co_lessee")}
    return len(ids)


def _upcoming_ends(db, as_of, days, kind=None):
    return len(upcoming_ends(db, as_of, days, kind))  # zentrale Definition in services/leases.py (gleiche Quelle wie /reminders)


def _units(db):
    """Aktive Wohneinheiten aktiver Objekte (analog economics.Structure)."""
    return db.scalar(select(func.count()).select_from(Unit).join(Property, Property.id == Unit.property_id)
                     .where(Unit.is_active.is_(True), Property.is_active.is_(True)))


def _fig(db):
    """Die Monatsauswertung ist aufwendig und wird je Dashboard-Aufruf (= je Session) nur einmal berechnet.
    Sie bezieht sich immer auf den heutigen Monat (keine Historie, siehe ADR 0002 A6); der Stichtag ist Teil des Cache-Schlüssels."""
    from leventum.services.economics import current_month_figures
    key = ("_fig", db.info.get("_as_of"))
    if key not in db.info:
        db.info[key] = current_month_figures(db)
    return db.info[key]


def _pos(db, as_of):
    """Offene/überfällige Forderungen zum Stichtag – zentrale Funktion charges.receivable_position, je Stichtag einmal je Aufruf."""
    key = ("_pos", as_of)
    if key not in db.info:
        db.info[key] = receivable_position(db, as_of)
    return db.info[key]


# Zentrale, sichtbare Definitionen (Tooltip/Dokumentation) – jede Kennzahl hat genau EINE Berechnungsquelle.
DEFINITIONS = {
    "properties": "Aktive Objekte (nicht deaktiviert).",
    "units": "Aktive Wohneinheiten in aktiven Objekten (inaktive Einheiten oder Einheiten inaktiver Objekte zählen nicht).",
    "active_main_leases": "Hauptmietverträge mit Status aktiv/gekündigt, die heute laufen (Beginn ≤ heute ≤ wirksames Ende).",
    "active_subleases": "Untermietverträge mit Status aktiv/gekündigt, die heute laufen. Gekündigte Verträge laufen bis zum wirksamen Ende weiter und zählen mit (davon-Angabe).",
    "active_tenants": "Verschiedene Personen/Firmen mit mindestens einem laufenden Untermietvertrag als Mieter oder Mitmieter. Personen ohne laufenden Vertrag, Bewohner und Bürgen zählen nicht.",
    "main_rent_obligations": "Soll der Hauptmieten (Kalt + Nebenkosten) für den laufenden Monat, tagesanteilig laut Vertragskonditionen (aus der zentralen Soll-Berechnung).",
    "sublease_receivables": "Soll der Untermieten (Kalt + Nebenkosten) für den laufenden Monat, tagesanteilig laut Vertragskonditionen.",
    "open_receivables": "Summe aller offenen Forderungen gegen Untermieter zum Stichtag (Sollstellungen abzüglich der Zahlungen mit Buchungsdatum bis zum Stichtag), unabhängig von der Fälligkeit; später gebuchte Zahlungen mindern den Stand zum Stichtag nicht. Einschränkung: später zurückgenommene Zuordnungen und heute stornierte Sollstellungen wirken auch auf historische Stichtage (ADR 0002, A6).",
    "overdue_receivables": "EUR-Summe der offenen Beträge (nach Teilzahlungen mit Buchungsdatum bis zum Stichtag) aller Forderungen gegen Untermieter, deren Fälligkeit vor dem Stichtag liegt. Teilmenge der offenen Mietforderungen (diese enthalten auch noch nicht fällige Forderungen). Gleiche Einschränkungen für historische Stichtage wie dort (ADR 0002, A6).",
    "overdue_payments": "Anzahl offener Forderungspositionen (Sollstellungen) zum Stichtag, deren Fälligkeit vor dem Stichtag liegt – nach Teilzahlungen mit Buchungsdatum bis zum Stichtag.",
    "monthly_utility_costs": "Nebenkosten-Soll der Hauptmieten (Vorauszahlung + Pauschale) für den laufenden Monat.",
    "open_tasks": "Aufgaben mit Status offen, in Bearbeitung oder wartet.",
    "overdue_tasks": "Offene Aufgaben mit Fälligkeit vor heute.",
    "open_repairs": "Reparaturen mit Status gemeldet, terminiert, in Arbeit oder wartet.",
    "physical_vacancy": "Anzahl heute unbelegter kleinster Einheiten (Bett, Zimmer ohne Betten, Wohneinheit ohne Zimmer) ohne laufenden Untermietvertrag.",
    "economic_vacancy_cost": "Hauptmiete-Soll (Kalt+NK) des laufenden Monats an Tagen mit Mietverpflichtung, aber ohne laufenden Untermietvertrag (Teil der Hauptmietkosten).",
    "upcoming_contract_ends": "Zum Stichtag laufende Haupt- und Untermietverträge (Mietbeginn erreicht), deren wirksames Ende zwischen Stichtag und Stichtag + Vorschauzeitraum liegt (beide Grenzen inklusiv). Der Vorschauzeitraum ist konfigurierbar (Einstellung contract_end_preview_days, Standard 90 Tage). Verträge mit offenem Ende und nicht begonnene Verträge zählen nicht. Summe aus Hauptmiet- und Untermietvertragsenden.",
    "upcoming_main_lease_ends": "Zum Stichtag laufende Hauptmietverträge (Mietbeginn erreicht), deren wirksames Ende zwischen Stichtag und Stichtag + Vorschauzeitraum liegt (beide Grenzen inklusiv; Einstellung contract_end_preview_days, Standard 90 Tage). Offenes Ende und nicht begonnene Verträge zählen nicht.",
    "upcoming_sublease_ends": "Zum Stichtag laufende Untermietverträge (Mietbeginn erreicht, auch gekündigte mit wirksamem Ende), deren wirksames Ende zwischen Stichtag und Stichtag + Vorschauzeitraum liegt (beide Grenzen inklusiv; Einstellung contract_end_preview_days, Standard 90 Tage). Offenes Ende und nicht begonnene Verträge zählen nicht.",
}


def _hint(db, key, as_of=None):
    if key in ("active_subleases", "active_tenants"):
        running = _running(db, "sub", as_of)
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


# Implementierte Kennzahlen: key -> Funktion(db, as_of, days) -> Wert. Geld als String-Dezimal.
IMPLEMENTED_MONEY: dict = {
    "main_rent_obligations": lambda db, a, n: _fig(db)["main_total"],
    "sublease_receivables": lambda db, a, n: _fig(db)["sub_total"],
    "open_receivables": lambda db, a, n: _pos(db, a)["open_total"],
    "overdue_receivables": lambda db, a, n: _pos(db, a)["overdue_total"],
    "monthly_utility_costs": lambda db, a, n: _fig(db)["main_utility"],
    "economic_vacancy_cost": lambda db, a, n: _fig(db)["economic_vacancy_cost"],
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
    "open_tasks": lambda db, a, n: _open_tasks(db), "overdue_tasks": lambda db, a, n: _overdue_tasks(db), "open_repairs": lambda db, a, n: _open_repairs(db),
    "overdue_payments": lambda db, a, n: _pos(db, a)["overdue_count"],
    "physical_vacancy": lambda db, a, n: _fig(db)["vacant_leaves"],
    "properties": lambda db, a, n: db.scalar(select(func.count()).select_from(Property).where(Property.is_active.is_(True))),
    "units": lambda db, a, n: _units(db),
    "active_main_leases": lambda db, a, n: len(_running(db, "main", a)),
    "active_subleases": lambda db, a, n: len(_running(db, "sub", a)),
    "active_tenants": lambda db, a, n: _active_tenants(db, a),
    "upcoming_contract_ends": _upcoming_ends,
    "upcoming_main_lease_ends": lambda db, a, n: _upcoming_ends(db, a, n, "main"),
    "upcoming_sublease_ends": lambda db, a, n: _upcoming_ends(db, a, n, "sub"),
}

# Stichtagsfähig (as_of wirkt echt): Verträge (Status/Stammdaten zeigen den heutigen Stand, ADR 0002 A6c), Forderungen, Überfällige, Vertragsenden.
# Alle übrigen Kennzahlen zeigen immer den heutigen Stand bzw. den heutigen Monat (keine erfundene Historie).
HISTORICAL_SUPPORTED = {"active_main_leases", "active_subleases", "active_tenants", "open_receivables", "overdue_receivables", "overdue_payments",
                        "upcoming_contract_ends", "upcoming_main_lease_ends", "upcoming_sublease_ends"}

DASHBOARD_LIMITATIONS = [
    "Historisch (Stichtag in der Vergangenheit) berechnet: Vertragsstatus, Forderungen, Überfällige und Vertragsenden.",
    "Immobilien, Wohneinheiten, Monatswerte (Soll, Betriebskosten, Leerstand), Aufgaben und Reparaturen zeigen immer den heutigen Stand.",
    "Später zurückgenommene Zuordnungen, heute stornierte Sollstellungen und vorzeitig beendete Verträge wirken auch auf historische Stichtage (ADR 0002, A6).",
    "Verträge mit gespeichertem Status „beendet“ fehlen in historischen Ständen vor ihrem Ende (A6c; Review M5); Verträge mit Enddatum in der Vergangenheit und Status „aktiv“ werden dagegen korrekt gezählt.",
]


def build_dashboard(db: Session, as_of: date | str | None = None, preview_days: int | None = None, include_finance: bool = True) -> dict:
    """as_of=None -> heute (Datum oder ISO-Text; Auflösung über services/stichtag.resolve). Zukunft -> 422. preview_days: Vorschauzeitraum Vertragsenden
    (None -> Standard aus Settings). include_finance=False (Recht finance:read fehlt): nur KPIs aus NON_FINANCE_KPI_KEYS (Allow-Liste) und nur nicht-finanzielle Hinweise; Rest wird weder
    berechnet noch ausgeliefert; `stichtag.historical_available` = include_finance."""
    from leventum.security.finance_access import NON_FINANCE_KPI_KEYS
    st = ST.resolve(as_of)
    as_of = st.as_of
    if preview_days is None:
        from leventum.config import Settings
        preview_days = Settings().contract_end_preview_days
    db.info["_as_of"] = as_of
    kpis = []
    for key, label, phase in KPI_DEFINITIONS:
        if not include_finance and key not in NON_FINANCE_KPI_KEYS:  # Allow-Liste: unklassifizierte KPIs bleiben ohne finance:read verborgen
            continue
        fn = IMPLEMENTED.get(key)
        if key in IMPLEMENTED_MONEY:
            kpis.append({"key": key, "label": label, "value": format(IMPLEMENTED_MONEY[key](db, as_of, preview_days), "f"), "format": "eur", "available": True, "planned_phase": phase})
        elif fn is None:
            kpis.append({"key": key, "label": label, "value": None, "available": False, "planned_phase": phase})
        else:
            kpis.append({"key": key, "label": label, "value": fn(db, as_of, preview_days), "available": True, "planned_phase": phase})
    for k in kpis:
        k["definition"] = DEFINITIONS[k["key"]]
        k["hint"] = _hint(db, k["key"], as_of)
        k["historical_supported"] = k["key"] in HISTORICAL_SUPPORTED
    from leventum.api.master import js
    from leventum.services import reminders as rem, tasks as tk
    from leventum.api.master import ser
    return {"as_of": as_of.isoformat(), "stichtag": ST.meta("dashboard", st, historical_supported=True, limitations=DASHBOARD_LIMITATIONS, historical_available=include_finance),
            "kpis": kpis, "warnings": js(rem.compute(db, preview_days=preview_days, include_finance=include_finance)[:8]),
            "tasks": [{**ser(t), "overdue": tk.is_overdue(t)} for t in tk.query(db, open_only=True)[:5]]}
