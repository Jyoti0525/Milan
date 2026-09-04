"""How wrong the schedule turned out to be.

A schedule that cannot be graded is a claim, and this project does not ship
claims. `milan.forecast.schedule` is built from payments captured on or
before one day and settlement rows already paid by it; this module takes that
schedule and the *complete* settlement report - the half the schedule was
never allowed to read - and reports the gap.

Two kinds of wrong, kept apart because they cost a merchant different things:

* **Date error.** The money arrived, on a different day. A payout that lands
  a day late is a nuisance; one that lands a day early is not an error a
  merchant will ever complain about, which is why the count is signed rather
  than absolute.
* **Amount error.** The money arrived, and less of it than the fee stack said
  it would. This is the number that would quietly become a leak if nobody
  measured it.

And one that is neither: **money that never arrived at all**. A payment the
settlement report never mentions is not a mis-dated payout, it is a payout
that does not exist, and folding it into a date distribution would let the
most serious failure in the set improve the average. It is counted on its
own and its rupees are reported beside the rest.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import date

from pydantic import BaseModel, ConfigDict

from milan.domain.calendar import working_days_between
from milan.domain.enums import EntityType
from milan.domain.money import ZERO, Paise
from milan.domain.records import SettlementRow
from milan.forecast.schedule import Schedule

__all__ = ["Accuracy", "Landed", "grade"]


class Landed(BaseModel):
    """One dated commitment, against what the report eventually said."""

    model_config = ConfigDict(frozen=True)

    payment_id: str
    due: date
    predicted: Paise

    landed_on: date | None
    actual: Paise
    """What the settlement row credited. Zero when nothing ever settled."""

    @property
    def arrived(self) -> bool:
        return self.landed_on is not None

    @property
    def days_out(self) -> int | None:
        """Working days between the predicted date and the real one.

        Positive is late, negative is early, `None` is money that never came.
        """
        if self.landed_on is None:
            return None
        return working_days_between(self.due, self.landed_on)

    @property
    def error(self) -> Paise:
        """Actual minus predicted. Negative means the payout was short."""
        return Paise(self.actual - self.predicted)


class Accuracy(BaseModel):
    """What a schedule got right, over the commitments it dated."""

    model_config = ConfigDict(frozen=True)

    as_of: date
    checked: tuple[Landed, ...]

    @property
    def total(self) -> int:
        return len(self.checked)

    @property
    def arrived(self) -> tuple[Landed, ...]:
        return tuple(item for item in self.checked if item.arrived)

    @property
    def never_arrived(self) -> tuple[Landed, ...]:
        """The honest exception list of the forecast."""
        return tuple(item for item in self.checked if not item.arrived)

    @property
    def dated_exactly(self) -> float:
        """Share of *all* commitments that landed on the day predicted.

        Measured over everything dated, not over everything that arrived. A
        payment that never settled was dated wrongly in the only sense a
        merchant cares about, and moving it out of the denominator would let
        a report of missing money raise the score.
        """
        return self._share(lambda item: item.days_out == 0)

    @property
    def within_a_working_day(self) -> float:
        return self._share(lambda item: item.days_out is not None and abs(item.days_out) <= 1)

    @property
    def predicted(self) -> Paise:
        return Paise(sum(item.predicted for item in self.checked))

    @property
    def landed(self) -> Paise:
        return Paise(sum(item.actual for item in self.checked))

    @property
    def error(self) -> Paise:
        """Signed. Negative means the merchant received less than scheduled."""
        return Paise(self.landed - self.predicted)

    @property
    def error_on_arrivals(self) -> Paise:
        """The same figure over money that actually came.

        Reported beside `error` rather than instead of it, because the two
        answer different questions. This one asks whether the fee arithmetic
        is right; the other asks whether the merchant got the money.
        """
        arrived = self.arrived
        return Paise(sum(item.actual - item.predicted for item in arrived))

    @property
    def missing(self) -> Paise:
        return Paise(sum(item.predicted for item in self.never_arrived))

    @property
    def money_on_the_day(self) -> float:
        """Share of scheduled rupees that arrived on the scheduled day.

        The figure a merchant would use, and always the harsher of the two
        rates when the misses cluster on large payments - which is the case a
        count of transactions is blind to.
        """
        if self.predicted <= 0:
            return 0.0
        hit = sum(item.predicted for item in self.checked if item.days_out == 0)
        return hit / self.predicted

    @property
    def to_the_paisa(self) -> float:
        """Share of arrivals whose amount was right to the last paisa."""
        arrived = self.arrived
        if not arrived:
            return 0.0
        return sum(1 for item in arrived if item.error == ZERO) / len(arrived)

    def _share(self, holds: Callable[[Landed], bool]) -> float:
        if not self.checked:
            return 0.0
        return sum(1 for item in self.checked if holds(item)) / len(self.checked)


def grade(schedule: Schedule, rows: tuple[SettlementRow, ...]) -> Accuracy:
    """Check a schedule against the settlement report it could not see.

    `rows` is the complete report, including everything settled after the
    schedule's `as_of`. That is the point: the schedule was built from one
    half of the month and is being marked against the other.
    """
    outcomes = _outcomes(rows)
    nothing: tuple[date | None, Paise] = (None, ZERO)
    checked: list[Landed] = []
    for landing in schedule.landings:
        for item in landing.commitments:
            landed_on, actual = outcomes.get(item.payment_id, nothing)
            checked.append(
                Landed(
                    payment_id=item.payment_id,
                    due=item.due,
                    predicted=item.net,
                    landed_on=landed_on,
                    actual=actual,
                )
            )
    return Accuracy(as_of=schedule.as_of, checked=tuple(checked))


def _outcomes(rows: tuple[SettlementRow, ...]) -> dict[str, tuple[date, Paise]]:
    """What the report eventually said about each settled payment.

    Payment rows only. A refund row carries the `payment_id` of the sale it
    reverses, so indexing every row by that column marks the refunded payment
    as having settled on the refund's date for the refund's negative amount -
    grading a correct forecast as both mis-dated and short by the whole
    payout. It read as an 11% date error on the seeds it hit, and it was a
    property of the grader rather than of anything being graded.

    Keyed by both identifiers a payment row may be found under, for the same
    reason the schedule reads both: an export that populates only `entity_id`
    would otherwise grade every commitment as money that never arrived, and a
    perfect forecast would score zero.
    """
    routed: dict[str, Paise] = defaultdict(lambda: ZERO)
    for row in rows:
        # A Route transfer leaves in the same payout as the payment it was
        # taken from, so a payment's true contribution to what reaches the
        # bank is its own credit less whatever was paid onward out of it.
        # Grading against the credit alone would score a schedule that
        # correctly nets the split as short by exactly the split.
        if row.type is EntityType.TRANSFER and row.payment_id is not None:
            routed[row.payment_id] = Paise(routed[row.payment_id] + row.debit)

    found: dict[str, tuple[date, Paise]] = {}
    for row in rows:
        if row.type is not EntityType.PAYMENT or row.settled_at is None:
            continue
        landed = Paise(row.signed_net - routed.get(row.entity_id, ZERO))
        if row.payment_id is not None:
            landed = Paise(row.signed_net - routed.get(row.payment_id, ZERO))
        outcome = (row.settled_at.date(), landed)
        found[row.entity_id] = outcome
        if row.payment_id is not None:
            found[row.payment_id] = outcome
    return found
