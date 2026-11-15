"""Wirtschaftlichkeit und Leerstand.

Methode (vollständig in docs/08-phase-d-konzept.md):
* Kleinste Rechen-Einheit ist das BLATT (Bett | Zimmer ohne Betten | Wohneinheit ohne Zimmer). Alle Beträge werden auf Blätter verteilt
  und für beliebige Auswertungsebenen (Portfolio, Objekt, Wohneinheit, Vermietungseinheit) aufsummiert → keine Doppelzählung.
* Soll = aus Verträgen berechnet (gleiche Funktion wie die Sollstellungen). Ist = Zahlungen (Buchungsdatum). Offen = Sollstellungen − Zuordnungen.
* Kautionen kommen NICHT vor (eigene Tabellen, werden hier nie gelesen).
* Das Ergebnis ist ein VORLÄUFIGER Deckungsbeitrag. Leerstandskosten sind ein Teil der Hauptmietkosten und werden NICHT zusätzlich abgezogen."""
from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from leventum import domain
from leventum.models import (Bed, Charge, Invoice, Lease, LeaseAllocationWeight, Payment, PaymentAllocation, Property, RentableUnit, Room, Unit,
                             UtilityStatement)
from leventum.services import payments as pay
from leventum.services.charges import BILLABLE_STATUS, month_range, monthly_components, open_amount
from leventum.services.errors import ServiceError
from leventum.services.leases import OPEN_END, effective_end
from leventum.services.master import chain as ru_chain, get_or_404
from leventum.services.utility import compute_statement, largest_remainder, q

ZERO = Decimal("0.00")
RENT_TYPES = ("base_rent", "other_charges")
UTIL_TYPES = ("utility_prepayment", "utility_flat_rate")


# --- Intervalle ----------------------------------------------------------------------------------------------------------------
def union(iv: list[tuple[date, date]]) -> list[tuple[date, date]]:
    out: list[tuple[date, date]] = []
    for s, e in sorted(iv):
        if out and (out[-1][1] == OPEN_END or s <= out[-1][1] + timedelta(days=1)):
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def subtract(a: list[tuple[date, date]], b: list[tuple[date, date]]) -> list[tuple[date, date]]:
    out = []
    for s, e in a:
        cur = s
        for bs, be in b:
            if be < cur or bs > e:
                continue
            if bs > cur:
                out.append((cur, bs - timedelta(days=1)))
            if be >= e:  # restlicher Abschnitt vollständig überdeckt (auch bei offenem Ende, ohne date.max + 1)
                cur = None
                break
            cur = max(cur, be + timedelta(days=1))
        if cur is not None and cur <= e:
            out.append((cur, e))
    return out


def days_in(iv: list[tuple[date, date]], lo: date, hi: date) -> int:
    return sum(max(0, (min(e, hi) - max(s, lo)).days + 1) for s, e in iv)


# --- Struktur (Blätter) ----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Leaf:
    chain: tuple
    property_id: int
    unit_id: int
    weight: Decimal
    label: str


class Structure:
    def __init__(self, db: Session):
        self.leaves: list[Leaf] = []
        self.by_unit: dict[int, list[Leaf]] = defaultdict(list)
        self.unit_area: dict[int, Decimal | None] = {}
        self.unit_label: dict[int, str] = {}
        props = {p.id: p for p in db.scalars(select(Property).where(Property.is_active.is_(True)))}
        for u in db.scalars(select(Unit).where(Unit.is_active.is_(True)).order_by(Unit.property_id, Unit.unit_number)):
            if u.property_id not in props:
                continue
            pname = props[u.property_id].name
            self.unit_area[u.id] = u.living_area
            self.unit_label[u.id] = f"{pname} · WE {u.unit_number}"
            rooms = list(db.scalars(select(Room).where(Room.unit_id == u.id, Room.is_active.is_(True)).order_by(Room.name)))
            base = (("P", u.property_id), ("U", u.id))
            if not rooms:
                self._add(Leaf(base, u.property_id, u.id, Decimal(1), f"{pname} · WE {u.unit_number}"))
                continue
            by_area = all(r.area and r.area > 0 for r in rooms)
            for r in rooms:
                rw = r.area if by_area else Decimal(1)
                beds = list(db.scalars(select(Bed).where(Bed.room_id == r.id, Bed.is_active.is_(True)).order_by(Bed.label)))
                if not beds:
                    self._add(Leaf(base + (("R", r.id),), u.property_id, u.id, rw, f"{pname} · WE {u.unit_number} · Zimmer {r.name}"))
                for b in beds:
                    self._add(Leaf(base + (("R", r.id), ("B", b.id)), u.property_id, u.id, rw / len(beds), f"{pname} · WE {u.unit_number} · Zimmer {r.name} · Bett {b.label}"))

    def _add(self, leaf: Leaf):
        self.leaves.append(leaf)
        self.by_unit[leaf.unit_id].append(leaf)

    def under(self, ru: RentableUnit) -> list[Leaf]:
        c = ru_chain(ru)
        return [l for l in self.leaves if l.chain[:len(c)] == c]


