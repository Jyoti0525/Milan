"""The cascade-vs-adaptive result, pinned.

Build order item 21b decides a word: cut rule 9 says that until this benchmark
runs, the project calls itself a cascade and never an agent. A word that rests
on a measurement needs the measurement to keep being true, so the figures the
README publishes are asserted here rather than remembered.

The interesting assertion is the last one. Adaptivity is not tested for being
worthless - it is tested for never being *better*, on either axis, which is a
claim that a future change could genuinely falsify.
"""

from __future__ import annotations

import pytest

from milan.chaos.config import Difficulty
from milan.evaluation.control import compare

SEEDS = tuple(range(1, 21))
ORDERS = 600

CASCADE = "cascade (fixed order)"
ADAPTIVE = "adaptive (routed per credit)"


@pytest.fixture(scope="module")
def adversarial():
    return compare(Difficulty.ADVERSARIAL, SEEDS, ORDERS)


class TestThePublishedFigures:
    """What the README says, checked against a fresh run."""

    def test_the_cascade_scores_what_the_readme_claims(self, adversarial) -> None:
        arm = adversarial.arm(CASCADE)
        assert (arm.named("match rate").numerator, arm.named("match rate").denominator) == (
            389,
            389,
        )
        assert (
            arm.named("settlement attributed").numerator,
            arm.named("settlement attributed").denominator,
        ) == (499, 509)
        assert (
            arm.named("shortfalls named").numerator,
            arm.named("shortfalls named").denominator,
        ) == (110, 120)

    def test_the_adaptive_arm_scores_what_the_readme_claims(self, adversarial) -> None:
        arm = adversarial.arm(ADAPTIVE)
        assert (arm.named("match rate").numerator, arm.named("match rate").denominator) == (
            389,
            389,
        )
        assert (
            arm.named("settlement attributed").numerator,
            arm.named("settlement attributed").denominator,
        ) == (496, 509)
        assert (
            arm.named("shortfalls named").numerator,
            arm.named("shortfalls named").denominator,
        ) == (107, 120)

    def test_routing_costs_about_twice_the_work(self, adversarial) -> None:
        """The cost axis, which is what actually settles the question.

        A ratio rather than two totals. The absolute attempt counts move with
        anything that changes a rung's reach, and pinning them would make this
        a test about the generator; the ratio is the finding.
        """
        fixed = adversarial.arm(CASCADE).attempts
        routed = adversarial.arm(ADAPTIVE).attempts
        assert routed / fixed == pytest.approx(2.0, abs=0.15)


class TestAdaptivityNeverWins:
    """The claim the vocabulary rests on."""

    def test_it_never_scores_higher_on_any_measure(self, adversarial) -> None:
        fixed, routed = adversarial.arm(CASCADE), adversarial.arm(ADAPTIVE)
        better = [
            name
            for name in adversarial.measures
            if routed.named(name).numerator > fixed.named(name).numerator
        ]
        assert not better, f"adaptive beat the cascade on {better}; the docs need rewriting"

    def test_it_never_asks_for_less_work(self, adversarial) -> None:
        assert adversarial.arm(ADAPTIVE).attempts >= adversarial.arm(CASCADE).attempts

    @pytest.mark.parametrize(
        "difficulty",
        [Difficulty.CLEAN, Difficulty.REALISTIC, Difficulty.MESSY],
    )
    def test_the_easier_tiers_are_a_dead_heat(self, difficulty: Difficulty) -> None:
        """Identical counts, not similar rates.

        Two arms differing by one credit in five hundred agree to one decimal
        place and do not agree.
        """
        result = compare(difficulty, tuple(range(1, 11)), 300)
        assert result.accuracy_matches
