"""Betriebs-/Nebenkosten.
Ebene A (Vermieter → Leventum): Eingangsabrechnung erfassen, Nachzahlung/Guthaben berechnen, auf Wohneinheiten verteilen.
Ebene B (Leventum → Untermieter): hier NUR vergleichende Auswertung auf Basis der Nebenkostenvereinbarungen.
Es werden KEINE Forderungen gegenüber Untermietern erzeugt. Umlagefähigkeit wird nie angenommen."""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from leventum import domain
from leventum.models import (CostType, Lease, Property, Unit, UtilityLineWeight, UtilityStatement,
                             UtilityStatementLine, UtilityStatementUnit)
from leventum.services import audit
from leventum.services.errors import ServiceError
from leventum.services.leases import OPEN_END, _span, overlaps
from leventum.services.master import chain, get_or_404

CENT = Decimal("0.01")


def q(x: Decimal) -> Decimal:
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


# --- Rechenkerne (rein, ohne DB) ---------------------------------------------------------------------
def largest_remainder(total: Decimal, weights: dict) -> dict:
    """Verteilt `total` (2 Nachkommastellen) proportional; Summe der Teile == total exakt (Cent-Rest nach größtem Rest)."""
    total = q(total)
    wsum = sum(weights.values(), Decimal(0))
    if not weights or wsum <= 0:
        raise ValueError("Gewichte müssen eine positive Summe ergeben.")
    cents = int(total * 100)
    raw = {k: Decimal(cents) * w / wsum for k, w in weights.items()}
    floors = {k: int(v) if v >= 0 else -int(-v) for k, v in raw.items()}
    rest = cents - sum(floors.values())
    order = sorted(weights, key=lambda k: (-(raw[k] - floors[k]), k))  # Gleichstand: kleinerer Schlüssel zuerst
    for k in order[:abs(rest)]:
        floors[k] += 1 if rest > 0 else -1
    return {k: Decimal(v) / 100 for k, v in floors.items()}


def months_overlap(a_start: date, a_end: date | None, p_start: date, p_end: date) -> Decimal:
    """Tagesgenaue Monatsanteile der Überschneidung [a] ∩ [p] (Teilmonat = Tage/Tage des Monats). Annahme siehe docs."""
    s, e = max(a_start, p_start), min(a_end or OPEN_END, p_end)
    if e < s:
        return Decimal(0)
    total, y, m = Decimal(0), s.year, s.month
    while (y, m) <= (e.year, e.month):
        dim = monthrange(y, m)[1]
        ms, me = max(s, date(y, m, 1)), min(e, date(y, m, dim))
        total += Decimal((me - ms).days + 1) / Decimal(dim)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return total


# --- Erfassung -----------------------------------------------------------------------------------------
def create_statement(db: Session, actor_id: int | None, *, main_lease_id: int, period_start: date, period_end: date,
                     unit_ids: list[int], statement_date: date | None = None, received_on: date | None = None,
                     stated_balance=None, notes: str | None = None) -> UtilityStatement:
    lease = get_or_404(db, Lease, main_lease_id, "Hauptmietvertrag")
    if lease.kind != "main":
        raise ServiceError("invalid", "Eingangsabrechnungen gehören zu einem Hauptmietvertrag.")
    if period_end < period_start:
        raise ServiceError("invalid", "Abrechnungszeitraum ungültig.")
    props = {i.rentable_unit.property_id for i in lease.items}
    if len(props) != 1:
        raise ServiceError("invalid", "Der Hauptmietvertrag muss genau einem Objekt zugeordnet sein.")
    prop_id = props.pop()
    if not overlaps(_span(lease), (period_start, period_end)):
        raise ServiceError("invalid", "Der Abrechnungszeitraum liegt außerhalb der Laufzeit des Hauptmietvertrags.")
    st = UtilityStatement(level="upstream", property_id=prop_id, main_lease_id=lease.id, period_start=period_start,
                          period_end=period_end, statement_date=statement_date, received_on=received_on,
                          stated_balance=stated_balance, notes=notes)
    for uid in dict.fromkeys(unit_ids):
        u = get_or_404(db, Unit, uid, "Wohneinheit")
        if u.property_id != prop_id:
            raise ServiceError("invalid", f"Wohneinheit {u.unit_number} gehört nicht zum Objekt der Abrechnung.")
        st.units.append(UtilityStatementUnit(unit_id=uid))
    db.add(st)
    db.flush()
    audit.record(db, "utility_statement.created", actor_user_id=actor_id, entity_type="utility_statement", entity_id=st.id,
                 summary="Eingehende Nebenkostenabrechnung erfasst", details={"period": f"{period_start}..{period_end}"})
    return st


