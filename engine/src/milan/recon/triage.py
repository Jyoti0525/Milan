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

from datetime import date
from decimal import Decimal

from milan.domain.enums import EntityType, ExceptionCode
from milan.domain.money import Paise, format_inr
from milan.domain.rates import RateCard
from milan.domain.records import BankCredit, Payment, SettlementRow
from milan.domain.results import ReconException
from milan.recon.batches import BatchGroup, GatewayBatch
from milan.recon.matching.base import Attempt, Verdict
from milan.recon.waterfall import UnprovenCredit

_GST_SLABS = (Decimal("0.05"), Decimal("0.12"), Decimal("0.18"), Decimal("0.28"))
"""India's GST rate slabs. A shortfall is only called a tax variance when it
implies one of these; anything else is an unexplained deduction that happens
to divide neatly."""


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

    def unsettled_payment(self, payment: Payment, cutoff: date) -> ReconException:
        """A captured payment the settlement report never mentions.

        This one is not found by looking at bank credits at all. Every credit
        can reconcile perfectly and this money still be gone, because the
        gateway never claimed to have paid it - so nothing is unmatched and
        nothing looks wrong. The only way to see it is to read the payments
        file and ask what the report is missing.

        The cutoff matters. A payment captured yesterday has not been settled
        yet and that is normal; flagging it would bury the real ones under
        ordinary gateway lag.
        """
        return ReconException(
            code=ExceptionCode.UNSETTLED_PAYMENT,
            subject_id=payment.payment_id,
            amount=payment.amount,
            summary=(
                f"{format_inr(payment.amount)} was captured on "
                f"{payment.captured_at.date()} and appears nowhere in the settlement "
                f"report, which is complete to {cutoff}."
            ),
            evidence={
                "captured_on": payment.captured_at.date().isoformat(),
                "method": payment.method.value,
                "order": payment.order_id,
                "report_complete_to": cutoff.isoformat(),
            },
        )

    # ------------------------------------------- matches that would not prove

    def unproven_credit(
        self, unproven: UnprovenCredit, group: BatchGroup, all_rows: tuple[SettlementRow, ...]
    ) -> ReconException:
        """A credit matched to a settlement that does not reconstruct it.

        Checked in order of how specific the explanation is, and the order
        is load-bearing. A refund matches the shortfall to the paisa; a GST
        slab matches it to a published rate; a fee surcharge merely has to
        divide into gross at some small percentage, which almost any number
        does. Running the loosest check first made it answer for a tax
        variance it had no business explaining.
        """
        for check in (self._as_recovery_gap, self._as_tax_variance, self._as_fee_variance):
            found = check(unproven, group, all_rows)
            if found is not None:
                return found

        return ReconException(
            code=ExceptionCode.UNEXPLAINED,
            subject_id=unproven.credit_id,
            amount=Paise(abs(unproven.residual)),
            summary=unproven.reason,
            evidence={
                "settlements": ", ".join(unproven.settlement_ids),
                "residual": format_inr(unproven.residual),
                "rows": str(len(group.rows)),
            },
        )

    def _as_recovery_gap(
        self, unproven: UnprovenCredit, group: BatchGroup, all_rows: tuple[SettlementRow, ...]
    ) -> ReconException | None:
        """Short by exactly the size of a refund sitting somewhere else.

        Refunds are netted into whichever group is running when they clear,
        five to seven working days later - normally a group with no other
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
            and row.settlement_id not in group.settlement_set
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
                f"{row.entity_id}. It was recovered from {landed}, not from this group."
            ),
            evidence={
                "settlements": ", ".join(unproven.settlement_ids),
                "recovered_by": landed,
                "entity": row.entity_id,
                "raised_on": row.created_at.date().isoformat(),
            },
        )

    def _as_fee_variance(
        self, unproven: UnprovenCredit, group: BatchGroup, all_rows: tuple[SettlementRow, ...]
    ) -> ReconException | None:
        """More came off than the report's own fee column accounts for.

        Two different things can go wrong with a fee and only one of them is
        visible here. If the report shows a rate the merchant is not
        contracted to, the batch still balances and nothing is unmatched -
        that is a leak, and it is found by comparing against the contract,
        not by arithmetic. This is the other case: the report is internally
        consistent and the bank still paid less, which means a deduction was
        applied at payout that the export never mentions.

        The shortfall is read back as a rate on gross rather than matched
        against a list of known rates, because the useful output for a
        finance team is "you were charged an extra 0.15%", which is a
        sentence they can take to their account manager.
        """
        del all_rows
        if unproven.residual >= 0 or not group.gross:
            return None

        shortfall = Paise(-unproven.residual)
        # A surcharge carries GST like any other fee, so strip that back off
        # before reading the rate, or every rate reported here is 18% high.
        base = Paise(round(shortfall / (1 + float(self._rates.gst))))
        implied = Decimal(base) / Decimal(group.gross)
        if not (Decimal("0.0005") <= implied <= Decimal("0.01")):
            return None

        return ReconException(
            code=ExceptionCode.FEE_DEDUCTION,
            subject_id=unproven.credit_id,
            amount=shortfall,
            summary=(
                f"Short by {format_inr(shortfall)} against a report that foots. "
                f"That is an extra {implied:.3%} of the {format_inr(group.gross)} "
                "settled, plus GST on it - a deduction taken at payout that the "
                "settlement report does not show."
            ),
            evidence={
                "settlements": ", ".join(unproven.settlement_ids),
                "fee_reported": format_inr(group.fee),
                "extra_charged": format_inr(base),
                "implied_rate": f"{implied:.3%}",
                "rows": str(len(group.payment_rows)),
            },
        )

    def _as_tax_variance(
        self, unproven: UnprovenCredit, group: BatchGroup, all_rows: tuple[SettlementRow, ...]
    ) -> ReconException | None:
        """GST came off at a rate that is not the statutory one.

        Read from the shortfall rather than from the report, because the
        report says 18% - it is the payout that disagrees. Only the real GST
        slabs are accepted as an explanation: an arbitrary percentage that
        happens to fit is a coincidence, and naming it "GST" would attach a
        tax to a number that has nothing to do with tax.
        """
        del all_rows
        if unproven.residual >= 0 or not group.fee:
            return None

        shortfall = Paise(-unproven.residual)
        applied = Decimal(group.tax + shortfall) / Decimal(group.fee)
        slab = next(
            (rate for rate in _GST_SLABS if abs(applied - rate) <= Decimal("0.005")),
            None,
        )
        if slab is None or slab == self._rates.gst:
            return None

        return ReconException(
            code=ExceptionCode.TAX_DEDUCTION,
            subject_id=unproven.credit_id,
            amount=shortfall,
            summary=(
                f"GST was deducted at {slab:.0%} of the {format_inr(group.fee)} fee, "
                f"not the {self._rates.gst:.0%} the report shows. The "
                f"{format_inr(shortfall)} difference is the shortfall."
            ),
            evidence={
                "settlements": ", ".join(unproven.settlement_ids),
                "tax_reported": format_inr(group.tax),
                "tax_implied": format_inr(Paise(group.tax + shortfall)),
                "rate_applied": f"{slab:.0%}",
            },
        )
