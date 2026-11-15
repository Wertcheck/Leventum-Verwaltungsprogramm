from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select

from leventum.models import BankImport, BankTransaction, Charge, Payment
from leventum.services import bank as B, bank_parsers as BP, charges as C, deposits as DEP, master as M, payments as P
from leventum.services.errors import ServiceError
from tests.helpers import World

HEAD = "Buchungstag;Valuta;Name Zahlungsbeteiligter;IBAN Zahlungsbeteiligter;Verwendungszweck;Betrag;Währung\n"
TENANT_IBAN = "DE89370400440532013000"
OWNER_IBAN = "DE02120300000000202051"


def csv(*rows, head=HEAD, enc="utf-8"):
    return (head + "\n".join(rows) + "\n").encode(enc)


RENT = f"02.01.2026;02.01.2026;Max Mustermann;DE89 3704 0044 0532 0130 00;Miete Januar;1.370,00;EUR"


@pytest.fixture
def w(app):
    w = World(app)
    w.main_l = w.activate_main()
    w.tenant_p = w.tenant("Max Mustermann")
    M.update_party(w.db, None, w.tenant_p.id, {"iban": TENANT_IBAN})
    M.update_party(w.db, None, w.owner.id, {"iban": OWNER_IBAN})
    w.sub_l = w.sub([w.ru_unit(w.we2)], [w.tenant_p], date(2026, 1, 1), None)
    C.generate_charges(w.db, None, from_month=date(2026, 1, 1), through_month=date(2026, 2, 1), today=date(2026, 2, 15))
    w.acc = B.create_account(w.db, None, "Geschäftskonto", "DE00 1234")
    yield w
    w.db.close()


def n(w, model): return w.db.scalar(select(func.count()).select_from(model))


# ---- Parser / Validierung ---------------------------------------------------------------------------------------------------------------
def test_parses_german_csv_with_semicolon_cp1252_and_formats():
    res = BP.CsvParser().parse(csv(RENT, "03.01.2026;;Eigentümer Immobilien;;Miete 850,00-;-1.030,00;EUR", enc="cp1252"))
    assert not res.errors and res.meta["encoding"] == "cp1252" and res.meta["delimiter"] == ";"
    a, b = res.rows
    assert (a.amount, a.counterparty_iban, a.booking_date) == (D("1370.00"), TENANT_IBAN, date(2026, 1, 2))
    assert b.amount == D("-1030.00") and b.counterparty_name == "Eigentümer Immobilien" and b.value_date is None


def test_parses_comma_delimited_english_numbers_and_iso_dates():
    data = b"Date,Amount,Name,Reference\n2026-01-05,\"1,150.50\",Max,Miete\n2026-01-06,-20.5,Shop,Kauf\n"
    res = BP.CsvParser().parse(data)
    assert not res.errors and [r.amount for r in res.rows] == [D("1150.50"), D("-20.50")]


def test_debit_credit_columns_and_explicit_mapping():
    data = "Datum;Gegenpartei;Haben;Soll;Text\n05.01.2026;Max;100,00;;Miete\n06.01.2026;Shop;;25,00;Kauf\n".encode()
    res = BP.CsvParser().parse(data, {"mapping": {"counterparty_name": "Gegenpartei", "reference": "Text"}})
    assert [r.amount for r in res.rows] == [D("100.00"), D("-25.00")]


@pytest.mark.parametrize("row,msg", [
    ("31.02.2026;;X;;Test;10,00;EUR", "Datum"), ("02.01.2026;;X;;Test;12,345;EUR", "Nachkommastellen"), ("02.01.2026;;X;;Test;abc;EUR", "Betrag"),
    ("02.01.2026;;X;;Test;10,00;USD", "Währung"), ("02.01.2026;;X;XX12;Test;10,00;EUR", "IBAN"), ("02.01.2026;;X;;Test;0,00;EUR", "0"),
    ("02.01.2026;;X", "Spalten")])
def test_invalid_rows_are_reported_with_row_numbers(row, msg):
    res = BP.CsvParser().parse(csv(RENT, row))
    assert len(res.errors) == 1 and res.errors[0]["row"] == 3 and msg in res.errors[0]["message"]


@pytest.mark.parametrize("data", [b"", b"nur eine zeile ohne trenner", "Buchungstag;Name\n01.01.2026;X\n".encode(), "Name;Betrag\nX;1,00\n".encode(), b"\xff\xfe\x00"])
def test_structural_problems_are_rejected(data):
    assert BP.CsvParser().parse(data).errors


