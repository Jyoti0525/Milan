"""Auditing the generator against what it claims to be.

Every accuracy figure this project reports is measured on data this project
writes, so the data is the ruler. A bent ruler does not announce itself: it
produces confident numbers that mean nothing, and every other test still
passes.

These are the checks a first audit did not have. That audit found one
artifact - statements printing a negative deposit - and the fair reading of
finding something is not "one bug fixed", it is "the list was too short". So
the list was extended, starting with the sentence the whole engine rests on
and never actually tested here: the settlement identity itself.

Two of the extended checks fired, and both turned out to be the check being
wrong rather than the data. They are kept, narrowed to the case that would
genuinely be an artifact - see `TestThePayoutCalendarIsKeptWhereItApplies`.
A check that was wrong once is worth keeping honest rather than deleting.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.calendar import is_working_day
from milan.domain.dataset import Dataset
from milan.domain.enums import EntityType, PaymentMethod
from milan.domain.money import apply_rate
from milan.domain.rates import RateCard

SEEDS = (1, 2, 3, 42)

SHAPES: tuple[tuple[str, dict[str, object]], ...] = (
    ("plain", {}),
    ("194-O", {"rates": RateCard(tds_applies=True)}),
    ("route", {"route_probability": 0.30}),
    ("instant", {"instant_settlement_probability": 0.35}),
    (
        "everything",
        {
            "rates": RateCard(tds_applies=True),
            "route_probability": 0.30,
            "instant_settlement_probability": 0.35,
        },
    ),
)
"""The five merchant shapes, because a check that only runs on the default
one is a check that has never seen a withholding or a Route transfer."""


def build(shape: dict[str, object], seed: int, tier: Difficulty, orders: int = 250) -> Dataset:
    return ChaosEngine(
        GenerationConfig(seed=seed, difficulty=tier, order_count=orders, **shape)  # type: ignore[arg-type]
    ).generate()


def months() -> list[tuple[str, Dataset, RateCard]]:
    """One month per tier per shape. Built once, read by several tests."""
    built = []
    for tier in Difficulty:
        for name, shape in SHAPES:
            data = build(shape, seed=42, tier=tier)
            rates = shape.get("rates", RateCard())
            assert isinstance(rates, RateCard)
            built.append((f"{tier.value}/{name}", data, rates))
    return built


@pytest.fixture(scope="module")
def corpus() -> list[tuple[str, Dataset, RateCard]]:
    return months()


# ------------------------------------------------------------ the identity


class TestEveryRowKeepsTheSettlementIdentity:
    """`credit - debit == amount - fee - tax`, and 194-O off the payments.

    The first audit checked GST against the fee and the row against its
    payment, and never checked this. It is the sentence every proof in this
    system is a restatement of, so a generator that broke it would have made
    every accuracy figure meaningless while every other check stayed green.
    """

    def test_a_payment_row_credits_its_gross_less_what_came_off(
        self, corpus: list[tuple[str, Dataset, RateCard]]
    ) -> None:
        for label, data, rates in corpus:
            for row in data.settlement_rows:
                if row.type is not EntityType.PAYMENT:
                    continue
                withheld = apply_rate(row.amount, rates.tds) if rates.tds_applies else 0
                expected = row.amount - row.fee - row.tax - withheld

                assert row.signed_net == expected, f"{label}: {row.entity_id}"

    def test_a_reversal_row_debits_its_gross_plus_what_came_off(
        self, corpus: list[tuple[str, Dataset, RateCard]]
    ) -> None:
        """Refunds, chargebacks and Route transfers all take money out.

        The sign flips and the fee moves to the same side as the amount: a
        refund costs the merchant the sale *and* whatever it cost to send it
        back. No withholding term - 194-O is deducted when money is paid to
        the merchant, and none is here.
        """
        for label, data, _ in corpus:
            for row in data.settlement_rows:
                if row.type is EntityType.PAYMENT:
                    continue

                assert row.signed_net == -(row.amount + row.fee + row.tax), (
                    f"{label}: {row.entity_id}"
                )

    def test_a_row_is_a_credit_or_a_debit_and_never_both(
        self, corpus: list[tuple[str, Dataset, RateCard]]
    ) -> None:
        for label, data, _ in corpus:
            for row in data.settlement_rows:
                assert not (row.credit and row.debit), f"{label}: {row.entity_id}"

    def test_a_provable_credit_is_exactly_what_its_batches_netted(
        self, corpus: list[tuple[str, Dataset, RateCard]]
    ) -> None:
        """The bank side against the report side, through the answer key.

        Allowed the same rounding drift the rest of the system allows and no
        more. A credit that is not its batches' net, on a month the key
        calls provable, is the key and the data disagreeing about where the
        money went.
        """
        for label, data, _ in corpus:
            nets: dict[str, int] = defaultdict(int)
            for row in data.settlement_rows:
                if row.settlement_id:
                    nets[row.settlement_id] += row.signed_net
            credits = {credit.credit_id: credit for credit in data.bank_credits}

            for truth in data.answer_key.credits:
                if not truth.settlement_ids or not truth.provable:
                    continue
                owed = sum(nets[settlement_id] for settlement_id in truth.settlement_ids)

                assert abs(credits[truth.credit_id].amount - owed) <= 500, (
                    f"{label}: {truth.credit_id}"
                )


# ----------------------------------------------------------- the answer key


class TestTheAnswerKeyDescribesTheDataItCameWith:
    """The key is the ruler's markings. Nothing else checks them."""

    def test_every_bank_credit_is_accounted_for(
        self, corpus: list[tuple[str, Dataset, RateCard]]
    ) -> None:
        for label, data, _ in corpus:
            told = {truth.credit_id for truth in data.answer_key.credits}

            for credit in data.bank_credits:
                assert credit.credit_id in told, f"{label}: {credit.credit_id}"

    def test_the_key_never_names_a_settlement_that_has_no_rows(
        self, corpus: list[tuple[str, Dataset, RateCard]]
    ) -> None:
        for label, data, _ in corpus:
            real = {row.settlement_id for row in data.settlement_rows if row.settlement_id}

            for truth in data.answer_key.credits:
                for settlement_id in truth.settlement_ids:
                    assert settlement_id in real, f"{label}: {truth.credit_id}"

    def test_a_payment_called_unreported_is_absent_from_the_report(
        self, corpus: list[tuple[str, Dataset, RateCard]]
    ) -> None:
        """Otherwise the one defect no bank-side matching can find is
        findable, and the hardest number in the harness is measuring a
        defect that was never injected."""
        for label, data, _ in corpus:
            settled = {row.payment_id for row in data.settlement_rows if row.payment_id}

            for payment_id in data.answer_key.unreported_payment_ids:
                assert payment_id not in settled, f"{label}: {payment_id}"

    def test_a_credit_called_unmatchable_carries_no_working_reference(
        self, corpus: list[tuple[str, Dataset, RateCard]]
    ) -> None:
        """The refusal rate is measured against this flag.

        If a credit the key calls impossible still has a reference that
        resolves to exactly one settlement, then refusing it is the wrong
        answer and our headline refusal figure is rewarding a mistake.
        """
        for label, data, _ in corpus:
            by_utr: dict[str, set[str]] = defaultdict(set)
            for row in data.settlement_rows:
                if row.settlement_utr and row.settlement_id:
                    by_utr[row.settlement_utr].add(row.settlement_id)
            credits = {credit.credit_id: credit for credit in data.bank_credits}

            for truth in data.answer_key.credits:
                credit = credits.get(truth.credit_id)
                if truth.matchable or credit is None or not credit.utr:
                    continue

                assert len(by_utr.get(credit.utr, ())) != 1, f"{label}: {truth.credit_id}"


