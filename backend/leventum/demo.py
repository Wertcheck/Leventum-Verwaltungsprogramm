"""Demo-Starter: legt eine eigene, getrennte Demo-Datenbank mit ERFUNDENEN Beispieldaten an und startet den Server.

    python -m leventum.demo                # Demo-Daten anlegen (falls noch nicht vorhanden) und Server starten
    python -m leventum.demo --reset        # vorhandene Demo-Daten verwerfen und neu anlegen
    python -m leventum.demo --no-serve     # nur anlegen (Tests, Skripte)

Grundsätze:
- Alle Daten laufen über die normale REST-API (gleiche Validierung, gleiche Finanzregeln wie im Echtbetrieb); es gibt keine Direktschreibzugriffe.
- Die Demo nutzt ein EIGENES Datenverzeichnis (Standard: neben dem echten Datenverzeichnis, Name „leventum-demo“). Löschen (--reset) geschieht nur in Verzeichnissen,
  die die Markierungsdatei `.leventum-demo` enthalten – echte Daten werden nie angefasst.
- Die Oberfläche zeigt im Demo-Modus dauerhaft ein Banner „Demo-Modus“. Alle Personen, Adressen, IBANs sind erfunden.
- Alle Termine sind relativ zum heutigen Datum, damit Dashboard, Überfälligkeiten und Fristen jederzeit sinnvoll aussehen.
- Das Demo-Passwort wird zufällig erzeugt und beim Start ausgegeben (oder per --password gesetzt); es steht nicht im Quellcode."""
from __future__ import annotations

import argparse
import os
import secrets
import shutil
import socket
import sys
import threading
import time
import urllib.request
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

MARKER = ".leventum-demo"
MARKER_TEXT = "leventum-demo-v1: von python -m leventum.demo angelegt; enthält nur erfundene Demo-Daten.\n"
USERNAME = "demo"
# Diese Umgebungsvariablen würden die Demo auf echte Daten lenken; sie müssen für den Demo-Start ungesetzt sein (Abbruch statt stilles Überschreiben).
FORBIDDEN_ENV = ("LEVENTUM_DATABASE_URL", "LEVENTUM_DOCUMENTS_DIR", "LEVENTUM_BACKUP_DIR")


def default_demo_dir() -> Path:
    """Standard-Demoverzeichnis: neben dem echten Datenverzeichnis, nie darin."""
    from leventum.config import default_data_dir
    return default_data_dir().parent / "leventum-demo"


def _check_env() -> None:
    bad = [v for v in FORBIDDEN_ENV if os.environ.get(v)]
    if bad:
        sys.exit(f"Abbruch: {', '.join(bad)} ist gesetzt und würde die Demo auf echte Daten lenken. Variable(n) entfernen und erneut starten.")


def _check_target(data_dir: Path) -> None:
    """Lehnt Zielverzeichnisse ab, die echte Daten enthalten könnten (echtes Datenverzeichnis, Eltern davon, Home, Arbeitsordner, Wurzel)."""
    from leventum.config import Settings, default_data_dir
    target = data_dir.expanduser().resolve()
    if data_dir.is_symlink() or getattr(data_dir, "is_junction", lambda: False)():  # is_junction (NTFS) erst ab Python 3.12; unter 3.11 nicht erkennbar
        sys.exit(f"Abbruch: {data_dir} ist ein symbolischer Link bzw. eine Junction.")
    if target.exists() and not target.is_dir():
        sys.exit(f"Abbruch: {data_dir} ist kein Verzeichnis.")
    protected = {Path.home().resolve(), Path.cwd().resolve(), Path(target.anchor), default_data_dir().resolve(), Settings(_env_file=None).data_dir.resolve()}
    for p in protected:
        if target == p and (p / MARKER).is_file():
            continue  # eigenes, bereits markiertes Demo-Verzeichnis (z. B. LEVENTUM_DATA_DIR aus einem früheren Demo-Start im selben Prozess)
        if target == p or target in p.parents or (p == default_data_dir().resolve() and p in target.parents):
            sys.exit(f"Abbruch: {data_dir} ist (oder enthält/liegt in) {p} – das könnte echte Daten betreffen. Bitte ein eigenes Demo-Verzeichnis wählen.")


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))


def _first(d: date, back: int = 0) -> date:
    return _add_months(d.replace(day=1), -back)


