"""Money already captured, dated forward.

This is the only part of Milan that talks about the future, and it earns the
right to by never predicting anything. Nothing here estimates sales, fits a
trend or extrapolates a run rate. It reads payments the merchant has already
taken, applies Razorpay's published settlement cycle to each capture
timestamp, applies the merchant's own fee stack to each amount, and prints
the dates that fall out.

The distinction is the whole design. A forecast says what is likely; a
schedule says what is owed and when it is due. One of those can be wrong
about the world; the other can only be wrong about arithmetic, and arithmetic
is the only thing this project lets conclude anything.

**What it is allowed to read.** Only what the merchant would actually hold on
`as_of`: payments captured on or before that day, and settlement rows that
had already been paid by it. A row the gateway will write next Tuesday is not
evidence available today, and using it would turn the schedule into a copy of
the answer rather than a derivation of it. That restriction is what makes
`milan.forecast.accuracy` a real measurement instead of a tautology.

**Three buckets, and the last two are the honest ones.**

* `landings` - captured money with a due date still ahead. Dated arithmetic.
* `overdue` - captured money whose due date has passed with no payout behind
  it. Not a forecast at all: it is the reconciliation queue seen from the
  other side, and it is here so that a total labelled "coming" never quietly
  includes money that should already have come.
* `undated` - money the files prove exists and give no date for. A refund
  waiting for a payout large enough to absorb it, or a row the gateway has
  flagged on hold. Both are real cash effects with no derivable date, and the
  correct output for a date that cannot be derived is no date.

**What it cannot see, stated rather than hidden.** Three things move a real
payout, and two of them turned out to be reachable once they were measured
rather than assumed:

1. *Instant settlement.* Not a blind spot. A payout pulled early carries a
   settlement row dated the day of capture, so by the time a schedule is
   drawn that money is already in the bank - it is left out rather than
   mis-dated. Measured at 40% and 80% instant: no date error at all.
2. *Route.* Handled, and it belongs here rather than in the caveats because a
   transfer row is written when the payment is *captured*. The merchant is
   already holding it on `as_of`, so netting it reads no future row and
   guesses no date - a split leaves in the same payout as the payment it came
   out of. Exact through a 60% Route share.
3. *Refunds still to be raised.* The one that stays. A customer who asks for
   their money back tomorrow reduces a payout this schedule has already
   dated, and no arithmetic reaches a decision nobody has made yet. Refunds
   that already exist are in `undated`. Ones that do not are not forecastable,
   and this refuses to forecast them - which is the same refusal the whole
   module is built on, not an omission.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from pydantic import BaseModel, ConfigDict

from milan.domain.calendar import (
    DOMESTIC_SETTLEMENT_DAYS,
    INTERNATIONAL_SETTLEMENT_DAYS,
    settlement_due,
)
from milan.domain.enums import CardType, EntityType
from milan.domain.money import ZERO, Paise
from milan.domain.rates import RateCard, compute_deductions
from milan.domain.records import Payment, SettlementRow
from milan.recon.inputs import ReconInput

__all__ = [
    "Commitment",
    "Landing",
    "Schedule",
    "Undated",
    "last_capture",
    "schedule_from",
]


class Commitment(BaseModel):
    """One captured payment, with the date and amount its cycle implies."""

    model_config = ConfigDict(frozen=True)

    payment_id: str
    captured_on: date
    due: date
    cycle_days: int
    """2 or 7. Carried so a date can explain itself: an international card
    sitting a week out is not the same fact as a domestic one running late."""

    gross: Paise
    net: Paise

    routed: Paise = ZERO
    """Paid onward to a linked account through Route, with its commission.

    Its own field rather than folded into the deductions, because it is not a
    deduction. A fee is the merchant's money going to the gateway; a Route
    split is a share of the sale that was never the merchant's to begin with,
    and the proof layer gives it a separate line for exactly this reason.

    Knowable on the day, which is why it can be here at all: a transfer row is
    written when the payment is captured, not when the payout runs, so a
    merchant standing on `as_of` is already holding it. Nothing about a future
    settlement is read to find it.
    """

    @property
    def deducted(self) -> Paise:
        """Fee, GST and any withholding. Not the Route split - see `routed`."""
        return Paise(self.gross - self.net - self.routed)


class Landing(BaseModel):
    """Everything due to reach the bank on one date."""

    model_config = ConfigDict(frozen=True)

    on: date
    commitments: tuple[Commitment, ...]

    @property
    def net(self) -> Paise:
        return Paise(sum(item.net for item in self.commitments))

    @property
    def gross(self) -> Paise:
        return Paise(sum(item.gross for item in self.commitments))

    @property
    def routed(self) -> Paise:
        return Paise(sum(item.routed for item in self.commitments))

    @property
    def count(self) -> int:
        return len(self.commitments)


class Undated(BaseModel):
    """A cash effect the files prove and give no date for.

    `amount` is signed from the merchant's point of view, so a refund waiting
    to be recovered is negative and money the gateway is holding is positive.
    Refusing to date these is the point of the class: a refund lands in
    whichever payout is next large enough to absorb it, and which one that
    will be depends on sales that have not happened.
    """

    model_config = ConfigDict(frozen=True)

    subject_id: str
    kind: str
    amount: Paise
    because: str


class Schedule(BaseModel):
    """What the files say is coming, as of one day."""

    model_config = ConfigDict(frozen=True)

    as_of: date
    landings: tuple[Landing, ...]
    overdue: tuple[Commitment, ...]
    undated: tuple[Undated, ...]

    @property
    def committed(self) -> Paise:
        """The dated total. What is coming, and only what is coming."""
        return Paise(sum(landing.net for landing in self.landings))

    @property
    def gross(self) -> Paise:
        return Paise(sum(landing.gross for landing in self.landings))

    @property
    def routed(self) -> Paise:
        """Money in these payouts that is paid straight on to somebody else."""
        return Paise(sum(landing.routed for landing in self.landings))

    @property
    def deducted(self) -> Paise:
        return Paise(self.gross - self.committed - self.routed)

    @property
    def overdue_net(self) -> Paise:
        return Paise(sum(item.net for item in self.overdue))

    @property
    def undated_net(self) -> Paise:
        return Paise(sum(item.amount for item in self.undated))

    @property
    def payments(self) -> int:
        return sum(landing.count for landing in self.landings)

    @property
    def horizon(self) -> date | None:
        """The last date anything is due. `None` when nothing is."""
        return self.landings[-1].on if self.landings else None

    def through(self, day: date) -> Paise:
        """The dated total arriving on or before `day`.

        Cumulative rather than per-day because the question a merchant
        actually asks is whether a bill falling on Friday is covered, and
        that is a running total, not a bar on a chart.
        """
        return Paise(sum(landing.net for landing in self.landings if landing.on <= day))


def last_capture(payments: tuple[Payment, ...] | list[Payment]) -> date | None:
    """The most recent day the merchant took money.

    The default `as_of`, and deliberately read off the files rather than from
    a clock. A run archived in July and opened in September should describe
    the same day it described when it was written; a schedule that moved
    because somebody came back to it later would be reporting the calendar
    rather than the books.
    """
    return max((payment.captured_at.date() for payment in payments), default=None)


def schedule_from(data: ReconInput, rates: RateCard, as_of: date | None = None) -> Schedule:
    """Date every rupee already captured and not yet paid out.

    `as_of` defaults to the merchant's last capture, which is the day their
    own files describe. Passing an earlier date is how the accuracy harness
    works: it asks for a schedule from halfway through the month and then
    checks it against the second half, which the schedule was not allowed to
    read.
    """
    when = as_of if as_of is not None else last_capture(data.payments)
    if when is None:
        return Schedule(as_of=date.min, landings=(), overdue=(), undated=())

    settled = _settled_by(data.settlement_rows, when)
    routed = _routed_by(data.settlement_rows, when)
    dated: list[Commitment] = []
    late: list[Commitment] = []

    for payment in data.payments:
        captured = payment.captured_at.date()
        if captured > when or payment.payment_id in settled:
            continue
        commitment = _commitment(payment, rates, routed.get(payment.payment_id, ZERO))
        (dated if commitment.due > when else late).append(commitment)

    return Schedule(
        as_of=when,
        landings=_group(dated),
        overdue=tuple(sorted(late, key=lambda item: (item.due, item.payment_id))),
        undated=_undatable(data.settlement_rows, when),
    )


# ----------------------------------------------------------------- internals


def _commitment(payment: Payment, rates: RateCard, routed: Paise) -> Commitment:
    """One payment's date and net, both derived rather than looked up."""
    deductions = compute_deductions(payment.amount, payment.method, payment.card_type, rates)
    captured = payment.captured_at.date()
    return Commitment(
        payment_id=payment.payment_id,
        captured_on=captured,
        due=settlement_due(captured, payment.card_type),
        cycle_days=(
            INTERNATIONAL_SETTLEMENT_DAYS
            if payment.card_type is CardType.INTERNATIONAL
            else DOMESTIC_SETTLEMENT_DAYS
        ),
        gross=payment.amount,
        net=Paise(deductions.net - routed),
        routed=routed,
    )