# -------------------------------------------------------------- the leakage


DEFECT_WORDS = re.compile(
    r"orphan|ambig|merged|damag|corrupt|variance|defect|inject|chaos|seed",
    re.IGNORECASE,
)
"""The generator's own vocabulary. None of it may reach a merchant-visible
field."""


class TestNothingInTheFilesGivesAwayTheAnswer:
    """The check that decides whether any of the numbers mean anything.

    If an injected defect is spelled out anywhere the engine can read, then
    the engine can score well by reading the label instead of doing the
    arithmetic, and every figure is an artifact of the generator rather than
    a measurement of the matcher.
    """

    def test_no_merchant_visible_field_names_a_defect(
        self, corpus: list[tuple[str, Dataset, RateCard]]
    ) -> None:
        for label, data, _ in corpus:
            for credit in data.bank_credits:
                assert not DEFECT_WORDS.search(credit.narration), f"{label}: {credit.narration}"
                assert not DEFECT_WORDS.search(credit.credit_id), f"{label}: {credit.credit_id}"

            for row in data.settlement_rows:
                text = " ".join(
                    str(part)
                    for part in (
                        row.entity_id,
                        row.settlement_id,
                        row.settlement_utr,
                        row.order_receipt,
                    )
                    if part
                )
                assert not DEFECT_WORDS.search(text), f"{label}: {text}"

    def test_the_unmatchable_credits_are_not_all_at_the_end_of_the_file(
        self, corpus: list[tuple[str, Dataset, RateCard]]
    ) -> None:
        """Leakage by position rather than by content.

        A generator that appends its injected records hands over the answer
        in the row order, and a matcher could score well on file position
        alone without anyone noticing.
        """
        for label, data, _ in corpus:
            impossible = [
                index
                for index, credit in enumerate(data.bank_credits)
                if not {t.credit_id: t for t in data.answer_key.credits}[credit.credit_id].matchable
            ]
            if len(impossible) < 2 or len(data.bank_credits) < len(impossible) + 3:
                continue
            tail = set(range(len(data.bank_credits) - len(impossible), len(data.bank_credits)))

            assert set(impossible) != tail, f"{label}: every unmatchable credit is last"


