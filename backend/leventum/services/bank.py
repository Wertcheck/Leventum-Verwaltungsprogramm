"""Bankimport: Import → Duplikaterkennung → Zuordnungsvorschläge → MANUELLE Bestätigung.
Nichts wird ohne Bestätigung zu einer Zahlung. Es werden keine Zugangsdaten gespeichert."""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from leventum import domain
from leventum.models import (BankAccount, BankImport, BankTransaction, Charge, Deposit, DepositTransaction, Invoice, Lease, Party, Payment)
from leventum.services import audit, deposits as dep, payments as pay
from leventum.services.bank_parsers import PARSERS, ParseResult
from leventum.services.charges import open_amount
from leventum.services.errors import ServiceError
from leventum.services.master import get_or_404
from leventum.services.utility import q

MIN_SCORE = 30


def _n(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def fingerprint(account_id: int, row, occurrence: int) -> str:
    parts = [str(account_id), row.booking_date.isoformat(), str(row.amount), _n(row.counterparty_name), (row.counterparty_iban or "").upper(),
             _n(row.reference), row.external_id or "", str(occurrence)]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def create_account(db: Session, actor_id: int | None, name: str, iban: str | None) -> BankAccount:
    if not name.strip():
        raise ServiceError("invalid", "Kontoname fehlt.")
    iban = re.sub(r"\s", "", iban).upper() if iban else None
    a = BankAccount(name=name.strip(), iban=iban)
    db.add(a)
    db.flush()
    audit.record(db, "bank.account_created", actor_user_id=actor_id, entity_type="bank_account", entity_id=a.id, summary=f"Bankkonto angelegt: {a.name}")
    return a


def _classify(db: Session, account_id: int, parsed: ParseResult) -> list[tuple]:
    """[(row, fingerprint, is_duplicate)] – gleiche Zeilen innerhalb einer Datei bekommen eine laufende Nummer,
    damit echte Mehrfachbuchungen nicht als Duplikat gelten, ein erneuter Import derselben Datei aber vollständig."""
    seen: dict[tuple, int] = {}
    out = []
    for r in parsed.rows:
        base = (r.booking_date, r.amount, _n(r.counterparty_name), r.counterparty_iban, _n(r.reference), r.external_id)
        seen[base] = seen.get(base, 0) + 1
        fp = fingerprint(account_id, r, seen[base])
        exists = db.scalar(select(BankTransaction.id).where(BankTransaction.account_id == account_id, BankTransaction.fingerprint == fp)) is not None
        out.append((r, fp, exists))
    return out


def _parse(fmt: str, data: bytes, options: dict | None) -> ParseResult:
    parser = PARSERS.get(fmt)
    if parser is None:
        raise ServiceError("unsupported_format", f"Format {fmt!r} wird nicht unterstützt (verfügbar: {', '.join(PARSERS)}).")
    return parser.parse(data, options)


def preview(db: Session, account_id: int, data: bytes, fmt: str = "csv", options: dict | None = None) -> dict:
    get_or_404(db, BankAccount, account_id, "Bankkonto")
    parsed = _parse(fmt, data, options)
    rows = _classify(db, account_id, parsed) if not parsed.errors else []
    sha = hashlib.sha256(data).hexdigest()
    return {"errors": parsed.errors, "meta": parsed.meta, "total_rows": len(parsed.rows), "new_rows": sum(1 for *_, d in rows if not d),
            "duplicate_rows": sum(1 for *_, d in rows if d), "file_already_imported": db.scalar(select(BankImport.id).where(BankImport.file_sha256 == sha, BankImport.account_id == account_id)) is not None,
            "sample": [{"row": r.row_no, "booking_date": r.booking_date, "amount": r.amount, "counterparty_name": r.counterparty_name,
                        "reference": r.reference, "duplicate": d} for r, _, d in rows[:20]]}


def import_statement(db: Session, actor_id: int | None, account_id: int, filename: str, data: bytes, fmt: str = "csv", options: dict | None = None) -> BankImport:
    """Alles-oder-nichts: Enthält die Datei ungültige Zeilen, wird nichts importiert."""
    get_or_404(db, BankAccount, account_id, "Bankkonto")
    parsed = _parse(fmt, data, options)
    if parsed.errors:
        raise ServiceError("invalid_file", "Die Datei enthält Fehler und wurde nicht importiert.", 422, parsed.errors)
    rows = _classify(db, account_id, parsed)
    imp = BankImport(account_id=account_id, format=fmt, filename=filename[:255], file_sha256=hashlib.sha256(data).hexdigest(), imported_by_user_id=actor_id,
                     total_rows=len(rows), new_rows=sum(1 for *_, d in rows if not d), duplicate_rows=sum(1 for *_, d in rows if d))
    db.add(imp)
    db.flush()
    for r, fp, dup in rows:
        if dup:
            continue
        db.add(BankTransaction(account_id=account_id, import_id=imp.id, booking_date=r.booking_date, value_date=r.value_date, amount=r.amount,
                               currency=r.currency, counterparty_name=r.counterparty_name, counterparty_iban=r.counterparty_iban, reference=r.reference,
                               external_id=r.external_id, fingerprint=fp, raw=r.raw))
    db.flush()
    audit.record(db, "bank.imported", actor_user_id=actor_id, entity_type="bank_import", entity_id=imp.id, summary=f"Kontoauszug importiert: {filename}",
                 details={"total": imp.total_rows, "new": imp.new_rows, "duplicates": imp.duplicate_rows, "sha256": imp.file_sha256})
    return imp


# --- Vorschläge --------------------------------------------------------------------------------------------------------------
def _name_match(party_name: str | None, txn_name: str | None, reference: str | None = None) -> bool:
    a = set(_n(party_name).replace(",", " ").split())
    b = set(_n(txn_name).replace(",", " ").split())
    if not a or not b:
        return False
    return a <= b or b <= a or a <= set(_n(reference).replace(",", " ").split())


def _party_hit(p: Party, t: BankTransaction) -> list[tuple[int, str]]:
    hits = []
    if p.iban and t.counterparty_iban and re.sub(r"\s", "", p.iban).upper() == t.counterparty_iban:
        hits.append((50, "IBAN stimmt mit Partei überein"))
    if _name_match(p.display_name, t.counterparty_name):
        hits.append((30, "Name stimmt überein"))
    return hits


def _fifo(db: Session, charges: list[Charge], amount: Decimal, as_of: date | None = None) -> tuple[list[dict], Decimal]:
    plan, left = [], amount
    for c in sorted(charges, key=lambda c: (c.due_date, c.id)):
        o = open_amount(db, c, as_of)
        if o <= 0 or left <= 0:
            continue
        take = min(o, left)
        plan.append({"charge_id": c.id, "amount": take, "charge_type": c.charge_type, "due_date": c.due_date, "open_before": o})
        left = q(left - take)
    return plan, left


def suggest(db: Session, t: BankTransaction) -> list[dict]:
    """Rein beratend. Liefert Kandidaten mit Punktzahl und Gründen; es wird nichts gebucht.
    Offene Beträge gelten zum Stichtag heute: Zahlungen mit Buchungsdatum in der Zukunft mindern sie nicht (Phase I3)."""
    out: list[dict] = []
    today = date.today()
    ref = _n(t.reference)
    amount = abs(t.amount)
    incoming = t.amount > 0
    leases = db.scalars(select(Lease).where(Lease.kind == ("sub" if incoming else "main"), Lease.status.in_(("active", "terminated", "ended")))).all()
    for lease in leases:
        score, reasons = 0, []
        counterparties = [lp.party for lp in lease.parties if lp.role in (("lessee", "co_lessee") if incoming else ("lessor",))]
        best = max((h for p in counterparties for h in [_party_hit(p, t)] if h), key=lambda h: sum(s for s, _ in h), default=[])
        for s, r in best:
            score += s
            reasons.append(r)
        if lease.contract_number and _n(lease.contract_number) in ref:
            score += 40
            reasons.append("Vertragsnummer im Verwendungszweck")
        if not score:
            continue
        charges = db.scalars(select(Charge).where(Charge.lease_id == lease.id, Charge.voided_at.is_(None))).all()
        plan, left = _fifo(db, charges, amount, today)
        if not plan:
            continue
        if left == 0:
            score += 20
            reasons.append("Betrag deckt offene Sollstellungen exakt")
        month_total = {}
        for c in charges:
            o_c = open_amount(db, c, today)
            if o_c > 0:
                month_total[c.period_start] = month_total.get(c.period_start, Decimal(0)) + o_c
        if amount in month_total.values():
            score += 10
            reasons.append("Betrag entspricht einem Monatssoll")
        if score >= MIN_SCORE:
            out.append({"kind": "charges", "lease_id": lease.id, "score": score, "reasons": reasons, "allocations": plan, "unallocated_remainder": left})
    if not incoming:
        for inv in db.scalars(select(Invoice).where(Invoice.voided_at.is_(None))):
            o = pay.invoice_open(db, inv)
            if o <= 0:
                continue
            score, reasons = 0, []
            if inv.invoice_number and _n(inv.invoice_number) in ref:
                score += 50
                reasons.append("Rechnungsnummer im Verwendungszweck")
            sup = db.get(Party, inv.supplier_party_id) if inv.supplier_party_id else None
            for s, r in (_party_hit(sup, t) if sup else []):
                score += s
                reasons.append("Lieferant: " + r)
            if o == amount:
                score += 20
                reasons.append("Betrag entspricht dem offenen Rechnungsbetrag")
            if score >= MIN_SCORE and (inv.invoice_number and _n(inv.invoice_number) in ref or sup and _party_hit(sup, t)):
                out.append({"kind": "invoice", "invoice_id": inv.id, "invoice_label": inv.invoice_number or f"#{inv.id}", "score": score, "reasons": reasons,
                            "allocations": [{"invoice_id": inv.id, "amount": min(o, amount)}], "unallocated_remainder": q(amount - min(o, amount))})
    if "kaution" in ref:
        for d in db.scalars(select(Deposit)):
            lease = db.get(Lease, d.lease_id)
            s = dep.summary(d, lease)
            kind = None
            if lease.kind == "sub" and incoming and s["open"] > 0:
                kind = "paid"
            elif lease.kind == "sub" and not incoming and s["held"] > 0:
                kind = "refunded"
            elif lease.kind == "main" and not incoming and s["open"] > 0:
                kind = "paid"
            elif lease.kind == "main" and incoming and s["held"] > 0:
                kind = "refunded"
            if kind is None:
                continue
            counter = [lp.party for lp in lease.parties if lp.role in ("lessee", "co_lessee", "lessor") and lp.party.is_own_organization is False]
            score, reasons = 20, ["Verwendungszweck enthält 'Kaution'"]
            for p in counter:
                for sc, r in _party_hit(p, t):
                    score += sc
                    reasons.append(r)
            if score >= MIN_SCORE:
                out.append({"kind": "deposit", "deposit_id": d.id, "lease_id": lease.id, "deposit_kind": kind, "score": score, "reasons": reasons, "amount": amount})
    return sorted(out, key=lambda x: -x["score"])[:5]


# --- Bestätigung -------------------------------------------------------------------------------------------------------------------
def _must_be_open(t: BankTransaction):
    if t.status != "open":
        raise ServiceError("invalid_state", f"Die Buchung ist bereits '{t.status}'.", 409)


def confirm_payment(db: Session, actor_id: int | None, txn_id: int, *, allocations: list[dict], counterparty_party_id: int | None = None,
                    lease_id: int | None = None, property_id: int | None = None, note: str | None = None,
                    accept_possible_duplicate: bool = False) -> Payment:
    """Bestätigt eine Zuordnung. Ohne Zuordnungen ist `note` (Begründung, z. B. 'sonstige Einnahme') Pflicht;
    die Zahlung bleibt dann bewusst nicht zugeordnet."""
    t = get_or_404(db, BankTransaction, txn_id, "Bankbuchung")
    _must_be_open(t)
    if not allocations and not (note or "").strip():
        raise ServiceError("note_required", "Ohne Zuordnung zu Sollstellung/Rechnung ist eine Begründung erforderlich.")
    total = q(sum((Decimal(a["amount"]) for a in allocations), Decimal(0)))
    if total > abs(t.amount):
        raise ServiceError("exceeds_amount", f"Zuordnungen ({total}) übersteigen den Buchungsbetrag ({abs(t.amount)}).", 409)
    p = pay.create_payment(db, actor_id, direction="in" if t.amount > 0 else "out", booking_date=t.booking_date, amount=abs(t.amount),
                           counterparty_party_id=counterparty_party_id, lease_id=lease_id, property_id=property_id, reference=t.reference,
                           note=note, source="bank_import", allocations=allocations, accept_possible_duplicate=accept_possible_duplicate)
    t.status, t.payment_id, t.confirmed_by_user_id, t.confirmed_at = "confirmed", p.id, actor_id, datetime.now(timezone.utc)
    audit.record(db, "bank.confirmed", actor_user_id=actor_id, entity_type="bank_transaction", entity_id=t.id, summary="Bankbuchung bestätigt und als Zahlung übernommen",
                 details={"payment_id": p.id, "allocations": [{k: str(v) for k, v in a.items()} for a in allocations]})
    db.flush()
    return p


def confirm_deposit(db: Session, actor_id: int | None, txn_id: int, *, deposit_id: int, kind: str, reason: str | None = None) -> DepositTransaction:
    t = get_or_404(db, BankTransaction, txn_id, "Bankbuchung")
    _must_be_open(t)
    d = get_or_404(db, Deposit, deposit_id, "Kaution")
    lease = db.get(Lease, d.lease_id)
    expected_in = (lease.kind == "sub") == (kind == "paid")  # Untermiete: Einzahlung = Eingang; Hauptmiete: Einzahlung = Ausgang
    if kind not in ("paid", "refunded") or (t.amount > 0) != expected_in:
        raise ServiceError("direction_mismatch", "Richtung der Bankbuchung passt nicht zur Kautionsbuchung.", 409)
    tx = dep.add_transaction(db, actor_id, d.id, kind=kind, amount=abs(t.amount), transaction_date=t.booking_date, reason=reason, bank_transaction_id=t.id)
    t.status, t.confirmed_by_user_id, t.confirmed_at = "confirmed", actor_id, datetime.now(timezone.utc)
    audit.record(db, "bank.confirmed_deposit", actor_user_id=actor_id, entity_type="bank_transaction", entity_id=t.id, summary="Bankbuchung als Kautionsbuchung bestätigt",
                 details={"deposit_id": d.id, "kind": kind})
    db.flush()
    return tx


def ignore(db: Session, actor_id: int | None, txn_id: int, reason: str) -> BankTransaction:
    t = get_or_404(db, BankTransaction, txn_id, "Bankbuchung")
    _must_be_open(t)
    if not reason.strip():
        raise ServiceError("invalid", "Begründung erforderlich.")
    t.status, t.ignore_reason = "ignored", reason.strip()
    audit.record(db, "bank.ignored", actor_user_id=actor_id, entity_type="bank_transaction", entity_id=t.id, summary="Bankbuchung ausgeblendet", details={"reason": reason})
    db.flush()
    return t


def reopen(db: Session, actor_id: int | None, txn_id: int, reason: str) -> BankTransaction:
    """Macht Ignorieren oder Bestätigung rückgängig. Eine Zahlung wird per Gegenbuchung storniert, eine Kautionsbuchung storniert."""
    t = get_or_404(db, BankTransaction, txn_id, "Bankbuchung")
    if t.status == "open" or not reason.strip():
        raise ServiceError("invalid_state", "Nur bestätigte/ausgeblendete Buchungen (mit Begründung) können geöffnet werden.", 409)
    if t.status == "confirmed":
        if t.payment_id:
            pay.reverse_payment(db, actor_id, t.payment_id, reason=reason)
            t.payment_id = None
        else:
            tx = db.scalar(select(DepositTransaction).where(DepositTransaction.bank_transaction_id == t.id))
            if tx:
                dep.void_transaction(db, actor_id, tx.id, reason)
                tx.bank_transaction_id = None
    t.status, t.ignore_reason, t.confirmed_by_user_id, t.confirmed_at = "open", None, None, None
    audit.record(db, "bank.reopened", actor_user_id=actor_id, entity_type="bank_transaction", entity_id=t.id, summary="Bankbuchung wieder geöffnet", details={"reason": reason})
    db.flush()
    return t
