"""The similarity rung, and the refusals that keep it honest.

This rung is the only one that can be confidently wrong about a reference,
because it answers on resemblance rather than equality. So most of what is
tested here is what it must decline: narrations that resemble nothing, and
pairs where two references resemble the text equally well.

It was also, briefly, a rung that matched nothing at all. It was built, wired
into the cascade, and never fired once - every credit reaching it had already
been resolved by arithmetic. The conformance check caught that, and the fix
was to generate the case it exists for rather than to quietly excuse it.
"""

from __future__ import annotations

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.money import Paise
from milan.evaluation.harness import evaluate
from milan.recon.matching.base import Verdict
from milan.recon.matching.fuzzy import (
    FuzzyNarrationStrategy,
    normalise,
    similarity,
)
from tests.unit.test_merged_credits import bank_credit, batches_of, row

REFERENCE = "CJ3GZ79N4G1F"


def one_settlement(reference: str = REFERENCE) -> tuple:
    return batches_of(row("pay_1", "10000", "setl_a", 8, reference))


class TestNormalisation:
    def test_bank_words_are_stripped_before_comparing(self) -> None:
        """They are long runs of capitals, which is what a reference looks
        like to a similarity measure. Left in, every comparison competes
        against RAZORPAYSOFTWARE."""
        assert "RAZORPAY" not in normalise("NEFT-ABC123-RAZORPAY SOFTWARE PVT LTD")

    def test_delimiters_are_removed_so_a_split_reference_rejoins(self) -> None:
        assert "DJRJMSS5NDW4" in normalise("NEFT-DJR/JMSS5NDW4-RAZORPAY SOFTWARE")


class TestSimilarity:
    @pytest.mark.parametrize(
        ("narration", "why"),
        [
            (f"NEFT-{REFERENCE}-RAZORPAY SOFTWARE PVT LTD", "intact"),
            ("NEFT-CJ3G7Z9N4G1F-RAZORPAY SOFTWARE PVT LTD", "transposed"),
            ("NEFT-CJ3GZ79N4G1-RAZORPAY SOFTWARE PVT LTD", "truncated"),
            ("IMPS/CJ3GZ79N4G1F340/RAZORPAY/SETTLEMENT", "padded"),
            ("NEFT-CJ3G/Z79N4G1F-RAZORPAY SOFTWARE", "split"),
        ],
    )
    def test_every_kind_of_damage_still_resembles_the_original(
        self, narration: str, why: str
    ) -> None:
        assert similarity(REFERENCE, narration) >= 0.78, why

    def test_an_unrelated_reference_does_not(self) -> None:
        assert similarity(REFERENCE, "NEFT-9QWMPX4KTB27-RAZORPAY SOFTWARE") < 0.78


class TestTheRung:
    def test_it_matches_a_damaged_reference(self) -> None:
        result = FuzzyNarrationStrategy().attempt(
            bank_credit(Paise(1), utr=None).model_copy(
                update={"narration": "NEFT-CJ3G7Z9N4G1F-RAZORPAY SOFTWARE PVT LTD"}
            ),
            one_settlement(),
        )
        assert result.verdict is Verdict.MATCHED
        assert result.settlement_ids == ("setl_a",)

    def test_it_refuses_a_narration_that_resembles_nothing(self) -> None:
        result = FuzzyNarrationStrategy().attempt(
            bank_credit(Paise(1), utr=None).model_copy(
                update={"narration": "NEFT INWARD MR RAJESH KUMAR"}
            ),
            one_settlement(),
        )
        assert result.verdict is Verdict.NO_CANDIDATE

    def test_it_refuses_when_two_references_resemble_it_equally(self) -> None:
        """A ranked list always has a top entry. Without a margin this rung
        would answer every single time."""
        batches = batches_of(
            row("pay_1", "10000", "setl_a", 8, "AAAAAAAAAA1B"),
            row("pay_2", "25000", "setl_b", 8, "AAAAAAAAAA1C"),
        )
        result = FuzzyNarrationStrategy().attempt(
            bank_credit(Paise(1), utr=None).model_copy(
                update={"narration": "NEFT-AAAAAAAAAA1D-RAZORPAY SOFTWARE"}
            ),
            batches,
        )
        assert result.verdict is Verdict.AMBIGUOUS
        assert set(result.candidates) == {"setl_a", "setl_b"}

    def test_its_confidence_never_reaches_an_exact_match(self) -> None:
        """An intact reference proves identity; a damaged one argues for it,
        and the queue has to be able to tell which it is looking at."""
        result = FuzzyNarrationStrategy().attempt(
            bank_credit(Paise(1), utr=None).model_copy(
                update={"narration": f"NEFT-{REFERENCE}-RAZORPAY SOFTWARE PVT LTD"}
            ),
            one_settlement(),
        )
        assert result.verdict is Verdict.MATCHED
        assert result.confidence < 1.0


class TestItActuallyEarnsItsPlace:
    """The measurement that justifies the rung existing at all.

    A rung is not worth its complexity because it is clever. It is worth it
    if removing it costs credits, so that is what this asserts - on the tier
    built to need it, against the same cascade without it.
    """

    @pytest.mark.parametrize("difficulty", [Difficulty.MESSY, Difficulty.ADVERSARIAL])
    def test_removing_it_costs_matches(self, difficulty: Difficulty) -> None:
        dataset = ChaosEngine(
            GenerationConfig(seed=42, difficulty=difficulty, order_count=600)
        ).generate()
        cards = evaluate(dataset).scorecards
        without, with_fuzzy = cards[-2], cards[-1]

        assert with_fuzzy.match_rate > without.match_rate, (
            "the similarity rung resolved nothing the arithmetic rungs had not "
            "already resolved - it is dead weight in the cascade"
        )
        assert with_fuzzy.precision == 1.0, "it bought recall with a wrong answer"
