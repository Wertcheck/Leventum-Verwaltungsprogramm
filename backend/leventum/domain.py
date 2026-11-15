"""Fachliche Aufzählungen. Als Strings gespeichert (portabel); Validierung in Services/Schemas."""
PARTY_KINDS = ("person", "company")
PARTY_ROLES = ("owner", "landlord", "tenant", "service_provider")
PROPERTY_TYPES = ("mehrfamilienhaus", "wohnung", "einfamilienhaus", "gewerbeeinheit", "sonstige")
SPACE_LEVELS = ("property", "unit", "room", "bed")
UNIT_MANUAL_STATUS = ("reserved", "renovation", "unavailable")
LEASE_KINDS = ("main", "sub")
LEASE_STATUS = ("draft", "active", "terminated", "ended", "cancelled")
RUNNING_STATUS = ("active", "terminated")          # blockieren Flächen / zählen als laufend
LEASE_PARTY_ROLES = ("lessor", "lessee", "co_lessee", "occupant", "guarantor")
LEGAL_REVIEW = ("not_reviewed", "in_review", "reviewed")
RENT_PERIODS = ("month", "day")
PAYMENT_RHYTHMS = ("monthly", "quarterly", "yearly", "on_demand")
UTILITY_MODES = ("flat_rate", "prepayment", "included", "individual", "none")
ALLOC_KEYS = ("area", "equal", "persons", "consumption", "custom", "none")
ALLOCABLE_STATUS = ("unreviewed", "allocable", "not_allocable")
STATEMENT_STATUS = ("draft", "captured", "reviewed")
PREPAYMENT_SOURCES = ("agreed_calculated", "statement", "manual")
NOTE_KINDS = ("note", "review", "hint")

# Nur Vorschlagsliste für das Freitextfeld "rechtliche Grundlage". Keine automatische Zuordnung, keine Rechtsauskunft.
LEGAL_REF_SUGGESTIONS = ["§ 549 BGB"]

LEASE_TYPE_SEEDS = [
    # code, name, applies_to, requires_fixed_term_reason
    ("hauptmiete", "Hauptmietvertrag (Leventum als Mieter)", "main", False),
    ("wohnraum_unbefristet", "Untermiete Wohnraum, unbefristet", "sub", False),
    ("wohnraum_befristet", "Untermiete Wohnraum, befristet", "sub", True),
    ("zimmer", "Zimmervermietung", "sub", False),
    ("bett", "Bettenvermietung", "sub", False),
    ("monteurwohnung", "Monteurwohnung", "sub", False),
    ("boardinghouse", "Boardinghouse / möbliertes Wohnen auf Zeit", "sub", False),
    ("gewerbe", "Gewerbliche Vermietung", "both", False),
    ("sonstige", "Sonstige / individuell", "both", False),
]
COST_TYPE_SEEDS = [
    "Grundsteuer", "Wasserversorgung", "Entwässerung", "Heizung", "Warmwasser", "Aufzug",
    "Straßenreinigung / Müllbeseitigung", "Gebäudereinigung", "Gartenpflege", "Allgemeinstrom",
    "Schornsteinfeger", "Versicherungen", "Hauswart", "Kabel / Antenne", "Sonstige Kosten",
]
