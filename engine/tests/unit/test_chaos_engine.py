"""The generator has to be right before any number it produces means anything.

If the generator is wrong, every downstream metric is wrong in a way that
looks fine: the matcher would be scored against a corrupt answer key and
could report a high match rate while being useless. So the generator gets
tested harder than the code it feeds.
"""

from __future__ import annotations

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.calendar import is_working_day
from milan.domain.dataset import Dataset
from milan.domain.enums import EntityType
from milan.domain.money import Paise, apply_rate
from milan.domain.rates import GST_RATE


def build(difficulty: Difficulty = Difficulty.REALISTIC, **overrides: object) -> Dataset:
    settings: dict[str, object] = {"order_count": 120, "difficulty": difficulty}
    settings.update(overrides)
    return ChaosEngine(GenerationConfig(**settings)).generate()  # type: ignore[arg-type]


ALL_TIERS = pytest.mark.parametrize("difficulty", list(Difficulty))


class TestReproducibility:
    def test_same_seed_produces_identical_output(self) -> None:
        first = ChaosEngine(GenerationConfig(seed=7)).generate()
        second = ChaosEngine(GenerationConfig(seed=7)).generate()
        assert first.model_dump_json() == second.model_dump_json()

    def test_different_seeds_produce_different_output(self) -> None:
        first = ChaosEngine(GenerationConfig(seed=7)).generate()
        second = ChaosEngine(GenerationConfig(seed=8)).generate()
        assert first.model_dump_json() != second.model_dump_json()

    @ALL_TIERS
    def test_every_tier_is_reproducible(self, difficulty: Difficulty) -> None:
        """Difficulty and repeatability are independent axes.

        ADVERSARIAL is not "random noise" - it is exactly as deterministic as
        CLEAN. Only the problem is harder.
        """
        config = GenerationConfig(seed=3, difficulty=difficulty, order_count=60)
        assert (
            ChaosEngine(config).generate().model_dump_json()
            == ChaosEngine(config).generate().model_dump_json()
        )


class TestStructuralIntegrity:
    @ALL_TIERS
    def test_every_credit_has_exactly_one_truth(self, difficulty: Difficulty) -> None:
        data = build(difficulty)
        credit_ids = [credit.credit_id for credit in data.bank_credits]
        truth_ids = [truth.credit_id for truth in data.answer_key.credits]
        assert sorted(credit_ids) == sorted(truth_ids)
        assert len(set(credit_ids)) == len(credit_ids)

    @ALL_TIERS
    def test_identifiers_are_unique(self, difficulty: Difficulty) -> None:
        data = build(difficulty)
        identifiers = (
            [order.order_id for order in data.orders]
            + [payment.payment_id for payment in data.payments]
            + [refund.refund_id for refund in data.refunds]
            + [adjustment.adjustment_id for adjustment in data.adjustments]
            + [settlement.settlement_id for settlement in data.settlements]
            + [credit.credit_id for credit in data.bank_credits]
        )
        assert len(set(identifiers)) == len(identifiers)

    @ALL_TIERS
    def test_every_payment_points_at_a_real_order(self, difficulty: Difficulty) -> None:
        data = build(difficulty)
        order_ids = {order.order_id for order in data.orders}
        assert all(payment.order_id in order_ids for payment in data.payments)

    @ALL_TIERS
    def test_settlement_entity_ids_match_the_rows(self, difficulty: Difficulty) -> None:
        data = build(difficulty)
        rows_by_settlement: dict[str, set[str]] = {}
        for row in data.settlement_rows:
            if row.settlement_id is not None:
                rows_by_settlement.setdefault(row.settlement_id, set()).add(row.entity_id)
        for settlement in data.settlements:
            assert set(settlement.entity_ids) == rows_by_settlement.get(
                settlement.settlement_id, set()
            )

    @ALL_TIERS
    def test_settlements_never_land_on_a_weekend(self, difficulty: Difficulty) -> None:
        data = build(difficulty)
        assert all(is_working_day(s.settled_at.date()) for s in data.settlements)

    @ALL_TIERS
    def test_no_settlement_is_a_negative_payout(self, difficulty: Difficulty) -> None:
        """A gateway does not bill the merchant by sending a negative credit."""
        data = build(difficulty)
        assert all(settlement.amount >= 0 for settlement in data.settlements)


