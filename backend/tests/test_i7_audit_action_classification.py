"""Klassifikationspflicht für Audit-Aktionen (Security-Re-Review Phase I: Deny-Liste → Allow-Liste).
Jede im Code geschriebene audit.record-Aktion muss ausdrücklich als FINANZ (ohne finance:read in Historie/Mieterakte verborgen) oder als NICHT-FINANZ
eingestuft sein. Eine neue, unklassifizierte Aktion lässt diesen Test scheitern – damit ein neues Finanzereignis nicht still sichtbar wird."""
import re
from pathlib import Path

from leventum.security import finance_access as FA

SRC = Path(__file__).resolve().parents[1] / "leventum"


def code_actions():
    found = set()
    for f in SRC.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r'audit\.record\(\s*(?:db,\s*)?(f?)"([a-z_.{}]+)"', text):
            found.add(m.group(2) if not m.group(1) else re.sub(r"\{[^}]*\}.*$", "", m.group(2)) + "*")  # f-String: dynamischer Teil → Präfix + '*'
        for m in re.finditer(r"audit\.record\(\s*db,\s*([a-z_]+)\s*,", text):  # Aktion als Variable: deposits.py (action = f"deposit.{kind}")
            found.add(f"<variable:{m.group(1)}@{f.name}>")
    return found


def is_finance(action):
    return action.startswith(FA.FINANCE_AUDIT_ACTION_PREFIXES) or action in FA.FINANCE_AUDIT_ACTIONS or action in FA.FINANCE_REPAIR_AUDIT_ACTIONS


def test_every_audit_action_in_code_is_classified_exactly_once():
    unclassified, both = [], []
    for a in sorted(code_actions()):
        if a.startswith("<variable:"):
            continue  # separat geprüft
        base = a.rstrip("*")
        fin, non = is_finance(base), a in FA.NON_FINANCE_AUDIT_ACTIONS
        if fin and non:
            both.append(a)
        if not fin and not non:
            unclassified.append(a)
    assert both == [], f"in beiden Gruppen: {both}"
    assert unclassified == [], f"unklassifizierte Audit-Aktionen (bewusst als FINANZ oder NICHT-FINANZ einordnen): {unclassified}"


def test_dynamic_action_variables_are_known_and_finance():
    dyn = sorted(a for a in code_actions() if a.startswith("<variable:"))
    assert dyn == ["<variable:action@deposits.py>"], f"neue dynamische Audit-Aktion – Klassifikation prüfen: {dyn}"
    assert is_finance("deposit.paid") and is_finance("deposit.refunded")     # deposits.py: action = f"deposit.{kind}"


def test_classification_lists_contain_no_stale_actions():
    actions = {a.rstrip("*") for a in code_actions() if not a.startswith("<variable:")}
    stale = [a for a in FA.NON_FINANCE_AUDIT_ACTIONS if a not in actions]
    assert stale == [], f"veraltete Einträge in NON_FINANCE_AUDIT_ACTIONS: {stale}"


def test_finance_entity_types_cover_bank_and_utility_statements():
    for t in ("bank_account", "bank_import", "bank_transaction", "utility_statement", "deposit", "invoice", "payment", "charge", "dunning_notice"):
        assert FA.is_finance_audit(None, t), t
    assert FA.is_finance_audit("lease.allocation_set", "lease") and not FA.is_finance_audit("lease.updated", "lease")
