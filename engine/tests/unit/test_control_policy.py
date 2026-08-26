"""The adaptive matcher, and the collision rule both policies share.

The benchmark's whole value rests on the adaptive arm being a real attempt
rather than a strawman built to lose. Three of the tests below exist because
the first draft *was* a strawman in three separate ways, and each one cost the
adaptive arm accuracy that would have been published as a fact about
adaptivity.
"""

from __future__ import annotations

from datetime import date

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.dataset import Dataset
from milan.domain.enums import MatchStrategy
from milan.domain.money import Paise
from milan.domain.rates import RateCard
from milan.domain.records import BankCredit
from milan.evaluation.harness import to_recon_input
from milan.recon.batches import GatewayBatch, rebuild_batches
from milan.recon.matching.adaptive import EVIDENCE_RANK, AdaptiveMatcher, HeuristicRouter
from milan.recon.matching.base import Attempt, Verdict
from milan.recon.matching.cascade import Cascade
from milan.recon.matching.claims import resolve_collisions
from milan.recon.pipeline import ReconciliationPipeline, RunMetadata


def _credit(narration: str, amount: int = 100_000, utr: str | None = None) -> BankCredit:
    return BankCredit(
        credit_id="bank_test",
        amount=Paise(amount),
        value_date=date(2026, 7, 23),
        narration=narration,
        utr=utr,
    )


def _batches(seed: int = 1, orders: int = 200) -> tuple[Dataset, tuple[GatewayBatch, ...]]:
    config = GenerationConfig(seed=seed, difficulty=Difficulty.ADVERSARIAL, order_count=orders)
    dataset = ChaosEngine(config).generate()
    return dataset, rebuild_batches(dataset.settlement_rows)


class TestTheRouterIsNotRigged:
    """Every skip the router makes has to be a fact about what a rung reads."""

    def test_the_similarity_rung_is_never_skipped(self) -> None:
        """The rung for damaged references must run when none can be extracted.

        The first router skipped similarity whenever no reference could be
        pulled out of the narration, which reads plausibly and is backwards:
        that rung scores the raw narration against each candidate, so a
        reference damaged past recognition is precisely its case. The gate cost
        the adaptive arm nine matches.
        """
        _, batches = _batches()
        order = HeuristicRouter().preference(_credit("ACH C- RAZORPAYSOFTWARE"), batches)
        assert MatchStrategy.FUZZY_NARRATION in order

    def test_a_credit_with_no_reference_skips_the_reference_rung(self) -> None:
        """A saving the fixed order cannot make, and a sound one."""
        _, batches = _batches()
        order = HeuristicRouter().preference(_credit("NEFT INWARD RAZORPAY"), batches)
        assert MatchStrategy.EXACT_UTR not in order

    def test_every_preference_ends_somewhere(self) -> None:
        """A credit routed to nothing would have no attempt to record."""
        assert HeuristicRouter().preference(_credit("anything"), ()) == (MatchStrategy.SHORTFALL,)

    def test_a_credit_larger_than_any_payout_goes_to_the_combination_search(self) -> None:
        _, batches = _batches()
        largest = max(batch.expected_net for batch in batches)
        order = HeuristicRouter().preference(_credit("NEFT INWARD", amount=largest + 1), batches)
        assert order[0] is MatchStrategy.SUBSET_SUM


class TestTheCollisionRule:
    """Shared by both policies, so a benchmark cannot vary it by accident."""

    @staticmethod
    def _claim(credit_id: str, strategy: MatchStrategy) -> Attempt:
        return Attempt(
            strategy=strategy,
            verdict=Verdict.MATCHED,
            settlement_ids=("setl_a",),
            confidence=1.0,
        )

    def test_without_a_priority_every_claimant_is_refused(self) -> None:
        attempts = {
            "a": self._claim("a", MatchStrategy.EXACT_UTR),
            "b": self._claim("b", MatchStrategy.AMOUNT_DATE),
        }
        settled = resolve_collisions(attempts)
        assert all(not attempt.resolved for attempt in settled.values())

    def test_with_a_priority_the_stronger_evidence_keeps_it(self) -> None:
        attempts = {
            "a": self._claim("a", MatchStrategy.EXACT_UTR),
            "b": self._claim("b", MatchStrategy.AMOUNT_DATE),
        }
        settled = resolve_collisions(attempts, EVIDENCE_RANK)
        assert settled["a"].resolved
        assert not settled["b"].resolved
        assert "stronger evidence" in settled["b"].note

    def test_a_tie_in_strength_is_still_a_refusal(self) -> None:
        """Two claims from the same rung are genuinely indistinguishable."""
        attempts = {
            "a": self._claim("a", MatchStrategy.AMOUNT_DATE),
            "b": self._claim("b", MatchStrategy.AMOUNT_DATE),
        }
        settled = resolve_collisions(attempts, EVIDENCE_RANK)
        assert all(not attempt.resolved for attempt in settled.values())
        assert all("equally well" in attempt.note for attempt in settled.values())


class TestTheAdaptiveMatcherTerminates:
    """A policy that loops is not a policy."""

    def test_it_stops_when_a_pass_learns_nothing(self) -> None:
        dataset, batches = _batches()
        outcome = AdaptiveMatcher().run(dataset.bank_credits, batches)
        assert set(outcome) == {credit.credit_id for credit in dataset.bank_credits}

    def test_it_answers_for_every_credit_even_with_no_candidates(self) -> None:
        dataset, _ = _batches()
        outcome = AdaptiveMatcher().run(dataset.bank_credits, ())
        assert set(outcome) == {credit.credit_id for credit in dataset.bank_credits}
        assert all(not attempt.resolved for attempt in outcome.values())


class TestBothPoliciesReachTheSameAnswers:
    """The finding, asserted rather than described.

    Not an assertion that adaptivity is worthless - an assertion that on these
    tiers it arrives at exactly the cascade's answers. The adversarial tier is
    deliberately excluded here and measured in the benchmark instead, because
    that is the one tier where the two policies genuinely differ.
    """

    @pytest.mark.parametrize(
        "difficulty",
        [Difficulty.CLEAN, Difficulty.REALISTIC, Difficulty.MESSY],
    )
    def test_identical_proofs(self, difficulty: Difficulty) -> None:
        config = GenerationConfig(seed=7, difficulty=difficulty, order_count=200)
        dataset = ChaosEngine(config).generate()
        data = to_recon_input(dataset)
        metadata = RunMetadata(seed=7, difficulty=difficulty.value)

        fixed = ReconciliationPipeline(rates=RateCard(), cascade=Cascade()).run(data, metadata)
        routed = ReconciliationPipeline(rates=RateCard(), cascade=AdaptiveMatcher()).run(
            data, metadata
        )

        assert {p.credit_id: p.settlement_set for p in fixed.proofs if p.balances} == {
            p.credit_id: p.settlement_set for p in routed.proofs if p.balances
        }