def _routed_by(rows: tuple[SettlementRow, ...], when: date) -> dict[str, Paise]:
    """Route splits already taken against payments, as of `when`.

    A transfer leaves with the money it was taken from rather than rolling
    into a later payout, so it needs no date of its own - it reduces the
    payout its payment is already scheduled into. That is what makes it
    datable when a refund is not.

    Read on `created_at`, which is the capture, never on `settled_at`, which
    is a future payout the merchant does not yet hold. The whole `debit` is
    taken because it is the whole cash impact: the amount paid onward, the
    0.1% commission on it, and the GST on that commission.
    """
    routed: dict[str, Paise] = defaultdict(lambda: ZERO)
    for row in rows:
        if row.type is not EntityType.TRANSFER or row.payment_id is None:
            continue
        if row.created_at.date() > when:
            continue
        routed[row.payment_id] = Paise(routed[row.payment_id] + row.debit)
    return dict(routed)


def _settled_by(rows: tuple[SettlementRow, ...], when: date) -> frozenset[str]:
    """Payments the report shows already paid out on or before `when`.

    Rows dated after `when` are ignored on purpose. They exist in the file
    this function is handed, and a merchant standing on `when` would not have
    them, so reading one would let the schedule quietly know the answer it is
    supposed to be deriving.

    Only payment rows count, and that restriction is load-bearing rather than
    tidy. A refund row carries the `payment_id` of the sale it reverses, so a
    reader that indexed every row by that column would treat a refunded
    payment as already paid out - and quietly drop from the schedule the one
    payment whose payout is most worth watching.

    Both identifiers are collected off the rows that do count, because a
    settlement report identifies a payment row by `entity_id` and carries
    `payment_id` beside it, and a real export is not guaranteed to populate
    both.
    """
    paid: set[str] = set()
    for row in rows:
        if row.type is not EntityType.PAYMENT:
            continue
        if row.settled_at is None or row.settled_at.date() > when:
            continue
        paid.add(row.entity_id)
        if row.payment_id is not None:
            paid.add(row.payment_id)
    return frozenset(paid)


