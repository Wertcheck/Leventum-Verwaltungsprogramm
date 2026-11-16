#!/usr/bin/env python
"""Benchmark (Baseline) für die Lesepfade rund um offene Posten (N+1-Untersuchung, ADR 0002 Befund B).

Aufruf (aus dem Repo-Wurzelverzeichnis):
    .venv/bin/python scripts/bench_open_items.py --charges 30 100 500 --repeat 5 --json out.json

Je Datenmenge wird eine FRISCHE temporäre SQLite-DB mit ERFUNDENEN Daten aufgebaut (Migrationen über create_app, wie in tests/conftest.py;
Stammdaten über die Services wie tests/helpers.py World; Sollstellungen/Zahlungen/Zuordnungen direkt als Zeilen, damit der Aufbau schnell bleibt).
Gemessen wird je Pfad: (a) SQL-Statements (before_cursor_execute), (b) Laufzeit (1 Warmup, dann --repeat Läufe, Median/Min/Max, perf_counter,
jeweils frische Session ohne Listener), (c) EXPLAIN QUERY PLAN der 3 häufigsten und 3 zeitintensivsten Statements, (d) Testbedingungen.
Optional: cProfile (--profile-top) für die größte Datenmenge.

Das Skript schreibt nichts ins Repository; die Temp-DBs liegen unter --workdir (Standard: System-Temp) und werden danach gelöscht (--keep behält sie).
Keine echten Daten, keine Netzwerkzugriffe, kein Produktivcode wird verändert."""
from __future__ import annotations

import argparse
import cProfile
import io
import json
import platform
import pstats
import random
import re
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import event, func, select  # noqa: E402

from leventum.config import Settings  # noqa: E402
from leventum.main import create_app  # noqa: E402
from leventum.models import AppUser, Charge, Lease, LeaseType, Payment, PaymentAllocation, Role  # noqa: E402
from leventum.services import dashboard, economics, leases as L, master as M, reminders  # noqa: E402
from leventum.services.charges import receivable_position  # noqa: E402

SEED = 20261116


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


