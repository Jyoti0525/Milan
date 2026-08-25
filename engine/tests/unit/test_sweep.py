"""Pooling across seeds, and why it is pooling rather than averaging.

The distinction is not pedantic. A run with six shortfalls and a run with two
are not equally informative about the rate, and averaging their percentages
says they are. On the figures this project publishes the difference is large
enough to change what a reader concludes.
"""

from __future__ import annotations

import pytest

from milan.chaos.config import Difficulty
from milan.evaluation.sweep import Spread, _spread, sweep


class TestPoolingIsNotAveraging:
    def test_a_big_run_and_a_small_one_do_not_count_equally(self) -> None:
        """One seed names 1 of 9, another names 1 of 1.

        Averaging the rates gives 55.6% and suggests the system names about
        half. Pooling gives 20%, which is what actually happened.
        """
        spread = _spread("shortfalls named", [(1, 9), (1, 1)])

        assert spread.pooled == pytest.approx(0.2)
        assert (spread.numerator, spread.denominator) == (2, 10)
        assert spread.lowest == pytest.approx(1 / 9)
        assert spread.highest == 1.0

    def test_a_seed_with_nothing_to_measure_does_not_score_zero(self) -> None:
        """A run containing no shortfalls has no opinion about the rate.

        Counting it as 0% would drag the figure down for the wrong reason -
        the system did not fail to name anything, there was nothing there.
        """
        spread = _spread("shortfalls named", [(3, 3), (0, 0)])

        assert spread.pooled == 1.0
        assert spread.lowest == 1.0

    def test_the_swing_is_what_says_a_single_seed_was_publishable(self) -> None:
        steady = _spread("match rate", [(10, 10), (12, 12), (9, 9)])
        volatile = _spread("shortfalls named", [(1, 6), (5, 6), (3, 6)])

        assert steady.swing == 0.0
        assert volatile.swing == pytest.approx(4 / 6)

    def test_an_empty_measure_reports_nothing_rather_than_dividing(self) -> None:
        spread = _spread("merged credits resolved", [(0, 0)])

        assert spread.pooled == 0.0
        assert spread.denominator == 0


class TestTheSweepItself:
    """Small and slow enough to keep honest: three seeds, few orders."""

    def test_it_pools_every_seed_it_was_given(self) -> None:
        result = sweep(Difficulty.REALISTIC, seeds=(1, 2, 3), orders=120)

        assert result.seeds == (1, 2, 3)
        assert result.named("match rate").denominator >= 3
        assert {spread.name for spread in result.spreads} >= {
            "match rate",
            "precision",
            "refusal rate",
            "shortfalls named",
        }

    def test_a_forced_answer_would_show_up_as_lost_precision(self) -> None:
        """The property that has to hold for the pooled headline to mean
        anything: across every seed, nothing was claimed that was wrong."""
        result = sweep(Difficulty.MESSY, seeds=(1, 2, 3), orders=200)

        assert result.named("precision").pooled == 1.0

    def test_drift_totals_are_summed_across_the_sweep(self) -> None:
        result = sweep(Difficulty.MESSY, seeds=(1, 2), orders=200)

        assert result.drift_gross >= abs(result.drift_net)
        assert result.proofs_with_drift >= 0

    def test_it_is_reproducible(self) -> None:
        first = sweep(Difficulty.MESSY, seeds=(4, 5), orders=150)
        second = sweep(Difficulty.MESSY, seeds=(4, 5), orders=150)

        assert [s.pooled for s in first.spreads] == [s.pooled for s in second.spreads]


class TestSpreadIsFrozen:
    def test_a_published_figure_cannot_be_edited_after_the_fact(self) -> None:
        spread = Spread(
            name="match rate",
            pooled=1.0,
            numerator=10,
            denominator=10,
            lowest=1.0,
            middle=1.0,
            highest=1.0,
        )
        with pytest.raises(Exception, match=r"frozen|immutable"):
            spread.pooled = 0.5