# ------------------------------------------------------------- the calendar


class TestThePayoutCalendarIsKeptWhereItApplies:
    """The check that fired, narrowed to the case that would be an artifact.

    A first pass flagged 183 bank credits and 32 payouts dated on a Saturday
    or a Sunday. Every one of them belonged to an instant settlement, which
    is not an artifact - it is the product. Razorpay's instant settlement
    runs on rails that do not close, and a merchant paying for it on a
    Sunday is exactly what they are buying.

    So the check as written was wrong, not the data. What would be an
    artifact is a *scheduled* T+2 payout on a day the settlement calendar
    excludes, because that is the one this project's own calendar claims to
    prevent. That is what is asserted here.
    """

    def instant_batches(self, data: Dataset) -> set[str]:
        """Batches that paid out on the day they were captured."""
        return {
            row.settlement_id
            for row in data.settlement_rows
            if row.settlement_id
            and row.settled_at is not None
            and row.settled_at.date() == row.created_at.date()
        }

    @pytest.mark.parametrize("tier", list(Difficulty))
    def test_no_scheduled_payout_lands_on_a_non_working_day(self, tier: Difficulty) -> None:
        data = build({"instant_settlement_probability": 0.35}, seed=42, tier=tier)
        instant = self.instant_batches(data)

        for row in data.settlement_rows:
            if row.settled_at is None or row.settlement_id in instant:
                continue

            assert is_working_day(row.settled_at.date()), f"{row.entity_id} {row.settled_at}"

    @pytest.mark.parametrize("tier", list(Difficulty))
    def test_an_instant_payout_is_allowed_to(self, tier: Difficulty) -> None:
        """The other half, or the rule above would be satisfied by a
        generator that had quietly stopped producing instant settlements."""
        data = build({"instant_settlement_probability": 0.35}, seed=42, tier=tier)

        assert self.instant_batches(data), f"{tier.value}: no instant settlements at all"


# -------------------------------------------------------------- the realism