def _editable(st: UtilityStatement):
    if st.status == "reviewed":
        raise ServiceError("locked", "Geprüfte Abrechnungen sind gesperrt (historischer Stand).", 409)


def add_line(db: Session, actor_id: int | None, statement_id: int, *, cost_type_id: int, amount, allocation_key: str = "none",
             allocable_status: str = "unreviewed", description: str | None = None, note: str | None = None,
             weights: dict[int, Decimal] | None = None) -> UtilityStatementLine:
    st = get_or_404(db, UtilityStatement, statement_id, "Abrechnung")
    _editable(st)
    get_or_404(db, CostType, cost_type_id, "Kostenart")
    if allocation_key not in domain.ALLOC_KEYS or allocable_status not in domain.ALLOCABLE_STATUS:
        raise ServiceError("invalid", "Ungültiger Verteilungsschlüssel oder Umlagestatus.")
    line = UtilityStatementLine(cost_type_id=cost_type_id, amount=amount, allocation_key=allocation_key,
                                allocable_status=allocable_status, description=description, note=note)
    scope = {u.unit_id for u in st.units}
    for uid, w in (weights or {}).items():
        if uid not in scope:
            raise ServiceError("invalid", f"Wohneinheit {uid} gehört nicht zum Geltungsbereich der Abrechnung.")
        if w < 0:
            raise ServiceError("invalid", "Gewichte dürfen nicht negativ sein.")
        line.weights.append(UtilityLineWeight(unit_id=uid, weight=w))
    st.lines.append(line)
    db.flush()
    audit.record(db, "utility_statement.line_added", actor_user_id=actor_id, entity_type="utility_statement", entity_id=st.id,
                 summary="Kostenposition erfasst", details={"amount": str(amount), "cost_type_id": cost_type_id})
    return line


def set_prepayments(db: Session, actor_id: int | None, statement_id: int, amount, source: str) -> UtilityStatement:
    st = get_or_404(db, UtilityStatement, statement_id, "Abrechnung")
    _editable(st)
    if source not in domain.PREPAYMENT_SOURCES:
        raise ServiceError("invalid", "Ungültige Quelle der Vorauszahlungen.")
    st.prepayments_amount, st.prepayments_source = amount, source
    audit.record(db, "utility_statement.prepayments_set", actor_user_id=actor_id, entity_type="utility_statement",
                 entity_id=st.id, summary="Vorauszahlungen gesetzt", details={"amount": str(amount), "source": source})
    db.flush()
    return st


def set_status(db: Session, actor_id: int | None, statement_id: int, status: str) -> UtilityStatement:
    st = get_or_404(db, UtilityStatement, statement_id, "Abrechnung")
    order = domain.STATEMENT_STATUS
    if status not in order or order.index(status) != order.index(st.status) + 1:
        raise ServiceError("invalid_state", "Statuswechsel nur schrittweise vorwärts (draft → captured → reviewed).", 409)
    if status == "reviewed" and st.prepayments_amount is None:
        raise ServiceError("incomplete", "Vor der Prüfung müssen die Vorauszahlungen erfasst sein.", 409)
    st.status = status
    audit.record(db, "utility_statement.status", actor_user_id=actor_id, entity_type="utility_statement", entity_id=st.id,
                 summary=f"Status: {status}")
    db.flush()
    return st


# --- Berechnung Ebene A ----------------------------------------------------------------------------------
def suggest_prepayments(st: UtilityStatement, main_lease: Lease) -> dict:
    """Vorauszahlungen laut Nebenkostenvereinbarung (SOLL, nicht tatsächlich gezahlt – Zahlungen folgen in Phase D)."""
    total, warnings = Decimal(0), []
    for a in main_lease.utility_agreements:
        m = months_overlap(a.valid_from, a.valid_to, st.period_start, st.period_end)
        if m == 0:
            continue
        if a.mode == "prepayment":
            total += a.monthly_amount * m
        else:
            warnings.append({"code": f"agreement_{a.mode}", "message": f"Im Zeitraum gilt eine Vereinbarung '{a.mode}' – nicht als Vorauszahlung gewertet."})
    return {"amount": q(total), "warnings": warnings}


