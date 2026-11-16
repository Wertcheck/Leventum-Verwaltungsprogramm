"""Zentrale Stichtagslogik für alle Ist-Auswertungen (Dashboard, Forderungsliste, Mahnwesen, Wirtschaftlichkeit).

Ein Stichtag ist ein Datum <= heute: Zahlungen wirken ab ihrem Buchungsdatum (booking_date <= Stichtag). Zukünftige Stichtage sind
KEINE Ist-Stichtage (Prognosen werden getrennt und gekennzeichnet ausgewiesen) und werden mit `as_of_in_future` (422) abgelehnt.
Reiner Lesepfad, keine Datenbankzugriffe."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from leventum.services.errors import ServiceError

_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Stichtag:
    as_of: date
    today: date

    @property
    def is_historical(self) -> bool:
        return self.as_of < self.today

    @property
    def mode(self) -> str:
        return "historical" if self.is_historical else "current"


def resolve(raw: date | str | None, today: date | None = None) -> Stichtag:
    """None -> heute; date oder ISO-Text (JJJJ-MM-TT) -> Stichtag. Zukunft -> as_of_in_future, ungültiges Format -> invalid_as_of (je 422)."""
    today = today or date.today()
    if raw is None:
        return Stichtag(today, today)
    if isinstance(raw, date):
        day = raw
    else:
        text = str(raw).strip()
        try:
            if not _ISO_DAY.match(text):
                raise ValueError(text)
            day = date.fromisoformat(text)
        except ValueError:
            raise ServiceError("invalid_as_of", "Der Stichtag muss als Datum im Format JJJJ-MM-TT angegeben werden.", 422) from None
    if day > today:
        raise ServiceError("as_of_in_future", "Der Stichtag darf nicht in der Zukunft liegen (Ist-Auswertung, keine Prognose).", 422)
    return Stichtag(day, today)


def meta(view: str, st: Stichtag, *, historical_supported: bool = True, limitations: list[str] | None = None, mode: str | None = None, **extra) -> dict:
    """Antwortblock 'stichtag': {view, mode, as_of (ISO), historical_supported, limitations?}. `mode` überschreibt den Modus (z. B. 'datenstand')."""
    out = {"view": view, "mode": mode or st.mode, "as_of": st.as_of.isoformat(), "historical_supported": bool(historical_supported)}
    if limitations:
        out["limitations"] = list(limitations)
    out.update(extra)
    return out


# Gemeinsame Hinweise (ADR 0002, A6): gelten für alle Forderungsansichten.
LIMITATIONS_RECEIVABLES = [
    "Zahlungen wirken ab ihrem Buchungsdatum; später zurückgenommene Zuordnungen (Rücknahme) wirken auch auf zurückliegende Stichtage.",
    "Heute stornierte Sollstellungen fehlen in historischen Stichtagen.",
]