# --- Datenaufbau (erfundene Daten) -------------------------------------------------------------------------------------------------
def build_world(data_dir: Path, n_charges: int, today: date) -> dict:
    rng = random.Random(SEED + n_charges)
    app = create_app(Settings(data_dir=data_dir, frontend_dist=data_dir / "nodist"))
    db = app.state.session_factory()
    own = M.create_party(db, None, {"kind": "company", "company_name": "Bench GmbH", "is_own_organization": True}, [])
    owner = M.create_party(db, None, {"kind": "person", "first_name": "Erika", "last_name": "Mustermann"}, ["owner", "landlord"])
    prop = M.create_property(db, None, {"name": "Bench-Haus", "property_type": "mehrfamilienhaus", "street": "Teststr. 1", "city": "Teststadt", "owner_party_id": owner.id})
    db.add(AppUser(username="bench", display_name="Bench", password_hash="x", role_id=db.scalar(select(Role.id).where(Role.code == "admin"))))
    db.flush()
    types = {c.code: c.id for c in db.scalars(select(LeaseType))}
    start = add_months(date(today.year, today.month, 1), -30)
    n_sub = max(3, n_charges // 10)   # ca. 10 Sollstellungen je Untermietvertrag
    units, rus = [], []
    for j in range(n_sub):
        u = M.create_unit(db, None, prop.id, {"unit_number": f"WE {j + 1}", "living_area": D(30 + (j * 7) % 50)})
        units.append(u)
        if j % 3 == 0:   # jede dritte Einheit: 2 Zimmer, vermietet wird Zimmer 1 (Zimmer 2 bleibt leer -> Leerstandsberechnung)
            r1 = M.create_room(db, None, u.id, {"name": "Zimmer 1", "area": D("14.00")})
            M.create_room(db, None, u.id, {"name": "Zimmer 2", "area": D("12.00")})
            rus.append(M.ensure_rentable_unit(db, None, property_id=prop.id, room_id=r1.id))
        else:
            rus.append(M.ensure_rentable_unit(db, None, property_id=prop.id, unit_id=u.id))
    main = L.create_lease(db, None, kind="main", lease_type_id=types["hauptmiete"], start_date=start, end_date=None,
                          parties=[{"party_id": owner.id, "role": "lessor"}, {"party_id": own.id, "role": "lessee"}],
                          rentable_unit_ids=[M.ensure_rentable_unit(db, None, property_id=prop.id).id], subletting_permitted=True)
    L.add_term(db, None, main.id, valid_from=start, valid_to=None, base_rent=D("9000.00"))
    L.add_utility_agreement(db, None, main.id, valid_from=start, valid_to=None, mode="prepayment", monthly_amount=D("1500.00"))
    L.activate_lease(db, None, main.id)
    subs = []
    for j, ru in enumerate(rus):
        t = M.create_party(db, None, {"kind": "person", "first_name": f"Mieter{j}", "last_name": f"Muster{j}"}, ["tenant"])
        rent = D(rng.randrange(40000, 130000)) / 100
        s = L.create_lease(db, None, kind="sub", lease_type_id=types["wohnraum_unbefristet"], start_date=start, end_date=None,
                           parties=[{"party_id": own.id, "role": "lessor"}, {"party_id": t.id, "role": "lessee"}], rentable_unit_ids=[ru.id])
        L.add_term(db, None, s.id, valid_from=start, valid_to=None, base_rent=rent)
        L.add_utility_agreement(db, None, s.id, valid_from=start, valid_to=None, mode="prepayment", monthly_amount=D("120.00"))
        L.activate_lease(db, None, s.id)
        subs.append((s, t))
    # Sollstellungen: ~90 % Forderungen auf Untermietverträge (je Vertrag fortlaufende Monate, jüngster Monat = nächster Monat -> künftig fällig), ~10 % Verbindlichkeiten (Hauptmiete)
    n_pay = max(1, n_charges // 10)
    n_rec = n_charges - n_pay
    created = datetime.now(timezone.utc)
    charges: list[tuple[Charge, str]] = []
    for i in range(n_rec):
        s, _t = subs[i % len(subs)]
        off = 1 - (i // len(subs))                       # 1 = nächster Monat, 0 = laufender Monat, negativ = Vergangenheit
        m0 = add_months(date(today.year, today.month, 1), off)
        due = m0.replace(day=3)
        amt = D(rng.randrange(50000, 150000)) / 100
        roll = rng.random()
        c = Charge(lease_id=s.id, direction="receivable", charge_type="base_rent", period_start=m0, period_end=add_months(m0, 1) - timedelta(days=1),
                   due_date=due, amount=amt, dedupe_key=f"bench:r:{i}", source="generated")
        if due > today:
            kind = "future"
        elif roll < 0.05:
            kind = "voided"
            c.voided_at, c.dedupe_key, c.void_reason = created, None, "Benchmark-Storno"
        elif roll < 0.55:
            kind = "paid"
        elif roll < 0.75:
            kind = "partial"
        else:
            kind = "unpaid"                              # überfällig (Fälligkeit in der Vergangenheit)
        charges.append((c, kind))
    for i in range(n_pay):
        off = 1 - i
        m0 = add_months(date(today.year, today.month, 1), off)
        due = m0.replace(day=3)
        kind = "future" if due > today else rng.choice(["paid", "paid", "partial", "unpaid"])
        charges.append((Charge(lease_id=main.id, direction="payable", charge_type="base_rent", period_start=m0, period_end=add_months(m0, 1) - timedelta(days=1),
                               due_date=due, amount=D(rng.randrange(800000, 950000)) / 100, dedupe_key=f"bench:p:{i}", source="generated"), kind))
    db.add_all([c for c, _ in charges])
    db.flush()
    for c, kind in charges:
        if kind not in ("paid", "partial"):
            continue
        direction = "in" if c.direction == "receivable" else "out"
        parts = [c.amount] if kind == "paid" else [q2(c.amount * D(rng.randrange(30, 70)) / 100)]
        if kind == "partial" and rng.random() < 0.4:   # zwei Teilzahlungen
            parts = [q2(parts[0] / 2), parts[0] - q2(parts[0] / 2)]
        for k, part in enumerate(parts):
            if part <= 0:
                continue
            p = Payment(direction=direction, booking_date=min(today, c.due_date + timedelta(days=rng.randrange(0, 12) + 5 * k)), amount=part, lease_id=c.lease_id,
                        method="bank_transfer", source="manual", reference=f"bench-{c.id}-{k}")
            db.add(p)
            db.flush()
            db.add(PaymentAllocation(payment_id=p.id, charge_id=c.id, amount=part))
    db.commit()
    counts = {
        "charges_total": db.scalar(select(func.count()).select_from(Charge)),
        "charges_voided": db.scalar(select(func.count()).select_from(Charge).where(Charge.voided_at.is_not(None))),
        "charges_receivable_active": db.scalar(select(func.count()).select_from(Charge).where(Charge.direction == "receivable", Charge.voided_at.is_(None))),
        "charges_payable_active": db.scalar(select(func.count()).select_from(Charge).where(Charge.direction == "payable", Charge.voided_at.is_(None))),
        "charges_due_future": db.scalar(select(func.count()).select_from(Charge).where(Charge.due_date > today, Charge.voided_at.is_(None))),
        "charges_due_le_today_active": db.scalar(select(func.count()).select_from(Charge).where(Charge.due_date <= today, Charge.voided_at.is_(None))),
        "payments": db.scalar(select(func.count()).select_from(Payment)),
        "payment_allocations": db.scalar(select(func.count()).select_from(PaymentAllocation)),
        "leases": db.scalar(select(func.count()).select_from(Lease)),
    }
    # aus Sicht von receivable_position (Referenz für „offen/überfällig“)
    pos = receivable_position(db, today)
    counts["receivable_overdue_count"] = pos["overdue_count"]
    counts["receivable_open_total"] = str(pos["open_total"])
    db_file = next(data_dir.rglob("*.db"), None) or next(data_dir.rglob("*.sqlite*"), None)
    db.close()
    return {"app": app, "counts": counts, "db_file": str(db_file) if db_file else None, "db_bytes": db_file.stat().st_size if db_file else None}


def q2(x: D) -> D:
    return x.quantize(D("0.01"))


# --- Messung ---------------------------------------------------------------------------------------------------------------------
class Recorder:
    def __init__(self, engine):
        self.engine, self.active = engine, False
        self.reset()
        event.listen(engine, "before_cursor_execute", self._before)
        event.listen(engine, "after_cursor_execute", self._after)

    def reset(self):
        self.count, self.stmts, self.sql_seconds = 0, {}, 0.0

    def _before(self, conn, cursor, statement, parameters, context, executemany):
        if self.active:
            context._bench_t0 = time.perf_counter()

    def _after(self, conn, cursor, statement, parameters, context, executemany):
        if not self.active:
            return
        dt = time.perf_counter() - context._bench_t0
        self.count += 1
        self.sql_seconds += dt
        key = re.sub(r"\s+", " ", statement).strip()
        e = self.stmts.setdefault(key, {"count": 0, "seconds": 0.0, "params": parameters})
        e["count"] += 1
        e["seconds"] += dt


def explain(engine, sql: str, params) -> list[str]:
    try:
        with engine.connect() as c:
            rows = c.exec_driver_sql("EXPLAIN QUERY PLAN " + sql, tuple(params) if not isinstance(params, dict) else params).fetchall()
        return [r[-1] for r in rows]
    except Exception as e:  # pragma: no cover - nur Diagnose
        return [f"EXPLAIN fehlgeschlagen: {type(e).__name__}: {e}"]


def classify(plan: list[str]) -> str:
    if any(re.match(r"SCAN (?!.*USING)", d) and "SUBQUERY" not in d and "CO-ROUTINE" not in d for d in plan):
        return "SCAN (kein Index)" if not any("USING" in d for d in plan) else "SCAN + Index gemischt"
    return "SEARCH/Index"


def make_paths(today: date):
    first, last = date(today.year, today.month, 1), date(today.year, today.month, 28)
    last = add_months(first, 1) - timedelta(days=1)
    return {
        "engine_portfolio": lambda db: economics.Engine(db, first, last).report("portfolio"),
        "engine_open_only": None,   # Sonderfall, siehe run_path
        "current_month_figures": lambda db: economics.current_month_figures(db, today),
        "build_dashboard": lambda db: dashboard.build_dashboard(db),
        "reminders_compute": lambda db: reminders.compute(db, today),
        "receivable_position": lambda db: receivable_position(db, today),
    }, first, last


def run_path(app, name, fn, today, first, last, repeat, recorder, with_profile):
    sf = app.state.session_factory

    def once(counting: bool, profile: cProfile.Profile | None = None):
        db = sf()
        try:
            if name == "engine_open_only":
                eng = economics.Engine(db, first, last, today)   # Aufbau gehört nicht zur Messung (enthält selbst _open-Aufrufe, siehe engine_portfolio)
                recorder.reset()
                recorder.active = counting
                t0 = time.perf_counter()
                if profile:
                    profile.enable()
                eng._open(eng.data_as_of)
                if profile:
                    profile.disable()
                dt = time.perf_counter() - t0
            else:
                recorder.reset()
                recorder.active = counting
                t0 = time.perf_counter()
                if profile:
                    profile.enable()
                fn(db)
                if profile:
                    profile.disable()
                dt = time.perf_counter() - t0
            recorder.active = False
            return dt
        finally:
            db.rollback()
            db.close()

    once(False)                      # Warmup (SQLite-/SQLAlchemy-Caches)
    wall_count = once(True)          # Zählläufe mit Listener (Laufzeit hier NICHT für die Tabelle verwendet)
    count, sql_s, stmts = recorder.count, recorder.sql_seconds, dict(recorder.stmts)
    times = [once(False) for _ in range(repeat)]
    res = {"statements": count, "runtime_ms": {"median": round(statistics.median(times) * 1000, 2), "min": round(min(times) * 1000, 2), "max": round(max(times) * 1000, 2)},
           "sql_time_ms_in_counting_run": round(sql_s * 1000, 2), "wall_ms_counting_run": round(wall_count * 1000, 2)}
    ordered_n = sorted(stmts.items(), key=lambda kv: -kv[1]["count"])
    ordered_t = sorted(stmts.items(), key=lambda kv: -kv[1]["seconds"])
    res["distinct_statements"] = len(stmts)
    res["top_statements_by_count"] = [{"count": v["count"], "total_ms": round(v["seconds"] * 1000, 3), "sql": k[:300]} for k, v in ordered_n[:5]]
    res["top_statements_by_time"] = [{"count": v["count"], "total_ms": round(v["seconds"] * 1000, 3), "sql": k[:300]} for k, v in ordered_t[:5]]
    chosen = {}
    for k, v in ordered_n[:3] + ordered_t[:3]:
        chosen[k] = v
    res["plans"] = []
    for k, v in chosen.items():
        plan = explain(app.state.session_factory().get_bind(), k, v["params"])
        res["plans"].append({"count": v["count"], "total_ms": round(v["seconds"] * 1000, 3), "sql": k[:300], "plan": plan, "verdict": classify(plan)})
    if with_profile:
        prof = cProfile.Profile()
        once(False, prof)
        buf = io.StringIO()
        st = pstats.Stats(prof, stream=buf)
        st.sort_stats("cumulative").print_stats(10)
        res["profile_top10_cumulative"] = buf.getvalue()
        total = st.total_tt
        fn_cum = {}
        for (fname, line, func_name), (cc, nc, tt, ct, callers) in st.stats.items():
            if func_name in ("_open", "open_amount", "allocated") and "leventum" in fname:
                fn_cum[f"{Path(fname).name}:{line}:{func_name}"] = {"calls": nc, "cumulative_ms": round(ct * 1000, 2)}
        res["profile_total_ms_with_profiler_overhead"] = round(total * 1000, 2)
        res["profile_selected_functions"] = fn_cum
    return res


def machine_info() -> dict:
    info = {"platform": platform.platform(), "python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version, "machine": platform.machine(), "cpu_count": None}
    try:
        import os
        info["cpu_count"] = os.cpu_count()
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                info["cpu_model"] = line.split(":", 1)[1].strip()
                break
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                info["mem_total_kb"] = int(line.split()[1])
                break
    except Exception:
        pass
    return info


def render(report: dict) -> str:
    out = [f"# bench_open_items – {report['generated']}", "", "Testbedingungen: " + json.dumps(report["machine"], ensure_ascii=False), ""]
    out.append("| Pfad | Forderungen | Statements | Median ms | Min ms | Max ms | SQL-Anteil (Zählllauf) |")
    out.append("|---|---:|---:|---:|---:|---:|---:|")
    for size, r in report["runs"].items():
        for name, p in r["paths"].items():
            share = f"{100 * p['sql_time_ms_in_counting_run'] / p['wall_ms_counting_run']:.0f} %" if p["wall_ms_counting_run"] else "-"
            out.append(f"| {name} | {size} | {p['statements']} | {p['runtime_ms']['median']} | {p['runtime_ms']['min']} | {p['runtime_ms']['max']} | {share} |")
    for size, r in report["runs"].items():
        out += ["", f"## Datenmenge {size}: {json.dumps(r['counts'])}"]
        for name, p in r["paths"].items():
            out += ["", f"### {name} ({p['statements']} Statements, {p['distinct_statements']} verschieden)"]
            for pl in p["plans"]:
                out.append(f"- [{pl['verdict']}] {pl['count']}x, {pl['total_ms']} ms: `{pl['sql'][:160]}`")
                for d in pl["plan"]:
                    out.append(f"    - {d}")
            if "profile_top10_cumulative" in p:
                out += ["", "```", p["profile_top10_cumulative"].rstrip(), "```", f"Auswahl: {json.dumps(p['profile_selected_functions'])}"]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--charges", type=int, nargs="+", default=[30, 100, 500], help="Anzahl Sollstellungen je Lauf")
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--json", default="-", help="Ausgabedatei für JSON (Standard/'-': stdout)")
    ap.add_argument("--workdir", default=None, help="Verzeichnis für temporäre DBs (Standard: System-Temp)")
    ap.add_argument("--profile-top", action="store_true", help="cProfile (Top 10 kumulativ) für die größte Datenmenge")
    ap.add_argument("--keep", action="store_true", help="Temporäre DBs behalten")
    a = ap.parse_args()
    today = date.today()
    report = {"generated": datetime.now().isoformat(timespec="seconds"), "machine": machine_info(), "today": str(today), "repeat": a.repeat, "runs": {}}
    base = Path(tempfile.mkdtemp(prefix="bench_open_items_", dir=a.workdir))
    try:
        for n in a.charges:
            w = build_world(base / f"n{n}", n, today)
            engine = w["app"].state.session_factory().get_bind()
            rec = Recorder(engine)
            paths, first, last = make_paths(today)
            run = {"counts": {**w["counts"], "db_bytes": w["db_bytes"]}, "paths": {}}
            for name, fn in paths.items():
                run["paths"][name] = run_path(w["app"], name, fn, today, first, last, a.repeat, rec, a.profile_top and n == max(a.charges))
                print(f"[{n}] {name}: {run['paths'][name]['statements']} Statements, Median {run['paths'][name]['runtime_ms']['median']} ms", file=sys.stderr)
            report["runs"][str(n)] = run
            engine.dispose()
    finally:
        if not a.keep:
            shutil.rmtree(base, ignore_errors=True)
    if a.json == "-":
        print(json.dumps(report, indent=1, ensure_ascii=False, default=str))
    else:
        Path(a.json).write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        print(render(report))


if __name__ == "__main__":
    main()
