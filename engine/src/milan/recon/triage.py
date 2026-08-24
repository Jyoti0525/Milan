"""Sorting what could not be resolved, using rules only.

No model is involved here and none is needed. Every category below is decided
by arithmetic that has a right answer: either a refund of exactly this size
exists somewhere in the report, or it does not.

This is the tier-one categoriser, not a fallback for when an LLM is
unavailable. It runs first, it runs always, and the measured share of
exceptions it settles on its own is the number that says how much judgment is
actually left over.
"""

from __future__ import annotations

from milan.domain.enums import EntityType, ExceptionCode
from milan.domain.money import Paise, apply_rate, format_inr
from milan.domain.rates import RateCard
from milan.domain.records import BankCredit, SettlementRow
from milan.domain.results import ReconException
from milan.recon.batches import GatewayBatch
from milan.recon.matching.base import Attempt, Verdict
from milan.recon.waterfall import UnprovenCredit


class Categoriser:
    """Assigns an exception code and a plain-language summary."""

    def __init__(self, rates: RateCard) -> None:
        self._rates = rates

    # ------------------------------------------------- credits without a match

    def unmatched_credit(
        self, credit: BankCredit, attempt: Attempt, batches: tuple[GatewayBatch, ...]
    ) -> ReconException:
        """A bank credit no settlement claims."""
        if attempt.verdict is Verdict.AMBIGUOUS:
            return ReconException(
                code=ExceptionCode.UNEXPLAINED,
                subject_id=credit.credit_id,
                amount=credit.amount,
                summary=(
                    f"{format_inr(credit.amount)} on {credit.value_date} fits "
                    f"{len(attempt.candidates)} settlements equally well. "
                    "Picking one would be a guess."
                ),
                evidence={
                    "reason": "ambiguous",
                    "candidates": ", ".join(attempt.candidates),
                    "narration": credit.narration,
                    "strategy": attempt.strategy.value,
                },
            )

        same_day = [b for b in batches if b.settled_on == credit.value_date]
        return ReconException(
            code=ExceptionCode.UNEXPLAINED,
            subject_id=credit.credit_id,
            amount=credit.amount,
            summary=(
                f"{format_inr(credit.amount)} arrived on {credit.value_date} with no "
                "settlement behind it. Not a gateway payout, or a payout this report "
                "does not cover."
            ),
            evidence={
                "reason": "no candidate",
                "narration": credit.narration,
                "settlements_that_day": str(len(same_day)),
                "last_attempt": attempt.note,
            },
        )

    def missing_settlement(self, batch: GatewayBatch) -> ReconException:
        """A payout the gateway reported that never reached the bank."""
        return ReconException(
            code=ExceptionCode.MISSING_SETTLEMENT,
            subject_id=batch.settlement_id,
            amount=batch.expected_net,
            summary=(
                f"The gateway reported {format_inr(batch.expected_net)} settled on "
                f"{batch.settled_on} across {len(batch.rows)} records. No bank credit "
                "matches it."
            ),
            evidence={
                "settled_on": batch.settled_on.isoformat(),
                "rows": str(len(batch.rows)),
                "reference": batch.settlement_utr or "absent",
            },
        )

    # ------------------------------------------- matches that would not prove

    def unproven_credit(
        self, unproven: UnprovenCredit, batch: GatewayBatch, all_rows: tuple[SettlementRow, ...]
    ) -> ReconException:
        """A credit matched to a settlement that does not reconstruct it.

        Checked in order of how specific the explanation is. A generic
        "amounts differ" is the last resort, not the first answer.
        """
        for check in (self._as_recovery_gap, self._as_fee_variance, self._as_tax_variance):
            found = check(unproven, batch, all_rows)
            if found is not None:
                return found

        return ReconException(
            code=ExceptionCode.UNEXPLAINED,
            subject_id=unproven.credit_id,
            amount=Paise(abs(unproven.residual)),
            summary=unproven.reason,
            evidence={
                "settlement": unproven.settlement_id,
                "residual": format_inr(unproven.residual),
                "rows": str(len(batch.rows)),
            },
        )

    def _as_recovery_gap(
        self, unproven: UnprovenCredit, batch: GatewayBatch, all_rows: tuple[SettlementRow, ...]
    ) -> ReconException | None:
        """Short by exactly the size of a refund sitting somewhere else.

        Refunds are netted into whichever batch is running when they clear,
        five to seven working days later - normally a batch with no other
        connection to the sale. A shortfall that equals a known refund to the
        paisa is that, and saying so turns a variance into a fact.
        """
        if unproven.residual >= 0:
            return None
        shortfall = Paise(-unproven.residual)
        culprits = [
            row
            for row in all_rows
            if row.type in (EntityType.REFUND, EntityType.ADJUSTMENT)
            and row.debit == shortfall
            and row.settlement_id != batch.settlement_id
        ]
        if not culprits:
            return None

        row = culprits[0]
        landed = row.settlement_id or "no batch yet"
        return ReconException(
            code=ExceptionCode.PARTIAL_PAYMENT,
            subject_id=unproven.credit_id,
            amount=shortfall,
            summary=(
                f"Short by {format_inr(shortfall)}, which is exactly {row.type.value} "
                f"{row.entity_id}. It was recovered from {landed}, not from this batch."
            ),
            evidence={
                "settlement": unproven.settlement_id,
                "recovered_by": landed,
                "entity": row.entity_id,
                "raised_on": row.created_at.date().isoformat(),
            },
        )

    def _as_fee_variance(
        self, unproven: UnprovenCredit, batch: GatewayBatch, all_rows: tuple[SettlementRow, ...]
    ) -> ReconException | None:
        """The batch was charged at a rate the merchant is not contracted to."""
        del all_rows
        expected = Paise(
            sum(
                apply_rate(row.amount, self._rates.platform_rate(row.method, row.card_type))
                for row in batch.payment_rows
                if row.method is not None
            )
        )
        difference = Paise(batch.fee - expected)
        if difference == 0:
            return None

        with_gst = Paise(difference + apply_rate(difference, self._rates.gst))
        if abs(with_gst + unproven.residual) > batch.rounding_allowance:
            return None

        return ReconException(
            code=ExceptionCode.FEE_DEDUCTION,
            subject_id=unproven.credit_id,
            amount=Paise(abs(difference)),
            summary=(
                f"Fee charged was {format_inr(batch.fee)} against a contracted "
                f"{format_inr(expected)}. The {format_inr(Paise(abs(difference)))} "
                "difference, plus GST on it, accounts for the shortfall."
            ),
            evidence={
                "settlement": unproven.settlement_id,
                "fee_charged": format_inr(batch.fee),
                "fee_contracted": format_inr(expected),
                "rows": str(len(batch.payment_rows)),
            },
        )

    def _as_tax_variance(
        self, unproven: UnprovenCredit, batch: GatewayBatch, all_rows: tuple[SettlementRow, ...]
    ) -> ReconException | None:
        """GST that is not the statutory rate on the fee that was charged."""
        del all_rows
        expected = apply_rate(batch.fee, self._rates.gst)
        difference = Paise(batch.tax - expected)
        if difference == 0 or abs(difference) <= batch.rounding_allowance:
            return None
        if abs(difference + unproven.residual) > batch.rounding_allowance:
            return None

        return ReconException(
            code=ExceptionCode.TAX_DEDUCTION,
            subject_id=unproven.credit_id,
            amount=Paise(abs(difference)),
            summary=(
                f"GST of {format_inr(batch.tax)} is not {self._rates.gst:.0%} of the "
                f"{format_inr(batch.fee)} fee charged. Expected {format_inr(expected)}."
            ),
            evidence={
                "settlement": unproven.settlement_id,
                "tax_charged": format_inr(batch.tax),
                "tax_expected": format_inr(expected),
            },
        )