# --- Rechenmotor -------------------------------------------------------------------------------------------------------------------
def validate_period(start: date, end: date):
    if start.day != 1 or end != date(end.year, end.month, monthrange(end.year, end.month)[1]) or end < start:
        raise ServiceError("invalid_period", "Der Zeitraum muss aus ganzen Kalendermonaten bestehen (Beginn: 1., Ende: Monatsletzter).")
    if (end.year - start.year) * 12 + end.month - start.month > 59:
        raise ServiceError("invalid_period", "Maximal 60 Monate.")


class Engine:
    def __init__(self, db: Session, start: date, end: date):
        validate_period(start, end)
        self.db, self.start, self.end = db, start, end
        self.s = Structure(db)
        self.leases = list(db.scalars(select(Lease).where(Lease.status.in_(BILLABLE_STATUS)).order_by(Lease.id)))
        self.custom = defaultdict(dict)
        for w in db.scalars(select(LeaseAllocationWeight)):
            self.custom[w.lease_id][w.unit_id] = w.weight
        self.leaf = defaultdict(lambda: defaultdict(lambda: ZERO))
        self.prop = defaultdict(lambda: defaultdict(lambda: ZERO))
        self.port = defaultdict(lambda: ZERO)
        self.warnings: list[dict] = []
        self._cover: dict[int, list[Leaf]] = {}
        self.main_cost: dict[tuple, Decimal] = defaultdict(lambda: ZERO)  # (lease_id, (y,m), chain) -> Gesamt-Soll
        self._soll()
        self._objects_and_other_charges()
        self._ist()
        self._open()
        self._vacancy()

    # -- Verteilung --
    def covered(self, lease: Lease) -> list[Leaf]:
        if lease.id not in self._cover:
            seen, out = set(), []
            for it in lease.items:
                for l in self.s.under(it.rentable_unit):
                    if l.chain not in seen:
                        seen.add(l.chain)
                        out.append(l)
            self._cover[lease.id] = out
        return self._cover[lease.id]

    def lease_property(self, lease: Lease) -> int:
        return lease.items[0].rentable_unit.property_id

    def distribute(self, lease: Lease, amount: Decimal) -> tuple[dict, Decimal]:
        """→ ({leaf.chain: Anteil}, nicht verteilter Betrag). Zweistufig: Wohneinheiten (Fläche/gleich/individuell), dann Blätter (Gewichte)."""
        leaves = self.covered(lease)
        if not leaves:
            self._warn("no_active_space", lease.id, "Mietgegenstand enthält keine aktiven Räume – Betrag nicht verteilt.")
            return {}, amount
        units = sorted({l.unit_id for l in leaves})
        if len(units) == 1:
            unit_shares = {units[0]: amount}
        else:
            method = lease.allocation_method if lease.kind == "main" else "area"
            if method == "equal":
                w = {u: Decimal(1) for u in units}
            elif method == "custom":
                w = {u: self.custom[lease.id].get(u) for u in units}
            else:
                w = {u: self.s.unit_area.get(u) for u in units}
            if any(v is None or v <= 0 for v in w.values()):
                self._warn("missing_allocation_data", lease.id, f"Verteilung ({method}) nicht möglich: Fläche/Gewicht fehlt – Betrag nicht auf Wohneinheiten verteilt.")
                return {}, amount
            unit_shares = largest_remainder(amount, w)
        out: dict = {}
        for u, share in unit_shares.items():
            ls = [l for l in leaves if l.unit_id == u]
            for k, v in largest_remainder(share, {l.chain: l.weight for l in ls}).items():
                out[k] = out.get(k, ZERO) + v
        return out, ZERO

    def _warn(self, code, ref, msg):
        w = {"code": code, "lease_id": ref, "message": msg}
        if w not in self.warnings:
            self.warnings.append(w)

    def _add(self, lease: Lease, metric: str, amount: Decimal, chain_store: dict | None = None):
        parts, un = self.distribute(lease, amount)
        for k, v in parts.items():
            self.leaf[k][metric] += v
        if un:
            self.prop[self.lease_property(lease)][metric] += un
        if chain_store is not None:
            for k, v in parts.items():
                chain_store[k] += v

    # -- Soll --
    def _soll(self):
        for lease in self.leases:
            kind = "main" if lease.kind == "main" else "sub"
            for y, m in month_range(self.start, self.end):
                comps = monthly_components(lease, y, m)
                store = defaultdict(lambda: ZERO)
                for t, amt in comps.items():
                    cat = "rent" if t in RENT_TYPES else "utility"
                    self._add(lease, f"soll_{kind}_{cat}", amt, store if kind == "main" else None)
                for k, v in store.items():
                    self.main_cost[(lease.id, (y, m), k)] += v

    def _objects_and_other_charges(self):
        for inv in self.db.scalars(select(Invoice).where(Invoice.voided_at.is_(None), Invoice.invoice_date >= self.start, Invoice.invoice_date <= self.end)):
            self._attach_invoice(inv, "soll_object_costs", inv.amount)
        for c in self.db.scalars(select(Charge).where(Charge.voided_at.is_(None), Charge.charge_type == "other", Charge.period_start >= self.start, Charge.period_start <= self.end)):
            self._add(self.db.get(Lease, c.lease_id), f"soll_{'sub' if c.direction == 'receivable' else 'main'}_other", c.amount)

    def _attach_invoice(self, inv: Invoice, metric: str, amount: Decimal):
        ls = self.s.by_unit.get(inv.unit_id) if inv.unit_id else None
        if ls:
            for k, v in largest_remainder(amount, {l.chain: l.weight for l in ls}).items():
                self.leaf[k][metric] += v
        else:
            self.prop[inv.property_id][metric] += amount

    # -- Ist --
    def _ist(self):
        pays = list(self.db.scalars(select(Payment).where(Payment.booking_date >= self.start, Payment.booking_date <= self.end)))
        for p in pays:
            allocs = list(self.db.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == p.id)))
            for a in allocs:
                if a.charge_id:
                    c = self.db.get(Charge, a.charge_id)
                    lease = self.db.get(Lease, c.lease_id)
                    self._add(lease, "ist_in_receivables" if c.direction == "receivable" else "ist_out_payables", a.amount)
                else:
                    inv = self.db.get(Invoice, a.invoice_id)
                    self._attach_invoice(inv, "ist_out_invoices", a.amount)
            rest = q(pay.signed(p) - sum((a.amount for a in allocs), Decimal(0)))
            if rest:
                metric = "ist_in_other" if p.direction == "in" else "ist_out_other"
                (self.prop[p.property_id] if p.property_id else self.port)[metric] += rest

    # -- Offen (Stichtag = Periodenende) --
    def _open(self):
        as_of = self.end
        for c in self.db.scalars(select(Charge).where(Charge.voided_at.is_(None), Charge.due_date <= as_of)):
            o = open_amount(self.db, c, as_of)
            if o <= 0:
                continue
            lease = self.db.get(Lease, c.lease_id)
            base = "receivables" if c.direction == "receivable" else "payables"
            self._add(lease, f"open_{base}", o)
            if c.due_date < as_of:
                self._add(lease, f"overdue_{base}", o)
        for inv in self.db.scalars(select(Invoice).where(Invoice.voided_at.is_(None), Invoice.invoice_date <= as_of)):
            o = q(inv.amount - pay.invoice_allocated(self.db, inv.id, as_of))
            if o > 0:
                self._attach_invoice(inv, "open_invoices", o)

    # -- Leerstand --
    def _vacancy(self):
        lo, hi = self.start, self.end
        occ: dict[tuple, list] = defaultdict(list)
        mains = []
        for lease in self.leases:
            span = (lease.start_date, effective_end(lease) or OPEN_END)
            if lease.kind == "sub":
                for l in self.covered(lease):
                    occ[l.chain].append(span)
            else:
                mains.append((lease, span))
        occ_u = {k: union(v) for k, v in occ.items()}
        total_days = (hi - lo).days + 1
        main_cov: dict[tuple, list] = defaultdict(list)
        for lease, span in mains:
            for l in self.covered(lease):
                main_cov[l.chain].append(span)
        self.leaf_rows = []
        for l in self.s.leaves:
            o = occ_u.get(l.chain, [])
            od = days_in(o, lo, hi)
            mc = union(main_cov.get(l.chain, []))
            md = days_in(mc, lo, hi)
            mvd = days_in(subtract(mc, o), lo, hi)
            m = self.leaf[l.chain]
            m["phys_days_total"] += total_days
            m["phys_days_vacant"] += total_days - od
            m["phys_wdays_total"] += l.weight * total_days
            m["phys_wdays_vacant"] += l.weight * (total_days - od)
            m["main_days"] += md
            m["main_vacant_days"] += mvd
        for lease, span in mains:
            for l in self.covered(lease):
                vac = subtract([span], occ_u.get(l.chain, []))
                for y, mth in month_range(lo, hi):
                    ms, me = date(y, mth, 1), date(y, mth, monthrange(y, mth)[1])
                    cov, vd = days_in([span], ms, me), days_in(vac, ms, me)
                    if cov and vd:
                        cost = self.main_cost.get((lease.id, (y, mth), l.chain), ZERO)
                        self.leaf[l.chain]["vacancy_cost"] += q(cost * vd / cov)

    # -- Auswertung --
    def select(self, scope: str, id_: int | None):
        if scope == "portfolio":
            return self.s.leaves, list(self.prop), True
        if scope == "property":
            return [l for l in self.s.leaves if l.property_id == id_], [id_], False
        if scope == "unit":
            return self.s.by_unit.get(id_, []), [], False
        if scope == "rentable_unit":
            ru = get_or_404(self.db, RentableUnit, id_, "Vermietungseinheit")
            return self.s.under(ru), [], False
        raise ServiceError("invalid", "Ungültiger Bereich (portfolio|property|unit|rentable_unit).")

    def report(self, scope: str, id_: int | None = None) -> dict:
        if scope != "portfolio" and id_ is None:
            raise ServiceError("invalid", "ID fehlt.")
        leaves, props, with_port = self.select(scope, id_)
        tot: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for l in leaves:
            for k, v in self.leaf.get(l.chain, {}).items():
                tot[k] += v
        for p in props:
            for k, v in self.prop.get(p, {}).items():
                tot[k] += v
        if with_port:
            for k, v in self.port.items():
                tot[k] += v
        g = lambda k: q(tot.get(k, ZERO))
        sub_soll = g("soll_sub_rent") + g("soll_sub_utility") + g("soll_sub_other")
        main_soll = g("soll_main_rent") + g("soll_main_utility") + g("soll_main_other")
        obj = g("soll_object_costs")
        ist_in = g("ist_in_receivables") + g("ist_in_other")
        ist_out = g("ist_out_payables") + g("ist_out_invoices") + g("ist_out_other")
        settle = self._settlements(scope, id_)
        pdays = tot.get("phys_days_total", ZERO)
        warnings = list(self.warnings)
        if scope in ("unit", "rentable_unit"):
            warnings.append({"code": "object_level_costs_excluded", "message": "Objektweite Kosten ohne Wohneinheiten-Bezug, nicht verteilte Hauptmieten und Nebenkosten-Abrechnungssalden sind in Wohneinheiten-/Vermietungseinheiten-Auswertungen nicht enthalten."})
        if g("ist_in_other") or g("ist_out_other"):
            warnings.append({"code": "unallocated_payments", "message": "Es gibt Zahlungen ohne Zuordnung zu Sollstellungen/Rechnungen; sie sind nur im Ist-Gesamtergebnis enthalten."})
        return {
            "scope": {"type": scope, "id": id_}, "period": {"start": self.start, "end": self.end}, "status": "vorläufig",
            "soll": {"sub_rent": g("soll_sub_rent"), "sub_utility": g("soll_sub_utility"), "sub_other": g("soll_sub_other"), "sub_total": q(sub_soll),
                     "main_rent": g("soll_main_rent"), "main_utility": g("soll_main_utility"), "main_other": g("soll_main_other"), "main_total": q(main_soll),
                     "object_costs": obj},
            "ist": {"in_from_subleases": g("ist_in_receivables"), "in_other_unallocated": g("ist_in_other"), "in_total": q(ist_in),
                    "out_main_rent": g("ist_out_payables"), "out_invoices": g("ist_out_invoices"), "out_other_unallocated": g("ist_out_other"), "out_total": q(ist_out)},
            "offen_zum_stichtag": {"as_of": self.end, "receivables": g("open_receivables"), "receivables_overdue": g("overdue_receivables"),
                                   "payables": g("open_payables"), "payables_overdue": g("overdue_payables"), "invoices": g("open_invoices")},
            "vacancy": {"economic_vacancy_cost": g("vacancy_cost"), "note": "Teil der Hauptmietkosten (nicht zusätzlich abgezogen)",
                        "physical_vacancy_rate_by_count": (q(tot.get("phys_days_vacant", ZERO) * 100 / pdays) if pdays else None),
                        "physical_vacancy_rate_by_weight": (q(tot.get("phys_wdays_vacant", ZERO) * 100 / tot["phys_wdays_total"]) if tot.get("phys_wdays_total") else None)},
            "contribution": {"label": "Vorläufiger Deckungsbeitrag (kein Gewinn)",
                             "rent_margin_soll": q(g("soll_sub_rent") - g("soll_main_rent")),
                             "utility_flow_soll": q(g("soll_sub_utility") - g("soll_main_utility")),
                             "soll_basis": q(sub_soll - main_soll - obj),
                             "ist_basis": q(ist_in - ist_out),
                             "utility_settlement_upstream": settle,
                             "soll_basis_incl_upstream_settlement": q(sub_soll - main_soll - obj - settle["balance"]) if settle else None},
            "deposits": "ausgeschlossen (Kautionen sind kein Ertrag und keine Kosten)",
            "warnings": warnings,
            "assumptions": ["Soll = aus Mietkonditionen/Nebenkostenvereinbarung, tagesgenau anteilig; Ist = Zahlungen nach Buchungsdatum.",
                            "Hauptmiete: zuerst auf Wohneinheiten (Methode je Hauptmietvertrag: Fläche/gleich/individuell), dann auf Betten/Zimmer nach Gewicht.",
                            "Leerstandskosten = Hauptmiete-Soll der Blätter an Tagen ohne laufenden Untermietvertrag (Teilmenge der Hauptmietkosten).",
                            "Soll- und Ist-Basis dürfen nicht addiert oder verwechselt werden."],
        }

    def _settlements(self, scope: str, id_):
        if scope not in ("portfolio", "property"):
            return None
        total, counted, missing = ZERO, 0, 0
        for st in self.db.scalars(select(UtilityStatement).where(UtilityStatement.period_end >= self.start, UtilityStatement.period_end <= self.end)):
            if scope == "property" and st.property_id != id_:
                continue
            b = compute_statement(self.db, st.id)["balance"]
            if b is None:
                missing += 1
            else:
                total += b
                counted += 1
        return {"balance": q(total), "statements_counted": counted, "statements_without_prepayments": missing,
                "note": "+ = Nachzahlung an Vermieter (Kosten), − = Guthaben. Zusätzlich zum Soll der Vorauszahlungen; nicht in Unter-Ebenen verteilt."}

    def vacancy_rows(self, property_id: int | None = None) -> list[dict]:
        rows = []
        for l in self.s.leaves:
            if property_id and l.property_id != property_id:
                continue
            m = self.leaf.get(l.chain, {})
            total = int(m.get("phys_days_total", 0))
            vac = int(m.get("phys_days_vacant", 0))
            rows.append({"label": l.label, "unit_id": l.unit_id, "weight": q(l.weight), "days_total": total, "days_occupied": total - vac, "days_vacant": vac,
                         "days_with_main_obligation": int(m.get("main_days", 0)), "days_vacant_with_main_obligation": int(m.get("main_vacant_days", 0)),
                         "economic_vacancy_cost": q(m.get("vacancy_cost", ZERO))})
        return rows


