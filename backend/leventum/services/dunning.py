"""Mahnwesen: drei Stufen, automatische Erkennung, vorbereitete Entwürfe, manuelle Freigabe.
Es gibt KEINEN Versandcode. Mahngebühren und Verzugszinsen werden nicht berechnet.
Die Stufen-Abstände (MIN_DAYS_BETWEEN_LEVELS) und Wortlaute sind Annahmen und nicht rechtlich geprüft."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from leventum import domain
from leventum.models import Charge, DunningLine, DunningNotice, Lease
from leventum.services import audit
from leventum.services.charges import open_amount
from leventum.services.errors import ServiceError
from leventum.services.master import get_or_404
from leventum.services.utility import q

MIN_DAYS_BETWEEN_LEVELS = 7
LIVE = ("draft", "approved", "sent")
PLACEHOLDER = "[Frist"


def _levels(db: Session, charge_id: int):
    """Mahnstufen-Historie einer Sollstellung aus nicht stornierten Mahnungen: [(level, status, sent_on)]."""
    rows = db.execute(select(DunningNotice.level, DunningNotice.status, DunningNotice.sent_on, DunningNotice.approved_at)
                      .join(DunningLine, DunningLine.notice_id == DunningNotice.id)
                      .where(DunningLine.charge_id == charge_id, DunningNotice.status.in_(LIVE))).all()
    return rows


def candidates(db: Session, as_of: date | None = None, grace_days: int = 0, lease_id: int | None = None) -> list[dict]:
    """Überfällige Forderungen (Teilzahlungen berücksichtigt) mit der als Nächstes fälligen Mahnstufe."""
    as_of = as_of or date.today()
    stmt = select(Charge).where(Charge.direction == "receivable", Charge.voided_at.is_(None), Charge.due_date < as_of - timedelta(days=grace_days))
    if lease_id:
        stmt = stmt.where(Charge.lease_id == lease_id)
    out = []
    for c in db.scalars(stmt.order_by(Charge.lease_id, Charge.due_date)):
        open_ = open_amount(db, c, as_of)
        if open_ <= 0:
            continue
        hist = _levels(db, c.id)
        last = max(hist, key=lambda r: r[0]) if hist else None
        state, level = "due", 1
        if last:
            lvl, status, sent_on, approved_at = last
            level = lvl
            if status == "draft":
                state = "draft_exists"
            elif status == "approved":
                state = "approved_not_sent"       # freigegeben, aber Versand noch nicht dokumentiert → keine Eskalation
            elif lvl >= 3:
                state = "max_level_reached"
            else:                                  # nur eine als VERSANDT dokumentierte Stufe darf eskalieren
                level = lvl + 1
                state = "due" if (as_of - sent_on).days >= MIN_DAYS_BETWEEN_LEVELS else "waiting"
        out.append({"charge_id": c.id, "lease_id": c.lease_id, "charge_type": c.charge_type, "charge_label": f"{CHARGE_LABEL.get(c.charge_type, c.charge_type)} {c.period_start:%m/%Y}",
                    "period_start": c.period_start, "period_end": c.period_end, "due_date": c.due_date, "amount": c.amount,
                    "open_amount": open_, "days_overdue": (as_of - c.due_date).days, "last_level": last[0] if last else 0,
                    "proposed_level": level, "state": state})
    return out


def summarize(items: list[dict]) -> dict:
    """Konsistente Zähler für die Oberfläche: jede Position fällt in genau einen Zustand."""
    states = ("due", "draft_exists", "approved_not_sent", "waiting", "max_level_reached")
    out = {s: {"positions": 0, "leases": 0, "open_amount": Decimal("0.00")} for s in states}
    leases: dict[str, set] = {s: set() for s in states}
    for i in items:
        o = out[i["state"]]
        o["positions"] += 1
        o["open_amount"] = q(o["open_amount"] + i["open_amount"])
        leases[i["state"]].add(i["lease_id"])
    for s_ in states:
        out[s_]["leases"] = len(leases[s_])
    return {"total_positions": len(items), "by_state": out}


def _recipient(lease: Lease) -> str:
    names = [p.party.display_name for p in lease.parties if p.role in ("lessee", "co_lessee")]
    return ", ".join(names) or "Mieter"


def eur(x: Decimal) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def _body(level: int, recipient: str, lines: list[dict], total: Decimal, as_of: date) -> tuple[str, str]:
    title = domain.DUNNING_LEVELS[level]
    intro = {1: "bei der Durchsicht unserer Buchhaltung haben wir festgestellt, dass die folgenden Beträge noch nicht bei uns eingegangen sind. Sollten Sie die Zahlung bereits veranlasst haben, betrachten Sie dieses Schreiben bitte als gegenstandslos.",
             2: "trotz unserer Zahlungserinnerung konnten wir den Eingang der folgenden Beträge nicht feststellen. Wir bitten Sie, den offenen Betrag umgehend zu begleichen.",
             3: "trotz unserer bisherigen Schreiben konnten wir den Eingang der folgenden Beträge weiterhin nicht feststellen. Wir fordern Sie auf, den offenen Betrag zu begleichen."}[level]
    rows = "\n".join(f"  - {l['label']}, fällig am {l['due_date']:%d.%m.%Y}: offen {eur(l['open_amount'])}" for l in lines)
    body = (f"{title}\n\nSehr geehrte(r) {recipient},\n\n{intro}\n\n{rows}\n\nOffener Gesamtbetrag (Stand {as_of:%d.%m.%Y}): {eur(total)}\n\n"
            f"Bitte überweisen Sie den Betrag bis zum [Frist eintragen].\n\nMit freundlichen Grüßen\nLeventum Real Estate")
    return title, body


CHARGE_LABEL = {"base_rent": "Kaltmiete", "other_charges": "Zuschlag", "utility_prepayment": "Nebenkostenvorauszahlung",
                "utility_flat_rate": "Nebenkostenpauschale", "other": "Sonstige Forderung"}


def prepare_notices(db: Session, actor_id: int | None, *, as_of: date | None = None, lease_id: int | None = None, grace_days: int = 0) -> list[DunningNotice]:
    """Legt Entwürfe an (ein Entwurf je Vertrag und Stufe). Idempotent: Sollstellungen mit bestehendem Entwurf werden nicht erneut aufgenommen."""
    as_of = as_of or date.today()
    groups: dict[tuple[int, int], list[dict]] = {}
    for c in candidates(db, as_of, grace_days, lease_id):
        if c["state"] == "due":
            groups.setdefault((c["lease_id"], c["proposed_level"]), []).append(c)
    created = []
    for (lid, level), items in groups.items():
        lease = db.get(Lease, lid)
        recipient = _recipient(lease)
        lines = [{**i, "label": f"{CHARGE_LABEL.get(i['charge_type'], i['charge_type'])} {i['due_date']:%m/%Y}"} for i in items]
        total = q(sum((i["open_amount"] for i in items), Decimal(0)))
        title, body = _body(level, recipient, lines, total, as_of)
        n = DunningNotice(lease_id=lid, level=level, status="draft", as_of_date=as_of, recipient_name=recipient, subject=f"{title} – Vertrag {lease.contract_number or lease.id}",
                          body=body, total_open=total, created_by_user_id=actor_id,
                          review_hint="ENTWURF – vor Versand prüfen. Mahngebühren und Verzugszinsen sind NICHT enthalten. Frist eintragen. Wortlaut, Fristen und "
                                      "rechtliche Anforderungen an Mahnschreiben sind nicht geprüft. Es erfolgt kein automatischer Versand.")
        for i in items:
            n.lines.append(DunningLine(charge_id=i["charge_id"], open_amount=i["open_amount"], due_date=i["due_date"]))
        db.add(n)
        db.flush()
        audit.record(db, "dunning.prepared", actor_user_id=actor_id, entity_type="dunning_notice", entity_id=n.id,
                     summary=f"{title} vorbereitet (Entwurf)", details={"lease_id": lid, "total_open": str(total), "charges": [i["charge_id"] for i in items]})
        created.append(n)
    return created


def update_draft(db: Session, actor_id: int | None, notice_id: int, *, subject: str | None = None, body: str | None = None) -> DunningNotice:
    n = get_or_404(db, DunningNotice, notice_id, "Mahnung")
    if n.status != "draft":
        raise ServiceError("invalid_state", "Nur Entwürfe können bearbeitet werden.", 409)
    if subject is not None:
        n.subject = subject
    if body is not None:
        n.body = body
    audit.record(db, "dunning.edited", actor_user_id=actor_id, entity_type="dunning_notice", entity_id=n.id, summary="Entwurf bearbeitet")
    db.flush()
    return n


def approve(db: Session, actor_id: int | None, notice_id: int) -> DunningNotice:
    """Manuelle Freigabe. Prüft vorher den aktuellen Stand: Wurde inzwischen gezahlt, ist der Entwurf veraltet und muss neu erstellt werden."""
    n = get_or_404(db, DunningNotice, notice_id, "Mahnung")
    if n.status != "draft":
        raise ServiceError("invalid_state", "Nur Entwürfe können freigegeben werden.", 409)
    if PLACEHOLDER in n.body:
        raise ServiceError("placeholder_unresolved", "Im Text ist noch ein Platzhalter (z. B. die Zahlungsfrist) einzutragen.", 422)
    stale = []
    today = date.today()  # gleicher Stichtagsbegriff wie prepare/candidates: Zahlungen wirken ab Buchungsdatum (booking_date <= heute)
    for ln in n.lines:
        c = db.get(Charge, ln.charge_id)
        cur = open_amount(db, c, today)
        if c.voided_at or cur != ln.open_amount:
            stale.append({"charge_id": c.id, "draft_amount": ln.open_amount, "current_open": cur if not c.voided_at else Decimal("0.00")})
    if stale:
        raise ServiceError("stale_draft", "Seit der Erstellung haben sich die offenen Beträge geändert (Zahlung/Storno). Entwurf verwerfen und neu erstellen.", 409, stale)
    n.status, n.approved_by_user_id, n.approved_at = "approved", actor_id, datetime.now(timezone.utc)
    audit.record(db, "dunning.approved", actor_user_id=actor_id, entity_type="dunning_notice", entity_id=n.id, summary="Mahnung freigegeben (noch nicht versandt)")
    db.flush()
    return n


def mark_sent(db: Session, actor_id: int | None, notice_id: int, *, sent_on: date, via: str) -> DunningNotice:
    """Dokumentiert den MANUELLEN Versand. Die Software versendet selbst nichts."""
    n = get_or_404(db, DunningNotice, notice_id, "Mahnung")
    if n.status != "approved":
        raise ServiceError("invalid_state", "Nur freigegebene Mahnungen können als versandt markiert werden.", 409)
    if not via.strip():
        raise ServiceError("invalid", "Versandweg angeben (z. B. Brief, E-Mail).")
    n.status, n.sent_on, n.sent_via, n.sent_marked_by_user_id = "sent", sent_on, via.strip(), actor_id
    audit.record(db, "dunning.marked_sent", actor_user_id=actor_id, entity_type="dunning_notice", entity_id=n.id, summary="Versand manuell dokumentiert",
                 details={"sent_on": str(sent_on), "via": via})
    db.flush()
    return n


def cancel(db: Session, actor_id: int | None, notice_id: int, reason: str) -> DunningNotice:
    n = get_or_404(db, DunningNotice, notice_id, "Mahnung")
    if n.status not in ("draft", "approved") or not reason.strip():
        raise ServiceError("invalid_state", "Nur Entwürfe/freigegebene Mahnungen können (mit Begründung) verworfen werden.", 409)
    n.status, n.cancelled_at, n.cancel_reason = "cancelled", datetime.now(timezone.utc), reason.strip()
    audit.record(db, "dunning.cancelled", actor_user_id=actor_id, entity_type="dunning_notice", entity_id=n.id, summary="Mahnung verworfen", details={"reason": reason})
    db.flush()
    return n
