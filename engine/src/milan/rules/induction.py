"""Learning a merchant's fee stack from their own history.

The last item named in the original build plan and never built. Everything
else in this engine that needs a rate card is either handed one or falls back
to Razorpay's published pricing - which is fine for a graded run, where the
contract is known and holding it fixed is what keeps a measured number
comparable, and useless for the case the project actually claims to serve.
A merchant brings three files. Nobody brings a rate card.

**Why it was deferred, and what the resolution is.** Learning the rate from
the rows and then checking the rows against it is circular: whatever the
gateway charged becomes, by construction, what the gateway was contracted to
charge, and `milan.leaks` - the finding this project is proudest of - would
go silent on every merchant it was pointed at.

The way out is that an overcharge is a minority. A merchant contracted at 2%
and charged 2.15% on some of their cards has most of their rows at 2%, so the
*modal* rate over a group is the contracted one and the rows that disagree are
the leak. That is not an assumption about the world dressed up as arithmetic;
it is a stated condition, and `milan.rules.induction` refuses out loud when it
does not hold. A group whose rows split evenly between two rates has not told
anybody which one is the contract, and saying so is the only honest output.

**It reads groups the report itself declares**, never groups it invents. A
settlement row states its method and its card type, and those columns are what
Razorpay's pricing actually varies on - so the induction is asking "what were
rows like this one charged", not "what clusters can I find". Two rates the
merchant genuinely holds are two findings, not one averaged answer.

**Every rate must reproduce the fee to the paisa.** A modal rate that only
approximately explains its own group is not a contract, it is a line of best
fit, and `apply_rate` is the same function the fee was computed with. The
count reported beside each finding is of rows the rate reproduces exactly,
never of rows that merely voted for it.

The output is deliberately the same shape as `milan.domain.merchant`: findings
with counts and populations, three-valued, and a `card()` that falls back to
the published rate wherever nothing was concluded. Nothing here silently
replaces a rate somebody stated.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from pydantic import BaseModel, ConfigDict

from milan.domain.enums import CardType, EntityType, PaymentMethod
from milan.domain.money import Paise, apply_rate
from milan.domain.rates import RateCard
from milan.domain.records import SettlementRow

__all__ = ["Band", "InducedRates", "RateFinding", "induce_rates"]

MINIMUM_ROWS: Final = 12
"""Below this, nothing is concluded about a group.

The same floor `milan.domain.merchant` uses, for the same reason. Eight rows
agreeing on a rate is eight rows, not a contract - and the groups this splits
into are uneven by nature, because a merchant takes far more UPI than
international cards. The small groups are exactly the ones where a confident
wrong rate would do the most damage, since a rate card built from them then
governs the leak check on every row of that kind.
"""

DOMINANT: Final = Decimal("0.6")
"""Share of a group its modal rate must reproduce before it is a conclusion.

The stated condition this whole module rests on: an overcharge is a minority.
Set well above a bare majority because the failure it guards is not noise, it
is a merchant who genuinely holds two rates - and for them the right answer is
a question, not the more popular of the two.
"""

GRANULARITY: Final = Decimal("0.0001")
"""One hundredth of a percent - the resolution rates are voted on at.

Fees are rounded to the paisa before anybody sees them, so the rate read back
off a row is only approximate and two rows on the identical contract disagree
in the sixth decimal place. Rounding the vote is what lets them agree; the
exactness is then recovered by requiring the winner to reproduce each fee.
"""

_STANDARD = "Standard rate"
_CONSUMER = "Domestic consumer cards"
_CORPORATE = "Domestic corporate cards"
_INTERNATIONAL = "International cards"
_GST = "GST on the fee"


class Band(BaseModel):
    """One kind of row, as the settlement report itself labels it."""

    model_config = ConfigDict(frozen=True)

    name: str
    method: PaymentMethod | None
    """`None` means every non-card method, which share one contracted rate."""

    card_type: CardType | None


class RateFinding(BaseModel):
    """What one band of rows was charged, or that they would not say.

    `rate` is three-valued exactly as `merchant.Finding.held` is. A rate is a
    conclusion; `None` is not "we found nothing", it is "these rows do not
    agree with each other", which is a different message and the only one that
    should ever reach a person as a question.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    rate: Decimal | None
    rows: int
    """Rows the rate reproduces to the paisa. Never rows that merely voted."""

    of: int
    because: str

    @property
    def settled(self) -> bool:
        return self.rate is not None

    @property
    def share(self) -> str:
        """The count and the population it was counted over, never one alone."""
        if not self.of:
            return "no rows to read"
        return f"{self.rows} of {self.of}"

    @property
    def disagreeing(self) -> int:
        """Rows this rate does not explain.

        On a settled finding these are candidate overcharges rather than
        noise, which is the whole reason the induction is safe to run against
        the leak check: it hands over the majority rate and leaves the
        minority to be reported, instead of absorbing them into a contract.
        """
        return self.of - self.rows