def build_demo(data_dir: Path, password: str, today: date | None = None):
    """Legt die Demo-Daten im (leeren) Datenverzeichnis an und gibt (app, Zusammenfassung) zurück."""
    _check_env()
    if len(password) < 12:
        raise ValueError("Das Demo-Passwort muss mindestens 12 Zeichen haben.")
    os.environ["LEVENTUM_DATA_DIR"] = str(data_dir)
    os.environ["LEVENTUM_DEMO_MODE"] = "1"
    from leventum.config import Settings, get_settings
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from leventum.main import create_app

    today = today or date.today()
    app = create_app(Settings(_env_file=None, data_dir=data_dir, demo_mode=True))  # keine .env, keine Überschreibung durch Umgebung
    c = TestClient(app, headers={"X-Leventum-Client": "1"})

    def A(method: str, path: str, body=None):
        r = c.request(method, "/api/v1" + path, json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"Demo-Daten: {method} {path} -> {r.status_code} {r.text[:300]}")
        return r.json()

    A("POST", "/auth/setup", {"username": USERNAME, "password": password, "display_name": "Demo-Nutzer"})
    party = lambda kind, o, roles=(), **extra: A("POST", "/parties", {"kind": kind, **o, "roles": list(roles), **extra})  # noqa: E731
    own = party("company", {"company_name": "Leventum Real Estate GmbH"}, is_own_organization=True)
    o1 = party("person", {"first_name": "Helga", "last_name": "Brandt", "city": "Berlin"}, ["owner"], iban="DE02120300000000202051")
    o2 = party("company", {"company_name": "Lindenallee Immobilien GmbH", "city": "Potsdam"}, ["owner"])
    names = [("Max", "Mustermann", "DE89370400440532013000"), ("Sandra", "Klein", None), ("Bernd", "Hoffmann", None), ("Lisa", "Schneider", None),
             ("Thomas", "Keller", None), ("Anna", "Weber", None), ("Jonas", "Becker", None), ("Maria", "Kovac", None)]
    T = {l: party("person", {"first_name": f, "last_name": l, "email": f"{f.lower()}.{l.lower()}@example.org"}, ["tenant"], **({"iban": i} if i else {})) for f, l, i in names}
    supplier = party("company", {"company_name": "Sanitär Schmidt GmbH"}, ["service_provider"])
    types = {t["code"]: t["id"] for t in A("GET", "/lease-types")["items"]}

    pA = A("POST", "/properties", {"name": "Haus Bergmann", "property_type": "mehrfamilienhaus", "street": "Bergmannstraße 12", "postal_code": "10961", "city": "Berlin", "owner_party_id": o1["id"], "year_built": 1965, "heating_type": "Gas-Zentralheizung"})
    pB = A("POST", "/properties", {"name": "Lindenallee 5", "property_type": "mehrfamilienhaus", "street": "Lindenallee 5", "postal_code": "14469", "city": "Potsdam", "owner_party_id": o2["id"], "year_built": 1998})
    unit = lambda p, n, area, **x: A("POST", f"/properties/{p['id']}/units", {"unit_number": n, "living_area": area, **x})  # noqa: E731
    a1, a2, a3 = unit(pA, "WE 01", "78.50", floor="2", rooms_count=3), unit(pA, "WE 02", "55.00", floor="1", rooms_count=2), unit(pA, "WE 03", "92.00", floor="3", rooms_count=4)
    b1, b2 = unit(pB, "1", "62.00", floor="EG"), unit(pB, "2", "48.00", floor="1")
    rooms = {n: A("POST", f"/units/{a3['id']}/rooms", {"name": n, "area": ar}) for n, ar in [("Zimmer 1", "18.00"), ("Zimmer 2", "14.00"), ("Zimmer 3", "16.00")]}
    beds = {b: A("POST", f"/rooms/{rooms['Zimmer 1']['id']}/beds", {"label": b}) for b in ("Bett A", "Bett B")}
    RU = lambda **o: A("POST", "/rentable-units", o)  # noqa: E731
    ruAp, ruBp = RU(property_id=pA["id"]), RU(property_id=pB["id"])
    ru = {"a1": RU(property_id=pA["id"], unit_id=a1["id"]), "a2": RU(property_id=pA["id"], unit_id=a2["id"]), "b1": RU(property_id=pB["id"], unit_id=b1["id"]),
          "b2": RU(property_id=pB["id"], unit_id=b2["id"]),
          "r1a": RU(property_id=pA["id"], bed_id=beds["Bett A"]["id"]), "r1b": RU(property_id=pA["id"], bed_id=beds["Bett B"]["id"]), "r2": RU(property_id=pA["id"], room_id=rooms["Zimmer 2"]["id"])}
    # Zimmer 3 und WE 03 bleiben bewusst unvermietet bzw. nur teilbelegt -> sichtbarer Leerstand/Auslastung < 100 %

    def lease(kind, typ, start, rus, parties, rent, mode, nk, **extra):
        l = A("POST", "/leases", {"kind": kind, "lease_type_id": types[typ], "start_date": start.isoformat(), "parties": parties, "rentable_unit_ids": rus, **extra})
        A("POST", f"/leases/{l['id']}/terms", {"valid_from": start.isoformat(), "base_rent": rent})
        A("POST", f"/leases/{l['id']}/utility-agreements", {"valid_from": start.isoformat(), "mode": mode, "monthly_amount": nk or None})
        A("POST", f"/leases/{l['id']}/activate")
        return l

    s0 = _first(today, 11)
    m1 = lease("main", "hauptmiete", s0, [ruAp["id"]], [{"party_id": o1["id"], "role": "lessor"}, {"party_id": own["id"], "role": "lessee"}], "3100.00", "prepayment", "780.00", subletting_permitted=True, notice_period_months=3)
    m2 = lease("main", "hauptmiete", s0, [ruBp["id"]], [{"party_id": o2["id"], "role": "lessor"}, {"party_id": own["id"], "role": "lessee"}], "1450.00", "prepayment", "340.00", subletting_permitted=True)

    def sub(typ, start, rus, tenant, rent, mode, nk, **extra):
        return lease("sub", typ, start, rus, [{"party_id": own["id"], "role": "lessor"}, {"party_id": T[tenant]["id"], "role": "lessee"}], rent, mode, nk, **extra)

    s = {}
    s["mm"] = sub("wohnraum_unbefristet", _first(today, 9), [ru["a1"]["id"]], "Mustermann", "1120.00", "prepayment", "280.00", contract_number="DEMO-001")
    s["kl"] = sub("wohnraum_unbefristet", _first(today, 9), [ru["a2"]["id"]], "Klein", "890.00", "prepayment", "210.00")
    s["we"] = sub("bett", _first(today, 8), [ru["r1a"]["id"]], "Weber", "420.00", "flat_rate", "60.00")
    s["be"] = sub("bett", _first(today, 8), [ru["r1b"]["id"]], "Becker", "420.00", "flat_rate", "60.00")
    s["ko"] = sub("zimmer", _first(today, 7), [ru["r2"]["id"]], "Kovac", "560.00", "flat_rate", "70.00")
    s["ho"] = sub("wohnraum_unbefristet", _first(today, 9), [ru["b1"]["id"]], "Hoffmann", "1060.00", "prepayment", "250.00")
    end_ke = _first(today, -2).replace(day=1) - timedelta(days=1)  # Ende des nächsten Monats -> je nach Datum in ca. 11–60 Tagen
    s["ke"] = sub("wohnraum_befristet", _first(today, 9), [ru["b2"]["id"]], "Keller", "900.00", "prepayment", "200.00", end_date=end_ke.isoformat(), is_fixed_term=True,
                  fixed_term_reason="Demo: befristet wegen Eigenbedarf des Eigentümers", notice_period_months=2)
    A("POST", f"/leases/{s['ke']['id']}/terminate", {"terminated_on": (today - timedelta(days=15)).isoformat(), "effective_on": end_ke.isoformat()})

    A("POST", "/charges/generate", {"from_month": s0.isoformat(), "through_month": _first(today).isoformat(), "allow_backdated": True})
    charges = [x for x in A("GET", "/charges")["items"] if not x.get("voided_at")]
    prev, cur = _first(today, 1), _first(today)
    n_pay = 0
    for ch in sorted(charges, key=lambda x: x["due_date"]):
        due = date.fromisoformat(ch["due_date"])
        if due > today:
            continue
        lid = ch["lease_id"]
        if (lid == s["kl"]["id"] and due >= prev) or (lid == s["ho"]["id"] and due >= cur) or (lid == s["ke"]["id"] and due >= cur):
            continue  # unbezahlt -> Rückstände/Überfälligkeit im Dashboard
        out = ch["direction"] == "payable"
        amount = "800.00" if (lid == s["ho"]["id"] and due == prev and ch["charge_type"] == "base_rent") else ch["amount"]  # eine Teilzahlung
        A("POST", "/payments", {"direction": "out" if out else "in", "booking_date": ch["due_date"], "amount": amount, "reference": f"DEMO {ch['period_start'][:7]} {ch['charge_type']}",
                                "accept_possible_duplicate": True, "allocations": [{"charge_id": ch["id"], "amount": amount}]})
        n_pay += 1

    for lid, amt, paid in [(s["mm"]["id"], "2800.00", "2800.00"), (s["kl"]["id"], "1780.00", "1780.00"), (s["ho"]["id"], "2120.00", "1000.00")]:
        d = A("POST", "/deposits", {"lease_id": lid, "agreed_amount": amt, "due_date": _first(today, 9).isoformat()})
        A("POST", f"/deposits/{d['id']}/transactions", {"kind": "paid", "amount": paid, "transaction_date": (_first(today, 9) + timedelta(days=2)).isoformat()})
    dm = A("POST", "/deposits", {"lease_id": m1["id"], "agreed_amount": "9300.00", "due_date": s0.isoformat()})
    A("POST", f"/deposits/{dm['id']}/transactions", {"kind": "paid", "amount": "9300.00", "transaction_date": (s0 + timedelta(days=1)).isoformat()})

    inv = A("POST", "/invoices", {"property_id": pA["id"], "unit_id": a1["id"], "supplier_party_id": supplier["id"], "invoice_number": "DEMO-SAN-114", "amount": "476.00",
                                  "invoice_date": (today - timedelta(days=20)).isoformat(), "description": "Heizungswartung WE 01"})
    rep = A("POST", "/repairs", {"property_id": pA["id"], "unit_id": a1["id"], "lease_id": s["mm"]["id"], "title": "Heizung in WE 01 bleibt kalt", "category": "heizung", "priority": "urgent",
                                 "reported_on": (today - timedelta(days=9)).isoformat(), "cost_estimate": "400.00", "scheduled_for": (today + timedelta(days=5)).isoformat(), "contractor_party_id": supplier["id"]})
    A("POST", f"/repairs/{rep['id']}/invoices", {"invoice_id": inv["id"]})
    A("POST", f"/repairs/{rep['id']}/status", {"status": "scheduled"})
    A("POST", f"/repairs/{rep['id']}/notes", {"text": "Termin mit Sanitär Schmidt vereinbart."})
    A("POST", "/repairs", {"property_id": pB["id"], "title": "Wasserhahn tropft (Küche)", "category": "sanitaer", "priority": "normal", "reported_on": (today - timedelta(days=4)).isoformat()})

    for title, prio, d, extra in [("Nachmieter für Wohnung Keller suchen", "high", today + timedelta(days=20), {"lease_id": s["ke"]["id"]}),
                                  ("Rauchmelder in Haus Bergmann prüfen lassen", "normal", today + timedelta(days=35), {"property_id": pA["id"]}),
                                  ("Mahnung Klein vorbereiten", "high", today - timedelta(days=3), {"lease_id": s["kl"]["id"]}),
                                  ("Versicherungsnachweis Lindenallee anfordern", "low", None, {"property_id": pB["id"]})]:
        A("POST", "/tasks", {"title": title, "priority": prio, "due_date": d.isoformat() if d else None, **extra})
    A("POST", "/communications", {"channel": "email", "direction": "in", "subject": "Heizung ist seit Tagen kalt", "body": "Herr Mustermann meldet, dass die Heizung im Wohnzimmer nicht warm wird.",
                                  "party_id": T["Mustermann"]["id"], "lease_id": s["mm"]["id"], "repair_id": rep["id"]})
    A("POST", "/communications", {"channel": "phone", "direction": "out", "subject": "Rückruf wegen Mietrückstand", "party_id": T["Klein"]["id"], "lease_id": s["kl"]["id"]})
    A("POST", "/handover-protocols", {"lease_id": s["mm"]["id"], "kind": "move_in", "protocol_date": _first(today, 9).isoformat(), "keys_handed": 3, "condition_notes": "Wände weiß, Parkett ohne Mängel.", "signed": True})

    acc = A("POST", "/bank/accounts", {"name": "Geschäftskonto Leventum (Demo)", "iban": "DE12 5001 0517 5407 3249 31"})
    de = lambda d: d.strftime("%d.%m.%Y")  # noqa: E731
    csv = "\n".join(["Buchungstag;Valuta;Name Zahlungsbeteiligter;IBAN Zahlungsbeteiligter;Verwendungszweck;Betrag;Währung",
                     f"{de(cur)};{de(cur)};Max Mustermann;DE89 3704 0044 0532 0130 00;Miete DEMO-001;1.400,00;EUR",
                     f"{de(cur)};{de(cur)};Stadtwerke Potsdam;;Abschlag Allgemeinstrom;-84,00;EUR",
                     f"{de(cur)};{de(cur)};Unbekannt;DE44500105175407324931;Spende Sommerfest;25,00;EUR"])
    r = c.post("/api/v1/bank/imports", files={"file": ("Kontoauszug-Demo.csv", csv.encode(), "text/csv")}, data={"account_id": str(acc["id"])})
    if r.status_code >= 400:
        raise RuntimeError(f"Demo-Daten: Bankimport -> {r.status_code} {r.text[:200]}")
    for name, et, eid, dt in [("Mietvertrag Mustermann (Demo).pdf", "lease", s["mm"]["id"], "mietvertrag"), ("Mietvertrag Klein (Demo).pdf", "lease", s["kl"]["id"], "mietvertrag"),
                              ("Hauptmietvertrag Haus Bergmann (Demo).pdf", "lease", m1["id"], "mietvertrag"), ("Rechnung DEMO-SAN-114.pdf", "invoice", inv["id"], "rechnung")]:
        r = c.post("/api/v1/documents", files={"file": (name, b"%PDF-1.4 Demo-Beispiel, erfundener Inhalt", "application/pdf")}, data={"entity_type": et, "entity_id": str(eid), "doc_type": dt})
        if r.status_code >= 400:
            raise RuntimeError(f"Demo-Daten: Dokument {name} -> {r.status_code} {r.text[:200]}")
    A("POST", "/dunning/prepare", {})
    dash = A("GET", "/dashboard")
    k = {x["key"]: x["value"] for x in dash["kpis"]}
    return app, {"properties": k["properties"], "units": k["units"], "active_subleases": k["active_subleases"], "payments": n_pay, "occupancy_rate": k.get("occupancy_rate"),
                 "open_receivables": k["open_receivables"]}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Leventum mit erfundenen Demo-Daten starten")
    ap.add_argument("--data-dir", type=Path, default=None, help="Demo-Datenverzeichnis (Standard: neben dem echten Datenverzeichnis, Name leventum-demo)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--password", default=None, help="Demo-Passwort (Standard: zufällig, mind. 12 Zeichen)")
    ap.add_argument("--reset", action="store_true", help="vorhandene Demo-Daten verwerfen (nur Verzeichnisse mit Markierung .leventum-demo)")
    ap.add_argument("--no-serve", action="store_true", help="nur Daten anlegen, Server nicht starten")
    ap.add_argument("--open", action="store_true", help="Browser öffnen")
    args = ap.parse_args(argv)
    _check_env()
    if args.password is not None and len(args.password) < 12:
        sys.exit("Abbruch: Das Demo-Passwort muss mindestens 12 Zeichen haben.")
    data_dir = args.data_dir or default_demo_dir()
    _check_target(data_dir)
    if data_dir.exists() and any(data_dir.iterdir()):
        marker = data_dir / MARKER
        if not marker.is_file() or not marker.read_text(encoding="utf-8", errors="replace").startswith("leventum-demo-v1"):
            sys.exit(f"Abbruch: {data_dir} ist kein Demo-Verzeichnis (Markierung {MARKER} fehlt). Es wird nichts verändert.")
        if not args.reset:
            sys.exit(f"Demo-Daten existieren bereits in {data_dir}. Mit --reset neu anlegen, oder die Demo über LEVENTUM_DATA_DIR={data_dir} LEVENTUM_DEMO_MODE=1 "
                     "python -m leventum.desktop --browser starten (Passwort siehe erste Ausgabe).")
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / MARKER).write_text(MARKER_TEXT, encoding="utf-8")
    password = args.password or secrets.token_urlsafe(12)
    try:
        app, summary = build_demo(data_dir, password)
    except BaseException:
        shutil.rmtree(data_dir, ignore_errors=True)  # eigenes, gerade angelegtes Demo-Verzeichnis (Markierung gesetzt) – kein halbfertiger Bestand
        raise
    print(f"Demo-Daten angelegt in {data_dir}: {summary}", flush=True)
    if args.no_serve:
        return
    import uvicorn

    port = args.port
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{port}/"
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "api/v1/health", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    print(f"\nLeventum-Demo läuft auf {url}\n  Benutzer: {USERNAME}\n  Passwort: {password}\n(Strg+C beendet; alle Daten sind erfunden)", flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(url)
    try:
        t.join()
    except KeyboardInterrupt:
        server.should_exit = True


if __name__ == "__main__":
    main()
