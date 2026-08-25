"""Asking the same question twice, tested without a model.

The experiment itself needs a GPU and forty seconds. What it *counts* does
not, and the counting is where this could quietly go wrong: a comparison that
called two answers equal when they named different refunds would report
perfect stability from a model that had changed its mind on every question.

So the providers here are scripted. One repeats itself, one does not, and the
assertions are about the arithmetic between them rather than about anything a
model said.
"""

from __future__ import annotations

from milan.chaos.config import Difficulty
from milan.evaluation.twice import Answer, Question, run_twice
from milan.llm.provider import Completion, Request, StaticProvider

SEEDS = (1,)
ORDERS = 300


class Alternating:
    """Answers differently every other call, deterministically.

    The shape of a model that has not been pinned: same question, same
    prompt, two answers.
    """

    name = "alternating"
    model = "scripted"

    def __init__(self, *answers: str) -> None:
        self._answers = answers
        self.calls = 0

    def complete(self, request: Request) -> Completion:
        del request
        answer = self._answers[self.calls % len(self._answers)]
        self.calls += 1
        return Completion(text=answer, provider=self.name, model=self.model)


class TestWhatCountsAsAChange:
    def test_the_same_claim_twice_is_not_a_change(self) -> None:
        left = Answer(kind="recovery_gap", entity_id="rfnd_a")
        assert not Question(credit_id="bank_1", first=left, second=left).changed

    def test_a_different_record_under_the_same_kind_is_a_change(self) -> None:
        """The expensive disagreement, and the one a naive comparison of
        categories would miss entirely."""
        question = Question(
            credit_id="bank_1",
            first=Answer(kind="recovery_gap", entity_id="rfnd_a"),
            second=Answer(kind="recovery_gap", entity_id="rfnd_b"),
        )

        assert question.changed
        assert question.named_a_different_record

    def test_changing_its_mind_about_the_category_is_a_change_but_not_that_one(
        self,
    ) -> None:
        """`unknown` then `recovery_gap` is instability, not a wrong record -
        there is no first record to have been wrong about."""
        question = Question(
            credit_id="bank_1",
            first=Answer(kind="unknown"),
            second=Answer(kind="recovery_gap", entity_id="rfnd_b"),
        )

        assert question.changed
        assert not question.named_a_different_record


class TestTheExperiment:
    def test_a_model_that_repeats_itself_reports_no_movement(self) -> None:
        result = run_twice(
            StaticProvider('{"kind": "tax_variance"}'),
            seeds=SEEDS,
            difficulty=Difficulty.ADVERSARIAL,
            orders=ORDERS,
            limit=4,
        )

        assert result.asked > 0
        assert result.stable
        assert result.changed == 0

    def test_a_model_that_does_not_is_counted_question_by_question(self) -> None:
        """Two passes, alternating answers, so every question disagrees with
        itself - and the count has to be the number of questions rather than
        the number of calls."""
        result = run_twice(
            # JSON, because that is what the parser reads - and two kinds
            # that need no record id, so the test does not depend on which
            # refunds a seed happens to generate.
            Alternating('{"kind": "tax_variance"}', '{"kind": "fee_variance"}'),
            seeds=SEEDS,
            difficulty=Difficulty.ADVERSARIAL,
            orders=ORDERS,
            limit=4,
        )

        assert result.asked == 4
        assert result.changed == 4
        assert not result.stable

    def test_the_limit_is_a_limit_on_questions_not_on_seeds(self) -> None:
        result = run_twice(
            StaticProvider('{"kind": "tax_variance"}'),
            seeds=(1, 2, 3),
            difficulty=Difficulty.ADVERSARIAL,
            orders=ORDERS,
            limit=3,
        )

        assert result.asked == 3