class TestAMonthLooksLikeAMerchantsMonth:
    """Not correctness - plausibility. Data that is arithmetically perfect
    and obviously synthetic is still a bad ruler, because a matcher tuned on
    it is tuned on a shape nobody has."""

    def test_payments_are_not_mostly_round_hundreds(
        self, corpus: list[tuple[str, Dataset, RateCard]]
    ) -> None:
        for label, data, _ in corpus:
            amounts = [payment.amount for payment in data.payments]
            round_hundreds = sum(1 for amount in amounts if amount % 10_000 == 0)

            assert round_hundreds <= len(amounts) * 0.5, f"{label}: {round_hundreds}/{len(amounts)}"

    def test_leading_digits_are_not_uniform(
        self, corpus: list[tuple[str, Dataset, RateCard]]
    ) -> None:
        """Benford's law, used as a smell rather than a law.

        Real transaction amounts start with a 1 far more often than a 9. A
        uniform distribution would mean amounts drawn flat out of a range,
        which is the signature of data nobody spent money to produce.
        """
        for label, data, _ in corpus:
            leading = Counter(str(payment.amount)[0] for payment in data.payments if payment.amount)
            share = leading["1"] / len(data.payments)

            assert 0.10 <= share <= 0.55, f"{label}: {share:.0%} start with 1"

    def test_upi_is_not_a_minority(self, corpus: list[tuple[str, Dataset, RateCard]]) -> None:
        """India, 2026. A generated month where cards outnumber UPI is a
        month from somewhere else."""
        for label, data, _ in corpus:
            upi = sum(1 for payment in data.payments if payment.method is PaymentMethod.UPI)

            assert upi >= len(data.payments) * 0.15, f"{label}: {upi}/{len(data.payments)}"

    def test_captures_are_spread_across_the_day(
        self, corpus: list[tuple[str, Dataset, RateCard]]
    ) -> None:
        """The settlement cycle is chosen by capture hour, so payments all
        landing at midnight would collapse every batch into one cycle and
        quietly make the matching easier than it looks."""
        for label, data, _ in corpus:
            hours = Counter(payment.captured_at.hour for payment in data.payments)

            assert len(hours) >= 6, f"{label}: {sorted(hours)}"
            assert hours[0] <= len(data.payments) * 0.3, f"{label}: {hours[0]} at midnight"

    def test_no_two_credits_carry_the_same_reference(
        self, corpus: list[tuple[str, Dataset, RateCard]]
    ) -> None:
        """A duplicated UTR would make the first rung ambiguous for reasons
        the answer key knows nothing about."""
        for label, data, _ in corpus:
            utrs = [credit.utr for credit in data.bank_credits if credit.utr]

            assert len(utrs) == len(set(utrs)), (
                f"{label}: {[u for u, n in Counter(utrs).items() if n > 1]}"
            )


# ---------------------------------------------------------- reproducibility


class TestTheSameSeedIsTheSameMonth:
    """`milan reproduce` checks this for one configuration. These are the
    configurations that were added afterwards."""

    @pytest.mark.parametrize("name,shape", SHAPES)
    def test_two_runs_are_byte_identical(self, name: str, shape: dict[str, object]) -> None:
        digests = {
            hashlib.sha256(
                build(shape, seed=7, tier=Difficulty.REALISTIC, orders=150)
                .model_dump_json()
                .encode()
            ).hexdigest()
            for _ in range(2)
        }

        assert len(digests) == 1, name


# ------------------------------------------------------------- cross-file


class TestTheFilesAgreeWithEachOther:
    def test_no_row_names_an_order_nobody_placed(
        self, corpus: list[tuple[str, Dataset, RateCard]]
    ) -> None:
        for label, data, _ in corpus:
            orders = {order.order_id for order in data.orders}

            for row in data.settlement_rows:
                if row.order_id:
                    assert row.order_id in orders, f"{label}: {row.entity_id}"
            for payment in data.payments:
                assert payment.order_id in orders, f"{label}: {payment.payment_id}"

    def test_a_settled_row_names_the_batch_and_the_day_it_settled(
        self, corpus: list[tuple[str, Dataset, RateCard]]
    ) -> None:
        for label, data, _ in corpus:
            for row in data.settlement_rows:
                if not row.settled:
                    assert row.settlement_id is None, f"{label}: {row.entity_id}"
                    continue

                assert row.settlement_id is not None, f"{label}: {row.entity_id}"
                assert row.settled_at is not None, f"{label}: {row.entity_id}"

    def test_no_payout_predates_the_capture_it_pays(
        self, corpus: list[tuple[str, Dataset, RateCard]]
    ) -> None:
        for label, data, _ in corpus:
            for row in data.settlement_rows:
                if row.settled_at is None:
                    continue

                assert row.settled_at.date() >= row.created_at.date(), f"{label}: {row.entity_id}"


def test_the_corpus_is_actually_twenty_months() -> None:
    """The tests above iterate a fixture. If it ever came back short they
    would all pass over nothing."""
    assert len(months()) == len(list(Difficulty)) * len(SHAPES) == 20
