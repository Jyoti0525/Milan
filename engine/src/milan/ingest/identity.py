"""Checking a proposed mapping against the file's own arithmetic.

Every other check in the import is about one column at a time: does this
column hold dates, is this header named like a fee. Those can only ever
narrow a guess, which is why a settlement export with unfamiliar headers came
out as a wall of questions — five money columns, all holding money, and
nothing able to say which was which.

A settlement report can say which is which, because its rows are an equation:

    a payment row:  credit - debit  ==  amount - fee - tax
    a refund row:   credit - debit  == -(amount + fee + tax)

The gateway did that arithmetic when it wrote the file. If a proposed mapping
is right, the equation holds on every row; if `credit` and `debit` are the
wrong way round it fails on every payment row; if `amount` is pointed at a
running balance it fails immediately and enormously.

So a model's proposal for these five columns need not be taken on trust and
need not be put to a person either. It can be *checked* — against the
merchant's own numbers, by the same arithmetic that will later be used to
prove their payouts. That is the whole principle of this codebase applied one
level earlier than usual: a model may propose, only arithmetic may conclude.

Two deliberate limits.

**It proves the set, not each column.** Swap `fee` and `tax` and the equation
still holds, because both are subtracted. The payout arithmetic is unaffected;
the GST figure would be split wrongly between two columns that sum to the same
total. So a verdict here settles the five columns as a group at `unconfirmed`,
which is the certainty that means "checked, not attested" — never `confirmed`.

**Silence is not proof.** A file whose rows cannot be read as numbers, or
which has too few rows to be convincing, returns `holds=False` with a reason.
The caller asks its question. An identity check that cannot run must never
read as an identity check that passed.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from milan.domain.money import Paise
from milan.ingest.parsing import parse_money
from milan.ingest.reading import SourceFile
from milan.ingest.schema import RecordKind

__all__ = ["MONEY_FIELDS", "Verdict", "bank_amount", "check"]

MONEY_FIELDS = ("amount", "fee", "tax", "credit", "debit")
"""The five columns the settlement equation is written over."""

MINIMUM_ROWS = 12
"""Below this the equation is not evidence.

Twelve is not a statistical threshold - it is the point past which a mapping
that satisfies the equation by coincidence stops being plausible. Each row is
an independent five-column constraint; a wrong mapping surviving twelve of
them would need the file to be constructed against us.
"""

SAMPLE = 400
"""Rows read before the verdict is called. A settlement report is large and
the check is not improved by reading all of it."""


@dataclass(frozen=True, slots=True)
class Verdict:
    """Whether the file's own arithmetic supports a proposed mapping."""

    holds: bool
    checked: int
    """Rows the equation was evaluated on."""

    failed: int
    reason: str

    settlement: bool = True
    """Whether `account` should describe the settlement equation. The bank
    check reaches its conclusion by elimination and states its own."""

    @property
    def account(self) -> str:
        """The sentence that goes on screen, and into the saved mapping."""
        if self.holds and self.settlement:
            return (
                f"the arithmetic holds with these columns: credit - debit "
                f"reconstructs amount - fee - tax on all {self.checked} rows checked"
            )
        return self.reason


def _rows(source: SourceFile, columns: dict[str, str]) -> list[dict[str, str]]:
    """The rows to check, refusing a mapping that points two fields at one column.

    Two money fields sharing a column satisfies the equation trivially in some
    arrangements - `fee` and `tax` both aimed at an all-zero column, say - so
    the collision is rejected here rather than being allowed to pass as proof.
    """
    wanted = [columns[name] for name in MONEY_FIELDS]
    if len(set(wanted)) != len(wanted):
        return []
    if any(name not in source.headers for name in wanted):
        return []
    return list(source.rows[:SAMPLE])


