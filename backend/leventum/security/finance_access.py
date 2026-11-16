"""Zentrale Prüfung für Finanzinformationen (Eigentümerentscheidung: Finanzinformationen nur mit Recht finance:read).

Gilt für Stellen, die Finanzwerte in sonst nicht-finanzielle Routen einbetten (Dashboard, Hinweise, Mieterliste/-akte).
Die Prüfung erfolgt immer serverseitig; die 403-Antwort enthält keine Beträge."""
from __future__ import annotations

from fastapi import HTTPException

from leventum.models import AppUser
from leventum.security.permissions import has_permission

FINANCE_PERMISSION = "finance:read"

# Dashboard-KPIs mit Finanzbezug. physical_vacancy (reine Anzahl) bleibt bewusst für alle sichtbar.
FINANCE_KPI_KEYS = frozenset({"main_rent_obligations", "sublease_receivables", "open_receivables", "overdue_payments",
                              "monthly_utility_costs", "economic_vacancy_cost", "overdue_receivables"})  # overdue_receivables: vorbereitet, noch nicht vorhanden

# Hinweistypen (reminders) mit Finanzbezug und die zugehörigen Schlüsselpräfixe (Teil vor dem ersten ':' des Hinweisschlüssels).
FINANCE_REMINDER_TYPES = frozenset({"overdue_payment", "deposit_overdue", "utility_statement_due"})
FINANCE_REMINDER_KEY_PREFIXES = frozenset({"overdue", "deposit", "utility_statement"})


def can_read_finance(user: AppUser) -> bool:
    return has_permission(user.role.code, FINANCE_PERMISSION)


def require_finance_read(user: AppUser) -> None:
    """Gleiche Antwort wie api.deps.require (403, Code forbidden, ohne Beträge)."""
    if not can_read_finance(user):
        raise HTTPException(403, detail={"code": "forbidden", "detail": "Keine Berechtigung."})


def is_finance_reminder_key(key: str) -> bool:
    return key.split(":", 1)[0] in FINANCE_REMINDER_KEY_PREFIXES