def _group(commitments: list[Commitment]) -> tuple[Landing, ...]:
    """Collapse commitments into one entry per date, earliest first."""
    by_day: dict[date, list[Commitment]] = defaultdict(list)
    for item in commitments:
        by_day[item.due].append(item)
    return tuple(
        Landing(
            on=day,
            commitments=tuple(sorted(by_day[day], key=lambda item: item.payment_id)),
        )
        for day in sorted(by_day)
    )


def _undatable(rows: tuple[SettlementRow, ...], when: date) -> tuple[Undated, ...]:
    """Known cash effects with no date the files support.

    Two shapes, and both are ordinary rather than exotic. A gateway does not
    send a negative payout, so a refund larger than the batch it should have
    come out of rolls forward until a batch can absorb it - and which batch
    that turns out to be depends on sales nobody has made yet. A row flagged
    on hold is money the gateway has and is not releasing, with no release
    date anywhere in the export.

    Rows created after `when` are excluded for the same reason future
    settlement rows are: the merchant does not have them yet.
    """
    found = [
        Undated(
            subject_id=row.entity_id,
            kind=row.type.value,
            amount=row.signed_net,
            because=_why_undated(row),
        )
        for row in rows
        if row.created_at.date() <= when and row.settled_at is None and row.signed_net != ZERO
    ]
    return tuple(sorted(found, key=lambda item: item.subject_id))


def _why_undated(row: SettlementRow) -> str:
    if row.on_hold:
        return "on hold at the gateway, with no release date anywhere in the report"
    match row.type:
        case EntityType.REFUND:
            return "netted out of the next payout large enough to absorb it, which is not yet known"
        case EntityType.ADJUSTMENT:
            return "recovered from a future payout the gateway has not named"
        case _:
            return "reported without a settlement date"
