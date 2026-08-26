"""Payouts that arrive in minutes instead of T+2 working days.

A merchant attribute rather than a defect, and the tests below are shaped by
that: what matters is that turning it on changes the dates and nothing else,
and that turning it *off* changes nothing at all.
"""

from __future__ import annotations

from collections import Counter

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.dataset import Dataset
from milan.domain.enums import CardType, EntityType
from milan.evaluation.harness import evaluate
from milan.persistence.store import content_hash
from milan.recon.batches import rebuild_batches


def _dataset(share: float, seed: int = 3, orders: int = 300) -> Dataset:
    return ChaosEngine(
        GenerationConfig(
            seed=seed,
            difficulty=Difficulty.ADVERSARIAL,
            order_count=orders,
            instant_settlement_probability=share,
        )
    ).generate()


class TestTheFeatureOffChangesNothing:
    """The regression that nearly shipped.

    Drawing from the random stream even when the probability is zero shifts
    every later draw, so a merchant who does not use the feature would get a
    different month than the one every published figure was measured on.
    """

    def test_a_zero_share_reproduces_the_default_dataset(self) -> None:
        default = ChaosEngine(
            GenerationConfig(seed=3, difficulty=Difficulty.ADVERSARIAL, order_count=300)
        ).generate()
        assert content_hash(_dataset(0.0)) == content_hash(default)

    def test_no_batch_settles_on_its_capture_date(self) -> None:
        dataset = _dataset(0.0)
        captured = {p.payment_id: p.captured_at.date() for p in dataset.payments}
        rows = [r for r in dataset.settlement_rows if r.type is EntityType.PAYMENT]
        batches = {b.settlement_id: b for b in rebuild_batches(dataset.settlement_rows)}
        assert not [
            row
            for row in rows
            if row.payment_id in captured
            and row.settlement_id is not None
            and batches[row.settlement_id].settled_on == captured[row.payment_id]
        ]


class TestTheFeatureOnMovesDatesOnly:
    def test_some_payouts_now_settle_the_day_they_were_captured(self) -> None:
        dataset = _dataset(0.35)
        captured = {p.payment_id: p.captured_at.date() for p in dataset.payments}
        batches = {b.settlement_id: b for b in rebuild_batches(dataset.settlement_rows)}
        same_day = [
            row
            for row in dataset.settlement_rows
            if row.type is EntityType.PAYMENT
            and row.payment_id in captured
            and row.settlement_id is not None
            and batches[row.settlement_id].settled_on == captured[row.payment_id]
        ]
        assert same_day

    def test_international_cards_never_settle_instantly(self) -> None:
        """They clear on their own timetable and the product does not apply."""
        dataset = _dataset(0.9)
        international = {
            p.payment_id for p in dataset.payments if p.card_type is CardType.INTERNATIONAL
        }
        captured = {p.payment_id: p.captured_at.date() for p in dataset.payments}
        batches = {b.settlement_id: b for b in rebuild_batches(dataset.settlement_rows)}
        assert not [
            row
            for row in dataset.settlement_rows
            if row.payment_id in international
            and row.settlement_id is not None
            and batches[row.settlement_id].settled_on == captured[row.payment_id]
        ]

    def test_it_adds_volume_without_adding_ambiguity(self) -> None:
        """The measurement that corrected the prediction.

        The reasoning written before this ran was that same-day payouts would
        crowd the date buckets and give amount-plus-date more ways to be
        wrong. They do not: an instant batch holds only that day's instant
        payments, so its total looks nothing like a scheduled run's.
        """
        scheduled = rebuild_batches(_dataset(0.0).settlement_rows)
        instant = rebuild_batches(_dataset(0.35).settlement_rows)
        assert len(instant) > len(scheduled)

        collisions = Counter((b.settled_on, b.expected_net) for b in instant)
        assert not [pair for pair, count in collisions.items() if count > 1]


class TestTheEngineHoldsUnderIt:
    @pytest.mark.parametrize("share", [0.0, 0.35, 0.6])
    def test_match_rate_and_precision_do_not_move(self, share: float) -> None:
        card = evaluate(_dataset(share), headline_only=True).headline
        assert card.match_rate == 1.0
        assert card.precision == 1.0
