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

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise, permutations

from milan.domain.money import Paise
from milan.ingest.parsing import parse_money, parse_temporal, temporal_patterns
from milan.ingest.reading import SourceFile
from milan.ingest.schema import RecordKind

__all__ = [
    "MONEY_FIELDS",
    "Verdict",
    "bank_amount",
    "check",
    "earliest_date",
    "joined",
    "only_deposit",
    "proven",
    "solve",
]

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


def _evaluate(
    records: Sequence[dict[str, str]], columns: dict[str, str], stop_after: int = 0
) -> tuple[int, int]:
    """Rows the equation could be read on, and rows it failed on.

    `stop_after` abandons a mapping as soon as it has failed that many times.
    A wrong arrangement of the five columns fails on the very first row it can
    be read on, so a search over arrangements spends almost all of its time
    confirming failures it already knows about.
    """
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
            if stop_after and failed >= stop_after:
                return checked, failed
    return checked, failed


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

    checked, failed = _evaluate(records, columns)

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


MOST_UNKNOWN = 3
"""How many of the five money columns may be unknown and still be solved for.

Not a performance limit — the search is small either way. It is the point past
which a unique solution stops being evidence. Two unknowns leave the equation
heavily overdetermined by four hundred rows; five unknowns would be asking the
arithmetic to invent the entire mapping, and a single arrangement surviving
that says more about how few columns the file has than about which is which.
"""

MOST_CANDIDATES = 12
"""Columns considered per unknown. A settlement export has five or six money
columns; a file offering more than twelve is not one this should be guessing
over."""

PROBE = 24
"""Rows a candidate arrangement is tried on before the full sample.

A wrong arrangement fails on the first row it can be read on. Trying two dozen
first turns a search over hundreds of arrangements into one full pass for the
handful that survive.
"""


def solve(
    source: SourceFile,
    kind: RecordKind,
    known: dict[str, str],
    missing: Sequence[str],
    candidates: Sequence[str],
) -> tuple[dict[str, str] | None, Verdict]:
    """The one arrangement of the unknown money columns that the file supports.

    `check` answers "does this mapping hold", which needs a mapping to have
    been proposed. That was the whole of it for as long as a model was assumed
    to be running, and it left the honest configuration — no provider at all —
    asking about a workbook's `Amount Paid In` and `Amount Taken Out` when the
    file could have answered.

    It can answer, because the equation is not a test. It is a constraint, and
    with three of the five columns known there are only so many ways to fill
    the other two — a few hundred, of which the merchant's own rows accept
    exactly one. Swap credit and debit in that solution and every payment row
    breaks; point the gross at a fee and the first row breaks.

    Where more than one arrangement survives, nothing is settled and the
    question stands. That is not a rare corner: `fee` and `tax` are both
    subtracted, so if both are unknown the equation cannot tell them apart and
    two solutions come back. Refusing there is the check working, not failing.
    """
    if kind is not RecordKind.SETTLEMENT_ROWS:
        return None, Verdict(False, 0, 0, "no arithmetic identity is defined for this kind of file")

    wanted = [name for name in MONEY_FIELDS if name in missing]
    if not wanted or len(wanted) > MOST_UNKNOWN:
        return None, Verdict(
            False, 0, 0, f"{len(wanted)} of the five money columns are unknown, which is too many"
        )
    if any(name not in known for name in MONEY_FIELDS if name not in wanted):
        return None, Verdict(
            False, 0, 0, "the money columns that are not in question are not settled either"
        )

    spoken_for = set(known.values())
    free = [
        name
        for name in candidates
        if name in source.headers and name not in spoken_for and _numeric(source, name)
    ]
    if len(free) > MOST_CANDIDATES:
        return None, Verdict(
            False,
            0,
            0,
            f"{len(free)} columns could be any of them, which is too many to conclude from",
        )

    head = list(source.rows[:PROBE])
    records = list(source.rows[:SAMPLE])
    if len(records) < MINIMUM_ROWS:
        return None, Verdict(False, len(records), 0, f"only {len(records)} rows to check against")

    solutions: list[dict[str, str]] = []
    for arrangement in permutations(free, len(wanted)):
        columns = {**known, **dict(zip(wanted, arrangement, strict=True))}
        if _evaluate(head, columns, stop_after=1)[1]:
            continue
        checked, failed = _evaluate(records, columns)
        if failed or checked < MINIMUM_ROWS:
            continue
        solutions.append(columns)
        if len(solutions) > 1:
            break

    if not solutions:
        return None, Verdict(
            False, 0, 0, "no arrangement of these columns reconstructs the file's own arithmetic"
        )
    if len(solutions) > 1:
        return None, Verdict(
            False,
            0,
            0,
            f"more than one arrangement of {', '.join(wanted)} satisfies the equation, "
            f"so the file cannot say which",
        )

    columns = solutions[0]
    checked, _ = _evaluate(records, columns)
    return {name: columns[name] for name in wanted}, Verdict(True, checked, 0, "")


