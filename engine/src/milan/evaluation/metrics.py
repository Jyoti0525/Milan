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

from milan.domain.money import ZERO, Paise


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

    proofs_with_drift: int = 0
    """Proofs that closed on the rounding allowance rather than on the rows."""

    drift_net: Paise = ZERO
    """Signed total of that drift across the run - what the merchant actually
    kept or lost to it.

    Reported because this is the one figure a merchant is routinely told to
    ignore, and "ignore it" is only sound advice if somebody has added it up.
    Per credit it is a few paise and there is no exception worth raising; a
    month of it is a number, and a number nobody computes is a number nobody
    can notice moving."""

    drift_gross: Paise = ZERO
    """Sum of the absolute drift.

    Kept separate from the net because drift largely cancels, and a net near
    zero would otherwise read as "this does not happen" when what it means is
    "this happens in both directions". Gross is the exposure; net is the
    outcome. Reporting only one of them is how the other stops being looked
    at."""

    exceptions_total: int
    exceptions_by_code: dict[str, int] = Field(default_factory=dict)

    missing_settlements_expected: int = 0
    missing_settlements_detected: int = 0

    unreported_payments_expected: int = 0
    unreported_payments_detected: int = 0
    """Captured payments the settlement report never mentions. Found by
    reading the payments file, not by matching credits - no bank-side
    technique can see this money, because it never arrived."""

    unprovable_expected: int = 0
    unprovable_explained: int = 0
    """Credits that are identifiable but cannot be reconstructed, because the
    payout disagrees with the report. The right output is a named exception,
    never a match - so these are scored on whether the shortfall was
    explained, not on whether it was claimed."""

    attributed: int = 0
    """Credits whose settlement the engine identified, provable or not.

    The measurement gap this closes was a real one and it took reading 54
    failures to find. `match_rate` deliberately excludes unprovable credits,
    because the right output for those is an exception rather than a match -
    but that exclusion also meant a credit which failed to match *and* was
    unprovable was scored only against explanation, where it looked like a
    naming problem. It was a matching failure with nowhere to be reported.

    This is the number that reports it: of every credit the evidence can
    single out, how many did the engine actually pin to the right settlement -
    whether it went on to prove them or to name what they were short by."""

    leaks_expected: int = 0
    leaks_found: int = 0
    leaks_false: int = 0
    """Charges above contract: how many exist, how many were found, and how
    many were claimed that were not there.

    The third number is the one that matters and it is why this is scored at
    all rather than demonstrated. A missed leak costs a merchant money they
    were already losing. A *false* leak sends them to their account manager
    to complain about an overcharge that did not happen, and there is no
    faster way for a tool like this to stop being believed."""

    leak_overcharge: Paise = ZERO
    """Fees charged above contract, in paise. The permanent loss - the GST on
    top of it is recoverable as input tax credit and is not counted here."""

    merged_expected: int = 0
    merged_resolved: int = 0
    """Credits covering more than one settlement. Broken out because they
    are the case the aggregate rate is least sensitive to and the one most
    likely to be silently wrong."""

    matches_by_strategy: dict[str, int] = Field(default_factory=dict)
    unresolved_by_defect: dict[str, int] = Field(default_factory=dict)
    unexplained_by_defect: dict[str, int] = Field(default_factory=dict)

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
    def unreported_detection_rate(self) -> float:
        return _ratio(self.unreported_payments_detected, self.unreported_payments_expected)

    @property
    def explained_rate(self) -> float:
        """Of the credits no proof can close, the share we could still name."""
        return _ratio(self.unprovable_explained, self.unprovable_expected)

    @property
    def leak_recall(self) -> float:
        """Share of the leaks in the data that were found."""
        return _ratio(self.leaks_found, self.leaks_expected)

    @property
    def leak_precision(self) -> float:
        """Share of claimed leaks that were real. Must be 1.0."""
        claimed = self.leaks_found + self.leaks_false
        return _ratio(self.leaks_found, claimed)

    @property
    def attribution_rate(self) -> float:
        """Share of every identifiable credit pinned to the right settlement.

        A strictly harder denominator than `match_rate`: it adds back the
        credits that are identifiable but unprovable, which the match rate
        excludes on purpose. Reported beside it rather than instead of it,
        because they answer different questions - "did we reconcile it" and
        "did we work out what it was".
        """
        return _ratio(self.attributed, self.matchable + self.unprovable_expected)

    @property
    def merged_rate(self) -> float:
        """Share of merged credits resolved to the exact set behind them."""
        return _ratio(self.merged_resolved, self.merged_expected)

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
