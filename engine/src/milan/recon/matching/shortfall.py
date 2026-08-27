"""The last rung: a payout that arrived, minus something.

Every rung above this one asks a credit to agree with a settlement. This one
asks whether it *nearly* does, and it exists because of a population the other
four are structurally unable to see.

A credit whose bank reference was corrupted **and** whose payout carried an
unexplained deduction fails all four for different reasons. The reference rung
has no reference. The amount rung wants the total to the paisa and the credit
is short. Subset-sum wants a combination summing to the credit and no
combination does. Similarity has nothing to be similar to. So a credit that is
identifiably one settlement, short by a fee the report does not show, comes
out the far end as "no settlement behind it" - the least useful sentence this
engine can produce, and measured across twenty adversarial seeds it produced
it 43 times.

The evidence is real. Those credits land on the settlement date exactly, and
they are short by a median of 0.31%. What they are not is *exact*, and every
rung above treats exactness as the whole of the evidence.

**This rung claims; it does not conclude.** The claim goes to the same
verifier every other rung answers to, the proof comes up short, and the claim
is withdrawn - which is the intended outcome rather than a failure. A
withdrawn claim carries `withdrawn_ids`, and the pipeline turns that into "this
is settlement A, and it is short by exactly refund R" instead of a shrug. The
credit never becomes a match, so nothing here can move the match rate,
precision, or the refusal count.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from milan.domain.enums import MatchStrategy
from milan.domain.money import Paise, format_inr
from milan.domain.rates import RateCard
from milan.domain.records import BankCredit
from milan.recon.batches import GatewayBatch
from milan.recon.matching.base import Attempt, Verdict

SETTLEMENT_DATE_WINDOW = timedelta(days=1)


def widest_deduction(rates: RateCard) -> Decimal:
    """The most a payout can legitimately be reduced by, as a share of gross.

    Derived from the rate card rather than tuned against the data, and that
    distinction is the whole defensibility of this rung. A band fitted to the
    generator would be fitting to the defects somebody chose to write, and
    every accuracy figure in this project is already conditional on that
    catalogue - a tolerance read off the same data would make it circular.

    The worst legitimate case is an international card at 3%, the GST charged
    on that fee, and Section 194-O withholding on gross. Anything short by
    more than that is not a fee stack, whatever else it may be.

    What it is a share *of* is worth stating, because it is not what it looks
    like. The gap this bounds is measured against `expected_net`, which is the
    sum of the settlement rows' own `credit - debit` - already net of fee, GST
    and any withholding. So the band is not "how much of the fee stack is
    missing"; the report has already shown all of it. It is a ceiling on a
    deduction the report does *not* show, sized by the largest one that could
    legitimately exist, and the fee stack is the right ruler for that even
    though it is not the thing being measured.

    The withholding term therefore covers one specific shape: a settlement
    report written before the tax came off, paid out by a bank that took it.
    That leaves a credit short by exactly 1% of gross with nothing in the
    report to explain it. A merchant whose report already nets the withholding
    - which is the ordinary case, and the one the generator produces - never
    reaches this rung on account of it.
    """
    worst_fee = max(rates.standard, rates.corporate_card, rates.international_card)
    return worst_fee * (Decimal(1) + rates.gst) + (rates.tds if rates.tds_applies else Decimal(0))


class ShortfallStrategy:
    """Match on date and near-total, when the payout arrived light."""

    name = MatchStrategy.SHORTFALL

    def __init__(self, rates: RateCard | None = None) -> None:
        self._rates = rates if rates is not None else RateCard()
        self._band = widest_deduction(self._rates)

    def attempt(self, credit: BankCredit, candidates: tuple[GatewayBatch, ...]) -> Attempt:
        near = [batch for batch in candidates if self._within_window(credit, batch)]
        fits = [batch for batch in near if self._short_by_a_plausible_deduction(credit, batch)]

        if not fits:
            return Attempt(
                strategy=self.name,
                verdict=Verdict.NO_CANDIDATE,
                note=(
                    f"{len(near)} settlements near {credit.value_date}, none of them "
                    f"{format_inr(credit.amount)} less a plausible deduction"
                ),
            )

        if len(fits) > 1:
            # Two payouts this credit could be short of is not a near miss, it
            # is a coin flip. The band is wide by construction, so this rung
            # has more chances to collide than any above it and has to be
            # correspondingly less willing to pick.
            return Attempt(
                strategy=self.name,
                verdict=Verdict.AMBIGUOUS,
                candidates=tuple(batch.settlement_id for batch in fits),
                note=(
                    f"{len(fits)} settlements are within a deduction of "
                    f"{format_inr(credit.amount)} on {credit.value_date}"
                ),
            )

        batch = fits[0]
        gap = Paise(batch.expected_net - credit.amount)
        return Attempt(
            strategy=self.name,
            verdict=Verdict.MATCHED,
            settlement_ids=(batch.settlement_id,),
            # Deliberately the lowest confidence any rung reports. This is the
            # weakest evidence in the system: it identifies a payout without
            # explaining it, and it is offered so the shortfall can be named
            # rather than so the credit can be called reconciled.
            confidence=0.35,
            note=(
                f"{format_inr(credit.amount)} on {credit.value_date} is "
                f"{format_inr(gap)} short of {batch.settlement_id}, within the "
                f"{self._band:.2%} a fee stack can account for"
            ),
        )

    def _within_window(self, credit: BankCredit, batch: GatewayBatch) -> bool:
        return abs(credit.value_date - batch.settled_on) <= SETTLEMENT_DATE_WINDOW

    def _short_by_a_plausible_deduction(self, credit: BankCredit, batch: GatewayBatch) -> bool:
        """Short, and short by an amount a deduction could explain.

        Strictly short. A credit *larger* than the payout it claims is not a
        near miss - nothing in the fee stack pays a merchant more - and
        accepting one would let this rung explain money arriving from
        somewhere else entirely.

        The lower bound excludes what the rung above already handles: a gap
        inside the rounding allowance is an exact match, and it belongs to
        `AmountDateStrategy` where it will be proved rather than merely
        claimed.
        """
        gap = batch.expected_net - credit.amount
        if gap <= batch.rounding_allowance:
            return False
        return Decimal(gap) <= Decimal(batch.expected_net) * self._band
