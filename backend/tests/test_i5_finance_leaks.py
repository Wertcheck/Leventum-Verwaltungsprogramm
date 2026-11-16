"""Phase I5: Finanzdaten-Lecks für Rollen OHNE finance:read (Soll-Verhalten laut Entscheidungen des Orchestrators; Tests entstehen VOR der Implementierung).

Rollen (security/permissions.py): admin(*), buchhaltung und lesend HABEN finance:read; verwaltung und objektbetreuung NICHT.
Gruppen: B1 Erinnerung->Aufgabe betragsfrei · B2 Reparaturkosten · B3 Kaution im Vertrag · B4 Historie/Mieterakte · B5 IBAN maskiert ·
B6 Dokumente mit Finanztyp · K Klassifikationen + Route-Scan über alle GET-Routen · H HTTP-Randfälle.

Entscheidungen (bewusst, Eigentümerbestätigung offen, jeweils nur festgehalten):
* cost_estimate (geplante Schätzung) bleibt für repair:read sichtbar; birth_date bleibt sichtbar.
* Vertragskonditionen (terms, monthly_total, utility_agreements) bleiben Stammdaten (master:read). Die Marker unten sind so gewählt, dass die
  Konditionen sie NICHT tragen (Untermiete 1150,00, ohne NK; Hauptmiete 850,00 + NK 180,00): der Route-Scan braucht daher keine Ausnahme.

Testwelt (erfundene Daten, zeitstabil relativ zu date.today(), EIN gemeinsames Modul-Szenario):
* Untermietvertrag Zimmer 1 (Miete 1150,00, ohne NK, Lease.deposit_amount 2300,00) mit EINER überfälligen Forderung 600,00 (fällig vor 20 Tagen),
  einer vollständig bezahlten Forderung 100,00 (Zahlung 100,00, Referenz MARKER-ZAHLUNG), überfälliger Kaution 2300,00 (fällig vor 10 Tagen),
  Mahnentwurf, Reparatur (Schätzung 300,00) mit verknüpfter Rechnung 476,00, Mieter-IBAN DE89370400440532013000, Dokumente aller Finanztypen.
* Hauptmietvertrag (ab 2025-01-01, NK-Vorauszahlung) -> Hinweis utility_statement_due (Vorjahr ohne Abrechnung).
Marker (600.00/600,00, 2300.00/2.300,00, 476.00/476,00, volle IBAN, MARKER-ZAHLUNG) kommen im Szenario sonst nirgends vor.

Schnittstellenannahmen (neu, vom Backend zu liefern): security.finance_access.NON_FINANCE_KPI_KEYS, NON_FINANCE_REMINDER_TYPES (frozensets);
GET /history akzeptiert entity_type=dunning_notice (mit Recht 200); Reparatur-/Vertragsantworten lassen 'costs' bzw. 'deposit_amount' ohne Recht weg."""
import re
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from leventum.config import Settings
from leventum.main import create_app
from leventum.security import finance_access as FA
from leventum.services import charges as C, dashboard as DASH, payments as P, reminders as REM
from tests.helpers import World
from tests.test_e_api import role_client

V = "/api/v1"
PW = "ein-langes-passwort-123"
HDR = {"X-Leventum-Client": "1"}
TODAY = date.today()
NO_FIN_ROLES = ["verwaltung", "objektbetreuung"]
FIN_ROLES = ["buchhaltung", "lesend", "admin"]
FIN_TYPES = {"overdue_payment", "deposit_overdue", "utility_statement_due"}
FIN_DOC_TYPES = ("rechnung", "betriebskostenabrechnung", "kaution")
IBAN = "DE89370400440532013000"
BIRTH = "1980-05-17"
MARKERS = ("600.00", "2300.00", "476.00", "600,00", "2.300,00", "476,00", IBAN, "MARKER-ZAHLUNG")
# Betragsmuster ohne Datumstreffer: das wörtliche Muster \d+[.,]\d{2} träfe auch Daten wie 27.10.2026 ("27.10"); Daten sind erlaubt.
AMOUNT = re.compile(r"(?<![\d.,])\d{1,3}(?:\.\d{3})*,\d{2}(?![\d,])|(?<![\d.,])\d+\.\d{2}(?![\d.,])")


def d(n):
    return TODAY + timedelta(days=n)


def leaks(text):
    """Gefundene Marker im Antworttext (IBAN auch mit Leerzeichen-Gruppierung)."""
    flat = text.replace(" ", "")
    return [m for m in MARKERS if m in text or (m == IBAN and m in flat)]


def has_amount(text):
    return bool(AMOUNT.search(text)) or "€" in text