class TestTheMoneyAddsUp:
    """The generator's arithmetic, checked independently of the matcher."""

    @ALL_TIERS
    def test_each_settlement_equals_its_rows_plus_drift(self, difficulty: Difficulty) -> None:
        data = build(difficulty)
        rows_by_settlement: dict[str, list[Paise]] = {}
        row_tax: dict[str, Paise] = {}
        for row in data.settlement_rows:
            if row.settlement_id is None:
                continue
            rows_by_settlement.setdefault(row.settlement_id, []).append(row.signed_net)
            row_tax[row.settlement_id] = Paise(row_tax.get(row.settlement_id, 0) + row.tax)

        for settlement in data.settlements:
            rows_total = sum(rows_by_settlement.get(settlement.settlement_id, []))
            drift = row_tax.get(settlement.settlement_id, Paise(0)) - settlement.tax
            assert settlement.amount == rows_total + drift

    @ALL_TIERS
    def test_batch_gst_is_charged_on_the_batch_fee(self, difficulty: Difficulty) -> None:
        data = build(difficulty)
        for settlement in data.settlements:
            assert settlement.tax == apply_rate(settlement.fee, GST_RATE) or (
                settlement.tax == _row_tax_total(data, settlement.settlement_id)
            )

    @ALL_TIERS
    def test_matchable_credits_agree_with_their_settlement(self, difficulty: Difficulty) -> None:
        """The answer key's arithmetic must reconstruct the credited amount.

        gross - fee - tax - tds - adjustments + drift == what arrived.
        """
        data = build(difficulty)
        credits = {credit.credit_id: credit for credit in data.bank_credits}
        for truth in data.answer_key.credits:
            if not truth.settlement_ids:
                continue
            expected = (
                truth.gross
                - truth.fee
                - truth.tax
                - truth.tds
                - truth.adjustments
                + truth.rounding_drift
            )
            assert credits[truth.credit_id].amount == expected

    @ALL_TIERS
    def test_refund_rows_carry_no_fee(self, difficulty: Difficulty) -> None:
        """Razorpay does not charge for processing a refund."""
        data = build(difficulty)
        for row in data.settlement_rows:
            if row.type in (EntityType.REFUND, EntityType.ADJUSTMENT):
                assert row.fee == 0
                assert row.tax == 0


class TestDefectsAreActuallyInjected:
    """A difficulty knob that quietly does nothing is worse than no knob."""

    def test_clean_has_no_impossible_records(self) -> None:
        data = build(Difficulty.CLEAN)
        assert data.answer_key.impossible_count == 0
        assert data.answer_key.missing_settlement_ids == ()
        assert all(credit.utr is not None for credit in data.bank_credits)

    def test_realistic_loses_some_utrs(self) -> None:
        data = build(Difficulty.REALISTIC, order_count=400)
        assert any(credit.utr is None for credit in data.bank_credits)

    def test_realistic_produces_rounding_drift(self) -> None:
        data = build(Difficulty.REALISTIC, order_count=400)
        assert any(truth.rounding_drift != 0 for truth in data.answer_key.credits)

    def test_messy_overcharges_somebody(self) -> None:
        """The leak case: it balances perfectly and is still wrong."""
        data = build(Difficulty.MESSY, order_count=400)
        assert data.answer_key.leaks
        assert all(leak.overcharge > 0 for leak in data.answer_key.leaks)

    def test_adversarial_contains_indistinguishable_credits(self) -> None:
        data = build(Difficulty.ADVERSARIAL, order_count=400)
        duplicates = [
            truth for truth in data.answer_key.credits if truth.defect == "AMBIGUOUS_DUPLICATE"
        ]
        assert len(duplicates) >= 4  # two pairs
        assert all(not truth.matchable for truth in duplicates)

        by_id = {credit.credit_id: credit for credit in data.bank_credits}
        signatures = [
            (by_id[t.credit_id].amount, by_id[t.credit_id].value_date) for t in duplicates
        ]
        # Each ambiguous credit shares its amount and date with at least one other.
        assert all(signatures.count(signature) >= 2 for signature in signatures)

    def test_unmatchable_records_are_genuinely_unmatchable(self) -> None:
        """Nothing marked impossible may still carry a usable UTR."""
        data = build(Difficulty.ADVERSARIAL, order_count=400)
        by_id = {credit.credit_id: credit for credit in data.bank_credits}
        for truth in data.answer_key.credits:
            if not truth.matchable:
                assert by_id[truth.credit_id].utr is None


class TestAnswerKeyIsolation:
    def test_the_recon_package_cannot_see_the_answers(self) -> None:
        """Enforced as a test, not as a convention people remember.

        If `milan.recon` could import the answer key, a future refactor could
        make the match rate meaningless without anything looking wrong.
        """
        import pkgutil
        from pathlib import Path

        import milan.recon

        offenders = []
        for path in Path(next(iter(milan.recon.__path__))).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if "domain.truth" in source or "answer_key" in source:
                offenders.append(str(path))
        assert not offenders, f"recon must not read ground truth: {offenders}"
        assert pkgutil is not None


def _row_tax_total(data: Dataset, settlement_id: str) -> Paise:
    return Paise(sum(row.tax for row in data.settlement_rows if row.settlement_id == settlement_id))