def _numeric(source: SourceFile, column: str) -> bool:
    """Whether enough of a column reads as money to be worth arranging."""
    read = sum(1 for value in _column_values(source, column) if value is not None)
    return read >= MINIMUM_ROWS


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


def _eliminate(source: SourceFile, candidates: Sequence[str]) -> tuple[list[str], list[str]]:
    """The columns that could be money arriving, and why the others could not.

    Three ways a column of numbers on a bank statement is not what landed in
    the account, each checkable without knowing anything about this bank:

    A **running balance** is the column that accumulates the one beside it.
    This is the case that matters most, because a statement whose deposit
    column is absent still has exactly one money column in it and that column
    is the balance — reading it as a credit would invent a month of income.

    A **counter** climbs by the same step on every row. ICICI's `S No.` parses
    as money as readily as its deposit column does, and it is a row number;
    what separates them is not the header but the shape, since real receipts
    vary and a counter does not.

    A column that is **zero on every row** is not money that arrived. A
    statement covering a month of payouts and no withdrawals writes its debit
    column as zeros, which is true and is not a credit.

    Returns what survives and the sentences for what did not, so the caller
    can say either "this is the one left" or "the one you named was ruled out
    because —". Both are the same reasoning and they are told differently.
    """
    # A question's choices carry more than columns - the answer meaning "no
    # column here holds it" is one of them - and anything that is not a header
    # in this file cannot be eliminated or endorsed by reading its values.
    real = tuple(name for name in candidates if name in source.headers)
    values = {name: _column_values(source, name) for name in real}

    alive: list[str] = []
    ruled_out: list[str] = []
    for name, column in values.items():
        if sum(1 for value in column if value is not None) < MINIMUM_ROWS:
            ruled_out.append(f"{name} could not be read as amounts")
            continue
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
    return alive, ruled_out


def _readable(source: SourceFile, column: str) -> int:
    return sum(1 for value in _column_values(source, column) if value is not None)


def only_deposit(source: SourceFile, candidates: Sequence[str]) -> tuple[str | None, Verdict]:
    """The one column on this statement that can be money arriving, if there is one.

    Elimination does not need something to check. It needs a list of columns
    and the file, and it either finishes with one standing or it does not - so
    this is the whole of the reasoning, and `bank_amount` is the same thing
    asked about a particular column.

    Written this way round because the useful case turned out to be the one
    with nothing to check. An ICICI export names its deposit column `Deposit
    Amount (INR )`, which the schema does not know, and with no model running
    there was no proposal to endorse and the import asked. The arithmetic that
    would have settled it was already there and was reachable only through a
    guess it did not need.
    """
    alive, ruled_out = _eliminate(source, candidates)
    if not alive:
        return None, Verdict(
            False, 0, 0, f"every candidate was ruled out: {'; '.join(ruled_out)}", settlement=False
        )
    if len(alive) > 1:
        return None, Verdict(
            False, 0, 0, f"more than one candidate is left: {', '.join(alive)}", settlement=False
        )

    survivor = alive[0]
    account = f"it is the only money column left once {' and '.join(ruled_out)}"
    return survivor, Verdict(True, _readable(source, survivor), 0, account, settlement=False)