def walk_keys(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from walk_keys(v)
    elif isinstance(o, list):
        for x in o:
            yield from walk_keys(x)


def find_values(o, key):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key:
                yield v
            yield from find_values(v, key)
    elif isinstance(o, list):
        for x in o:
            yield from find_values(x, key)


def must(r, *codes):
    assert r.status_code in codes, f"{r.request.method} {r.request.url}: {r.status_code} {r.text[:300]}"
    return r.json()


def upload(c, entity, eid, doc_type, name=None):
    data = b"%PDF-1.4 dummy " + doc_type.encode()
    r = c.post(V + "/documents", data={"entity_type": entity, "entity_id": eid, "doc_type": doc_type},
               files={"file": (name or f"{doc_type}-{entity}.pdf", data, "application/pdf")})
    return r, data


# ---------------------------------------------------------------------------------------------------------------------------------
# Szenario (einmal je Modul)
# ---------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def mapp(tmp_path_factory):
    base = tmp_path_factory.mktemp("i5")
    return create_app(Settings(data_dir=base / "data", frontend_dist=base / "nodist"))


@pytest.fixture(scope="module")
def scene(mapp):
    with TestClient(mapp, headers=HDR) as admin:
        must(admin.post(V + "/auth/setup", json={"username": "admin", "password": PW, "display_name": "Admin"}), 200)
        w = World(mapp)
        main = w.activate_main()
        tenant, tenant2 = w.tenant("Zahl Mieter"), w.tenant("Zweit Mieter")
        sub = w.sub([w.ru_room(w.room1)], [tenant], d(-400), None, nk_mode=None, deposit_amount=D("2300.00"))
        w.db.commit()
        C.create_manual_charge(w.db, None, lease_id=sub.id, amount=D("600.00"), due_date=d(-20), period_start=d(-20), period_end=d(9), note="Testforderung")
        c100 = C.create_manual_charge(w.db, None, lease_id=sub.id, amount=D("100.00"), due_date=d(-5), period_start=d(-5), period_end=d(24), note="Testforderung klein")
        w.db.commit()
        P.create_payment(w.db, None, direction="in", booking_date=d(-4), amount=D("100.00"), lease_id=sub.id, counterparty_party_id=tenant.id,
                         reference="MARKER-ZAHLUNG", allocations=[{"charge_id": c100.id, "amount": D("100.00")}])
        w.db.commit()
        ids = dict(own=w.own.id, owner=w.owner.id, prop=w.prop.id, we1=w.we1.id, we2=w.we2.id, room1=w.room1.id, room2=w.room2.id, tenant=tenant.id,
                   tenant2=tenant2.id, main=main.id, sub=sub.id, lt=w.t["wohnraum_unbefristet"])
        w.db.close()

        dep = must(admin.post(V + "/deposits", json={"lease_id": ids["sub"], "agreed_amount": "2300.00", "due_date": d(-10).isoformat()}), 201)
        must(admin.patch(V + f"/parties/{ids['tenant']}", json={"iban": IBAN, "birth_date": BIRTH}), 200)
        rep = must(admin.post(V + "/repairs", json={"property_id": ids["prop"], "title": "Heizung Test", "reported_on": d(-3).isoformat(), "unit_id": ids["we1"],
                                                    "lease_id": ids["sub"], "category": "heizung", "cost_estimate": "300.00"}), 201)
        inv = must(admin.post(V + "/invoices", json={"property_id": ids["prop"], "amount": "476.00", "invoice_date": d(-2).isoformat(), "invoice_number": "RE-T-1",
                                                     "unit_id": ids["we1"]}), 201)
        must(admin.post(V + f"/repairs/{rep['id']}/invoices", json={"invoice_id": inv["id"]}), 200)
        notices = must(admin.post(V + "/dunning/prepare", json={}), 200)["created"]
        assert notices, "Szenario: Mahnentwurf erwartet"

        docs = []
        for entity, eid, types in (("lease", ids["sub"], ("rechnung", "betriebskostenabrechnung", "kaution", "mietvertrag", "sonstige")),
                                   ("party", ids["tenant"], ("kaution", "sonstige")), ("repair", rep["id"], ("rechnung", "reparaturbeleg"))):
            for t in types:
                r, data = upload(admin, entity, eid, t)
                j = must(r, 201)
                docs.append({"id": j["id"], "type": t, "entity": entity, "entity_id": eid, "bytes": data})

        items = must(admin.get(V + "/reminders"), 200)["items"]
        task_resp = {}
        for typ in sorted(FIN_TYPES):
            key = next(i["key"] for i in items if i["type"] == typ)
            task_resp[typ] = must(admin.post(V + "/reminders/task", json={"key": key}), 201)

        clients = {"admin": admin}
        for role in NO_FIN_ROLES + ["buchhaltung", "lesend"]:
            clients[role] = role_client(mapp, role, f"u_{role}")
        yield {**ids, "app": mapp, "c": clients, "admin": admin, "repair": rep["id"], "invoice": inv["id"], "deposit": dep["id"], "notice": notices[0]["id"],
               "task_resp": task_resp, "task_ids": {t: j["id"] for t, j in task_resp.items()}, "docs": docs,
               "fin_doc_id": next(x["id"] for x in docs if x["type"] in FIN_DOC_TYPES), "other_doc_id": next(x["id"] for x in docs if x["type"] == "mietvertrag")}


def fin_docs(s):
    return [x for x in s["docs"] if x["type"] in FIN_DOC_TYPES]


def other_docs(s):
    return [x for x in s["docs"] if x["type"] not in FIN_DOC_TYPES]


# ---------------------------------------------------------------------------------------------------------------------------------
# B1 Erinnerung -> Aufgabe: betragsfrei
# ---------------------------------------------------------------------------------------------------------------------------------
def test_b1_reminder_tasks_for_finance_types_are_amount_free(scene):
    """Aufgaben aus overdue_payment/deposit_overdue/utility_statement_due: Titel+Beschreibung ohne Betragsmuster und ohne '€' (Beispiel: 'Überfällige Zahlung – <Vertragstitel>')."""
    expected_lease = {"overdue_payment": scene["sub"], "deposit_overdue": scene["sub"], "utility_statement_due": scene["main"]}
    for typ, t in scene["task_resp"].items():
        text = f"{t['title']} || {t.get('description') or ''}"
        assert not has_amount(text), f"{typ}: Betrag in Titel/Beschreibung: {text}"
        assert leaks(text) == [], f"{typ}: {text}"
        assert t["title"].strip() and t["source"] == "reminder" and t["dedupe_key"], typ
        assert t["lease_id"] == expected_lease[typ], f"{typ}: Verknüpfung zum Vertrag muss erhalten bleiben"
    stored = {t["id"]: t for t in scene["admin"].get(V + "/tasks").json()["items"]}
    for typ, tid in scene["task_ids"].items():
        assert tid in stored and not has_amount(stored[tid]["title"] + " " + (stored[tid]["description"] or "")), typ  # auch gespeichert, nicht nur in der Antwort


BODY_SURFACES = ["tasks", "tasks-open", "task-overdue", "task-deposit", "task-utility", "dashboard", "history-party-tenant", "history-party-tenant-limit500",
                 "history-party-owner", "history-lease-sub", "history-lease-sub-limit500", "history-lease-main", "history-property", "history-unit", "history-repair",
                 "history-task-overdue", "history-task-deposit", "history-task-utility", "party-detail", "tenant-overview"]


def surface_path(s, name):
    t = s["task_ids"]
    h = lambda et, i, extra="": f"/history?entity_type={et}&entity_id={i}{extra}"
    return {"tasks": "/tasks", "tasks-open": "/tasks?open_only=true", "task-overdue": f"/tasks/{t['overdue_payment']}", "task-deposit": f"/tasks/{t['deposit_overdue']}",
            "task-utility": f"/tasks/{t['utility_statement_due']}", "dashboard": "/dashboard",
            "history-party-tenant": h("party", s["tenant"]), "history-party-tenant-limit500": h("party", s["tenant"], "&limit=500"), "history-party-owner": h("party", s["owner"]),
            "history-lease-sub": h("lease", s["sub"]), "history-lease-sub-limit500": h("lease", s["sub"], "&limit=500"), "history-lease-main": h("lease", s["main"]),
            "history-property": h("property", s["prop"]), "history-unit": h("unit", s["we1"]), "history-repair": h("repair", s["repair"]),
            "history-task-overdue": h("task", t["overdue_payment"]), "history-task-deposit": h("task", t["deposit_overdue"]), "history-task-utility": h("task", t["utility_statement_due"]),
            "party-detail": f"/parties/{s['tenant']}", "tenant-overview": f"/tenants/{s['tenant']}/overview"}[name]


@pytest.mark.parametrize("role", NO_FIN_ROLES)
@pytest.mark.parametrize("surface", BODY_SURFACES)
def test_b1_no_finance_markers_in_task_and_history_surfaces_without_finance_read(scene, role, surface):
    r = scene["c"][role].get(V + surface_path(scene, surface))
    assert r.status_code == 200, r.text
    assert leaks(r.text) == [], f"{role} {surface}: Finanzwert im Body: {leaks(r.text)}"


@pytest.mark.parametrize("role", NO_FIN_ROLES)
def test_b1_finance_reminder_tasks_are_visible_but_amount_free_without_finance_read(scene, role):
    """Kontrolle gegen leeres Bestehen: die drei Aufgaben sind sichtbar (task:read), nur betragsfrei."""
    items = {t["id"]: t for t in scene["c"][role].get(V + "/tasks").json()["items"]}
    for typ, tid in scene["task_ids"].items():
        assert tid in items, f"{role}: Aufgabe {typ} fehlt"
        assert not has_amount(items[tid]["title"] + " " + (items[tid]["description"] or "")), typ


@pytest.mark.parametrize("role", ["admin", *NO_FIN_ROLES])
def test_b1_audit_summary_task_created_has_no_amount(scene, role):
    """Audit-Zusammenfassung 'Aufgabe erstellt: …' trägt keinen Betrag (gespeicherter Text, daher auch für admin)."""
    for typ, tid in scene["task_ids"].items():
        items = scene["c"][role].get(V + f"/history?entity_type=task&entity_id={tid}").json()["items"]
        created = [i for i in items if i["action"] == "task.created"]
        assert len(created) == 1 and created[0]["summary"].startswith("Aufgabe erstellt:"), f"{typ}: {items}"
        assert not has_amount(created[0]["summary"]) and leaks(created[0]["summary"]) == [], created[0]["summary"]


# ---------------------------------------------------------------------------------------------------------------------------------
# B2 Reparaturen
# ---------------------------------------------------------------------------------------------------------------------------------
COST_KEYS = {"costs", "actual", "paid", "open", "invoice_ids", "deviation", "deviation_from_estimate"}


def _repair_from_list(body, rid):
    return next(x for x in body["items"] if x["id"] == rid)


@pytest.mark.parametrize("role", NO_FIN_ROLES)
def test_b2_repair_list_and_detail_have_no_cost_block_without_finance_read(scene, role):
    c, rid = scene["c"][role], scene["repair"]
    lst = c.get(V + "/repairs")
    det = c.get(V + f"/repairs/{rid}")
    assert lst.status_code == 200 and det.status_code == 200
    item = _repair_from_list(lst.json(), rid)
    for name, body, text in (("list", item, lst.text), ("detail", det.json(), det.text)):
        assert "costs" not in body, f"{name}: Block costs darf ohne finance:read nicht vorhanden sein"
        assert COST_KEYS.isdisjoint(set(walk_keys(body))), f"{name}: Kostenschlüssel {COST_KEYS & set(walk_keys(body))}"
        assert leaks(text) == [], f"{name}: {leaks(text)}"
        assert body["cost_estimate"] == "300.00", f"{name}: geplante Schätzung bleibt für repair:read sichtbar (Entscheidung)"


@pytest.mark.parametrize("role", NO_FIN_ROLES)
def test_b2_repair_events_and_history_carry_no_invoice_amount_without_finance_read(scene, role):
    """Ereignisse, die einen Rechnungsbetrag nennen, werden ausgelassen oder betragsfrei geliefert (Detail, History repair, Mieterakte)."""
    c, rid = scene["c"][role], scene["repair"]
    ev = c.get(V + f"/repairs/{rid}").json()["events"]
    assert any(e["kind"] == "reported" for e in ev), "Nicht-Finanz-Ereignisse bleiben"
    for e in ev:
        if e["kind"] == "invoice":
            assert not has_amount(e["text"]), e["text"]
    hist = c.get(V + f"/history?entity_type=repair&entity_id={rid}")
    assert hist.status_code == 200 and any(i["action"] == "repair.reported" for i in hist.json()["items"])
    for i in hist.json()["items"]:
        if i["action"] == "repair.invoice":
            assert not has_amount(i["summary"]), i["summary"]
    assert leaks(hist.text) == []
    for path in (f"/history?entity_type=party&entity_id={scene['tenant']}", f"/tenants/{scene['tenant']}/overview"):
        r = c.get(V + path)
        assert r.status_code == 200 and leaks(r.text) == [] and "476" not in r.text, path


@pytest.mark.parametrize("role", NO_FIN_ROLES)
def test_b2_repair_write_responses_have_no_cost_block_without_finance_read(scene, role):
    """Antworten der Reparatur-Schreibrouten liefern ebenfalls repair_out(full): ohne Recht kein costs-Block, keine Beträge."""
    c, rid = scene["c"][role], scene["repair"]
    note = c.post(V + f"/repairs/{rid}/notes", json={"text": f"Notiz {role}"})
    patch = c.patch(V + f"/repairs/{rid}", json={"description": f"Beschreibung {role}"})
    created = c.post(V + "/repairs", json={"property_id": scene["prop"], "title": f"Neu {role}", "reported_on": TODAY.isoformat()})
    for name, r, code in (("notes", note, 201), ("patch", patch, 200), ("create", created, 201)):
        assert r.status_code == code, f"{name}: {r.status_code} {r.text}"
        assert "costs" not in r.json() and COST_KEYS.isdisjoint(set(walk_keys(r.json()))), name
        assert leaks(r.text) == [], name


@pytest.mark.parametrize("role", ["admin", "lesend"])
def test_b2_with_finance_read_costs_and_invoice_event_are_complete(scene, role):
    c, rid = scene["c"][role], scene["repair"]
    for body in (_repair_from_list(c.get(V + "/repairs").json(), rid), c.get(V + f"/repairs/{rid}").json()):
        costs = body["costs"]
        assert costs["estimate"] == "300.00" and costs["actual"] == "476.00" and costs["paid"] == "0.00" and costs["open"] == "476.00"
        assert costs["invoice_ids"] == [scene["invoice"]] and costs["deviation_from_estimate"] == "176.00"
    ev = c.get(V + f"/repairs/{rid}").json()["events"]
    assert any(e["kind"] == "invoice" and "476,00" in e["text"] for e in ev)
    hist = c.get(V + f"/history?entity_type=repair&entity_id={rid}").json()["items"]
    assert any(i["action"] == "repair.invoice" and "476,00" in i["summary"] for i in hist)


# ---------------------------------------------------------------------------------------------------------------------------------
# B3 Kaution im Vertrag
# ---------------------------------------------------------------------------------------------------------------------------------
def no_deposit(body):
    return body.get("deposit_amount") is None


@pytest.mark.parametrize("role", NO_FIN_ROLES)
@pytest.mark.parametrize("which", ["sub", "main"])
def test_b3_lease_detail_has_no_deposit_amount_without_finance_read(scene, role, which):
    r = scene["c"][role].get(V + f"/leases/{scene[which]}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert no_deposit(body), f"deposit_amount sichtbar: {body.get('deposit_amount')}"
    assert leaks(r.text) == []
    # ENTSCHEIDUNG (Eigentümerbestätigung offen): Vertragskonditionen bleiben Stammdaten (master:read).
    assert body["terms"] and body["monthly_total"] is not None and "utility_agreements" in body
    if which == "sub":
        assert [t["base_rent"] for t in body["terms"]] == ["1150.00"] and body["monthly_total"]["total"] == "1150.00"


@pytest.mark.parametrize("role", FIN_ROLES)
def test_b3_lease_detail_keeps_deposit_amount_with_finance_read(scene, role):
    body = scene["c"][role].get(V + f"/leases/{scene['sub']}").json()
    assert body["deposit_amount"] == "2300.00"


def test_b3_lease_action_responses_have_no_deposit_amount_without_finance_read(scene):
    """create/activate/terminate/cancel/legal-review/PATCH liefern lease_detail: ohne finance:read kein deposit_amount (nur verwaltung hat master:write)."""
    admin, v = scene["admin"], scene["c"]["verwaltung"]
    ru_room = must(admin.post(V + "/rentable-units", json={"property_id": scene["prop"], "room_id": scene["room2"]}), 201)["id"]
    ru_unit = must(admin.post(V + "/rentable-units", json={"property_id": scene["prop"], "unit_id": scene["we2"]}), 201)["id"]

    def draft(client, ru, tenant, start, **extra):
        return client.post(V + "/leases", json={"kind": "sub", "lease_type_id": scene["lt"], "start_date": start.isoformat(), "rentable_unit_ids": [ru],
                                                "parties": [{"party_id": scene["own"], "role": "lessor"}, {"party_id": tenant, "role": "lessee"}], **extra})

    a = must(draft(admin, ru_room, scene["tenant2"], d(30), deposit_amount="2300.00"), 201)
    b = must(draft(admin, ru_unit, scene["tenant2"], d(30), deposit_amount="2300.00"), 201)
    assert a["deposit_amount"] == "2300.00" and b["deposit_amount"] == "2300.00"  # Kontrolle: mit Recht vorhanden

    def check(name, r, code=200):
        assert r.status_code == code, f"{name}: {r.status_code} {r.text}"
        assert no_deposit(r.json()) and "2300" not in r.text, f"{name}: deposit_amount sichtbar"

    check("create", draft(v, ru_room, scene["tenant2"], d(40)), 201)  # Entwurf ohne Aktivierung (keine Überschneidungsprüfung bei Entwürfen)
    check("legal-review", v.post(V + f"/leases/{a['id']}/legal-review", json={"status": "reviewed", "basis_ref": "intern", "basis_note": "Testvermerk"}))
    check("patch", v.patch(V + f"/leases/{a['id']}", json={"contract_number": "V-TEST-1"}))
    check("activate", v.post(V + f"/leases/{a['id']}/activate"))
    check("terminate", v.post(V + f"/leases/{a['id']}/terminate", json={"terminated_on": TODAY.isoformat(), "effective_on": d(60).isoformat()}))
    check("cancel", v.post(V + f"/leases/{b['id']}/cancel", json={"reason": "Testentwurf verworfen"}))
    assert admin.get(V + f"/leases/{a['id']}").json()["deposit_amount"] == "2300.00"  # gespeichert, nur für Rollen mit Recht sichtbar


# ---------------------------------------------------------------------------------------------------------------------------------
# B4 History / Mieterakte
# ---------------------------------------------------------------------------------------------------------------------------------
FIN_ACTION_PREFIXES = ("deposit.", "dunning.", "invoice.", "payment.")
FIN_ENTITY_TYPES = {"deposit", "dunning_notice", "invoice", "payment", "deposit_transaction"}


def fin_items(items):
    return [i for i in items if str(i.get("action", "")).startswith(FIN_ACTION_PREFIXES) or i.get("entity_type") in FIN_ENTITY_TYPES]


def entity_ids(s):
    return {"deposit": s["deposit"], "invoice": s["invoice"], "dunning_notice": s["notice"]}


@pytest.mark.parametrize("role", NO_FIN_ROLES)
@pytest.mark.parametrize("etype", ["deposit", "invoice", "dunning_notice"])
def test_b4_history_of_finance_entities_is_403_without_finance_read(scene, role, etype):
    r = scene["c"][role].get(V + f"/history?entity_type={etype}&entity_id={entity_ids(scene)[etype]}")
    assert r.status_code == 403, f"{role} {etype}: {r.status_code} {r.text}"
    assert r.json()["detail"]["code"] == "forbidden"
    assert leaks(r.text) == [] and not has_amount(r.text)


@pytest.mark.parametrize("role", ["admin", "lesend"])
@pytest.mark.parametrize("etype", ["deposit", "invoice", "dunning_notice"])
def test_b4_history_of_finance_entities_is_available_with_finance_read(scene, role, etype):
    r = scene["c"][role].get(V + f"/history?entity_type={etype}&entity_id={entity_ids(scene)[etype]}")
    assert r.status_code == 200, f"{role} {etype}: {r.status_code} {r.text}"
    assert len(r.json()["items"]) >= 1


def _timelines(c, s):
    pid = s["tenant"]
    hist = c.get(V + f"/history?entity_type=party&entity_id={pid}").json()["items"]
    detail = c.get(V + f"/parties/{pid}").json()["history"]
    activity = c.get(V + f"/tenants/{pid}/overview").json()["activity"]
    return hist, detail, activity


@pytest.mark.parametrize("role", NO_FIN_ROLES)
def test_b4_tenant_timeline_has_no_finance_entries_without_finance_read(scene, role):
    admin_hist = scene["admin"].get(V + f"/history?entity_type=party&entity_id={scene['tenant']}").json()["items"]
    fin = fin_items(admin_hist)
    assert any(i["action"].startswith("deposit.") for i in fin) and any(i["action"].startswith("dunning.") for i in fin), "Kontrolle: Szenario hat Kaution- und Mahn-Einträge"
    fin_summaries = {i["summary"] for i in fin}
    hist, detail, activity = _timelines(scene["c"][role], scene)
    assert fin_items(hist) == [] and fin_items(detail) == []
    assert not (fin_summaries & {i["summary"] for i in hist + detail + activity}), "Finanz-Summary in der Mieterakte"
    assert any(i["action"] == "lease.created" for i in hist), "Nicht-Finanz-Ereignisse bleiben"
    assert any(i["action"] == "task.created" for i in hist)
    for part in (hist, detail, activity):
        assert leaks(str(part)) == []


@pytest.mark.parametrize("role", ["admin", "lesend"])
def test_b4_tenant_timeline_keeps_finance_entries_with_finance_read(scene, role):
    hist, detail, activity = _timelines(scene["c"][role], scene)
    assert any(i["action"].startswith("deposit.") for i in hist) and any(i["action"].startswith("dunning.") for i in hist)
    assert [a["summary"] for a in activity] == [i["summary"] for i in hist[:len(activity)]], "Mieterakten-Aktivität ist mit Recht ungefiltert"


# ---------------------------------------------------------------------------------------------------------------------------------
# B5 IBAN maskiert
# ---------------------------------------------------------------------------------------------------------------------------------
def is_masked(v):
    return isinstance(v, str) and v.endswith(IBAN[-4:]) and len(v.rstrip()) > 4 and set(v[:-4]) <= set("•* ") and bool(set(v[:-4]) & set("•*")) and IBAN[:4] not in v


def iban_views(c, s):
    pid = s["tenant"]
    lst = c.get(V + "/parties")
    return {"parties": (lst, next(p for p in lst.json()["items"] if p["id"] == pid)),
            "party": (None, c.get(V + f"/parties/{pid}").json()),
            "overview": (None, c.get(V + f"/tenants/{pid}/overview").json()["party"])}


@pytest.mark.parametrize("role", NO_FIN_ROLES)
def test_b5_iban_is_masked_without_finance_read(scene, role):
    c = scene["c"][role]
    r_list, r_one, r_ov = c.get(V + "/parties"), c.get(V + f"/parties/{scene['tenant']}"), c.get(V + f"/tenants/{scene['tenant']}/overview")
    for name, r in (("parties", r_list), ("parties/{id}", r_one), ("overview", r_ov)):
        assert r.status_code == 200, name
        assert leaks(r.text) == [] and "04400532" not in r.text.replace(" ", ""), f"{name}: volle IBAN im Body"
    rows = {"parties": next(p for p in r_list.json()["items"] if p["id"] == scene["tenant"]), "parties/{id}": r_one.json(), "overview": r_ov.json()["party"]}
    for name, p in rows.items():
        assert is_masked(p["iban"]), f"{name}: IBAN nicht maskiert (nur letzte 4 Zeichen): {p['iban']!r}"
        assert p["birth_date"] == BIRTH, f"{name}: birth_date bleibt sichtbar (Entscheidung)"


@pytest.mark.parametrize("role", NO_FIN_ROLES)
def test_b5_party_without_iban_stays_none_without_finance_read(scene, role):
    p = scene["c"][role].get(V + f"/parties/{scene['owner']}").json()
    assert p["iban"] is None


@pytest.mark.parametrize("role", FIN_ROLES)
def test_b5_iban_is_unchanged_with_finance_read(scene, role):
    c = scene["c"][role]
    assert c.get(V + f"/parties/{scene['tenant']}").json()["iban"] == IBAN
    assert next(p for p in c.get(V + "/parties").json()["items"] if p["id"] == scene["tenant"])["iban"] == IBAN
    assert c.get(V + f"/tenants/{scene['tenant']}/overview").json()["party"]["iban"] == IBAN


def test_b5_patch_of_other_field_by_verwaltung_keeps_stored_iban(scene):
    r = scene["c"]["verwaltung"].patch(V + f"/parties/{scene['tenant']}", json={"city": "Teststadt"})
    assert r.status_code == 200, r.text
    assert leaks(r.text) == [], "PATCH-Antwort darf die volle IBAN nicht enthalten"
    assert is_masked(r.json()["iban"])
    stored = scene["admin"].get(V + f"/parties/{scene['tenant']}").json()
    assert stored["iban"] == IBAN, f"gespeicherte IBAN verändert: {stored['iban']!r}"
    assert stored["city"] == "Teststadt" and stored["birth_date"] == BIRTH


def test_b5_masked_iban_roundtrip_never_overwrites_stored_iban(scene):
    """Formular-Roundtrip: die maskiert gelesene IBAN wird mit zurückgeschickt. Ob 200 oder abgelehnt: gespeichert bleibt die volle IBAN."""
    v = scene["c"]["verwaltung"]
    masked = v.get(V + f"/parties/{scene['tenant']}").json()["iban"]
    assert is_masked(masked)
    v.patch(V + f"/parties/{scene['tenant']}", json={"iban": masked, "city": "Teststadt2"})
    assert scene["admin"].get(V + f"/parties/{scene['tenant']}").json()["iban"] == IBAN


# ---------------------------------------------------------------------------------------------------------------------------------
# B6 Dokumente mit Finanztyp
# ---------------------------------------------------------------------------------------------------------------------------------
def _ids(items):
    return {i["id"] for i in items}


@pytest.mark.parametrize("role", NO_FIN_ROLES)
def test_b6_finance_documents_are_hidden_in_search_and_entity_lists(scene, role):
    c = scene["c"][role]
    fin, other = {x["id"] for x in fin_docs(scene)}, {x["id"] for x in other_docs(scene)}
    for params in ({}, {"include_deleted": "true"}, {"doc_type": "rechnung"}, {"q": "rechnung"}, {"q": "kaution"}, {"q": "betriebskosten"}):
        r = c.get(V + "/documents/search", params=params)
        assert r.status_code == 200, r.text
        assert _ids(r.json()["items"]) & fin == set(), f"{role} search {params}: Finanzdokument sichtbar"
    assert other <= _ids(c.get(V + "/documents/search").json()["items"]), "andere Typen bleiben unverändert sichtbar"
    assert _ids(c.get(V + "/documents/search", params={"doc_type": "mietvertrag"}).json()["items"]) >= {scene["other_doc_id"]}
    for entity, eid in (("lease", scene["sub"]), ("party", scene["tenant"]), ("repair", scene["repair"])):
        got = _ids(c.get(V + "/documents", params={"entity_type": entity, "entity_id": eid}).json()["items"])
        assert got & fin == set(), f"{role} Liste {entity}: Finanzdokument sichtbar"
        assert got == {x["id"] for x in other_docs(scene) if x["entity"] == entity}, f"{role} Liste {entity}: nicht-finanzielle Dokumente müssen bleiben"
    # eingebettete Dokumentlisten (Mieterakte, Reparaturdetail)
    ov = _ids(c.get(V + f"/tenants/{scene['tenant']}/overview").json()["documents"])
    assert ov & fin == set() and ov, "Mieterakte: Finanzdokumente ausblenden, übrige behalten"
    rep = _ids(c.get(V + f"/repairs/{scene['repair']}").json()["documents"])
    assert rep & fin == set() and rep == {x["id"] for x in other_docs(scene) if x["entity"] == "repair"}


@pytest.mark.parametrize("role", NO_FIN_ROLES)
def test_b6_finance_document_download_and_verify_are_403_without_finance_read(scene, role):
    c = scene["c"][role]
    for x in fin_docs(scene):
        for path in (f"/documents/{x['id']}/download", f"/documents/{x['id']}/verify"):
            r = c.get(V + path)
            assert r.status_code == 403, f"{role} {x['type']} {path}: {r.status_code}"
            assert r.json()["detail"]["code"] == "forbidden"
    link = c.post(V + f"/documents/{fin_docs(scene)[0]['id']}/links", json={"entity_type": "property", "entity_id": scene["prop"]})
    assert link.status_code in (403, 404), f"Finanzdokument darf nicht verknüpfbar sein: {link.status_code}"


@pytest.mark.parametrize("role", NO_FIN_ROLES)
def test_b6_other_document_types_stay_downloadable_and_verifiable(scene, role):
    c = scene["c"][role]
    for x in other_docs(scene):
        dl = c.get(V + f"/documents/{x['id']}/download")
        assert dl.status_code == 200 and dl.content == x["bytes"], f"{x['type']}: {dl.status_code}"
        ver = c.get(V + f"/documents/{x['id']}/verify")
        assert ver.status_code == 200 and ver.json()["ok"] is True


@pytest.mark.parametrize("role", NO_FIN_ROLES)
@pytest.mark.parametrize("doc_type", FIN_DOC_TYPES)
def test_b6_upload_of_finance_document_types_is_403_without_finance_read(scene, role, doc_type):
    c = scene["c"][role]
    before = _ids(scene["admin"].get(V + "/documents/search", params={"include_deleted": "true"}).json()["items"])
    r, _ = upload(c, "property", scene["prop"], doc_type)
    assert r.status_code == 403, f"{role} {doc_type}: {r.status_code} {r.text}"
    assert r.json()["detail"]["code"] == "forbidden"
    assert _ids(scene["admin"].get(V + "/documents/search", params={"include_deleted": "true"}).json()["items"]) == before, "es darf kein Dokument entstanden sein"


@pytest.mark.parametrize("role", NO_FIN_ROLES)
@pytest.mark.parametrize("doc_type", ["mietvertrag", "sonstige", "reparaturbeleg"])
def test_b6_upload_of_other_types_is_unchanged_without_finance_read(scene, role, doc_type):
    r, data = upload(scene["c"][role], "property", scene["prop"], doc_type, name=f"{doc_type}-{role}.pdf")
    assert r.status_code == 201, r.text
    assert scene["c"][role].get(V + f"/documents/{r.json()['id']}/download").content == data


@pytest.mark.parametrize("role", ["admin", "lesend"])
def test_b6_with_finance_read_everything_is_visible_downloadable_and_verifiable(scene, role):
    c = scene["c"][role]
    allids = {x["id"] for x in scene["docs"]}
    assert allids <= _ids(c.get(V + "/documents/search").json()["items"])
    for entity, eid in (("lease", scene["sub"]), ("party", scene["tenant"]), ("repair", scene["repair"])):
        got = _ids(c.get(V + "/documents", params={"entity_type": entity, "entity_id": eid}).json()["items"])
        assert got == {x["id"] for x in scene["docs"] if x["entity"] == entity}
    assert {x["id"] for x in fin_docs(scene)} <= _ids(c.get(V + f"/tenants/{scene['tenant']}/overview").json()["documents"]) | {x["id"] for x in fin_docs(scene) if x["entity"] == "repair"}
    for x in scene["docs"]:
        dl = c.get(V + f"/documents/{x['id']}/download")
        assert dl.status_code == 200 and dl.content == x["bytes"], x["type"]
        assert c.get(V + f"/documents/{x['id']}/verify").json()["ok"] is True


@pytest.mark.parametrize("role", ["admin", "buchhaltung"])
@pytest.mark.parametrize("doc_type", FIN_DOC_TYPES)
def test_b6_upload_of_finance_document_types_is_allowed_with_finance_read_and_document_write(scene, role, doc_type):
    r, data = upload(scene["c"][role], "property", scene["prop"], doc_type, name=f"{doc_type}-{role}.pdf")
    assert r.status_code == 201, r.text
    assert scene["c"][role].get(V + f"/documents/{r.json()['id']}/download").content == data


# ---------------------------------------------------------------------------------------------------------------------------------
# K Klassifikationen (Wartbarkeit) und Route-Scan
# ---------------------------------------------------------------------------------------------------------------------------------
def test_k1_every_kpi_is_classified_exactly_once():
    non_fin = getattr(FA, "NON_FINANCE_KPI_KEYS", None)
    assert non_fin is not None, "security.finance_access.NON_FINANCE_KPI_KEYS fehlt"
    keys = {k for k, _, _ in DASH.KPI_DEFINITIONS}
    both, neither = keys & FA.FINANCE_KPI_KEYS & non_fin, keys - FA.FINANCE_KPI_KEYS - non_fin
    assert both == set(), f"in beiden Mengen: {sorted(both)}"
    assert neither == set(), f"unklassifiziert (neue KPI muss bewusst eingeordnet werden): {sorted(neither)}"
    assert FA.FINANCE_KPI_KEYS & non_fin == set()
    assert non_fin <= keys, f"veraltete nicht-finanzielle Schlüssel: {sorted(non_fin - keys)}"
    assert set(non_fin) == {"properties", "units", "active_main_leases", "active_subleases", "active_tenants", "open_tasks", "overdue_tasks", "open_repairs",
                            "physical_vacancy", "upcoming_contract_ends",
                            "upcoming_main_lease_ends", "upcoming_sublease_ends"}  # Phase I: getrennte Vertragsenden sind nicht finanziell (Orchestrator-Entscheidung 2.2)


def _reminder_calls():
    """(Schlüsselpräfix, Typ) je _r(...)-Aufruf aus dem Quelltext von services/reminders.py."""
    src = Path(REM.__file__).read_text(encoding="utf-8")
    calls = re.findall(r'_r\(\s*f?"([a-z_]+)(?::[^"]*)?"\s*,\s*"([a-z_]+)"', src)
    assert len(calls) == len(re.findall(r"\b_r\(", src)) - 1, "ein _r(...)-Aufruf wird von der Extraktion nicht erfasst"  # minus Definition
    assert len(calls) >= 9
    return calls


def test_k2_every_reminder_type_is_classified_exactly_once():
    non_fin = getattr(FA, "NON_FINANCE_REMINDER_TYPES", None)
    assert non_fin is not None, "security.finance_access.NON_FINANCE_REMINDER_TYPES fehlt"
    types = {t for _, t in _reminder_calls()}
    assert FA.FINANCE_REMINDER_TYPES == FIN_TYPES
    assert types & FA.FINANCE_REMINDER_TYPES & non_fin == set()
    assert types - FA.FINANCE_REMINDER_TYPES - non_fin == set(), f"unklassifizierte Typen: {sorted(types - FA.FINANCE_REMINDER_TYPES - non_fin)}"
    assert FA.FINANCE_REMINDER_TYPES & non_fin == set()
    assert FA.FINANCE_REMINDER_TYPES <= types and set(non_fin) <= types, "veraltete Typen in den Konstanten"


def test_k2_reminder_type_and_key_prefix_are_consistent_in_source():
    calls = _reminder_calls()
    fin_prefixes = {p for p, t in calls if t in FA.FINANCE_REMINDER_TYPES}
    other_prefixes = {p for p, t in calls if t not in FA.FINANCE_REMINDER_TYPES}
    assert fin_prefixes == set(FA.FINANCE_REMINDER_KEY_PREFIXES)
    assert other_prefixes & set(FA.FINANCE_REMINDER_KEY_PREFIXES) == set(), "Nicht-Finanz-Hinweis würde fälschlich als Finanzschlüssel gesperrt"
    for p, t in calls:
        assert FA.is_finance_reminder_key(f"{p}:1") == (t in FA.FINANCE_REMINDER_TYPES), (p, t)


def test_k2_reminder_keys_produced_by_compute_match_the_prefixes(scene):
    items = scene["admin"].get(V + "/reminders").json()["items"]
    assert FIN_TYPES <= {i["type"] for i in items}, "Szenario muss alle Finanztypen erzeugen"
    for i in items:
        assert FA.is_finance_reminder_key(i["key"]) == (i["type"] in FA.FINANCE_REMINDER_TYPES), (i["type"], i["key"])
        assert (i["key"].split(":", 1)[0] in FA.FINANCE_REMINDER_KEY_PREFIXES) == (i["type"] in FIN_TYPES)


def _id_maps(s):
    primary = {"parties": s["tenant"], "tenants": s["tenant"], "leases": s["sub"], "repairs": s["repair"], "tasks": s["task_ids"]["overdue_payment"],
               "documents": s["fin_doc_id"], "properties": s["prop"], "deposits": s["deposit"], "notices": s["notice"], "invoices": s["invoice"]}
    alt = {**primary, "parties": s["owner"], "tenants": s["owner"], "leases": s["main"], "tasks": s["task_ids"]["deposit_overdue"], "documents": s["other_doc_id"]}
    return [primary, alt, {}]  # {} -> überall Id 1


def _query_variants(s):
    hist = [("party", s["tenant"]), ("party", s["owner"]), ("lease", s["sub"]), ("lease", s["main"]), ("repair", s["repair"]), ("task", s["task_ids"]["overdue_payment"]),
            ("property", s["prop"]), ("unit", s["we1"]), ("deposit", s["deposit"]), ("invoice", s["invoice"]), ("dunning_notice", s["notice"]), ("party", 1)]
    docs = [("lease", s["sub"]), ("party", s["tenant"]), ("repair", s["repair"]), ("property", s["prop"]), ("invoice", s["invoice"]), ("lease", 1)]
    rng = {"start": d(-60).isoformat(), "end": TODAY.isoformat()}
    return {"/history": [{"entity_type": t, "entity_id": i} for t, i in hist], "/documents": [{"entity_type": t, "entity_id": i} for t, i in docs],
            "/economics": [rng], "/vacancy": [rng], "/handover-protocols": [{"lease_id": s["sub"]}, {"lease_id": 1}],
            "/search": [{"q": "Zahl"}, {"q": "Haus"}, {"q": "Heizung"}], "/parties": [{}, {"q": "zahl"}], "/documents/search": [{}, {"include_deleted": "true"}, {"doc_type": "rechnung"}],
            "/tasks": [{}, {"open_only": "true"}, {"overdue": "true"}], "/tenants": [{}, {"status": "arrears"}], "/dashboard": [{}, {"as_of": d(-7).isoformat()}],
            "/charges": [{}], "/dunning/overdue": [{}, {"as_of": TODAY.isoformat()}]}


def scan(client, s):
    """GET-Scan über alle Routen aus app.openapi(): Pfadparameter mit echten Ids, alternativen Ids und 1; nur 200-Antworten werden ausgewertet."""
    templates = sorted(p[len(V):] for p, ops in s["app"].openapi()["paths"].items() if "get" in ops)
    variants, hits, ok_templates, violations, n200 = _query_variants(s), set(), set(), [], 0
    for tpl in templates:
        for m in _id_maps(s):
            path = re.sub(r"/([^/{]+)/\{[^}]+\}", lambda mm: f"/{mm.group(1)}/{m.get(mm.group(1), 1)}", tpl)
            for params in variants.get(tpl, [{}]):
                r = client.get(V + path, params=params)
                if r.status_code != 200:
                    continue
                n200 += 1
                ok_templates.add(tpl)
                found = leaks(r.text)
                hits.update(found)
                if found:
                    violations.append(f"GET {path} {params}: {found}")
    return {"violations": sorted(set(violations)), "hits": hits, "templates": ok_templates, "n200": n200, "all": templates}


@pytest.mark.parametrize("role", NO_FIN_ROLES)
def test_k3_route_scan_no_finance_marker_in_any_get_route_without_finance_read(scene, role):
    """Kein 200-Body irgendeiner GET-Route enthält Marker. Keine Ausnahme nötig: Vertragskonditionen (1150,00; 850,00; 180,00) tragen keinen Marker."""
    res = scan(scene["c"][role], scene)
    assert res["violations"] == [], "\n".join(res["violations"])
    assert res["n200"] >= 40
    assert {"/leases/{lease_id}", "/parties/{party_id}", "/repairs/{rid}", "/repairs", "/tasks", "/dashboard", "/history", "/documents", "/documents/search",
            "/tenants", "/tenants/{party_id}/overview", "/reminders", "/documents/{did}/download"} <= res["templates"], "Scan hat zentrale Routen nicht erreicht"


def test_k3_scan_control_admin_sees_every_marker_so_the_scan_is_not_vacuous(scene):
    res = scan(scene["c"]["admin"], scene)
    assert res["hits"] == set(MARKERS), f"fehlende Marker im Szenario/Scan: {set(MARKERS) - res['hits']}"


# ---------------------------------------------------------------------------------------------------------------------------------
# H HTTP-Randfälle
# ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("role", NO_FIN_ROLES)
def test_h_dashboard_with_empty_as_of_is_403_without_finance_read(scene, role):
    r = scene["c"][role].get(V + "/dashboard?as_of=")
    assert r.status_code == 403, f"{role}: {r.status_code} {r.text}"
    assert r.json()["detail"]["code"] == "forbidden" and leaks(r.text) == []


@pytest.mark.parametrize("role", NO_FIN_ROLES)
@pytest.mark.parametrize("follow", [False, True], ids=["no-redirect", "follow-redirect"])
def test_h_dashboard_trailing_slash_leaks_no_finance_data(scene, role, follow):
    r = scene["c"][role].get(V + "/dashboard/", params={"as_of": d(-7).isoformat()}, follow_redirects=follow)
    assert r.status_code in (200, 307, 403, 404), f"{role} follow={follow}: {r.status_code}"
    assert leaks(r.text) == [] and not has_amount(r.text)
    if r.status_code == 200:
        keys = {k["key"] for k in r.json()["kpis"]}
        assert keys.isdisjoint(FA.FINANCE_KPI_KEYS), f"Finanz-KPIs im Body: {sorted(keys & FA.FINANCE_KPI_KEYS)}"
        assert not {w["type"] for w in r.json()["warnings"]} & FIN_TYPES
    if r.status_code in (307, 404):
        assert "kpis" not in r.text


@pytest.mark.parametrize("role", NO_FIN_ROLES)
@pytest.mark.parametrize("path", ["/dashboard", "/dashboard?as_of=" + d(-7).isoformat(), "/tenants", "/tenants?status=arrears"])
def test_h_head_requests_reveal_nothing(scene, role, path):
    r = scene["c"][role].head(V + path)
    assert r.status_code in (200, 405, 403), f"{role} HEAD {path}: {r.status_code}"
    if r.status_code == 200:
        assert r.content == b"", "HEAD mit 200 darf keinen Body liefern"
    assert leaks(r.text) == [] and "kpis" not in r.text and "payment_status" not in r.text and "overdue_amount" not in r.text
