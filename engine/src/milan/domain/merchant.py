"""Who this merchant is, worked out from their own settlement rows.

Three facts change what a payout is allowed to look like, and none of them is
a difficulty setting:

* **Section 194-O withholding.** An e-commerce operator has 1% of gross held
  back before the money reaches them. A shop selling its own goods does not.
* **Route.** A merchant with linked accounts pays part of each sale onward,
  and pays 0.1% again for the privilege.
* **Instant settlement.** A payout that lands the day it was captured instead
  of two working days later.

None of them can be assumed, and none of them should have to be asked. A
settlement report states all three, if it is read rather than configured: a
transfer row says `transfer` in its own type column; a same-day payout is a
date beside a date; and a withholding is the gap between what a row was worth
and what it credited.

So this module reads, and where reading is not enough it says so instead of
choosing. `Finding.held is None` is a real answer - it means the rows disagree
with each other, and the one thing worse than asking a merchant a question is
answering it for them wrongly.

The reason this has to exist at all, rather than staying an observation in the
proof: `widest_deduction` in the shortfall rung is derived from the rate card,
and for an operator the widest legitimate deduction is a full percentage point
larger. Get that wrong and a payout short by exactly the tax the government
took reads as a payout short for no reason.

It lives in `domain` rather than `ingest` because it is a fact about the
merchant rather than a step in reading a file. The reconciliation consults it,
the API publishes it, and neither should have to depend on the importer to
learn who it is working for.
"""

from __future__ import annotations

from datetime import date
from typing import Final

from pydantic import BaseModel, ConfigDict

from milan.domain.enums import EntityType
from milan.domain.money import Paise, apply_rate
from milan.domain.rates import RateCard
from milan.domain.records import SettlementRow

__all__ = ["Finding", "MerchantProfile", "profile_of"]

MINIMUM_ROWS: Final = 12
"""Below this, nothing is concluded either way.

The same floor the settlement identity uses, for the same reason. Unanimity
over eight rows is not evidence of a statutory obligation; it is eight rows.
"""

WITHHOLDING: Final = "Section 194-O withholding"
ROUTE: Final = "Route transfers"
INSTANT: Final = "Instant settlement"