def vacancy_report(db: Session, start: date, end: date, property_id: int | None = None, engine: Engine | None = None) -> dict:
    """Zwei getrennte Kennzahlen: A physisch (nicht belegte Blätter) und B wirtschaftlich (Hauptmietpflicht ohne Untermiete)."""
    e = engine or Engine(db, start, end)
    rows = e.vacancy_rows(property_id)
    leaves = [l for l in e.s.leaves if not property_id or l.property_id == property_id]
    today = min(max(date.today(), start), end)
    snap = {"as_of": today, "leaves_total": len(leaves), "leaves_occupied": 0}
    total_w = sum((l.weight for l in leaves), Decimal(0))
    leaf_by = {l.chain: l for l in leaves}
    occ = set()
    for lease in e.leases:
        if lease.kind == "sub" and lease.start_date <= today <= (effective_end(lease) or OPEN_END):
            for l in e.covered(lease):
                if l.chain in leaf_by:
                    occ.add(l.chain)
    snap["leaves_occupied"] = len(occ)
    snap["leaves_vacant"] = len(leaves) - len(occ)
    occupied_w = sum((leaf_by[c].weight for c in occ), Decimal(0))
    snap["occupied_share_by_weight_percent"] = q(occupied_w * 100 / total_w) if total_w else None
    rep = e.report("property", property_id) if property_id else e.report("portfolio")
    return {"period": {"start": start, "end": end}, "snapshot": snap, "physical": {"vacancy_rate_by_count_percent": rep["vacancy"]["physical_vacancy_rate_by_count"],
            "vacancy_rate_by_weight_percent": rep["vacancy"]["physical_vacancy_rate_by_weight"], "definition": "Anteil der Blatt-Tage (Bett/Zimmer/Wohneinheit) ohne laufenden Untermietvertrag"},
            "economic": {"cost": rep["vacancy"]["economic_vacancy_cost"], "days_vacant_with_main_obligation": sum(r["days_vacant_with_main_obligation"] for r in rows),
                         "definition": "Hauptmiete-Soll (Kalt+NK) an Tagen, an denen eine Mietverpflichtung besteht, aber kein laufender Untermietvertrag"},
            "rows": rows, "warnings": e.warnings}


