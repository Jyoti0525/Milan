"""Damaged settlement references.

For two days this generator modelled a reference as either perfect or absent.
Real narrations do neither reliably: they truncate at a field width, transpose
a pair of characters when re-keyed, confuse O for 0, pick up digits from an
adjacent column, or get split by a delimiter.

The distinction matters more than it sounds. A deleted reference announces
itself - there is nothing to match on, so the fallback rungs run. A damaged
one still looks like evidence, defeats string equality completely, and is
indistinguishable from a *wrong* reference without a technique that can
measure similarity. It is the input probabilistic linkage exists to handle,
and any argument about whether such a technique is needed is worthless until
this class is actually generated.
"""

from __future__ import annotations

import pytest

from milan.chaos.config import Difficulty, GenerationConfig, defects_for
from milan.chaos.generator import ChaosEngine
from milan.domain.dataset import Dataset
from milan.recon.matching.exact import extract_utr

DAMAGED = "UTR_DAMAGED"
HARD_TIERS = pytest.mark.parametrize(
    "difficulty", [Difficulty.REALISTIC, Difficulty.MESSY, Difficulty.ADVERSARIAL]
)


def build(difficulty: Difficulty, orders: int = 900, seed: int = 42) -> Dataset:
    return ChaosEngine(
        GenerationConfig(seed=seed, difficulty=difficulty, order_count=orders)
    ).generate()


def damaged_credits(data: Dataset) -> list:
    truth = data.answer_key.by_credit()
    return [c for c in data.bank_credits if truth[c.credit_id].defect == DAMAGED]


class TestTheDefectIsReal:
    @HARD_TIERS
    def test_the_harder_tiers_damage_some_references(self, difficulty: Difficulty) -> None:
        assert defects_for(difficulty).utr_damaged > 0
        assert damaged_credits(build(difficulty))

    def test_the_clean_tier_damages_none(self) -> None:
        """CLEAN stays the control case: if the engine cannot score 100% on
        it, the engine is broken rather than the data."""
        assert not damaged_credits(build(Difficulty.CLEAN))

    @HARD_TIERS
    def test_a_damaged_reference_never_survives_exact_matching(
        self, difficulty: Difficulty
    ) -> None:
        """Otherwise the knob records a defect it did not inject.

        A substitution landing on a character with no look-alike used to
        return the reference unchanged, which marked a credit damaged while
        leaving it perfectly matchable - inflating the fallback rungs' share
        of the credit for work the first rung had already done.
        """
        data = build(difficulty)
        real = {s.settlement_utr for s in data.settlements}
        for credit in damaged_credits(data):
            recovered = credit.utr or extract_utr(credit.narration)
            assert recovered not in real, f"{credit.narration!r} still yields a usable reference"

    @HARD_TIERS
    def test_damaged_references_stay_matchable(self, difficulty: Difficulty) -> None:
        """The reference is gone; the evidence is not.

        A damaged credit still has an amount and a date, so it is resolvable
        and counts against the match rate if missed. Marking it impossible
        would quietly convert a miss into a correct refusal.
        """
        data = build(difficulty)
        truth = data.answer_key.by_credit()
        for credit in damaged_credits(data):
            assert truth[credit.credit_id].matchable
            assert truth[credit.credit_id].settlement_ids


class TestMergingDoesNotPickItsVictims:
    """The bug this class exists to prevent.

    Merging used to consider only credits whose reference was intact, so it
    systematically consumed exactly the credits the first rung could resolve.
    The reference rung's score was then a measurement of that filter rather
    than of how often a bank keeps a reference - and it fell to 3.4% on the
    adversarial tier once damaged references shrank the clean pool further.
    """

    @HARD_TIERS
    def test_some_credits_keep_an_intact_reference(self, difficulty: Difficulty) -> None:
        data = build(difficulty)
        truth = data.answer_key.by_credit()
        intact = [c for c in data.bank_credits if truth[c.credit_id].defect is None]
        assert intact, "every credit carries a defect - merging has eaten the clean ones"

    @HARD_TIERS
    def test_merged_credits_are_not_all_drawn_from_clean_ones(self, difficulty: Difficulty) -> None:
        """A bank sweeping two transfers together does not check whether it
        kept the reference first."""
        data = build(difficulty, orders=1200)
        merged = [t for t in data.answer_key.credits if t.is_merged]
        assert merged
        # Some merged credits must come from groups where no member had a
        # usable reference, or the filter is still selecting on cleanliness.
        assert any(t.defect == "MERGED_CREDIT" for t in merged), (
            "every merged credit carries a reference - merging is still "
            "drawing only from credits whose reference survived"
        )
