"""The generator has to be right before any number it produces means anything.

If the generator is wrong, every downstream metric is wrong in a way that
looks fine: the matcher would be scored against a corrupt answer key and
could report a high match rate while being useless. So the generator gets
tested harder than the code it feeds.
"""

from __future__ import annotations

import time
from decimal import Decimal

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.calendar import is_working_day
from milan.domain.dataset import Dataset
from milan.domain.enums import EntityType
from milan.domain.money import Paise, apply_rate, from_rupees
from milan.domain.rates import GST_RATE, RateCard


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
            if row.type is EntityType.PAYMENT:
                # Drift is the disagreement between per-row and batch-level
                # GST on the platform fee. A refund row's tax is GST on a
                # flat instant-refund charge, rounded once on that row, and
                # never takes part in it.
                row_tax[row.settlement_id] = Paise(row_tax.get(row.settlement_id, 0) + row.tax)

        varied = _unprovable_settlements(data)
        for settlement in data.settlements:
            rows_total = sum(rows_by_settlement.get(settlement.settlement_id, []))
            drift = row_tax.get(settlement.settlement_id, Paise(0)) - settlement.tax
            if settlement.settlement_id in varied:
                # A payout variance is exactly this identity being broken on
                # purpose. It is checked at the credit level below, because a
                # merged credit marks every member unprovable while only one
                # of them actually carries the variance.
                continue
            assert settlement.amount == rows_total + drift

    @ALL_TIERS
    def test_an_unprovable_credit_really_does_not_reconstruct(self, difficulty: Difficulty) -> None:
        """The other half of the identity above.

        If a credit marked unprovable still added up, the defect would be a
        label rather than an injection, and the categoriser would be scored
        on explaining shortfalls that are not there.
        """
        data = build(difficulty)
        credits = {credit.credit_id: credit for credit in data.bank_credits}

        # What the report can reconstruct: the rows, and nothing else. The
        # gateway's own settlement summary already carries the variance, so
        # comparing against that would compare the defect with itself.
        rows_total: dict[str, int] = {}
        taxed_rows: dict[str, int] = {}
        for row in data.settlement_rows:
            if row.settlement_id is None:
                continue
            rows_total[row.settlement_id] = rows_total.get(row.settlement_id, 0) + row.signed_net
            taxed_rows[row.settlement_id] = taxed_rows.get(row.settlement_id, 0) + bool(row.tax)

        for truth in data.answer_key.credits:
            if truth.provable or not truth.settlement_ids:
                continue
            reconstructable = sum(rows_total.get(sid, 0) for sid in truth.settlement_ids)
            allowance = sum((taxed_rows.get(sid, 0) + 1) // 2 + 1 for sid in truth.settlement_ids)
            gap = abs(credits[truth.credit_id].amount - reconstructable)
            assert gap > allowance, (
                f"{truth.credit_id} is marked unprovable but its rows reconstruct it "
                f"to within {gap} paise - the defect is a label, not an injection"
            )

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
            if not truth.settlement_ids or not truth.provable:
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
    def test_an_ordinary_refund_costs_the_merchant_nothing(self, difficulty: Difficulty) -> None:
        """Razorpay does not charge for processing a refund - unless it is
        instant, which is a flat fee by size. Chargebacks are never charged.

        The rule got narrower rather than weaker when instant refunds went
        in. Asserting "no refund row has a fee" would now be false, and
        deleting the assertion would have left the only published Rs 0 in the
        whole fee stack unchecked.
        """
        data = build(difficulty)
        rates = RateCard()
        for row in data.settlement_rows:
            if row.type is EntityType.ADJUSTMENT:
                assert row.fee == 0, row.entity_id
                assert row.tax == 0, row.entity_id
            elif row.type is EntityType.REFUND and row.fee:
                assert row.fee == rates.instant_refund_fee(row.amount), row.entity_id
                assert row.tax == apply_rate(row.fee, rates.gst), row.entity_id

    @ALL_TIERS
    def test_a_refund_debit_is_the_whole_cash_impact(self, difficulty: Difficulty) -> None:
        """The debit column has to be what actually left the payout.

        If it were the refund alone, a batch would appear to net more than it
        paid, and the instant charge would vanish into the drift line where
        nobody would ever ask about it.
        """
        data = build(difficulty)
        for row in data.settlement_rows:
            if row.type in (EntityType.REFUND, EntityType.ADJUSTMENT):
                assert row.debit == row.amount + row.fee + row.tax, row.entity_id


class TestThePriceWindowCannotHangTheGenerator:
    """The amount draw used to be rejection sampling in an unbounded loop.

    It cost one over the acceptance probability, which is invisible on the
    default price window and ruinous on a narrow one: a single-price merchant
    - the benchmark shape built specifically to make batch totals collide -
    took twenty-two seconds and eleven million discarded samples to produce
    forty orders, and a window the distribution cannot reach at all would
    never have finished. None of that raises, logs, or slows down anything a
    default test would notice.
    """

    def test_a_single_price_merchant_generates_promptly(self) -> None:
        """The regression guard. Two seconds is enormously generous - this
        takes milliseconds - and it is set that way so the test fails on a
        return to unbounded sampling rather than on a slow machine."""
        started = time.perf_counter()
        data = build(
            Difficulty.MESSY,
            order_count=400,
            min_amount_rupees=Decimal("499"),
            max_amount_rupees=Decimal("499"),
        )
        assert time.perf_counter() - started < 2.0
        assert len(data.orders) == 400

    def test_a_single_price_merchant_really_has_one_price(self) -> None:
        """Speed is not the point on its own. A draw that was fast because it
        stopped respecting the window would be worse than a slow one."""
        data = build(
            Difficulty.CLEAN,
            order_count=60,
            min_amount_rupees=Decimal("499"),
            max_amount_rupees=Decimal("499"),
        )
        assert {order.amount for order in data.orders} == {from_rupees(Decimal("499"))}

    def test_a_narrow_window_is_respected(self) -> None:
        low, high = Decimal("2000"), Decimal("2100")
        data = build(
            Difficulty.CLEAN, order_count=120, min_amount_rupees=low, max_amount_rupees=high
        )
        assert all(from_rupees(low) <= order.amount <= from_rupees(high) for order in data.orders)

    def test_a_window_with_its_ends_reversed_is_refused(self) -> None:
        """Not a slow config - an impossible one, and it should fail where it
        is written rather than hang where it is used."""
        with pytest.raises(ValueError, match="min_amount_rupees"):
            GenerationConfig(min_amount_rupees=Decimal("5000"), max_amount_rupees=Decimal("100"))


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


def _unprovable_settlements(data: Dataset) -> set[str]:
    """Settlements behind a credit the report cannot reconstruct."""
    return {
        settlement_id
        for truth in data.answer_key.credits
        if not truth.provable
        for settlement_id in truth.settlement_ids
    }


def _row_tax_total(data: Dataset, settlement_id: str) -> Paise:
    """GST on the payment rows only.

    A refund row now carries tax of its own when the merchant paid for an
    instant refund, and that GST is on a processing charge rather than on the
    platform fee - it is never part of the batch's tax figure. Summing every
    row here compared two different quantities and passed only for as long as
    no batch happened to contain an instant refund.
    """
    return Paise(
        sum(
            row.tax
            for row in data.settlement_rows
            if row.settlement_id == settlement_id and row.type is EntityType.PAYMENT
        )
    )