class InducedRates(BaseModel):
    """A merchant's fee stack, read off their own settlement report."""

    model_config = ConfigDict(frozen=True)

    standard: RateFinding
    consumer_card: RateFinding
    corporate_card: RateFinding
    international_card: RateFinding
    gst: RateFinding

    @property
    def findings(self) -> tuple[RateFinding, ...]:
        return (
            self.standard,
            self.consumer_card,
            self.corporate_card,
            self.international_card,
            self.gst,
        )

    @property
    def settled(self) -> tuple[RateFinding, ...]:
        return tuple(finding for finding in self.findings if finding.settled)

    @property
    def questions(self) -> tuple[RateFinding, ...]:
        """The bands a person still has to settle."""
        return tuple(finding for finding in self.findings if not finding.settled)

    def card(self, base: RateCard | None = None) -> RateCard:
        """The rate card these rows imply, falling back where they said nothing.

        A band that would not conclude keeps whatever `base` holds - the
        published rate unless a caller stated otherwise. That fallback is the
        conservative direction: the published rate is what the merchant is
        most likely contracted to, and using it means the leak check on that
        band behaves exactly as it did before this module existed.

        The standard rate is taken from the non-card rows when they concluded,
        because UPI, netbanking and wallets are the largest population and the
        one a rate mismatch is never injected into. It falls through to the
        consumer-card band only when a merchant takes no non-card payments at
        all - a card-only merchant is rare and is not a reason to refuse.
        """
        card = base if base is not None else RateCard()
        standard = self.standard.rate
        if standard is None:
            standard = self.consumer_card.rate

        update: dict[str, Decimal] = {}
        if standard is not None:
            update["standard"] = standard
        if self.corporate_card.rate is not None:
            update["corporate_card"] = self.corporate_card.rate
        if self.international_card.rate is not None:
            update["international_card"] = self.international_card.rate
        if self.gst.rate is not None:
            update["gst"] = self.gst.rate
        return card.model_copy(update=update) if update else card


def induce_rates(rows: tuple[SettlementRow, ...] | list[SettlementRow]) -> InducedRates:
    """Read every rate this merchant is charged off their own report."""
    payments = [
        row
        for row in rows
        if row.type is EntityType.PAYMENT and row.amount > 0 and row.method is not None
    ]
    banded: dict[str, list[SettlementRow]] = defaultdict(list)
    for row in payments:
        banded[_band_of(row)].append(row)

    return InducedRates(
        standard=_platform(_STANDARD, banded[_STANDARD]),
        consumer_card=_platform(_CONSUMER, banded[_CONSUMER]),
        corporate_card=_platform(_CORPORATE, banded[_CORPORATE]),
        international_card=_platform(_INTERNATIONAL, banded[_INTERNATIONAL]),
        gst=_gst(payments),
    )


# ----------------------------------------------------------------- internals


def _band_of(row: SettlementRow) -> str:
    """Which contracted rate this row's own columns say it is on.

    Read from the report rather than inferred, because Razorpay's pricing
    varies on exactly these two columns. A row that says it is a domestic
    consumer card is a domestic consumer card for the purpose of asking what
    it should have cost - and whether it was charged that is a separate
    question, asked by `milan.leaks` afterwards.
    """
    if row.method is not PaymentMethod.CARD or row.card_type is None:
        return _STANDARD
    match row.card_type:
        case CardType.DOMESTIC_CORPORATE:
            return _CORPORATE
        case CardType.INTERNATIONAL:
            return _INTERNATIONAL
        case CardType.DOMESTIC_CONSUMER:
            return _CONSUMER


def _platform(name: str, rows: list[SettlementRow]) -> RateFinding:
    """The modal platform rate over one band, or a refusal."""
    return _conclude(name, [(row.fee, row.amount) for row in rows], "of the amount")


def _gst(rows: list[SettlementRow]) -> RateFinding:
    """The tax rate, read against the fee rather than the amount.

    GST is charged on the platform fee and never on the transaction value, so
    reading it against the amount would produce a number that is not a rate of
    anything. Rows with a zero fee are dropped: nothing can be inferred from
    tax on nothing, and they would otherwise all vote for a rate of zero.
    """
    return _conclude(_GST, [(row.tax, row.fee) for row in rows if row.fee > 0], "of the fee")


def _conclude(name: str, pairs: list[tuple[Paise, Paise]], against: str) -> RateFinding:
    """Vote on a rate, then make the winner prove it explains its own band.

    The two steps are separate on purpose. The vote is approximate because a
    rounded fee only implies a rate to within a paisa; the proof is exact,
    because `apply_rate` is the function the fee was computed with. Reporting
    the vote count as the finding's evidence would report agreement about a
    rounded number as agreement about a contract.
    """
    total = len(pairs)
    if total < MINIMUM_ROWS:
        return RateFinding(
            name=name,
            rate=None,
            rows=0,
            of=total,
            because=(
                f"only {total} row{'' if total == 1 else 's'} of this kind - "
                f"fewer than the {MINIMUM_ROWS} it takes to call a rate a contract"
            ),
        )

    votes = Counter(_implied(charged, base) for charged, base in pairs)
    candidate, _ = votes.most_common(1)[0]
    exact = sum(1 for charged, base in pairs if apply_rate(base, candidate) == charged)

    if Decimal(exact) / Decimal(total) < DOMINANT:
        spread = ", ".join(f"{rate:.3%} on {count}" for rate, count in votes.most_common(3))
        return RateFinding(
            name=name,
            rate=None,
            rows=exact,
            of=total,
            because=(
                f"these {total} rows do not agree on one rate ({spread}) - "
                "somebody has to say which is the contracted one"
            ),
        )

    return RateFinding(
        name=name,
        rate=candidate,
        rows=exact,
        of=total,
        because=(
            f"{candidate:.3%} {against}, reproducing the charge to the paisa on "
            f"{exact} of {total} rows"
        ),
    )


def _implied(charged: Paise, base: Paise) -> Decimal:
    """The rate this charge implies, rounded to the resolution rates are read at."""
    return (Decimal(charged) / Decimal(base)).quantize(GRANULARITY, rounding=ROUND_HALF_UP)
