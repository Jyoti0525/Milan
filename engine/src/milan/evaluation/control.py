"""Cascade against adaptive, on accuracy and on cost.

Build order item 21b, and the one that decides a word. Cut rule 9 says that
until this benchmark runs, the project calls itself a cascade and never an
agent - so this module exists to make that word answerable to a number rather
than to a preference.

**One variable.** Both arms use the same rungs, the same verifier, the same
collision rule, the same pipeline and the same scorer. The only thing that
differs is who decides what to try next. Anything else varying between the
arms would make the result a measurement of the harness.

**Two axes, because accuracy alone cannot settle it.** A policy that ties on
every rate and does twice the work has lost, and a policy that wins by a point
while doubling the work has to be argued for rather than simply declared
better. So every arm reports what it found *and* how many times it asked a
rung to look, counted by wrapping the rungs rather than by trusting either
policy to report its own effort.

**Only the measures that matching can move.** Leak detection reads settlement
rows against the rate card and never consults a match, so a leak row would sit
identical in both arms and pad the table with a fact about nothing. What is
listed here is what a control policy can actually change.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.enums import MatchStrategy
from milan.domain.rates import RateCard
from milan.domain.records import BankCredit
from milan.evaluation.harness import score, to_recon_input
from milan.evaluation.metrics import Scorecard
from milan.evaluation.sweep import Spread, pool
from milan.recon.batches import GatewayBatch
from milan.recon.matching.adaptive import AdaptiveMatcher
from milan.recon.matching.base import Attempt, Matcher, Strategy
from milan.recon.matching.cascade import Cascade
from milan.recon.matching.exact import ExactUtrStrategy
from milan.recon.matching.fuzzy import FuzzyNarrationStrategy
from milan.recon.matching.shortfall import ShortfallStrategy
from milan.recon.matching.subset import SubsetSumStrategy
from milan.recon.matching.tolerance import AmountDateStrategy
from milan.recon.pipeline import ReconciliationPipeline, RunMetadata


@dataclass
class Tally:
    """How much work a policy asked for, counted from outside it.

    Deliberately not a method on either policy. A policy that reports its own
    effort is a policy that can be wrong about it in the direction that
    flatters it, and the two arms would then be reporting two different
    definitions of the same word.
    """

    attempts: int = 0
    by_rung: dict[str, int] = field(default_factory=dict)

    def record(self, rung: MatchStrategy) -> None:
        self.attempts += 1
        self.by_rung[rung.value] = self.by_rung.get(rung.value, 0) + 1


class Counted:
    """One rung, wrapped so that asking it costs something visible."""

    def __init__(self, inner: Strategy, tally: Tally) -> None:
        self.name = inner.name
        self._inner = inner
        self._tally = tally

    def attempt(self, credit: BankCredit, candidates: tuple[GatewayBatch, ...]) -> Attempt:
        self._tally.record(self.name)
        return self._inner.attempt(credit, candidates)


def rungs(rates: RateCard, tally: Tally) -> tuple[Strategy, ...]:
    """The five rungs both arms share, each counting its own invocations."""
    built: tuple[Strategy, ...] = (
        ExactUtrStrategy(),
        AmountDateStrategy(),
        SubsetSumStrategy(),
        FuzzyNarrationStrategy(),
        ShortfallStrategy(rates),
    )
    return tuple(Counted(strategy, tally) for strategy in built)


class Arm(BaseModel):
    """One control policy, scored and priced."""

    model_config = ConfigDict(frozen=True)

    label: str
    spreads: tuple[Spread, ...]
    attempts: int
    by_rung: dict[str, int]
    seconds: float
    credits: int

    @property
    def attempts_per_credit(self) -> float:
        return self.attempts / self.credits if self.credits else 0.0

    def named(self, name: str) -> Spread:
        return next(spread for spread in self.spreads if spread.name == name)


class Comparison(BaseModel):
    """Both arms over the same seeds."""

    model_config = ConfigDict(frozen=True)

    difficulty: str
    seeds: tuple[int, ...]
    orders: int
    arms: tuple[Arm, ...]

    @property
    def measures(self) -> tuple[str, ...]:
        """The measure names, read off the first arm rather than restated.

        A hard-coded list here would silently drop a measure that stopped
        being produced, and a table missing a row looks exactly like a table
        that never had one.
        """
        return tuple(spread.name for spread in self.arms[0].spreads)

    def arm(self, label: str) -> Arm:
        return next(arm for arm in self.arms if arm.label == label)

    @property
    def accuracy_matches(self) -> bool:
        """Whether every arm reports identical pooled counts.

        The interesting outcome and the one the cut rule turns on. Compared on
        counts rather than on rounded rates, because two arms differing by one
        credit in five hundred agree to one decimal place and do not agree.
        """
        first = self.arms[0]
        return all(
            arm.named(name).numerator == first.named(name).numerator
            and arm.named(name).denominator == first.named(name).denominator
            for arm in self.arms[1:]
            for name in self.measures
        )


def _spreads(cards: list[Scorecard]) -> tuple[Spread, ...]:
    return (
        pool("match rate", [(c.true_positives, c.matchable) for c in cards]),
        pool(
            "settlement attributed",
            [(c.attributed, c.matchable + c.unprovable_expected) for c in cards],
        ),
        pool(
            "precision",
            [(c.true_positives, c.true_positives + c.false_positives) for c in cards],
        ),
        pool("refusal rate", [(c.correct_refusals, c.impossible) for c in cards]),
        pool(
            "shortfalls named",
            [(c.unprovable_explained, c.unprovable_expected) for c in cards],
        ),
        pool(
            "merged credits resolved",
            [(c.merged_resolved, c.merged_expected) for c in cards],
        ),
    )


def _run_arm(
    label: str,
    build: str,
    difficulty: Difficulty,
    seeds: tuple[int, ...],
    orders: int,
) -> Arm:
    tally = Tally()
    cards: list[Scorecard] = []
    seconds = 0.0
    credits = 0

    for seed in seeds:
        rates = RateCard()
        config = GenerationConfig(seed=seed, difficulty=difficulty, order_count=orders)
        dataset = ChaosEngine(config).generate()
        data = to_recon_input(dataset)

        matcher: Matcher = (
            Cascade(rungs(rates, tally))
            if build == "cascade"
            else AdaptiveMatcher(rungs(rates, tally))
        )
        report = ReconciliationPipeline(rates=rates, cascade=matcher).run(
            data, RunMetadata(seed=seed, difficulty=difficulty.value)
        )
        cards.append(score(report, dataset.answer_key, label))
        seconds += report.duration_seconds
        credits += len(data.bank_credits)

    return Arm(
        label=label,
        spreads=_spreads(cards),
        attempts=tally.attempts,
        by_rung=dict(tally.by_rung),
        seconds=seconds,
        credits=credits,
    )


def compare(
    difficulty: Difficulty,
    seeds: tuple[int, ...],
    orders: int = 600,
) -> Comparison:
    """Score both control policies over the same generated datasets.

    Each arm regenerates the dataset rather than sharing one. Generation is a
    pure function of its seed, so the two arms see byte-identical inputs, and
    regenerating costs less than the bug where one arm mutates a record the
    other has not read yet.
    """
    return Comparison(
        difficulty=difficulty.value,
        seeds=seeds,
        orders=orders,
        arms=(
            _run_arm("cascade (fixed order)", "cascade", difficulty, seeds, orders),
            _run_arm("adaptive (routed per credit)", "adaptive", difficulty, seeds, orders),
        ),
    )