def compute_statement(db: Session, statement_id: int) -> dict:
    st = get_or_404(db, UtilityStatement, statement_id, "Abrechnung")
    lease = db.get(Lease, st.main_lease_id)
    lines = st.lines
    total = q(sum((l.amount for l in lines), Decimal(0)))
    by_status = {s: q(sum((l.amount for l in lines if l.allocable_status == s), Decimal(0))) for s in domain.ALLOCABLE_STATUS}
    warnings = []
    if (st.period_end - st.period_start).days > 365:
        warnings.append({"code": "period_over_12_months", "message": "Abrechnungszeitraum länger als 12 Monate."})
    sug = suggest_prepayments(st, lease)
    warnings += sug["warnings"]
    prepay = st.prepayments_amount
    result = {"statement_id": st.id, "status": st.status, "period": [str(st.period_start), str(st.period_end)],
              "total_costs": total, "costs_by_allocable_status": by_status,
              "suggested_prepayments": sug["amount"], "prepayments": prepay, "prepayments_source": st.prepayments_source,
              "balance": None, "direction": None, "stated_balance": st.stated_balance, "deviation_from_stated": None,
              "warnings": warnings}
    if prepay is None:
        warnings.append({"code": "prepayments_missing", "message": "Vorauszahlungen noch nicht erfasst – kein Ergebnis berechnet."})
        return result
    balance = q(total - prepay)  # + = Nachzahlung durch Leventum, − = Guthaben
    result["balance"] = balance
    result["direction"] = "nachzahlung" if balance > 0 else "guthaben" if balance < 0 else "ausgeglichen"
    if st.stated_balance is not None and st.stated_balance != balance:
        result["deviation_from_stated"] = q(balance - st.stated_balance)
        warnings.append({"code": "deviates_from_stated", "message": "Berechnetes Ergebnis weicht vom ausgewiesenen Ergebnis des Vermieters ab."})
    return result


# --- Verteilung auf Wohneinheiten ----------------------------------------------------------------------------
def allocate_statement(db: Session, statement_id: int) -> dict:
    st = get_or_404(db, UtilityStatement, statement_id, "Abrechnung")
    units = {u.unit_id: db.get(Unit, u.unit_id) for u in st.units}
    per_unit = {uid: Decimal(0) for uid in units}
    lines_out, warnings, unallocated = [], [], Decimal(0)
    for ln in st.lines:
        info = {"line_id": ln.id, "cost_type": ln.cost_type.name, "amount": ln.amount, "key": ln.allocation_key, "shares": None}
        weights, problem = None, None
        if not units:
            problem = "no_units_in_scope"
        elif ln.allocation_key == "area":
            miss = [u.unit_number for u in units.values() if not u.living_area or u.living_area <= 0]
            weights = None if miss else {uid: u.living_area for uid, u in units.items()}
            problem = f"missing_area:{','.join(miss)}" if miss else None
        elif ln.allocation_key == "equal":
            weights = {uid: Decimal(1) for uid in units}
        elif ln.allocation_key in ("persons", "consumption", "custom"):
            w = {x.unit_id: x.weight for x in ln.weights}
            if set(w) >= set(units) and all(v >= 0 for v in w.values()) and sum(w.values()) > 0:
                weights = {uid: w[uid] for uid in units}
            else:
                problem = "weights_missing"
        else:
            problem = "no_key"
        if weights:
            shares = largest_remainder(ln.amount, weights)
            info["shares"] = shares
            for uid, s in shares.items():
                per_unit[uid] += s
        else:
            unallocated += ln.amount
            info["problem"] = problem
            warnings.append({"code": problem.split(":")[0], "message": f"Position {ln.id} ({ln.cost_type.name}) nicht verteilt: {problem}", "line_id": ln.id})
        lines_out.append(info)
    per_unit = {k: q(v) for k, v in per_unit.items()}
    return {"statement_id": st.id, "per_unit": per_unit, "unallocated": q(unallocated), "lines": lines_out, "warnings": warnings}


# --- Vergleich mit Untermiet-Vereinbarungen (Ebene B, nur Auswertung) ---------------------------------------------
CLAIM_STATUS = {
    "prepayment": "settlement_agreed_review_required",
    "flat_rate": "no_claim_flat_rate",
    "included": "no_claim_included_in_rent",
    "none": "no_claim_no_utility_agreement",
    "individual": "undetermined_manual_review",
}


