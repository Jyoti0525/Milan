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
from milan.recon.batches import GatewayBatch
from milan.recon.matching.base import Verdict
from milan.recon.matching.fuzzy import (
    FuzzyNarrationStrategy,
    normalise,
    similarity,
)
from tests.unit.test_merged_credits import bank_credit, batches_of, row

REFERENCE = "CJ3GZ79N4G1F"


def one_settlement(reference: str = REFERENCE) -> tuple[GatewayBatch, ...]:
    return batches_of(row("pay_1", "10000", "setl_a", 8, reference))


class TestNormalisation:
    def test_bank_words_are_stripped_before_comparing(self) -> None:
        """They are long runs of capitals, which is what a reference looks
        like to a similarity measure. Left in, every comparison competes
        against RAZORPAYSOFTWARE."""
        assert "RAZORPAY" not in normalise("NEFT-ABC123-RAZORPAY SOFTWARE PVT LTD")

    def test_delimiters_are_removed_so_a_split_reference_rejoins(self) -> None:
        assert "DJRJMSS5NDW4" in normalise("NEFT-DJR/JMSS5NDW4-RAZORPAY SOFTWARE")


class TestTheThingsNormalisingMustNotDo:
    """Both of these were live defects, found by a property test asking
    whether a reference is similar to itself. Neither would have been found
    by a hand-written narration, because a person writing one picks a
    reference that reads like a reference."""

    def test_a_reference_containing_a_bank_word_keeps_it(self) -> None:
        """`CR` inside `JMSS5NDW4CR` is two characters of the reference, not
        the bank's abbreviation for credit. Stripping it shortened the only
        evidence this rung has, on every reference that happened to contain
        CR, ACH, LTD, PVT or UTR."""
        assert normalise("NEFT-JMSS5NDW4CR-RAZORPAY") == "JMSS5NDW4CR"
        assert similarity("JMSS5NDW4CR", "NEFT-JMSS5NDW4CR-RAZORPAY") == 1.0

    def test_a_reference_is_always_perfectly_similar_to_itself(self) -> None:
        assert similarity("2222222222CR", "2222222222CR") == 1.0

    def test_a_label_glued_onto_a_truncated_reference_is_still_found(self) -> None:
        """`UTRRKBZWJLK` is the bank's own label with no separator, wrapped
        around a reference that has itself been cut short - so the narration
        is *shorter* than the reference it contains. A window sweep sized
        from the reference stops before the alignment that matches."""
        assert similarity("RKBZWJLKOM0N", "UTRRKBZWJLK RAZORPAY PAYOUT") >= 0.78

    def test_an_unrelated_reference_still_scores_nothing(self) -> None:
        """The sweep got wider; it must not have got more agreeable."""
        assert similarity("ABCDEFGH1234", "NEFT-ZZZZZZZZ9999-RAZORPAY") < 0.5


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
        # Found by label, not by position. This read `cards[-2], cards[-1]`
        # until a fifth rung was added to the ladder, at which point it
        # silently began comparing fuzzy against shortfall and failed for a
        # reason that had nothing to do with fuzzy. A test that names the two
        # things it compares cannot be repointed by an unrelated change.
        cards = {card.label: card for card in evaluate(dataset).scorecards}
        without = cards["+ subset sum"]
        with_fuzzy = cards["+ fuzzy narration"]

        assert with_fuzzy.match_rate > without.match_rate, (
            "the similarity rung resolved nothing the arithmetic rungs had not "
            "already resolved - it is dead weight in the cascade"
        )
        assert with_fuzzy.precision == 1.0, "it bought recall with a wrong answer"