def test_import_is_all_or_nothing_and_leaves_no_residue(w):
    with pytest.raises(ServiceError) as e:
        B.import_statement(w.db, None, w.acc.id, "x.csv", csv(RENT, "xx;;Y;;Z;1,00;EUR"))
    assert e.value.code == "invalid_file" and e.value.details[0]["row"] == 3
    assert n(w, BankTransaction) == 0 and n(w, BankImport) == 0


def test_import_creates_open_transactions_and_no_payments_and_logs(w):
    imp = B.import_statement(w.db, 1, w.acc.id, "jan.csv", csv(RENT))
    assert (imp.total_rows, imp.new_rows, imp.duplicate_rows) == (1, 1, 0)
    t = w.db.scalar(select(BankTransaction))
    assert t.status == "open" and t.payment_id is None and t.amount == D("1370.00") and n(w, Payment) == 0  # nichts wird ohne Bestätigung gebucht
    from leventum.models import AuditEvent
    ev = w.db.scalar(select(AuditEvent).where(AuditEvent.action == "bank.imported"))
    assert ev.details["new"] == 1 and len(ev.details["sha256"]) == 64


def test_unsupported_format_and_registry_is_extensible(w):
    with pytest.raises(ServiceError) as e:
        B.import_statement(w.db, None, w.acc.id, "x.xml", b"<x/>", "camt053")
    assert e.value.code == "unsupported_format"
    class Fake:
        format = "fake"
        def parse(self, data, options=None):
            from leventum.services.bank_parsers import ParseResult, ParsedRow
            return ParseResult(rows=[ParsedRow(1, date(2026, 1, 9), None, D("5.00"), "EUR", "Z", None, "Test", None, {})])
    BP.PARSERS["fake"] = Fake()
    try:
        assert B.import_statement(w.db, None, w.acc.id, "f", b"", "fake").new_rows == 1  # neues Format ohne Änderung am Import-Service
    finally:
        del BP.PARSERS["fake"]


# ---- Duplikate ----------------------------------------------------------------------------------------------------------------------------------------
def test_reimport_same_file_creates_no_duplicates(w):
    data = csv(RENT, "03.01.2026;;Shop;;Kauf;-20,00;EUR")
    B.import_statement(w.db, None, w.acc.id, "a.csv", data)
    prev = B.preview(w.db, w.acc.id, data)
    assert (prev["new_rows"], prev["duplicate_rows"], prev["file_already_imported"]) == (0, 2, True)
    again = B.import_statement(w.db, None, w.acc.id, "a-again.csv", data)
    assert (again.new_rows, again.duplicate_rows) == (0, 2) and n(w, BankTransaction) == 2


def test_overlapping_statements_only_new_rows_are_added(w):
    B.import_statement(w.db, None, w.acc.id, "a.csv", csv(RENT, "03.01.2026;;Shop;;Kauf;-20,00;EUR"))
    imp = B.import_statement(w.db, None, w.acc.id, "b.csv", csv("03.01.2026;;Shop;;Kauf;-20,00;EUR", "04.01.2026;;Bäcker;;Brot;-3,00;EUR"))
    assert (imp.new_rows, imp.duplicate_rows) == (1, 1) and n(w, BankTransaction) == 3


def test_identical_rows_within_one_file_are_real_repeat_bookings_not_duplicates(w):
    row = "05.01.2026;;Kantine;;Essen;-9,50;EUR"
    first = B.import_statement(w.db, None, w.acc.id, "a.csv", csv(row, row))
    assert first.new_rows == 2
    third = B.import_statement(w.db, None, w.acc.id, "b.csv", csv(row, row, row))  # Überschneidung: 2 bekannt, 1 neu
    assert (third.new_rows, third.duplicate_rows) == (1, 2) and n(w, BankTransaction) == 3


def test_same_row_in_different_account_is_not_a_duplicate(w):
    other = B.create_account(w.db, None, "Zweitkonto", None)
    B.import_statement(w.db, None, w.acc.id, "a.csv", csv(RENT))
    assert B.import_statement(w.db, None, other.id, "a.csv", csv(RENT)).new_rows == 1


# ---- Vorschläge ---------------------------------------------------------------------------------------------------------------------------------------------
def txn(w, row):
    B.import_statement(w.db, None, w.acc.id, "t.csv", csv(row))
    return w.db.scalars(select(BankTransaction).order_by(BankTransaction.id.desc())).first()


def test_incoming_rent_suggestion_by_iban_name_and_exact_amount_fifo(w):
    t = txn(w, RENT)  # 1.370 = Januar-Miete 1.150 + NK 220
    s = B.suggest(w.db, t)
    assert s[0]["kind"] == "charges" and s[0]["lease_id"] == w.sub_l.id and s[0]["unallocated_remainder"] == D("0.00")
    assert {a["amount"] for a in s[0]["allocations"]} == {D("1150.00"), D("220.00")} and all(a["due_date"] == date(2026, 1, 1) for a in s[0]["allocations"])
    assert any("IBAN" in r for r in s[0]["reasons"]) and s[0]["score"] >= 100
    assert n(w, Payment) == 0  # Vorschlag bucht nichts