def bank_amount(source: SourceFile, proposed: str, candidates: tuple[str, ...]) -> Verdict:
    """Whether `proposed` is the only column that can be the money that arrived.

    The same elimination, asked about one column rather than asked to name
    one. It exists because a wrong answer here is the expensive kind: taking a
    running balance for a credit reads a subtotal as income, and every figure
    downstream stays internally consistent while describing a month that did
    not happen.
    """
    if proposed not in candidates:
        return Verdict(False, 0, 0, f"{proposed} is not one of this file's money columns")

    readable = _readable(source, proposed)
    if readable < MINIMUM_ROWS:
        return Verdict(
            False, readable, 0, f"only {readable} rows of {proposed} could be read as amounts"
        )

    alive, ruled_out = _eliminate(source, candidates)
    if proposed not in alive:
        return Verdict(False, readable, 0, f"{proposed} was ruled out: {'; '.join(ruled_out)}")
    if len(alive) > 1:
        rest = ", ".join(name for name in alive if name != proposed)
        return Verdict(False, readable, 0, f"{proposed} is not the only candidate left: {rest}")

    account = f"it is the only money column left once {' and '.join(ruled_out)}"
    return Verdict(True, readable, 0, account, settlement=False)


PROOFS = (
    "the arithmetic holds",
    "it is the only money column left",
    "it is the only column that never runs ahead",
    "every value in it is an identifier",
)
"""The openings of the two accounts this module writes.

Matched as prefixes rather than carried as a flag on the resolution, because
the sentence is what reaches the screen and the saved mapping. A flag could
drift from the words beside it; a prefix cannot.
"""


def proven(reason: str) -> bool:
    """Whether this column was settled by the file's own arithmetic."""
    return reason.startswith(PROOFS)


# ------------------------------------------------------------ dates in order


STRICTLY_EARLIER = 0.5
"""How much of a date column must fall *before* the one it is checked against.

A column that merely never exceeds `settled_at` could be `settled_at` itself,
copied. Requiring that half the rows are strictly earlier separates the two
without demanding it of every row - a payment captured and settled on the same
day is ordinary, and an instant settlement makes every row that shape.
"""


def _dates(source: SourceFile, column: str) -> list[datetime | None]:
    """A column read as dates, under whichever known pattern reads most of it.

    The pattern is not known here. A resolved field carries one, but a
    candidate being *considered* has never been settled, so the format has to
    be found before the values can be compared - and the format that reads the
    most rows is the format the column is written in.
    """
    raw = tuple(row.get(column, "") for row in source.rows[:SAMPLE])
    best: list[datetime | None] = []
    for pattern in temporal_patterns():
        read = [parse_temporal(value, pattern) for value in raw]
        if sum(1 for value in read if value is not None) > sum(
            1 for value in best if value is not None
        ):
            best = read
    return best