def compare_with_downstream(db: Session, statement_id: int) -> dict:
    """Je Wohneinheit: verteilte tatsächliche Kosten (Ebene A) vs. vereinbarte Nebenkosten der Untermieter (Soll).
    Liefert nur Zahlen und Einordnungen. 'claim_status' ist KEINE Rechtsaussage und erzeugt keine Nachforderung."""
    st = get_or_404(db, UtilityStatement, statement_id, "Abrechnung")
    alloc = allocate_statement(db, statement_id)
    scope = {u.unit_id for u in st.units}
    period = (st.period_start, st.period_end)
    subs = db.scalars(select(Lease).where(Lease.kind == "sub", Lease.status.in_(("active", "terminated", "ended")))).all()
    rows = {uid: {"unit_id": uid, "unit_number": db.get(Unit, uid).unit_number, "allocated_actual_costs": alloc["per_unit"][uid],
                  "downstream_prepayments_soll": Decimal(0), "downstream_flat_rates_soll": Decimal(0),
                  "agreements": [], "claim_possible": False} for uid in scope}
    unattributable, warnings = [], list(alloc["warnings"])
    for lease in subs:
        if not overlaps(_span(lease), period):
            continue
        units_hit = {i.rentable_unit.unit_id for i in lease.items if i.rentable_unit.unit_id in scope}
        prop_level = any(i.rentable_unit.property_id == st.property_id and i.rentable_unit.unit_id is None for i in lease.items)
        if prop_level or len(units_hit) > 1:
            unattributable.append(lease.id)
            warnings.append({"code": "unattributable_sublease", "message": f"Untermietvertrag {lease.id} betrifft mehrere Wohneinheiten/das ganze Objekt – nicht automatisch zugeordnet."})
            continue
        if not units_hit:
            continue
        uid = units_hit.pop()
        for a in lease.utility_agreements:
            m = months_overlap(max(a.valid_from, lease.start_date), min(a.valid_to or OPEN_END, lease.termination_effective_on or lease.end_date or OPEN_END), *period)
            if m == 0:
                continue
            amt = q(a.monthly_amount * m) if a.mode in ("prepayment", "flat_rate") and a.monthly_amount is not None else Decimal(0)
            r = rows[uid]
            if a.mode == "prepayment":
                r["downstream_prepayments_soll"] += amt
            elif a.mode == "flat_rate":
                r["downstream_flat_rates_soll"] += amt
            status = CLAIM_STATUS[a.mode]
            if a.mode == "individual" and a.settlement_agreed is not True:
                status = "undetermined_manual_review"
            r["agreements"].append({"lease_id": lease.id, "mode": a.mode, "months": m.quantize(Decimal("0.0001")), "soll": amt, "claim_status": status})
            if status == "settlement_agreed_review_required":
                r["claim_possible"] = True
    totals = {"allocated_actual_costs": Decimal(0), "downstream_prepayments_soll": Decimal(0), "downstream_flat_rates_soll": Decimal(0)}
    for r in rows.values():
        for k in totals:
            totals[k] += r[k]
        r["nk_result_before_settlement"] = q(r["downstream_prepayments_soll"] + r["downstream_flat_rates_soll"] - r["allocated_actual_costs"])
        r["allocated_actual_costs"] = q(r["allocated_actual_costs"])
        r["downstream_prepayments_soll"] = q(r["downstream_prepayments_soll"])
        r["downstream_flat_rates_soll"] = q(r["downstream_flat_rates_soll"])
    nk_total = q(totals["downstream_prepayments_soll"] + totals["downstream_flat_rates_soll"] - totals["allocated_actual_costs"])
    return {"statement_id": st.id, "rows": list(rows.values()), "unattributable_subleases": unattributable,
            "unallocated_costs": alloc["unallocated"],
            "totals": {k: q(v) for k, v in totals.items()},
            "impact_on_preliminary_contribution": {
                "nk_result_before_downstream_settlement": nk_total,
                "note": "Nur Soll-Betrag der Untermieter-Nebenkosten minus verteilte tatsächliche Kosten (Ebene A). Mögliche Nachforderungen sind "
                        "NICHT enthalten und werden nicht automatisch erzeugt; nicht verteilte Kosten sind separat als 'unallocated_costs' ausgewiesen."},
            "warnings": warnings}