def test_partial_and_excess_amounts_oldest_first_with_remainder(w):
    s = B.suggest(w.db, txn(w, "04.01.2026;;Max Mustermann;;Miete;500,00;EUR"))[0]
    assert [a["amount"] for a in s["allocations"]] == [D("500.00")] and s["unallocated_remainder"] == D("0.00")
    s = B.suggest(w.db, txn(w, "05.01.2026;;Max Mustermann;;Miete;3.000,00;EUR"))[0]
    assert sum(a["amount"] for a in s["allocations"]) == D("2740.00") and s["unallocated_remainder"] == D("260.00")


def test_unknown_counterparty_has_no_suggestion_and_lands_on_review_list(w):
    t = txn(w, "06.01.2026;;Unbekannt GmbH;DE44500105175407324931;Irgendwas;1.370,00;EUR")  # Betrag passt, aber Partei nicht
    assert B.suggest(w.db, t) == []


def test_outgoing_main_rent_and_invoice_suggestions(w):
    t = txn(w, f"02.01.2026;;Olga Eigentümer;{OWNER_IBAN};Miete Haus Bergmann;-1.030,00;EUR")
    s = B.suggest(w.db, t)[0]
    assert s["lease_id"] == w.main_l.id and s["unallocated_remainder"] == D("0.00")
    sup = M.create_party(w.db, None, {"kind": "company", "company_name": "Sanitär Schmidt GmbH"}, ["service_provider"])
    inv = P.create_invoice(w.db, None, property_id=w.prop.id, supplier_party_id=sup.id, invoice_number="RE-2026-77", amount=D("238.00"), invoice_date=date(2026, 1, 20))
    s = B.suggest(w.db, txn(w, "10.02.2026;;Sanitär Schmidt;;Rechnung RE-2026-77;-238,00;EUR"))
    assert s[0]["kind"] == "invoice" and s[0]["invoice_id"] == inv.id and s[0]["allocations"][0]["amount"] == D("238.00")


def test_deposit_suggestion_sub_incoming_and_main_outgoing(w):
    ds = DEP.ensure_deposit(w.db, None, w.sub_l.id, agreed_amount=D("2000.00"))
    dm = DEP.ensure_deposit(w.db, None, w.main_l.id, agreed_amount=D("1500.00"))
    s = B.suggest(w.db, txn(w, "07.01.2026;;Max Mustermann;;Mietkaution;2.000,00;EUR"))
    assert any(x["kind"] == "deposit" and x["deposit_id"] == ds.id and x["deposit_kind"] == "paid" for x in s)
    s = B.suggest(w.db, txn(w, f"08.01.2026;;Olga Eigentümer;{OWNER_IBAN};Kaution Haus Bergmann;-1.500,00;EUR"))
    assert any(x["kind"] == "deposit" and x["deposit_id"] == dm.id and x["deposit_kind"] == "paid" for x in s)


# ---- Bestätigung (manuell) ------------------------------------------------------------------------------------------------------------------------------------
def charges_of(w, month=date(2026, 1, 1)):
    return w.db.scalars(select(Charge).where(Charge.lease_id == w.sub_l.id, Charge.period_start == month)).all()


def test_confirm_books_payment_with_allocations_exactly_as_confirmed(w):
    t = txn(w, RENT)
    plan = B.suggest(w.db, t)[0]["allocations"]
    p = B.confirm_payment(w.db, 1, t.id, allocations=[{"charge_id": a["charge_id"], "amount": a["amount"]} for a in plan], lease_id=w.sub_l.id)
    assert (t.status, t.payment_id, t.confirmed_by_user_id) == ("confirmed", p.id, 1) and p.source == "bank_import" and p.direction == "in"
    assert all(C.open_amount(w.db, c) == 0 for c in charges_of(w))
    with pytest.raises(ServiceError) as e:
        B.confirm_payment(w.db, 1, t.id, allocations=[], note="nochmal")
    assert e.value.code == "invalid_state" and n(w, Payment) == 1  # keine Doppelbuchung


