"""Scoring across seeds, because one seed is not a measurement.

Match rate, precision and refusal rate are stable here - they are measured
over twenty or thirty credits and they do not move between seeds. One figure
is not. "Shortfalls named" has a denominator of about six per run, and across
twenty adversarial seeds it ranged from 16.7% to 83.3% while everything else
sat at 100%.

That range is the point. A single-seed reading of 83% and a single-seed
reading of 17% are the same system, and either could have been published with
a straight face. Pooling the counts rather than averaging the rates gives one
number with a denominator attached, and the spread is reported beside it so a
reader can see how much confidence the denominator supports.

Pooled, not averaged: a run with six shortfalls and a run with two should not
count equally toward a percentage.
"""

from __future__ import annotations

from statistics import median

from pydantic import BaseModel, ConfigDict

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.money import Paise
from milan.domain.rates import RateCard
from milan.evaluation.harness import evaluate
from milan.evaluation.metrics import Scorecard


class Spread(BaseModel):
    """One rate across the seeds that produced it."""

    model_config = ConfigDict(frozen=True)

    name: str
    pooled: float
    """Numerator over denominator, summed across every seed."""

    numerator: int
    denominator: int
    lowest: float
    middle: float
    highest: float

    @property
    def swing(self) -> float:
        """How far the best seed sits above the worst.

        The figure that says whether a single-seed number was worth
        publishing.
        """
        return self.highest - self.lowest


class Sweep(BaseModel):
    """Every seed's headline configuration, pooled."""

    model_config = ConfigDict(frozen=True)

    difficulty: str
    seeds: tuple[int, ...]
    orders: int
    spreads: tuple[Spread, ...]

    drift_gross: Paise
    drift_net: Paise
    proofs_with_drift: int

    def named(self, name: str) -> Spread:
        return next(spread for spread in self.spreads if spread.name == name)


def _spread(name: str, pairs: list[tuple[int, int]]) -> Spread:
    """Pool the counts; report the range of the per-seed rates beside them."""
    numerator = sum(hit for hit, _ in pairs)
    denominator = sum(total for _, total in pairs)
    rates = [hit / total for hit, total in pairs if total]
    if not rates:
        rates = [0.0]
    return Spread(
        name=name,
        pooled=numerator / denominator if denominator else 0.0,
        numerator=numerator,
        denominator=denominator,
        lowest=min(rates),
        middle=median(rates),
        highest=max(rates),
    )


def sweep(
    difficulty: Difficulty,
    seeds: tuple[int, ...],
    orders: int = 600,
    withholding: bool = False,
) -> Sweep:
    """Generate and score one dataset per seed, then pool the counts."""
    cards: list[Scorecard] = []
    for seed in seeds:
        config = GenerationConfig(
            seed=seed,
            difficulty=difficulty,
            order_count=orders,
            rates=RateCard(tds_applies=withholding),
        )
        cards.append(evaluate(ChaosEngine(config).generate(), headline_only=True).headline)

    return Sweep(
        difficulty=difficulty.value,
        seeds=seeds,
        orders=orders,
        spreads=(
            _spread("match rate", [(c.true_positives, c.matchable) for c in cards]),
            _spread(
                "precision",
                [(c.true_positives, c.true_positives + c.false_positives) for c in cards],
            ),
            _spread("refusal rate", [(c.correct_refusals, c.impossible) for c in cards]),
            _spread(
                "shortfalls named",
                [(c.unprovable_explained, c.unprovable_expected) for c in cards],
            ),
            _spread(
                "merged credits resolved",
                [(c.merged_resolved, c.merged_expected) for c in cards],
            ),
            _spread(
                "missing payouts flagged",
                [(c.missing_settlements_detected, c.missing_settlements_expected) for c in cards],
            ),
            _spread(
                "unsettled payments flagged",
                [(c.unreported_payments_detected, c.unreported_payments_expected) for c in cards],
            ),
        ),
        drift_gross=Paise(sum(c.drift_gross for c in cards)),
        drift_net=Paise(sum(c.drift_net for c in cards)),
        proofs_with_drift=sum(c.proofs_with_drift for c in cards),
    )
