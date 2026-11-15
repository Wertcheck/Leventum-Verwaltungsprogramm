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
PAYMENT_RHYTHMS = ("monthly", "quarterly", "half_yearly", "yearly", "on_demand")
RHYTHM_MONTHS = {"monthly": 1, "quarterly": 3, "half_yearly": 6, "yearly": 12}  # on_demand: keine automatische Sollstellung
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

# --- Phase D ---
CHARGE_DIRECTIONS = ("receivable", "payable")
CHARGE_TYPES = ("base_rent", "other_charges", "utility_prepayment", "utility_flat_rate", "other")
PAYMENT_DIRECTIONS = ("in", "out")
PAYMENT_METHODS = ("bank_transfer", "cash", "direct_debit", "other")
DEPOSIT_TX_KINDS = ("paid", "refunded", "retained")
DUNNING_STATUS = ("draft", "approved", "sent", "cancelled")
DUNNING_LEVELS = {1: "Zahlungserinnerung", 2: "Erste Mahnung", 3: "Zweite Mahnung"}
ALLOCATION_METHODS = ("area", "equal", "custom")
BANK_TX_STATUS = ("open", "confirmed", "ignored")
DOC_TYPES = ("mietvertrag", "nachtrag", "uebergabeprotokoll", "rechnung", "betriebskostenabrechnung", "schriftverkehr",
             "versicherung", "reparaturbeleg", "kaution", "sonstige")
DOC_ENTITIES = ("party", "property", "unit", "lease", "invoice", "deposit", "deposit_transaction", "payment", "repair", "task", "communication", "handover_protocol")

# --- Phase E ---
TASK_STATUS = ("open", "in_progress", "waiting", "done", "cancelled")
TASK_OPEN = ("open", "in_progress", "waiting")
PRIORITIES = ("low", "normal", "high", "urgent")
REPAIR_STATUS = ("reported", "scheduled", "in_progress", "waiting", "done", "cancelled")
REPAIR_OPEN = ("reported", "scheduled", "in_progress", "waiting")
REPAIR_CATEGORIES = ("heizung", "wasserschaden", "elektrik", "sanitaer", "fenster", "tuerschloss", "instandhaltung", "sonstige")
COMM_CHANNELS = ("email", "phone", "letter", "in_person", "messenger", "other")
COMM_DIRECTIONS = ("in", "out")
HANDOVER_KINDS = ("move_in", "move_out")
# Annahme (nicht rechtlich, nur organisatorisch): welche Dokumenttypen je Vertragsart vorhanden sein sollen
REQUIRED_DOCS = {"main": ("mietvertrag",), "sub": ("mietvertrag", "uebergabeprotokoll")}
TASK_LABEL = {"open": "Offen", "in_progress": "In Bearbeitung", "waiting": "Wartet auf Rückmeldung", "done": "Erledigt", "cancelled": "Abgebrochen"}
REPAIR_LABEL = {"reported": "Gemeldet", "scheduled": "Terminiert", "in_progress": "In Arbeit", "waiting": "Wartet", "done": "Erledigt", "cancelled": "Abgebrochen"}
