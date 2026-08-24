"""The oracle test: is the answer key itself correct?

A matcher handed the right settlement for every credit must score exactly
100%. If it does not, the matching code is not what is wrong - the generated
data and the waterfall solver disagree about where the money went, and every
accuracy number in this project is being measured against a broken ruler.

This runs on every tier, including the ones designed to be hard, because a
generator bug that only appears under injected defects is the one most likely
to survive to submission.
"""

from __future__ import annotations

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.dataset import Dataset
from milan.evaluation.harness import score, to_recon_input
from milan.evaluation.oracle import OracleStrategy
from milan.recon.matching.cascade import Cascade
from milan.recon.pipeline import ReconciliationPipeline, RunMetadata

ALL_TIERS = pytest.mark.parametrize("difficulty", list(Difficulty))


def generate(difficulty: Difficulty, orders: int = 250, seed: int = 42) -> Dataset:
    return ChaosEngine(
        GenerationConfig(seed=seed, difficulty=difficulty, order_count=orders)
    ).generate()


def run_oracle(dataset: Dataset) -> tuple[object, object]:
    pipeline = ReconciliationPipeline(cascade=Cascade((OracleStrategy(dataset.answer_key),)))
    report = pipeline.run(
        to_recon_input(dataset),
        RunMetadata(seed=dataset.seed, difficulty=dataset.difficulty),
    )
    return report, score(report, dataset.answer_key, "oracle")


class TestTheAnswerKeyIsSound:
    @ALL_TIERS
    def test_a_perfect_matcher_scores_perfectly(self, difficulty: Difficulty) -> None:
        dataset = generate(difficulty)
        _, card = run_oracle(dataset)
        assert card.match_rate == 1.0, (  # type: ignore[attr-defined]
            "handed the right settlement for every credit, the solver still could not "
            "reconstruct them all - the generated data is inconsistent"
        )
        assert card.precision == 1.0  # type: ignore[attr-defined]
        assert card.false_positives == 0  # type: ignore[attr-defined]

    @ALL_TIERS
    def test_every_oracle_proof_balances_to_zero(self, difficulty: Difficulty) -> None:
        """The stricter form: not just matched, but reconstructed to the paisa."""
        dataset = generate(difficulty)
        report, _ = run_oracle(dataset)
        unbalanced = [p for p in report.proofs if not p.balances]  # type: ignore[attr-defined]
        assert not unbalanced, [(proof.credit_id, proof.residual) for proof in unbalanced]

    @ALL_TIERS
    def test_the_oracle_refuses_what_cannot_be_matched(self, difficulty: Difficulty) -> None:
        """Even with the answers, an unresolvable credit stays unresolved.

        Guards against a generator that marks a credit impossible while
        quietly leaving a settlement behind it - which would make the refusal
        metric measure nothing.
        """
        dataset = generate(difficulty)
        _, card = run_oracle(dataset)
        assert card.correct_refusals == card.impossible  # type: ignore[attr-defined]

    @pytest.mark.parametrize("seed", [1, 7, 99, 2026])
    def test_it_holds_across_seeds(self, seed: int) -> None:
        """One passing seed is an anecdote."""
        dataset = generate(Difficulty.ADVERSARIAL, orders=180, seed=seed)
        report, card = run_oracle(dataset)
        assert card.match_rate == 1.0  # type: ignore[attr-defined]
        assert all(proof.balances for proof in report.proofs)  # type: ignore[attr-defined]
