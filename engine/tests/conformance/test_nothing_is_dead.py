"""Checks that catch the two ways this project has actually gone wrong.

Every gap found in the days 1-3 audit had one of two shapes:

**Implemented but never exercised.** Section 194-O withholding was written,
unit-tested, and switched off everywhere, so no generated dataset ever
contained a withholding row and the whole solver path was dead. Correct dead
code raises no alarms - it is the state that looks most like being finished.

**Computed but never surfaced.** `Scorecard.rules_share` was calculated on
every run and rendered nowhere. A number nobody can see is a number nobody
checks.

Both are mechanically detectable, which is the point of this module. A
promise to be more careful does not scale; a failing test does.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.cli import render
from milan.domain.enums import ExceptionCode, MatchStrategy
from milan.domain.rates import RateCard
from milan.domain.results import ReconReport
from milan.evaluation.harness import to_recon_input
from milan.evaluation.metrics import Scorecard
from milan.recon.pipeline import ReconciliationPipeline, RunMetadata

TIERS = list(Difficulty)


def run(difficulty: Difficulty, withholding: bool = False) -> ReconReport:
    dataset = ChaosEngine(
        GenerationConfig(
            seed=42,
            difficulty=difficulty,
            order_count=600,
            rates=RateCard(tds_applies=withholding),
        )
    ).generate()
    return ReconciliationPipeline().run(
        to_recon_input(dataset),
        RunMetadata(seed=dataset.seed, difficulty=dataset.difficulty),
    )


@pytest.fixture(scope="module")
def every_code() -> set[str]:
    """Every exception code any tier actually emits."""
    emitted: set[str] = set()
    for difficulty in TIERS:
        for withholding in (False, True):
            emitted |= {e.code.value for e in run(difficulty, withholding).exceptions}
    return emitted


@pytest.fixture(scope="module")
def every_strategy() -> set[str]:
    matched: set[str] = set()
    for difficulty in TIERS:
        matched |= {p.strategy.value for p in run(difficulty).proofs if p.balances}
    return matched


class TestEveryCategoryIsReachable:
    """An exception code nothing emits reads as a category we support.

    The categoriser is Tier 1 and explicitly not a fallback, so a branch that
    never fires is not a spare tyre - it is a claim in the submission that
    the system sorts exceptions it has in fact never sorted.
    """

    @pytest.mark.parametrize("code", list(ExceptionCode))
    def test_some_tier_emits_it(self, code: ExceptionCode, every_code: set[str]) -> None:
        assert code.value in every_code, (
            f"{code.value} is defined and never emitted by any tier. Either the "
            "generator does not produce the situation it describes, or the "
            "categoriser cannot reach it."
        )


class TestEveryRungEarnsItsPlace:
    @pytest.mark.parametrize(
        "strategy", [s for s in MatchStrategy if s != MatchStrategy.FUZZY_NARRATION]
    )
    def test_some_tier_matches_with_it(
        self, strategy: MatchStrategy, every_strategy: set[str]
    ) -> None:
        """A rung that never produces a match is either unreachable or
        unnecessary, and both are worth knowing before the submission."""
        assert strategy.value in every_strategy


class TestEveryNumberIsShown:
    """A metric rendered nowhere is a metric nobody checks.

    Read statically rather than by scraping output, because a metric can be
    rendered in a table that a given run happens to leave empty. What matters
    is that some code path puts it in front of a person.
    """

    def test_every_scorecard_figure_reaches_the_screen(self) -> None:
        source = Path(inspect.getfile(render)).read_text(encoding="utf-8")
        shown = set(re.findall(r"card\.([a-z_]+)", source))

        reported = {
            name
            for name in (*Scorecard.model_fields, *_properties(Scorecard))
            if not name.startswith("_") and name != "label"
        }
        missing = sorted(reported - shown)
        assert not missing, (
            f"computed and never rendered: {missing}. A number nobody can see "
            "is a number nobody checks."
        )


def _properties(model: type) -> list[str]:
    return [name for name, value in vars(model).items() if isinstance(value, property)]