def check(source: SourceFile, kind: RecordKind, columns: dict[str, str]) -> Verdict:
    """Whether `columns` satisfies the equation this kind of file is written to.

    `columns` is a full field-to-column mapping. Only the money fields are
    consulted; a mapping missing any of them cannot be checked and is not
    thereby endorsed.
    """
    if kind is not RecordKind.SETTLEMENT_ROWS:
        return Verdict(False, 0, 0, "no arithmetic identity is defined for this kind of file")

    missing = [name for name in MONEY_FIELDS if not columns.get(name)]
    if missing:
        return Verdict(
            False, 0, 0, f"nothing to check against: no column for {', '.join(sorted(missing))}"
        )

    records = _rows(source, columns)
    if len(records) < MINIMUM_ROWS:
        return Verdict(
            False,
            len(records),
            0,
            f"only {len(records)} rows could be read as numbers, which is too few to "
            f"conclude anything from",
        )

    checked = 0
    failed = 0
    for record in records:
        values = {}
        for name in MONEY_FIELDS:
            parsed = parse_money(record[columns[name]])
            if parsed is None:
                break
            values[name] = parsed
        if len(values) != len(MONEY_FIELDS):
            continue

        checked += 1
        net = values["credit"] - values["debit"]
        settled = values["amount"] - values["fee"] - values["tax"]
        recovered = -(values["amount"] + values["fee"] + values["tax"])
        if net != settled and net != recovered:
            failed += 1

    if checked < MINIMUM_ROWS:
        return Verdict(
            False,
            checked,
            failed,
            f"only {checked} rows held numbers in all five columns, which is too few to "
            f"conclude anything from",
        )
    if failed:
        return Verdict(
            False,
            checked,
            failed,
            f"the arithmetic does not hold with these columns: credit - debit does not "
            f"reconstruct amount - fee - tax on {failed} of {checked} rows",
        )
    return Verdict(True, checked, 0, "")


# --------------------------------------------------------- bank statements


def _column_values(source: SourceFile, column: str) -> list[Paise | None]:
    return [parse_money(row.get(column, "")) for row in source.rows[:SAMPLE]]


def _is_running_total(balance: list[Paise | None], movement: list[Paise | None]) -> bool:
    """Whether `balance` is `movement` accumulated.

    The definition of a balance column, stated as arithmetic: each value is
    the one above it plus that row's movement. Checked on the rows where both
    are readable, and only believed if there are enough of them - a column of
    two numbers accumulates trivially.
    """
    steps = 0
    for index in range(1, len(balance)):
        previous, current, moved = balance[index - 1], balance[index], movement[index]
        if previous is None or current is None or moved is None:
            continue
        if current - previous != moved:
            return False
        steps += 1
    return steps >= MINIMUM_ROWS


def _is_counter(column: list[Paise | None]) -> bool:
    """Whether the column climbs by the same step on every row.

    `S No.` in an ICICI export parses as money as readily as the deposit
    column does - it is a number in a column - and it is a row number. What
    separates them is not the header but the shape: real receipts vary, and a
    counter does not. Ruling it out arithmetically keeps the elimination
    honest, where special-casing the name would only work on this one bank.
    """
    steps = {
        current - previous
        for previous, current in pairwise(column)
        if previous is not None and current is not None
    }
    return len(steps) == 1 and steps != {0}


def bank_amount(source: SourceFile, proposed: str, candidates: tuple[str, ...]) -> Verdict:
    """Whether `proposed` is the only column that can be the money that arrived.

    The failure this exists to rule out was written into the resolver as a
    reason *not* to accept a proposal: a statement whose deposit column is
    missing still has exactly one money column in it, and that column is the
    running balance. Taking a model's word there would read a balance as a
    credit and invent an entire month of income.

    It is ruled out by arithmetic rather than by refusing to decide. A balance
    is the column that accumulates the movement beside it, which is checkable;
    a column that is zero on every row is not what arrived, which is also
    checkable. If exactly one candidate survives both and it is the one
    proposed, the proposal is not a guess any more.
    """
    if proposed not in candidates:
        return Verdict(False, 0, 0, f"{proposed} is not one of this file's money columns")

    # A question's choices carry more than columns - the answer meaning "no
    # column here holds it" is one of them - and anything that is not a header
    # in this file cannot be eliminated or endorsed by reading its values.
    real = tuple(name for name in candidates if name in source.headers)
    values = {name: _column_values(source, name) for name in real}
    readable = sum(1 for value in values[proposed] if value is not None)
    if readable < MINIMUM_ROWS:
        return Verdict(
            False, readable, 0, f"only {readable} rows of {proposed} could be read as amounts"
        )

    alive: list[str] = []
    ruled_out: list[str] = []
    for name, column in values.items():
        if not any(value for value in column if value is not None):
            ruled_out.append(f"{name} is zero on every row")
            continue
        if _is_counter(column):
            ruled_out.append(f"{name} counts up by the same step on every row")
            continue
        others = [other for other in real if other != name]
        if any(_is_running_total(column, values[other]) for other in others):
            ruled_out.append(f"{name} is a running balance of the column beside it")
            continue
        alive.append(name)

    if proposed not in alive:
        return Verdict(False, readable, 0, f"{proposed} was ruled out: {'; '.join(ruled_out)}")
    if len(alive) > 1:
        rest = ", ".join(name for name in alive if name != proposed)
        return Verdict(False, readable, 0, f"{proposed} is not the only candidate left: {rest}")

    account = f"it is the only money column left once {' and '.join(ruled_out)}"
    return Verdict(True, readable, 0, account, settlement=False)