def current_month_figures(db: Session, today: date | None = None) -> dict:
    """Dashboard-Zahlen: Soll des laufenden Monats, offene/überfällige Forderungen, Leerstand."""
    today = today or date.today()
    y, m = today.year, today.month
    res = {"main_total": ZERO, "main_utility": ZERO, "sub_total": ZERO}
    for lease in db.scalars(select(Lease).where(Lease.status.in_(BILLABLE_STATUS))):
        comps = monthly_components(lease, y, m)
        tot = sum(comps.values(), Decimal(0))
        if lease.kind == "main":
            res["main_total"] += tot
            res["main_utility"] += sum((v for k, v in comps.items() if k in UTIL_TYPES), Decimal(0))
        else:
            res["sub_total"] += tot
    open_, overdue_n = ZERO, 0
    for c in db.scalars(select(Charge).where(Charge.voided_at.is_(None), Charge.direction == "receivable")):
        o = open_amount(db, c)
        if o > 0:
            open_ += o
            if c.due_date < today:
                overdue_n += 1
    first, last = date(y, m, 1), date(y, m, monthrange(y, m)[1])
    e = Engine(db, first, last)
    rep = e.report("portfolio")
    vacant_today = vacancy_report(db, first, last, engine=e)["snapshot"]["leaves_vacant"]
    return {"main_total": q(res["main_total"]), "main_utility": q(res["main_utility"]), "sub_total": q(res["sub_total"]), "open_receivables": q(open_),
            "overdue_count": overdue_n, "vacant_leaves": vacant_today, "economic_vacancy_cost": rep["vacancy"]["economic_vacancy_cost"]}