class Finding(BaseModel):
    """One fact about the merchant, with the count it was read from.

    `held` is deliberately three-valued. `True` and `False` are conclusions;
    `None` means the rows do not agree with each other, which is neither, and
    is the only case where a person needs to be asked.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    held: bool | None
    rows: int
    of: int
    because: str

    @property
    def settled(self) -> bool:
        """Whether this was concluded rather than left open."""
        return self.held is not None

    @property
    def share(self) -> str:
        """The count and the population it was counted over, never one alone."""
        if not self.of:
            return "no rows to read"
        return f"{self.rows} of {self.of}"


class MerchantProfile(BaseModel):
    """What the files say about the merchant who produced them."""

    model_config = ConfigDict(frozen=True)

    withholding: Finding
    route: Finding
    instant: Finding

    @property
    def findings(self) -> tuple[Finding, ...]:
        return (self.withholding, self.route, self.instant)

    @property
    def questions(self) -> tuple[Finding, ...]:
        """The findings a person still has to settle."""
        return tuple(finding for finding in self.findings if finding.held is None)

    @property
    def named(self) -> tuple[Finding, ...]:
        """Only the facts that turned out to be true of this merchant."""
        return tuple(finding for finding in self.findings if finding.held)

    def rates(self, base: RateCard | None = None) -> RateCard:
        """The rate card this merchant's payouts should be checked against.

        Only withholding reaches the rate card, because it is the only one of
        the three that changes what a *legitimate* payout may be short by.
        Route charges and instant-refund charges are already row-level facts
        the waterfall reads directly, so widening a tolerance for them would
        loosen a check that is currently exact.

        An unsettled finding is treated as withholding. The cost of the two
        mistakes is not symmetric: assuming an operator is not one leaves the
        shortfall band a percentage point too narrow and turns tax into an
        unexplained variance, while assuming a plain merchant is an operator
        widens a band that already refuses when two settlements fit. Neither
        is guessed silently - an unsettled finding is on screen as a question.
        """
        card = base if base is not None else RateCard()
        applies = self.withholding.held is not False
        if card.tds_applies == applies:
            return card
        return card.model_copy(update={"tds_applies": applies})


def profile_of(
    rows: tuple[SettlementRow, ...] | list[SettlementRow], rates: RateCard | None = None
) -> MerchantProfile:
    """Read all three facts off one settlement report."""
    card = rates if rates is not None else RateCard()
    found = tuple(rows)
    return MerchantProfile(
        withholding=_withholding(found, card),
        route=_route(found),
        instant=_instant(found),
    )


def _withholding(rows: tuple[SettlementRow, ...], rates: RateCard) -> Finding:
    """Whether every settled payment is short by exactly the statutory rate.

    Unanimity is the proof and the threshold is not negotiable downwards. One
    row short by 1% of its own gross is a coincidence a fee leak reproduces
    exactly; two hundred of them in a row is a filing obligation.

    A majority that is not unanimous is the interesting case and the one this
    refuses. It is the shape of both a 194-O merchant with a handful of
    anomalous payouts *and* an ordinary merchant being systematically
    overcharged a percent - and those two want opposite responses, one a wider
    tolerance and the other an exception on every affected row.
    """
    paid = tuple(row for row in rows if row.type is EntityType.PAYMENT and row.credit)
    if len(paid) < MINIMUM_ROWS:
        return Finding(
            name=WITHHOLDING,
            held=None if paid else False,
            rows=0,
            of=len(paid),
            because=(
                "no settled payment rows to read it from"
                if not paid
                else f"only {len(paid)} settled payments, and {MINIMUM_ROWS} is the floor"
            ),
        )

    statutory = sum(1 for row in paid if _beyond_the_fee(row) == apply_rate(row.amount, rates.tds))
    if statutory == len(paid):
        return Finding(
            name=WITHHOLDING,
            held=True,
            rows=statutory,
            of=len(paid),
            because=(
                f"every one of {len(paid)} settled payments credits exactly "
                f"{rates.tds:.0%} of its own gross less than its fee and GST account for"
            ),
        )
    if statutory * 2 > len(paid):
        return Finding(
            name=WITHHOLDING,
            held=None,
            rows=statutory,
            of=len(paid),
            because=(
                f"{statutory} of {len(paid)} settled payments are short by exactly "
                f"{rates.tds:.0%} of gross and the rest are not - which is what an "
                "operator with anomalies and a merchant being overcharged both look like"
            ),
        )
    return Finding(
        name=WITHHOLDING,
        held=False,
        rows=statutory,
        of=len(paid),
        because=(
            f"{len(paid) - statutory} of {len(paid)} settled payments credit their "
            "full net, so nothing is being withheld from this merchant"
        ),
    )


def _beyond_the_fee(row: SettlementRow) -> Paise:
    """What came off this row that its fee and GST columns do not account for."""
    return Paise(row.amount - row.fee - row.tax - row.credit)


def _route(rows: tuple[SettlementRow, ...]) -> Finding:
    """Whether any sale was paid on to a linked account.

    The only one of the three needing no inference at all: a Route split is a
    row whose own type column says `transfer`. Reported anyway, because a
    merchant reading a payout smaller than their sales needs the reason named,
    and "part of this was never yours" is the reason.
    """
    transfers = sum(1 for row in rows if row.type is EntityType.TRANSFER)
    if transfers:
        return Finding(
            name=ROUTE,
            held=True,
            rows=transfers,
            of=len(rows),
            because=(
                f"{transfers} rows are typed `transfer` - a share of a sale paid on to "
                "a linked account, charged at 0.1% on top of the platform fee"
            ),
        )
    return Finding(
        name=ROUTE,
        held=False,
        rows=0,
        of=len(rows),
        because="no row in the report is typed `transfer`",
    )


def _instant(rows: tuple[SettlementRow, ...]) -> Finding:
    """Whether any payout landed on the day it was captured.

    Two working days domestic and seven international is the ordinary
    timetable, so a settlement date equal to the capture date is not an early
    payout - it is a different product, paid for separately. Naming it matters
    because the settlement-date window every date-based rung uses is anchored
    on the ordinary timetable, and a merchant on instant settlement breaks
    that anchor for a share of their payouts rather than for all of them.
    """
    dated = tuple(
        (row.created_at.date(), row.settled_at.date())
        for row in rows
        if row.type is EntityType.PAYMENT and row.settled_at is not None
    )
    if not dated:
        return Finding(
            name=INSTANT,
            held=False,
            rows=0,
            of=0,
            because="no payment row carries both a capture date and a settlement date",
        )

    same_day = sum(1 for captured, settled in dated if _same_day(captured, settled))
    if same_day:
        return Finding(
            name=INSTANT,
            held=True,
            rows=same_day,
            of=len(dated),
            because=(
                f"{same_day} of {len(dated)} payments settled on the day they were "
                "captured, rather than the two working days the ordinary cycle takes"
            ),
        )
    return Finding(
        name=INSTANT,
        held=False,
        rows=0,
        of=len(dated),
        because=f"all {len(dated)} payments settled on a later day than they were captured",
    )


def _same_day(captured: date, settled: date) -> bool:
    return captured == settled