def test_confirm_validations_no_unauthorized_assignment(w):
    t = txn(w, "04.01.2026;;Max Mustermann;;Miete;500,00;EUR")
    c = charges_of(w)[0]
    with pytest.raises(ServiceError) as e:
        B.confirm_payment(w.db, 1, t.id, allocations=[{"charge_id": c.id, "amount": D("600.00")}])
    assert e.value.code == "exceeds_amount"
    with pytest.raises(ServiceError) as e:
        B.confirm_payment(w.db, 1, t.id, allocations=[])
    assert e.value.code == "note_required"
    pay_c = w.db.scalars(select(Charge).where(Charge.direction == "payable")).first()
    assert pay_c is not None
    with pytest.raises(ServiceError) as e:  # Eingang darf keiner Verbindlichkeit zugeordnet werden
        B.confirm_payment(w.db, 1, t.id, allocations=[{"charge_id": pay_c.id, "amount": D("100.00")}])
    assert e.value.code == "direction_mismatch"


def test_failed_confirm_leaves_transaction_open_after_rollback(w, app):
    t = txn(w, "04.01.2026;;Max Mustermann;;Miete;500,00;EUR")
    w.db.commit()
    try:
        B.confirm_payment(w.db, 1, t.id, allocations=[{"charge_id": 99999, "amount": D("10.00")}])
    except ServiceError:
        w.db.rollback()
    w.db.refresh(t)
    assert t.status == "open" and t.payment_id is None and n(w, Payment) == 0


def test_unallocated_confirmation_needs_reason_and_stays_unallocated(w):
    t = txn(w, "09.01.2026;;Versicherung AG;;Erstattung;80,00;EUR")
    p = B.confirm_payment(w.db, 1, t.id, allocations=[], note="Erstattung Versicherung, noch keiner Kostenposition zugeordnet", property_id=w.prop.id)
    assert P.payment_view(w.db, p)["unallocated"] == D("80.00")


def test_possible_duplicate_of_manual_payment_is_blocked_until_accepted(w):
    P.create_payment(w.db, None, direction="in", booking_date=date(2026, 1, 4), amount=D("500.00"), reference="Miete", note="manuell erfasst")
    t = txn(w, "04.01.2026;;Max Mustermann;;Miete;500,00;EUR")
    with pytest.raises(ServiceError) as e:
        B.confirm_payment(w.db, 1, t.id, allocations=[], note="x")
    assert e.value.code == "possible_duplicate" and t.status == "open"
    assert B.confirm_payment(w.db, 1, t.id, allocations=[], note="bewusst doppelt, zwei Zahlungen", accept_possible_duplicate=True)


def test_ignore_and_reopen_flow(w):
    t = txn(w, "09.01.2026;;Privat;;Test;-5,00;EUR")
    with pytest.raises(ServiceError):
        B.ignore(w.db, 1, t.id, " ")
    B.ignore(w.db, 1, t.id, "Privatbuchung")
    assert t.status == "ignored"
    with pytest.raises(ServiceError):
        B.confirm_payment(w.db, 1, t.id, allocations=[], note="x")
    B.reopen(w.db, 1, t.id, "Irrtum")
    assert t.status == "open" and t.ignore_reason is None


def test_reopen_confirmed_reverses_payment_and_allows_clean_reconfirmation(w):
    t = txn(w, "04.01.2026;;Max Mustermann;;Miete;1.150,00;EUR")
    c = next(c for c in charges_of(w) if c.charge_type == "base_rent")
    B.confirm_payment(w.db, 1, t.id, allocations=[{"charge_id": c.id, "amount": D("1150.00")}])
    B.reopen(w.db, 1, t.id, "Falsche Zuordnung")
    assert t.status == "open" and t.payment_id is None and C.open_amount(w.db, c) == D("1150.00") and n(w, Payment) == 2  # Original + Gegenbuchung
    d = charges_of(w)[0]
    B.confirm_payment(w.db, 1, t.id, allocations=[{"charge_id": c.id, "amount": D("1150.00")}])
    assert C.open_amount(w.db, c) == 0 and n(w, Payment) == 3


def test_confirm_deposit_checks_direction_and_records_bank_link(w):
    ds = DEP.ensure_deposit(w.db, None, w.sub_l.id, agreed_amount=D("2000.00"))
    wrong = txn(w, "07.01.2026;;Max Mustermann;;Kaution;-2.000,00;EUR")
    with pytest.raises(ServiceError) as e:
        B.confirm_deposit(w.db, 1, wrong.id, deposit_id=ds.id, kind="paid")
    assert e.value.code == "direction_mismatch"
    ok = txn(w, "08.01.2026;;Max Mustermann;;Kaution;2.000,00;EUR")
    tx = B.confirm_deposit(w.db, 1, ok.id, deposit_id=ds.id, kind="paid")
    assert tx.bank_transaction_id == ok.id and ok.status == "confirmed" and ok.payment_id is None and n(w, Payment) == 0  # Kaution erzeugt keine Zahlung
    B.reopen(w.db, 1, ok.id, "falsch")
    assert DEP.summary(ds, w.db.get(type(w.sub_l), ds.lease_id))["paid"] == D("0.00")
