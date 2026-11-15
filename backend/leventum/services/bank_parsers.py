"""Kontoauszugs-Parser. Neue Formate (CAMT.053, Open Banking) werden als weitere StatementParser registriert;
der Import-Service kennt nur das gemeinsame Ergebnisformat `ParseResult`. Es werden keine Zugangsdaten verarbeitet."""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

MAX_ROWS = 20000
MAX_BYTES = 5 * 1024 * 1024


@dataclass
class ParsedRow:
    row_no: int
    booking_date: date
    value_date: date | None
    amount: Decimal
    currency: str
    counterparty_name: str | None
    counterparty_iban: str | None
    reference: str | None
    external_id: str | None
    raw: dict


@dataclass
class ParseResult:
    rows: list[ParsedRow] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


class StatementParser(Protocol):
    format: str

    def parse(self, data: bytes, options: dict | None = None) -> ParseResult: ...


def _norm(h: str) -> str:
    h = unicodedata.normalize("NFKD", h.strip().lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", h)


ALIASES = {
    "booking_date": ["buchungstag", "buchungsdatum", "buchung", "bookingdate", "datum", "date"],
    "value_date": ["valuta", "wertstellung", "valutadatum", "valuedate"],
    "amount": ["betrag", "umsatz", "amount", "betrageur", "betragin"],
    "credit": ["haben", "gutschrift", "credit"],
    "debit": ["soll", "lastschrift", "debit"],
    "currency": ["waehrung", "whrung", "currency", "wahrung"],
    "counterparty_name": ["namezahlungsbeteiligter", "zahlungsbeteiligter", "auftraggeber", "empfaenger", "beguenstigter", "name", "auftraggeberempfaenger",
                          "empfangerzahlungspflichtiger", "counterparty", "beguenstigterzahlungspflichtiger"],
    "counterparty_iban": ["iban", "ibanzahlungsbeteiligter", "kontonummeriban", "counterpartyiban", "ibanauftraggeber"],
    "reference": ["verwendungszweck", "buchungstext", "reference", "zweck", "verwendungszweckzeile1"],
    "external_id": ["kundenreferenz", "endtoendreferenz", "transaktionsid", "externalid", "referenz", "id"],
}
CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def parse_amount(s: str) -> Decimal:
    s = s.strip().replace("€", "").replace(" ", "").replace(" ", "")
    if not s:
        raise ValueError("Betrag fehlt")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    if s.endswith("-"):  # 123,45-
        s = "-" + s[:-1]
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"Ungültiger Betrag: {s!r}")
    if d != d.quantize(Decimal("0.01")):
        raise ValueError(f"Betrag hat mehr als 2 Nachkommastellen: {s!r}")
    return d.quantize(Decimal("0.01"))


def parse_date(s: str) -> date:
    s = s.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Ungültiges Datum: {s!r} (erwartet TT.MM.JJJJ oder JJJJ-MM-TT)")


def _clean(v: str | None, limit: int = 1000) -> str | None:
    if v is None:
        return None
    v = CTRL.sub(" ", v).strip()
    return v[:limit] or None


class CsvParser:
    format = "csv"

    def parse(self, data: bytes, options: dict | None = None) -> ParseResult:
        options = options or {}
        res = ParseResult()
        if len(data) > MAX_BYTES:
            res.errors.append({"row": 0, "message": "Datei zu groß (max. 5 MB)."})
            return res
        text = None
        for enc in ("utf-8-sig", "cp1252"):
            try:
                text, res.meta["encoding"] = data.decode(enc), enc
                break
            except UnicodeDecodeError:
                continue
        if text is None or not text.strip():
            res.errors.append({"row": 0, "message": "Datei leer oder nicht lesbar."})
            return res
        first = text.splitlines()[0]
        delim = options.get("delimiter") or max(";,\t|", key=first.count)
        if first.count(delim) == 0:
            res.errors.append({"row": 1, "message": "Kein Trennzeichen in der Kopfzeile gefunden."})
            return res
        res.meta["delimiter"] = delim
        reader = csv.reader(io.StringIO(text), delimiter=delim)
        try:
            header = next(reader)
        except StopIteration:
            res.errors.append({"row": 0, "message": "Keine Kopfzeile."})
            return res
        norm = {_norm(h): i for i, h in enumerate(header)}
        mapping: dict[str, int] = {}
        explicit = options.get("mapping") or {}
        for field_, aliases in ALIASES.items():
            if field_ in explicit:
                idx = next((i for i, h in enumerate(header) if h.strip() == explicit[field_]), None)
                if idx is None:
                    res.errors.append({"row": 1, "message": f"Spalte {explicit[field_]!r} für {field_} nicht gefunden."})
                else:
                    mapping[field_] = idx
                continue
            for a in aliases:
                if a in norm:
                    mapping[field_] = norm[a]
                    break
        res.meta["mapping"] = {k: header[v] for k, v in mapping.items()}
        if "booking_date" not in mapping:
            res.errors.append({"row": 1, "message": "Pflichtspalte 'Buchungstag' nicht gefunden."})
        if "amount" not in mapping and not ({"credit", "debit"} <= mapping.keys()):
            res.errors.append({"row": 1, "message": "Pflichtspalte 'Betrag' (oder Soll/Haben) nicht gefunden."})
        if "reference" not in mapping and "counterparty_name" not in mapping:
            res.errors.append({"row": 1, "message": "Weder 'Verwendungszweck' noch 'Name' gefunden – Zuordnung nicht möglich."})
        if res.errors:
            return res
        for n, row in enumerate(reader, start=2):
            if not any(c.strip() for c in row):
                continue
            if len(res.rows) >= MAX_ROWS:
                res.errors.append({"row": n, "message": f"Mehr als {MAX_ROWS} Zeilen."})
                break
            get = lambda f_: row[mapping[f_]] if f_ in mapping and mapping[f_] < len(row) else ""
            try:
                if len(row) < len(header):
                    raise ValueError("Zeile hat weniger Spalten als die Kopfzeile")
                bd = parse_date(get("booking_date"))
                vd = parse_date(get("value_date")) if get("value_date").strip() else None
                if "amount" in mapping:
                    amount = parse_amount(get("amount"))
                else:
                    cr, de = get("credit").strip(), get("debit").strip()
                    amount = (parse_amount(cr) if cr else Decimal("0.00")) - abs(parse_amount(de) if de else Decimal("0.00"))
                if amount == 0:
                    raise ValueError("Betrag ist 0")
                cur = (get("currency").strip() or "EUR").upper()
                if cur != "EUR":
                    raise ValueError(f"Nicht unterstützte Währung {cur}")
                iban = re.sub(r"\s", "", get("counterparty_iban")).upper() or None
                if iban and not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
                    raise ValueError(f"Ungültige IBAN {iban!r}")
                res.rows.append(ParsedRow(n, bd, vd, amount, cur, _clean(get("counterparty_name"), 300), iban, _clean(get("reference")),
                                          _clean(get("external_id"), 120), {header[i]: _clean(c, 300) for i, c in enumerate(row[:len(header)])}))
            except ValueError as e:
                res.errors.append({"row": n, "message": str(e)})
        if not res.rows and not res.errors:
            res.errors.append({"row": 0, "message": "Keine Buchungszeilen gefunden."})
        return res


PARSERS: dict[str, StatementParser] = {"csv": CsvParser()}
# Erweiterung: PARSERS["camt053"] = Camt053Parser()  (liefert dasselbe ParseResult)
