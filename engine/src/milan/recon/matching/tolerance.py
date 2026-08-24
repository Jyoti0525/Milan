"""Rung two: amount and date, when the reference is gone.

With no UTR, what is left is that a payout of a particular size arrived on a
particular day. That is usually enough, because batch totals are effectively
unique - they are the sum of dozens of arbitrary order values.

Usually is not always, and this rung's real job is knowing the difference.
When two settlements fit the same credit, the honest output is not the closer
one. It is a refusal, because the second-best fit being close is exactly the
situation where picking wrong is most likely and least visible.
"""

from __future__ import annotations

from datetime import timedelta

from milan.domain.enums import MatchStrategy
from milan.domain.money import Paise, format_inr
from milan.domain.records import BankCredit
from milan.recon.batches import GatewayBatch
from milan.recon.matching.base import Attempt, Verdict

SETTLEMENT_DATE_WINDOW = timedelta(days=1)
"""A payout initiated on a working day normally lands the same day; a cut-off
miss pushes it to the next. Anything wider stops being evidence."""


class AmountDateStrategy:
    """Match on batch total and value date, within the rounding allowance."""

    name = MatchStrategy.AMOUNT_DATE

    def attempt(self, credit: BankCredit, candidates: tuple[GatewayBatch, ...]) -> Attempt:
        near = [batch for batch in candidates if self._within_window(credit, batch)]
        fits = [batch for batch in near if self._amount_fits(credit, batch)]

        if not fits:
            return Attempt(
                strategy=self.name,
                verdict=Verdict.NO_CANDIDATE,
                note=(
                    f"{len(near)} settlements on or near {credit.value_date}, "
                    f"none totalling {format_inr(credit.amount)}"
                ),
            )

        if len(fits) > 1:
            return Attempt(
                strategy=self.name,
                verdict=Verdict.AMBIGUOUS,
                candidates=tuple(batch.settlement_id for batch in fits),
                note=(
                    f"{len(fits)} settlements match {format_inr(credit.amount)} "
                    f"on {credit.value_date}; nothing distinguishes them"
                ),
            )

        batch = fits[0]
        gap = Paise(abs(credit.amount - batch.expected_net))
        return Attempt(
            strategy=self.name,
            verdict=Verdict.MATCHED,
            settlement_id=batch.settlement_id,
            candidates=(batch.settlement_id,),
            confidence=self._confidence(gap, batch.rounding_allowance),
            note=(
                f"unique batch totalling {format_inr(batch.expected_net)} "
                f"settled {batch.settled_on}"
            ),
        )

    def _within_window(self, credit: BankCredit, batch: GatewayBatch) -> bool:
        return abs(batch.settled_on - credit.value_date) <= SETTLEMENT_DATE_WINDOW

    def _amount_fits(self, credit: BankCredit, batch: GatewayBatch) -> bool:
        return abs(credit.amount - batch.expected_net) <= batch.rounding_allowance

    def _confidence(self, gap: Paise, allowance: Paise) -> float:
        """Exact to the paisa is stronger evidence than merely within drift.

        Reported rather than thresholded: a caller that wants to review the
        weakest matches needs the ordering, and collapsing it to a boolean
        throws that away.
        """
        if gap == 0:
            return 0.95
        return 0.80 - 0.10 * (gap / max(allowance, 1))
