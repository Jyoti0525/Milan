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
from functools import partial

from milan.domain.enums import EntityType, ExceptionCode
from milan.domain.money import ZERO, Paise, format_inr
from milan.domain.rates import RateCard
from milan.domain.records import BankCredit, Payment, SettlementRow
from milan.domain.results import ReconException, UnprovenCredit
from milan.recon.batches import BatchGroup, GatewayBatch
from milan.recon.matching.base import Attempt, Verdict

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
            return self._ambiguous(credit, attempt)

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

    def _ambiguous(self, credit: BankCredit, attempt: Attempt) -> ReconException:
        """Say which of the two kinds of ambiguity this is.

        A credit that fits several settlements and a settlement fitted by
        several credits are different questions for whoever picks this up:
        the first asks which payout arrived, the second asks which of these
        bank lines is the payout. Reporting the second as the first is not a
        wording problem - it sends somebody looking at the wrong file.
        """
        if attempt.contested_by:
            rivals = len(attempt.contested_by) + 1
            settlement = attempt.candidates[0] if attempt.candidates else "one settlement"
            return ReconException(
                code=ExceptionCode.UNEXPLAINED,
                subject_id=credit.credit_id,
                amount=credit.amount,
                summary=(
                    f"{format_inr(credit.amount)} on {credit.value_date} and "
                    f"{rivals - 1} other credit{'s' if rivals > 2 else ''} all fit "
                    f"settlement {settlement}. Only one of them can be it, and "
                    "nothing in the evidence says which."
                ),
                evidence={
                    "reason": "contested settlement",
                    "settlement": settlement,
                    "also claimed by": ", ".join(attempt.contested_by),
                    "narration": credit.narration,
                    "strategy": attempt.strategy.value,
                },
            )

        count = len(attempt.candidates)
        return ReconException(
            code=ExceptionCode.UNEXPLAINED,
            subject_id=credit.credit_id,
            amount=credit.amount,
            summary=(
                f"{format_inr(credit.amount)} on {credit.value_date} fits "
                f"{count} settlements equally well. Picking one would be a guess."
            ),
            evidence={
                "reason": "ambiguous",
                "candidates": ", ".join(attempt.candidates),
                "narration": credit.narration,
                "strategy": attempt.strategy.value,
            },
        )

    def missing_settlement(
        self,
        batch: GatewayBatch,
        batches: tuple[GatewayBatch, ...] = (),
        claimed_by: str | None = None,
    ) -> ReconException:
        """A payout the gateway reported that no credit was concluded for.

        `batches` is every payout in the run, and it is here so the evidence
        can record how many the gateway sent out that day. On its own that
        number says nothing; across several of these it is the difference
        between "two payouts went astray" and "the whole run of the 21st
        never left", and those are two different phone calls. Nothing else
        in the report carries the day's population, so without it a reader
        with several missing payouts on one date cannot tell which they have.

        `claimed_by` is the credit that *was* matched to this payout and had
        its claim withdrawn when the arithmetic would not close. Decision 242
        found that three quarters of what this rule reports is that case
        rather than a payout that went astray, and refused to suppress it -
        rightly, because suppressing means asserting a match the prover
        declined to assert. What was never fixed is that the sentence went on
        saying "no bank credit matches it" about a payout a bank credit
        plainly matched, and that the full net stayed in the amount, so a
        merchant with one short payout saw it twice and read roughly double
        their exposure.

        Both halves are fixed here without asserting anything. The exception
        still exists and still says no credit was concluded. It now names the
        credit that came up short, and carries no amount, because the money
        that did not arrive is the shortfall and the shortfall exception is
        already reporting it. That is what `ReconException.amount` means by
        "zero when the exception is structural".
        """
        that_day = sum(1 for other in batches if other.settled_on == batch.settled_on)
        return ReconException(
            code=ExceptionCode.MISSING_SETTLEMENT,
            subject_id=batch.settlement_id,
            amount=ZERO if claimed_by else batch.expected_net,
            summary=(
                (
                    f"The gateway reported {format_inr(batch.expected_net)} settled on "
                    f"{batch.settled_on} across {len(batch.rows)} records. {claimed_by} "
                    "was matched to it and would not reconstruct, so this payout and "
                    "that shortfall are the same money - counted here once."
                )
                if claimed_by
                else (
                    f"The gateway reported {format_inr(batch.expected_net)} settled on "
                    f"{batch.settled_on} across {len(batch.rows)} records. No bank credit "
                    "matches it."
                )
            ),
            evidence={
                "settled_on": batch.settled_on.isoformat(),
                "rows": str(len(batch.rows)),
                "reference": batch.settlement_utr or "absent",
                **({"batches_that_day": str(that_day)} if that_day else {}),
                **({"claimed_by": claimed_by} if claimed_by else {}),
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

        The refund check appears twice, and that is what the order above is
        really saying. "Matches the shortfall to the paisa" was true of it
        when it was written and stopped being true when it was widened to
        the batch's rounding allowance - so the sentence justifying its
        place at the top now only describes half of what it does.

        The two halves belong in different places. An exact refund is the
        sharpest test here: a named record, to the paisa, and nothing else
        in the report can beat it. A refund a few paise off is still a named
        record and still strong, but it is no longer sharper than a shortfall
        that lands on a published GST slab, so it sits below that and above
        the fee test - which its own docstring admits almost any number
        satisfies.

        Measured rather than argued. Checking induced causes against the
        answer key over thirty-six 2,000-order months, the original order
        put five clusters together from genuinely different defects; this
        order puts together one. The one that remains is a refund recovery
        and a 28% GST deduction that fit the same shortfall, where the
        evidence really does not choose.
        """
        checks = (
            partial(self._as_recovery_gap, exact=True),
            self._as_tax_variance,
            partial(self._as_recovery_gap, exact=False),
            self._as_fee_variance,
        )
        for check in checks:
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
                "identified_by": unproven.strategy.value.replace("_", " "),
                "identification_confidence": f"{unproven.confidence:.0%}",
                "residual": format_inr(unproven.residual),
                "rows": str(len(group.rows)),
            },
        )

    def _as_recovery_gap(
        self,
        unproven: UnprovenCredit,
        group: BatchGroup,
        all_rows: tuple[SettlementRow, ...],
        *,
        exact: bool = False,
    ) -> ReconException | None:
        """Short by the size of a refund sitting somewhere else.

        `exact` demands the refund equal the shortfall to the paisa. See
        `unproven_credit` for why this runs both ways round.

        Refunds are netted into whichever group is running when they clear,
        five to seven working days later - normally a group with no other
        connection to the sale. A shortfall that equals a known refund is
        that, and saying so turns a variance into a fact.

        Matched inside the group's rounding allowance rather than on exact
        equality, and that one word was most of this project's explanation
        gap. The shortfall is a residual, so it carries the same per-row
        against batch-level tax rounding every other figure here carries;
        demanding the refund equal it to the paisa meant a credit short by
        one paisa more than a refund got no explanation at all, while the
        prover two modules away was already treating that same paisa as
        drift. Same allowance, derived the same way, for the same reason.

        Uniqueness is required, not preferred. If two refunds both sit inside
        the window then the evidence does not say which one this is, and
        naming the nearer of them would be exactly the guess this system
        refuses to make everywhere else. In practice they are far apart - the
        runner-up is typically hundreds of paise away - so this rejects
        almost nothing while ruling out the case that would produce a
        confident wrong answer.
        """
        if unproven.residual >= 0:
            return None
        shortfall = Paise(-unproven.residual)
        allowance = ZERO if exact else group.rounding_allowance
        culprits = [
            row
            for row in all_rows
            if row.type in (EntityType.REFUND, EntityType.ADJUSTMENT)
            and abs(row.debit - shortfall) <= allowance
            and row.settlement_id not in group.settlement_set
        ]
        if len(culprits) != 1:
            return None

        row = culprits[0]
        landed = row.settlement_id or "no batch yet"
        drift = Paise(shortfall - row.debit)
        # Said out loud when it is not nil. A reader who checks this against
        # their own export will find the two numbers differ, and a sentence
        # claiming "exactly" would look like the tool got it wrong.
        if drift == 0:
            qualifier = f", which is {row.type.value} {row.entity_id}"
        else:
            direction = "more than" if drift > 0 else "less than"
            qualifier = (
                f", which is {format_inr(Paise(abs(drift)))} {direction} "
                f"{row.type.value} {row.entity_id} - rounding drift, inside the "
                f"{format_inr(allowance)} these rows carry"
            )
        return ReconException(
            code=ExceptionCode.PARTIAL_PAYMENT,
            subject_id=unproven.credit_id,
            amount=shortfall,
            summary=(
                f"Short by {format_inr(shortfall)}{qualifier}. It was recovered "
                f"from {landed}, not from this group."
            ),
            evidence={
                "settlements": ", ".join(unproven.settlement_ids),
                "identified_by": unproven.strategy.value.replace("_", " "),
                "identification_confidence": f"{unproven.confidence:.0%}",
                "recovered_by": landed,
                "entity": row.entity_id,
                "entity_amount": format_inr(row.debit),
                "rounding_drift": format_inr(drift),
                "allowance": format_inr(allowance),
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
                "identified_by": unproven.strategy.value.replace("_", " "),
                "identification_confidence": f"{unproven.confidence:.0%}",
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
                "identified_by": unproven.strategy.value.replace("_", " "),
                "identification_confidence": f"{unproven.confidence:.0%}",
                "tax_reported": format_inr(group.tax),
                "tax_implied": format_inr(Paise(group.tax + shortfall)),
                "rate_applied": f"{slab:.0%}",
            },
        )
