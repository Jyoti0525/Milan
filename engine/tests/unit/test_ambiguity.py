"""Two credits, one settlement — and saying so correctly.

Ambiguity has two shapes and the queue used to report them as one. A credit
that fits several settlements asks "which payout arrived?". Several credits
that fit one settlement ask "which of these bank lines is the payout?". They
send whoever picks the case up to different files.

Found by looking at the running queue rather than by a test: a collision was
being reported as `fits 1 settlements equally well`, which is wrong in its
grammar and, underneath that, wrong about what was uncertain. The grammar is
what made it visible; the substance is why it mattered.
"""

from __future__ import annotations

from datetime import date

import pytest

from milan.domain.enums import ExceptionCode, MatchStrategy
from milan.domain.money import from_rupees
from milan.domain.rates import RateCard
from milan.domain.records import BankCredit
from milan.domain.results import ReconException
from milan.recon.batches import rebuild_batches
from milan.recon.matching.base import Attempt, Verdict
from milan.recon.matching.cascade import Cascade
from milan.recon.triage import Categoriser
from tests.unit.test_merged_credits import row

CREDIT = BankCredit(
    credit_id="bank_one",
    amount=from_rupees("3010.37"),
    value_date=date(2026, 7, 10),
    narration="NEFT-QFTCBN9UALVV-RAZORPAY SOFTWARE PVT LTD",
    utr="QFTCBN9UALVV",
)


def _categorise(attempt: Attempt) -> ReconException:
    return Categoriser(RateCard()).unmatched_credit(CREDIT, attempt, ())


class TestAContestedSettlement:
    """Several credits claimed the same payout. The cascade withdraws them all."""

    def _attempt(self, rivals: tuple[str, ...]) -> Attempt:
        return Attempt(
            strategy=MatchStrategy.AMOUNT_DATE,
            verdict=Verdict.AMBIGUOUS,
            candidates=("setl_target",),
            contested_by=rivals,
        )

    def test_it_says_which_settlement_is_contested(self) -> None:
        exception = _categorise(self._attempt(("bank_two",)))

        assert "setl_target" in exception.summary
        assert exception.evidence["reason"] == "contested settlement"
        assert exception.evidence["also claimed by"] == "bank_two"

    def test_it_never_says_one_settlements(self) -> None:
        """The sentence that gave the bug away."""
        exception = _categorise(self._attempt(("bank_two",)))

        assert "1 settlements" not in exception.summary
        assert "fits 1" not in exception.summary

    @pytest.mark.parametrize(
        ("rivals", "expected"),
        [(("bank_two",), "1 other credit "), (("bank_two", "bank_three"), "2 other credits ")],
    )
    def test_it_counts_the_rivals_and_agrees_with_itself(
        self, rivals: tuple[str, ...], expected: str
    ) -> None:
        assert expected in _categorise(self._attempt(rivals)).summary

    def test_the_credit_itself_is_not_counted_among_its_rivals(self) -> None:
        """`contested_by` is everyone else, not everyone. Counting the subject
        twice would report three credits where there are two."""
        exception = _categorise(self._attempt(("bank_two",)))

        assert "bank_one" not in exception.evidence["also claimed by"]

    def test_it_is_still_an_exception_and_still_carries_the_amount(self) -> None:
        exception = _categorise(self._attempt(("bank_two",)))

        assert exception.code is ExceptionCode.UNEXPLAINED
        assert exception.amount == CREDIT.amount
        assert exception.subject_id == "bank_one"


class TestSeveralSettlementsFittingOneCredit:
    """The other shape, which was always reported correctly and has to stay so."""

    def test_it_counts_the_settlements(self) -> None:
        exception = _categorise(
            Attempt(
                strategy=MatchStrategy.AMOUNT_DATE,
                verdict=Verdict.AMBIGUOUS,
                candidates=("setl_a", "setl_b", "setl_c"),
            )
        )

        assert "fits 3 settlements equally well" in exception.summary
        assert exception.evidence["reason"] == "ambiguous"
        assert exception.evidence["candidates"] == "setl_a, setl_b, setl_c"

    def test_the_two_shapes_do_not_produce_the_same_sentence(self) -> None:
        """The point of the whole fix, asserted directly."""
        contested = _categorise(
            Attempt(
                strategy=MatchStrategy.AMOUNT_DATE,
                verdict=Verdict.AMBIGUOUS,
                candidates=("setl_a",),
                contested_by=("bank_two",),
            )
        )
        several = _categorise(
            Attempt(
                strategy=MatchStrategy.AMOUNT_DATE,
                verdict=Verdict.AMBIGUOUS,
                candidates=("setl_a", "setl_b"),
            )
        )

        assert contested.summary != several.summary
        assert contested.evidence["reason"] != several.evidence["reason"]


class TestTheCascadeRecordsTheRivals:
    def test_a_collision_leaves_every_contender_knowing_the_others(self) -> None:
        """End to end through the cascade rather than a hand-built attempt:
        two credits of the same amount and date, one settlement between them.
        """
        rows = (row("pay_1", "10000", "setl_a", 8, "AAAAAAAAAAAA"),)
        batches = rebuild_batches(rows)
        amount = batches[0].expected_net

        # Identical in every respect the evidence can see. `bank_credit` in
        # the merged-credit tests hard-codes one id, so these are built here.
        twins = tuple(
            BankCredit(
                credit_id=credit_id,
                amount=amount,
                value_date=date(2026, 7, 8),
                narration="NEFT INWARD RAZORPAY SOFTWARE",
                utr=None,
            )
            for credit_id in ("bank_one", "bank_two")
        )
        outcome = Cascade().run(twins, batches)

        for credit_id in ("bank_one", "bank_two"):
            attempt = outcome[credit_id]
            assert attempt.verdict is Verdict.AMBIGUOUS
            assert attempt.settlement_ids == ()
            assert attempt.candidates == ("setl_a",)
            assert len(attempt.contested_by) == 1
            assert credit_id not in attempt.contested_by
