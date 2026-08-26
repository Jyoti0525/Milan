"""What is actually in a column, decided by reading it rather than its name.

This module is the veto. Nothing downstream is allowed to map a column to a
field unless the values in that column can be read as that field's kind - so
a model that proposes `Balance` for the credit amount is overruled by
arithmetic, exactly the way a model proposing an explanation for a shortfall
is overruled by the waterfall.

The profile is computed once per column and then answers every question about
it. That matters for the date case in particular: whether `06-07-2026` is the
6th of July or the 7th of June cannot be settled one value at a time, only by
looking at the whole column and seeing whether any value in it has a day past
the twelfth. When none does, the column is genuinely ambiguous and the import
has to ask - which is the difference between reading a merchant's statement
and assuming an American wrote it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from milan.ingest import parsing
from milan.ingest.schema import ValueKind

CLEAN = 0.95
"""How much of a column has to parse for it to count as that kind.

Not 1.0. Exports carry the odd `N/A`, and a single junk cell in a thousand
should not disqualify a column that is obviously money. Not much below it
either - a column that parses four times in five is not that kind of column,
it is a coincidence.
"""

CATEGORICAL = 0.90
"""The same threshold for the enumerated fields, one notch looser. A method
column with a handful of values we have no name for is still the method
column."""

SPACEY = 0.20
"""How much whitespace an identifier column is allowed. Bank references never
have spaces; narrations always do. This is the only thing separating them
when both are just text."""

SAMPLES = 4


@dataclass(frozen=True, slots=True)
class ColumnProfile:
    """One column, measured."""

    name: str
    total: int
    filled: int
    distinct: int
    money: float
    boolean: float
    entity_type: float
    method: float
    card_type: float
    spacey: float
    temporal: tuple[str, ...]
    """Date formats that read every value in this column. Empty for a column
    that is not dates at all; longer than one when the column admits more
    than one reading."""

    conflict: str | None
    """A value the surviving date formats disagree about, if any exists."""

    samples: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return self.filled == 0

    @property
    def ambiguous_dates(self) -> bool:
        return self.conflict is not None

    def fits(self, kind: ValueKind) -> bool:
        """Whether this column's values could be this kind of field.

        An empty column fits nothing. That is not a technicality: a bank
        statement's debit column is entirely blank on a settlement-only
        account, and treating blankness as "could be anything" would let it
        be proposed as the credit amount.
        """
        if self.empty:
            return False
        match kind:
            case ValueKind.MONEY:
                return self.money >= CLEAN
            case ValueKind.TEMPORAL:
                return bool(self.temporal)
            case ValueKind.BOOLEAN:
                return self.boolean >= CLEAN and self.distinct <= 3
            case ValueKind.ENTITY_TYPE:
                return self.entity_type >= CATEGORICAL
            case ValueKind.PAYMENT_METHOD:
                return self.method >= CATEGORICAL
            case ValueKind.CARD_TYPE:
                return self.card_type >= CATEGORICAL
            case ValueKind.IDENTIFIER:
                return self.spacey <= SPACEY
            case ValueKind.TEXT:
                return True

    def why_not(self, kind: ValueKind) -> str:
        """One line saying what the values are, for a rejection nobody can argue with."""
        if self.empty:
            return f"{self.name} is empty in every row"
        shown = ", ".join(repr(value) for value in self.samples[:2])
        return f"{self.name} holds {shown}, which does not read as {kind.value}"


def _ratio(values: tuple[str, ...], read: Callable[[str | None], object]) -> float:
    """Share of values a parser could read. Callers pass the parser itself."""
    if not values:
        return 0.0
    return sum(1 for value in values if read(value) is not None) / len(values)


def _temporal(values: tuple[str, ...]) -> tuple[tuple[str, ...], str | None]:
    """Every date format that reads the whole column, and what they disagree on."""
    if not values:
        return (), None
    surviving = tuple(
        pattern
        for pattern in parsing.temporal_patterns()
        if _ratio(values, partial(_read_as, pattern=pattern)) >= CLEAN
    )
    return surviving, parsing.distinguishing_value(values, surviving)


def _read_as(value: str | None, *, pattern: str) -> object:
    return parsing.parse_temporal(value, pattern)


def profile_column(name: str, raw: tuple[str, ...]) -> ColumnProfile:
    filled = tuple(value for value in raw if value.strip())
    temporal, conflict = _temporal(filled)
    return ColumnProfile(
        name=name,
        total=len(raw),
        filled=len(filled),
        distinct=len(set(filled)),
        money=_ratio(filled, parsing.parse_money),
        boolean=_ratio(filled, parsing.parse_bool),
        entity_type=_ratio(filled, parsing.parse_entity_type),
        method=_ratio(filled, parsing.parse_method),
        card_type=_ratio(filled, parsing.parse_card_type),
        spacey=(
            sum(1 for value in filled if any(char.isspace() for char in value)) / len(filled)
            if filled
            else 0.0
        ),
        temporal=temporal,
        conflict=conflict,
        samples=tuple(dict.fromkeys(filled))[:SAMPLES],
    )
