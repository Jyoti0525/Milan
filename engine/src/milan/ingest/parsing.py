"""Turning strings somebody else wrote into the values this engine holds.

Every function here answers with `None` rather than raising or guessing. A
value that cannot be read is a fact about the file, and the caller needs it as
a fact - a parser that quietly returns zero for an unreadable amount would put
a wrong number into a balance and give nobody anything to look at.

Money goes through `from_rupees`, which means `Decimal` all the way down. A
float never touches an amount here, for the same reason it never does
anywhere else in this project.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TypeVar

from milan.domain.enums import CardType, EntityType, PaymentMethod
from milan.domain.money import Paise, from_rupees

ISO = "iso"
"""The format token for anything `datetime.fromisoformat` will take.

Kept apart from the strptime patterns because ISO is not one shape, it is a
family, and enumerating its members would be a worse job than the standard
library already does.
"""


# --------------------------------------------------------------------- money

_CURRENCY = re.compile(r"\b(?:inr|rs)\b\.?\s*|[₹₨]\s*", re.IGNORECASE)
_SIDE_MARKER = re.compile(r"\s*\b(cr|dr)\b\.?$", re.IGNORECASE)
_NUMERIC = re.compile(r"^\d+(?:,\d+)*(?:\.\d+)?$")


def parse_money(raw: str | None) -> Paise | None:
    """Read an amount in whatever way a finance export happened to write it.

    The shapes handled are the ones that actually turn up: thousands
    separators in either the Indian or the Western grouping, a rupee symbol or
    an `INR` prefix, parentheses for negatives, and the `Cr` / `Dr` suffix that
    Indian bank statements use instead of a sign.

    A blank cell is `None`, not zero. Bank statements leave the credit column
    empty on every debit line, and reading those as zero-rupee credits would
    invent a payout for every withdrawal the merchant ever made.
    """
    text = (raw or "").strip()
    if not text:
        return None

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1].strip()

    marker = _SIDE_MARKER.search(text)
    if marker is not None:
        negative = negative or marker.group(1).lower() == "dr"
        text = text[: marker.start()].strip()

    text = _CURRENCY.sub("", text).strip()
    if text.startswith("-"):
        negative, text = True, text[1:].strip()
    elif text.startswith("+"):
        text = text[1:].strip()

    if not _NUMERIC.match(text):
        return None
    try:
        value = Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None

    paise = from_rupees(value)
    return Paise(-paise) if negative else paise


# ------------------------------------------------------------------- dates

_DATE_PATTERNS = (
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%m-%d-%Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y/%m/%d",
    "%d.%m.%Y",
    "%d-%b-%Y",
    "%d %b %Y",
    "%d-%B-%Y",
    "%b %d, %Y",
    "%d-%m-%y",
    "%m-%d-%y",
    "%d/%m/%y",
    "%m/%d/%y",
)

_TIME_PATTERNS = ("", " %H:%M:%S", " %H:%M", " %H:%M:%S.%f")


def temporal_patterns() -> tuple[str, ...]:
    """Every date shape this reader will consider, ISO first.

    Day-first and month-first orderings are both in the list on purpose. Only
    the column's own values can say which one a file uses, and when they
    cannot say, the import has to ask rather than pick - see
    `distinguishing_value`.
    """
    return (ISO, *(f"{date}{time}" for date in _DATE_PATTERNS for time in _TIME_PATTERNS))


def parse_temporal(raw: str | None, pattern: str) -> datetime | None:
    """Read one value under one format. Never falls back to another."""
    text = (raw or "").strip()
    if not text:
        return None
    if pattern == ISO:
        candidate = f"{text[:-1]}+00:00" if text.endswith("Z") else text
        try:
            moment = datetime.fromisoformat(candidate)
        except ValueError:
            return None
        return moment.replace(tzinfo=None)
    try:
        return datetime.strptime(text, pattern)
    except ValueError:
        return None


def distinguishing_value(values: tuple[str, ...], patterns: tuple[str, ...]) -> str | None:
    """A value the surviving formats disagree about, if there is one.

    `06-07-2026` is the 6th of July under one convention and the 7th of June
    under another, and a column of nothing but low numbers admits both. This
    returns the first value that would be read two different ways, which is
    both the proof that the column is ambiguous and the example to put in
    front of the person being asked.

    Returns `None` when every surviving format agrees on every value - two
    formats that only differ in separators never actually conflict, and
    stopping to ask about those would be pedantry rather than caution.
    """
    if len(patterns) < 2:
        return None
    for value in values:
        seen = {parse_temporal(value, pattern) for pattern in patterns}
        if len(seen) > 1:
            return value
    return None


# ---------------------------------------------------------------- booleans

_TRUE = frozenset({"y", "yes", "true", "t", "1"})
_FALSE = frozenset({"n", "no", "false", "f", "0"})


def parse_bool(raw: str | None) -> bool | None:
    text = (raw or "").strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return None


# ------------------------------------------------------------------- enums


def normalise(text: str) -> str:
    """Fold a header or a value to the form aliases are written in.

    `Settled At`, `settled_at` and `SETTLED-AT` are one name. Everything that
    compares names in this package compares them through here, so the rules
    for what counts as the same name live in exactly one place.
    """
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


ENTITY_ALIASES: dict[str, str] = {
    "sale": "payment",
    "capture": "payment",
    "captured": "payment",
    "payments": "payment",
    "credit": "payment",
    "refunds": "refund",
    "credit_note": "refund",
    "reversal": "refund",
    "chargeback": "adjustment",
    "dispute": "adjustment",
    "adj": "adjustment",
    "adjustments": "adjustment",
    "transfers": "transfer",
    "route_transfer": "transfer",
    "split": "transfer",
}

METHOD_ALIASES: dict[str, str] = {
    "credit_card": "card",
    "debit_card": "card",
    "cards": "card",
    "cc": "card",
    "dc": "card",
    "net_banking": "netbanking",
    "internet_banking": "netbanking",
    "nb": "netbanking",
    "upi_collect": "upi",
    "upi_intent": "upi",
    "wallets": "wallet",
    "prepaid_wallet": "wallet",
    "pay_later": "paylater",
    "buy_now_pay_later": "paylater",
    "bnpl": "paylater",
    "emi_card": "emi",
}

CARD_TYPE_ALIASES: dict[str, str] = {
    "domestic": "domestic_consumer",
    "consumer": "domestic_consumer",
    "retail": "domestic_consumer",
    "personal": "domestic_consumer",
    "corporate": "domestic_corporate",
    "commercial": "domestic_corporate",
    "business": "domestic_corporate",
    "intl": "international",
    "foreign": "international",
    "overseas": "international",
}


_Vocabulary = TypeVar("_Vocabulary", EntityType, PaymentMethod, CardType)


def _parse_enum(
    raw: str | None, members: type[_Vocabulary], aliases: dict[str, str]
) -> _Vocabulary | None:
    text = normalise(raw or "")
    if not text:
        return None
    resolved = aliases.get(text, text)
    try:
        return members(resolved)
    except ValueError:
        return None


def parse_entity_type(raw: str | None) -> EntityType | None:
    return _parse_enum(raw, EntityType, ENTITY_ALIASES)


def parse_method(raw: str | None) -> PaymentMethod | None:
    return _parse_enum(raw, PaymentMethod, METHOD_ALIASES)


def parse_card_type(raw: str | None) -> CardType | None:
    return _parse_enum(raw, CardType, CARD_TYPE_ALIASES)
