"""Scoring a run against the answer key.

This module is the one place allowed to read ground truth, and the
reconciliation package is forbidden from importing it. That boundary is what
makes the numbers mean anything: if the matcher could see the answers, a high
match rate would only prove the wiring works.

A single configuration's score is not evidence either. Every evaluation runs
the reference-only baseline alongside the full cascade, because "we resolved
most of the batch" says nothing until you know how much of it the join key
alone was already going to resolve.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict

from milan.domain.dataset import Dataset
from milan.domain.rates import RateCard
from milan.domain.results import ReconReport
from milan.domain.truth import AnswerKey
from milan.evaluation.metrics import Scorecard
from milan.recon.inputs import ReconInput
from milan.recon.matching.cascade import Cascade
from milan.recon.matching.exact import ExactUtrStrategy
from milan.recon.matching.subset import SubsetSumStrategy
from milan.recon.matching.tolerance import AmountDateStrategy
from milan.recon.pipeline import ReconciliationPipeline, RunMetadata


class Evaluation(BaseModel):
    """Every configuration measured on the same dataset."""

    model_config = ConfigDict(frozen=True)

    seed: int
    difficulty: str
    scorecards: tuple[Scorecard, ...]

    @property
    def headline(self) -> Scorecard:
        return self.scorecards[-1]


def to_recon_input(dataset: Dataset) -> ReconInput:
    """The three merchant-side files, with the answers held back."""
    return ReconInput(
        orders=dataset.orders,
        payments=dataset.payments,
        settlement_rows=dataset.settlement_rows,
        bank_credits=dataset.bank_credits,
    )


def evaluate(dataset: Dataset, rates: RateCard | None = None) -> Evaluation:
    """Run every configuration over one dataset and score each."""
    data = to_recon_input(dataset)
    metadata = RunMetadata(seed=dataset.seed, difficulty=dataset.difficulty)
    rate_card = rates if rates is not None else RateCard()

    # One rung added per row, so each row's gain over the one above it is
    # what that rung is worth. A single headline number cannot show that, and
    # a headline number whose composition is unknown is not a measurement.
    configurations = (
        ("reference only (baseline)", Cascade((ExactUtrStrategy(),))),
        ("+ amount and date", Cascade((ExactUtrStrategy(), AmountDateStrategy()))),
        (
            "full cascade (+ subset sum)",
            Cascade((ExactUtrStrategy(), AmountDateStrategy(), SubsetSumStrategy())),
        ),
    )

    scorecards = tuple(
        score(
            ReconciliationPipeline(rates=rate_card, cascade=cascade).run(data, metadata),
            dataset.answer_key,
            label,
        )
        for label, cascade in configurations
    )
    return Evaluation(seed=dataset.seed, difficulty=dataset.difficulty, scorecards=scorecards)


def score(report: ReconReport, answers: AnswerKey, label: str) -> Scorecard:
    """Compare one report against ground truth."""
    truth = answers.by_credit()
    balanced = [proof for proof in report.proofs if proof.balances]
    claimed = {proof.credit_id: proof for proof in balanced}

    true_positives = 0
    false_positives = 0
    merged_resolved = 0
    for credit_id, proof in claimed.items():
        expected = truth[credit_id]
        if expected.matchable and expected.settlement_set == proof.settlement_set:
            # The whole set, not an overlap. A credit covering two settlements
            # that is matched to only one of them has been half explained,
            # and half an explanation of where a payout went is not a partial
            # success - the merchant is still short a settlement and now has a
            # green tick saying otherwise.
            true_positives += 1
            if expected.is_merged:
                merged_resolved += 1
        else:
            # Either the wrong settlement, or an answer forced onto a credit
            # the evidence could not single out. Both are counted against us,
            # including the case where the forced answer happens to be right:
            # a system that guesses on ambiguous credits is right about half
            # the time, and rewarding the lucky half is how a coin flip comes
            # to look like accuracy.
            false_positives += 1

    resolvable = [t for t in answers.credits if t.matchable]
    impossible = [t for t in answers.credits if not t.matchable]

    return Scorecard(
        label=label,
        records_processed=report.records_processed,
        duration_seconds=report.duration_seconds,
        credits_total=len(answers.credits),
        matchable=len(resolvable),
        impossible=len(impossible),
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=sum(1 for t in resolvable if t.credit_id not in claimed),
        correct_refusals=sum(1 for t in impossible if t.credit_id not in claimed),
        proofs_balanced=len(balanced),
        proofs_claimed=len(report.proofs),
        exceptions_total=len(report.exceptions),
        exceptions_by_code=dict(Counter(e.code.value for e in report.exceptions)),
        missing_settlements_expected=len(answers.missing_settlement_ids),
        missing_settlements_detected=_missing_detected(report, answers),
        unreported_payments_expected=len(answers.unreported_payment_ids),
        unreported_payments_detected=_unreported_detected(report, answers),
        merged_expected=answers.merged_count,
        merged_resolved=merged_resolved,
        matches_by_strategy=dict(Counter(p.strategy.value for p in balanced)),
        unresolved_by_defect=_unresolved_by_defect(answers, set(claimed)),
        categorised_by=dict(Counter(e.categorised_by for e in report.exceptions)),
    )


def _missing_detected(report: ReconReport, answers: AnswerKey) -> int:
    """Payouts correctly reported as never having arrived."""
    expected = set(answers.missing_settlement_ids)
    flagged = {
        exception.subject_id
        for exception in report.exceptions
        if exception.code.value == "MISSING_SETTLEMENT"
    }
    return len(expected & flagged)


def _unreported_detected(report: ReconReport, answers: AnswerKey) -> int:
    """Captured payments correctly reported as never having been settled."""
    expected = set(answers.unreported_payment_ids)
    flagged = {
        exception.subject_id
        for exception in report.exceptions
        if exception.code.value == "UNSETTLED_PAYMENT"
    }
    return len(expected & flagged)


def _unresolved_by_defect(answers: AnswerKey, claimed: set[str]) -> dict[str, int]:
    """Which injected defect each unresolved credit was carrying.

    An aggregate match rate says how much was missed. This says what was
    missed, which is the only version of the number that tells you where to
    spend the next day of work.
    """
    counts: Counter[str] = Counter()
    for candidate in answers.credits:
        if not candidate.matchable or candidate.credit_id in claimed:
            continue
        counts[candidate.defect or "none"] += 1
    return dict(counts)