def earliest_date(
    source: SourceFile, after: str, candidates: Sequence[str]
) -> tuple[str | None, Verdict]:
    """The one column that can be what happened before `after`, if there is one.

    A settlement report states a second identity beside the money one, and it
    is about time rather than amounts: a payment is captured before it is paid
    out. Never after. The gateway cannot settle money it has not yet taken.

    So `created_at` is not a guess to weigh against `settled_at` - it is the
    column that comes first, and any column that ever runs ahead of the payout
    date is disqualified by the file's own rows. Where exactly one candidate
    survives that and it is the one proposed, the proposal has been checked
    rather than trusted.

    Two things this does not do. It does not order two columns that are both
    always earlier - a capture date and an authorisation date differ by
    seconds and both precede settlement, and picking between them is a fact
    about the gateway rather than about the file. And it says nothing about a
    bank statement's value date against its transaction date, which is that
    same unresolvable pair one level down.
    """
    if after not in source.headers:
        return None, Verdict(False, 0, 0, f"{after} is not a column in this file", settlement=False)

    payout = _dates(source, after)
    real = [name for name in candidates if name in source.headers and name != after]

    alive: list[tuple[str, int]] = []
    for name in real:
        column = _dates(source, name)
        pairs = [
            (value, settled)
            for value, settled in zip(column, payout, strict=False)
            if value is not None and settled is not None
        ]
        if len(pairs) < MINIMUM_ROWS:
            continue
        if any(value > settled for value, settled in pairs):
            continue
        earlier = sum(1 for value, settled in pairs if value < settled)
        if earlier < len(pairs) * STRICTLY_EARLIER:
            continue
        alive.append((name, len(pairs)))

    if not alive:
        return None, Verdict(
            False,
            0,
            0,
            f"every date column here runs ahead of {after} on some row, or is never earlier",
            settlement=False,
        )
    if len(alive) > 1:
        names = ", ".join(name for name, _ in alive)
        return None, Verdict(
            False,
            0,
            0,
            f"more than one column always precedes {after}: {names}",
            settlement=False,
        )

    name, checked = alive[0]
    return name, Verdict(
        True,
        checked,
        0,
        f"it is the only column that never runs ahead of {after}, on all {checked} rows checked",
        settlement=False,
    )


# ---------------------------------------------------- the same IDs elsewhere


CONTAINED = 0.98
"""How much of a column must be found in the reference set to be called it.

Not 1.0, because a real folder is not a closed world - a settlement report
covering July can settle a payment captured on the last day of June, which a
July payments export does not contain. Not 0.9 either: the column this has to
be told apart from is `entity_id`, which on a settlement report *is* the
payment id on payment rows and is a refund or adjustment id on the others.
That column matches around four fifths, so the gap between the two is wide and
the threshold sits inside it rather than near either edge.
"""


def joined(
    source: SourceFile,
    known: frozenset[str],
    taken: frozenset[str],
) -> tuple[str | None, Verdict]:
    """The one column whose values are identifiers from another file's column.

    This is the only check here that reads outside the file it is deciding
    about, and it is the one that has to. An identifier column cannot be
    recognised from its own values: `Merchant Ref`, `Order Ref` and `Txn Ref
    No` are three columns of opaque strings, and nothing about the shape of
    `pay_S3kQ1nZ8vM2xLd` says which field it belongs to.

    What does say so is another file. A payments export names its own
    `payment_id` column in words the schema already knows, so the set of
    payment ids in this folder is a fact rather than a guess - and a column of
    the merchant's whose values are all drawn from that set is the payment id,
    whatever its header calls it.

    Nothing about a model is involved, which is the point. This runs with no
    provider and settles columns that were previously given up on: an
    unfamiliar export used to import with its `payment_id` marked absent while
    the column sat there in the file, and every downstream check that needed
    it went without.

    Returns the column and the verdict behind it, or `None` and the reason
    there is no answer. Candidates already assigned to another field are not
    considered, so proving one identifier cannot steal the column that proved
    another.
    """
    if len(known) < MINIMUM_ROWS:
        return None, Verdict(
            False,
            0,
            0,
            f"only {len(known)} known identifiers to compare against",
            settlement=False,
        )

    matches: list[tuple[str, int, int]] = []
    for header in source.headers:
        if header in taken:
            continue
        values = {
            value.strip() for row in source.rows[:SAMPLE] if (value := row.get(header, "")).strip()
        }
        if len(values) < MINIMUM_ROWS:
            continue
        found = len(values & known)
        if found >= len(values) * CONTAINED:
            matches.append((header, found, len(values)))

    if not matches:
        return None, Verdict(
            False, 0, 0, "no column here holds those identifiers", settlement=False
        )
    if len(matches) > 1:
        names = ", ".join(name for name, _, _ in matches)
        return None, Verdict(
            False,
            0,
            0,
            f"more than one column holds those identifiers: {names}",
            settlement=False,
        )

    header, found, total = matches[0]
    return header, Verdict(
        True,
        total,
        0,
        f"every value in it is an identifier another file names in its own header "
        f"({found} of {total} matched)",
        settlement=False,
    )
