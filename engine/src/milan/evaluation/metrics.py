"""What a run scored, and how.

Four counts do most of the work here, and keeping them separate is the whole
point:

- **true positive** - claimed a settlement, and it was the right one
- **false positive** - claimed a settlement that was wrong, *or* claimed one
  for a credit that had none to find
- **false negative** - a resolvable credit left unresolved
- **correct refusal** - an unresolvable credit correctly left alone

A single "match rate" hides the difference between the last two, and the
difference is the entire design stance. A system that forces an answer onto
every credit scores a perfect match rate and corrupts the books.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Scorecard(BaseModel):
    """One configuration, measured against ground truth."""

    model_config = ConfigDict(frozen=True)

    label: str

    records_processed: int
    duration_seconds: float

    credits_total: int
    matchable: int
    impossible: int

    true_positives: int
    false_positives: int
    false_negatives: int
    correct_refusals: int

    proofs_balanced: int
    proofs_claimed: int

    exceptions_total: int
    exceptions_by_code: dict[str, int] = Field(default_factory=dict)

    missing_settlements_expected: int = 0
    missing_settlements_detected: int = 0

    matches_by_strategy: dict[str, int] = Field(default_factory=dict)
    unresolved_by_defect: dict[str, int] = Field(default_factory=dict)

    categorised_by: dict[str, int] = Field(default_factory=dict)

    # ------------------------------------------------------------ derived

    @property
    def records_per_second(self) -> float:
        if self.duration_seconds <= 0:
            return 0.0
        return self.records_processed / self.duration_seconds

    @property
    def match_rate(self) -> float:
        """Share of resolvable credits that were resolved correctly.

        The denominator is deliberately the resolvable credits, not all of
        them. Counting impossible records against the match rate would
        penalise the refusal this system is built to make.
        """
        return _ratio(self.true_positives, self.matchable)

    @property
    def precision(self) -> float:
        """Of the settlements claimed, the share that were right."""
        return _ratio(self.true_positives, self.true_positives + self.false_positives)

    @property
    def refusal_rate(self) -> float:
        """Of the credits that could not be resolved, the share left alone."""
        return _ratio(self.correct_refusals, self.impossible)

    @property
    def exception_rate(self) -> float:
        return _ratio(self.exceptions_total, self.credits_total)

    @property
    def missing_detection_rate(self) -> float:
        return _ratio(self.missing_settlements_detected, self.missing_settlements_expected)

    @property
    def rules_share(self) -> float:
        """Share of exceptions categorised without a model.

        Reported because "we used AI here and not there" is a claim, and this
        is the number that makes it checkable.
        """
        total = sum(self.categorised_by.values())
        return _ratio(self.categorised_by.get("rules", 0), total)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0
