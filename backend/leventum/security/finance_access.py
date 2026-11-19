"""Zentrale Prüfung für Finanzinformationen (Eigentümerentscheidung: Finanzinformationen nur mit Recht finance:read).

Gilt für Stellen, die Finanzwerte in sonst nicht-finanzielle Routen einbetten (Dashboard, Hinweise, Mieterliste/-akte).
Die Prüfung erfolgt immer serverseitig; die 403-Antwort enthält keine Beträge."""
from __future__ import annotations

from fastapi import HTTPException

from leventum.models import AppUser
from leventum.security.permissions import has_permission

FINANCE_PERMISSION = "finance:read"

# Dashboard-KPIs: ALLOW-LISTE (NON_FINANCE_KPI_KEYS) statt Deny-Liste. Ohne finance:read bleiben nur ausdrücklich als nicht finanziell
# klassifizierte KPIs sichtbar; neue/unklassifizierte KPIs sind standardmäßig verborgen. Jeder Schlüssel aus dashboard.KPI_DEFINITIONS steht
# in genau einer der beiden Mengen (Test test_i5 K1). physical_vacancy (reine Anzahl) bleibt bewusst für alle sichtbar.
FINANCE_KPI_KEYS = frozenset({"main_rent_obligations", "sublease_receivables", "open_receivables", "overdue_payments",
                              "monthly_utility_costs", "economic_vacancy_cost", "overdue_receivables"})
NON_FINANCE_KPI_KEYS = frozenset({"properties", "units", "active_main_leases", "active_subleases", "active_tenants", "open_tasks", "overdue_tasks",
                                  "open_repairs", "physical_vacancy", "occupancy_rate", "upcoming_contract_ends",
                                  # Vertragsenden getrennt (Phase I, Entscheidung 2.2): reine Anzahlen, keine Finanzdaten
                                  "upcoming_main_lease_ends", "upcoming_sublease_ends"})

# Hinweistypen (reminders): Finanzbezug und die zugehörigen Schlüsselpräfixe (Teil vor dem ersten ':' des Hinweisschlüssels); NON_FINANCE = Allow-Liste.
FINANCE_REMINDER_TYPES = frozenset({"overdue_payment", "deposit_overdue", "utility_statement_due"})
NON_FINANCE_REMINDER_TYPES = frozenset({"contract_end", "notice_deadline", "missing_document", "repair_overdue", "repair_upcoming", "repair_urgent"})
FINANCE_REMINDER_KEY_PREFIXES = frozenset({"overdue", "deposit", "utility_statement"})

# Dokumenttypen mit Finanzbezug: ohne finance:read unsichtbar, nicht ladbar, nicht hochladbar, nicht verknüpfbar/löschbar.
FINANCE_DOC_TYPES = frozenset({"rechnung", "betriebskostenabrechnung", "kaution"})

# Wiederkehrende Audit-Ereignisse mit Finanzbezug (Historie/Mieterakte ohne finance:read).
FINANCE_AUDIT_ENTITY_TYPES = frozenset({"deposit", "deposit_transaction", "dunning_notice", "invoice", "payment", "charge", "bank_account", "bank_import",
                                        "bank_transaction", "utility_statement"})
FINANCE_AUDIT_ACTION_PREFIXES = ("deposit.", "dunning.", "invoice.", "payment.", "charge.", "bank.", "utility_statement.")
# Einzelaktionen mit Finanzbezug ohne eigenes Präfix (Review Phase I): Umlageschlüssel-Zuordnung am Vertrag
FINANCE_AUDIT_ACTIONS = frozenset({"lease.allocation_set"})
# ALLOW-Liste (Klassifikationspflicht): ALLE übrigen im Code geschriebenen Audit-Aktionen, bewusst als NICHT finanziell eingestuft.
# Jede neue Aktion in audit.record(...) muss in genau einer Gruppe stehen (Test test_i7_audit_action_classification), sonst schlägt der Test fehl.
NON_FINANCE_AUDIT_ACTIONS = frozenset({
    "auth.login", "auth.login_blocked", "auth.login_failed", "auth.logout", "backup.created", "backup.restore_started", "user.created",
    "bed.created", "bed.updated", "room.created", "room.updated", "unit.created", "unit.updated", "property.created", "property.updated", "rentable_unit.created",
    "communication.created", "handover.created", "party.created", "party.updated",
    "document.deleted", "document.integrity_failed", "document.linked", "document.purged", "document.uploaded",  # Finanzdokumente werden zusätzlich über details.document_id gefiltert
    "lease.activated", "lease.cancelled", "lease.created", "lease.ended", "lease.legal_review", "lease.note_added", "lease.terminated", "lease.updated",
    "lease.term_added", "lease.utility_agreement_added",  # Vertragskonditionen = Stammdaten (Entscheidung, Eigentümerbestätigung offen); Summaries ohne Beträge
    "repair.created", "repair.note", "repair.status", "repair.updated",
    "task.created", "task.status", "task.updated",
})
# Reparaturverlauf: Ereignisarten, die Rechnungen/Beträge nennen (RepairEvent.kind bzw. Aktion repair.<kind>)
FINANCE_REPAIR_EVENT_KINDS = frozenset({"invoice"})
FINANCE_REPAIR_AUDIT_ACTIONS = frozenset({"repair.invoice", "repair.invoice_linked"})


def can_read_finance(user: AppUser) -> bool:
    return has_permission(user.role.code, FINANCE_PERMISSION)


def require_finance_read(user: AppUser) -> None:
    """Gleiche Antwort wie api.deps.require (403, Code forbidden, ohne Beträge)."""
    if not can_read_finance(user):
        raise HTTPException(403, detail={"code": "forbidden", "detail": "Keine Berechtigung."})


def is_finance_reminder_key(key: str) -> bool:
    return key.split(":", 1)[0] in FINANCE_REMINDER_KEY_PREFIXES


def mask_iban(iban: str | None) -> str | None:
    """Nur die letzten 4 Zeichen (ohne Leerzeichen) bleiben sichtbar, davor '•'. None/leer bleibt unverändert."""
    if not iban or not iban.strip():
        return iban
    compact = iban.replace(" ", "")
    return "•" * max(len(compact) - 4, 4) + compact[-4:]


def is_masked_value(v: str | None) -> bool:
    """Von mask_iban erzeugte (oder sinngemäß maskierte) Werte: enthalten '•' oder '*'."""
    return bool(v) and ("•" in v or "*" in v)


def require_finance_doc_access(user: AppUser, doc_type: str | None) -> None:
    if doc_type in FINANCE_DOC_TYPES:
        require_finance_read(user)


def is_finance_audit(action: str | None, entity_type: str | None) -> bool:
    return (entity_type in FINANCE_AUDIT_ENTITY_TYPES) or bool(action and (action.startswith(FINANCE_AUDIT_ACTION_PREFIXES) or action in FINANCE_REPAIR_AUDIT_ACTIONS or action in FINANCE_AUDIT_ACTIONS))
