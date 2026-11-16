"""Erinnerungen und Hinweise – werden bei jedem Aufruf aus den tatsächlichen Daten BERECHNET (nicht gespeichert).
Alle Fristen sind rechnerische Hinweise aus den gespeicherten Vertragsdaten und KEINE Rechtsauskunft."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from leventum import domain
from leventum.models import Charge, Deposit, Lease, Repair, Task, UtilityStatement
from leventum.security.finance_access import NON_FINANCE_REMINDER_TYPES
from leventum.services import deposits as dep, documents as docs
from leventum.services.charges import receivable_position
from leventum.services.dunning import eur
from leventum.services.leases import _span, contract_end_due
from leventum.services.master import lease_title
from leventum.services.utility import q

NOTICE_DAYS = 60
REPAIR_DAYS = 7
SEV_ORDER = {"critical": 0, "warning": 1, "info": 2}


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, mo = d.year + m // 12, m % 12 + 1
    return date(y, mo, min(d.day, monthrange(y, mo)[1]))


def _r(key, typ, sev, title, detail, due=None, entity_type=None, entity_id=None, **extra):
    return {"key": key, "type": typ, "severity": sev, "title": title, "detail": detail, "due_date": due, "entity_type": entity_type, "entity_id": entity_id, **extra}


def compute(db: Session, today: date | None = None, preview_days: int | None = None, include_finance: bool = True) -> list[dict]:
    """preview_days: Vorschauzeitraum Vertragsenden; None -> Standard aus Settings (Aufrufer in der API reichen den App-Wert durch).
    include_finance=False: Hinweise mit Finanzbezug (overdue_payment, deposit_overdue, utility_statement_due) werden gar nicht erst berechnet (Recht finance:read fehlt)."""
    today = today or date.today()
    if preview_days is None:
        from leventum.config import Settings
        preview_days = Settings().contract_end_preview_days
    out: list[dict] = []
    leases = list(db.scalars(select(Lease).where(Lease.status.in_(domain.RUNNING_STATUS))))
    for l in leases:
        label = f"{'Hauptmietvertrag' if l.kind == 'main' else 'Untermietvertrag'} {lease_title(db, l)}"
        end = contract_end_due(l, today, preview_days)  # zentrale Definition inkl. is_running (ADR 0002)
        if end is not None:
            out.append(_r(f"contract_end:{l.id}:{end}", "contract_end", "warning" if (end - today).days <= 30 else "info", f"{label} endet am {end:%d.%m.%Y}",
                          f"Noch {(end - today).days} Tage. Anschlussregelung/Nachmieter prüfen.", end, "lease", l.id))
        if l.status == "active" and l.end_date is not None and l.notice_period_months is not None:
            dl = add_months(l.end_date, -l.notice_period_months)
            if dl < today:
                out.append(_r(f"notice:{l.id}:{dl}", "notice_deadline", "warning", f"{label}: rechnerischer Kündigungsstichtag verstrichen ({dl:%d.%m.%Y})",
                              "Rechnerisch aus Vertragsende minus Kündigungsfrist (Monate). Keine Rechtsprüfung – Zugang, Werktage und Form nicht berücksichtigt.", dl, "lease", l.id))
            elif dl <= today + timedelta(days=NOTICE_DAYS):
                out.append(_r(f"notice:{l.id}:{dl}", "notice_deadline", "warning", f"{label}: rechnerischer Kündigungsstichtag {dl:%d.%m.%Y}",
                              f"Noch {(dl - today).days} Tage. Rechnerisch aus Vertragsende minus Kündigungsfrist; keine Rechtsprüfung.", dl, "lease", l.id))
        for t in docs.missing_for_lease(db, l):
            out.append(_r(f"missing_doc:{l.id}:{t}", "missing_document", "warning" if t == "mietvertrag" else "info", f"{label}: Dokument fehlt ({t})",
                          "Laut Pflichtliste (organisatorische Annahme) ist kein entsprechendes Dokument zugeordnet.", None, "lease", l.id, doc_type=t))
    # überfällige Forderungen je Vertrag
    for lid, rows in (receivable_position(db, today)["overdue_by_lease"].items() if include_finance else ()):  # zentrale Stichtagslogik (ADR 0002)
        total, first = q(sum((o for _, o in rows), Decimal(0))), min(d for d, _ in rows)
        ltitle = lease_title(db, db.get(Lease, lid))
        out.append(_r(f"overdue:{lid}:{first}", "overdue_payment", "critical", f"Überfällige Zahlung – {ltitle}: {eur(total)} offen",
                      f"{len(rows)} Sollstellung(en), älteste fällig am {first:%d.%m.%Y}. Mahnwesen prüfen.", first, "lease", lid, amount=total,
                      task_title=f"Überfällige Zahlung – {ltitle}"))  # betragsfrei: Aufgaben sind auch ohne finance:read lesbar
    for d in (db.scalars(select(Deposit)) if include_finance else ()):
        lease = db.get(Lease, d.lease_id)
        s = dep.summary(d, lease, today)
        if s["overdue"]:
            out.append(_r(f"deposit:{d.id}", "deposit_overdue", "warning", f"Kaution überfällig – {lease_title(db, lease)}: {eur(s['open'])} offen", f"Fällig seit {d.due_date:%d.%m.%Y}.", d.due_date, "deposit", d.id,
                          task_title=f"Kaution überfällig – {lease_title(db, lease)}"))
    for r in db.scalars(select(Repair).where(Repair.status.in_(domain.REPAIR_OPEN))):
        if r.scheduled_for and r.scheduled_for < today:
            out.append(_r(f"repair_late:{r.id}:{r.scheduled_for}", "repair_overdue", "critical", f"Reparatur #{r.id} „{r.title}“: Termin verstrichen ({r.scheduled_for:%d.%m.%Y})", "Status noch offen.", r.scheduled_for, "repair", r.id))
        elif r.scheduled_for and r.scheduled_for <= today + timedelta(days=REPAIR_DAYS):
            out.append(_r(f"repair:{r.id}:{r.scheduled_for}", "repair_upcoming", "info", f"Reparatur #{r.id} „{r.title}“ am {r.scheduled_for:%d.%m.%Y}", "Anstehender Termin.", r.scheduled_for, "repair", r.id))
        elif r.priority == "urgent" and r.status == "reported":
            out.append(_r(f"repair_urgent:{r.id}", "repair_urgent", "critical", f"Dringende Reparatur #{r.id} „{r.title}“ noch nicht terminiert", "Priorität dringend, Status gemeldet.", None, "repair", r.id))
    # Betriebskostenabrechnung Vorjahr (Ebene A): Hauptvertrag mit Vorauszahlung, im Vorjahr aktiv, keine erfasste Abrechnung
    y = today.year - 1
    ys, ye = date(y, 1, 1), date(y, 12, 31)
    for l in (leases if include_finance else ()):
        if l.kind != "main" or not any(a.mode == "prepayment" for a in l.utility_agreements):
            continue
        s0, e0 = _span(l)
        if not (s0 <= ye and ys <= e0):
            continue
        has = db.scalar(select(UtilityStatement.id).where(UtilityStatement.main_lease_id == l.id, UtilityStatement.period_end >= ys, UtilityStatement.period_start <= ye))
        if has is None:
            out.append(_r(f"utility_statement:{l.id}:{y}", "utility_statement_due", "info", f"Hauptmietvertrag {lease_title(db, l)}: keine Nebenkostenabrechnung für {y} erfasst",
                          "Eingehende Abrechnung des Vermieters erfassen oder anfordern. Fristen sind rechtlich zu prüfen.", None, "lease", l.id))
    existing = {t.dedupe_key: t for t in db.scalars(select(Task).where(Task.dedupe_key.is_not(None)))}
    if not include_finance:  # Allow-Liste: nur ausdrücklich als nicht finanziell klassifizierte Typen (unbekannte Typen bleiben verborgen)
        out = [r for r in out if r["type"] in NON_FINANCE_REMINDER_TYPES]
    for r in out:
        r.setdefault("task_title", r["title"])  # Titel einer daraus erzeugten Aufgabe (Finanztypen: ohne Betrag)
        t = existing.get(r["key"])
        r["task_id"], r["task_status"] = (t.id, t.status) if t else (None, None)
    out.sort(key=lambda r: (SEV_ORDER[r["severity"]], r["due_date"] or date.max, r["key"]))
    return out
