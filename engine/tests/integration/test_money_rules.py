"""The generated month, checked against `docs/02-THE-MONEY-RULES.md`.

Every figure this project reports is measured on data it generated itself. So
the data has to be right, and "right" is not a matter of taste: the fee stack,
the settlement calendar and the refund timing are published facts about how
Razorpay actually charges an Indian merchant, and the document lists them with
citations.

What this checks is the *output*, not the constants. `rates.py` states a 2%
platform fee and 18% GST on it; that is only worth anything if the rows the
generator wrote actually carry those numbers. A rule declared in one module
and not applied in another would pass every unit test in the codebase and
produce a month that quietly is not India.

The tiers are not treated alike, on purpose. `clean` is the control case and
everything must be exact there. The harder tiers inject short payouts and
mischarged rates deliberately - those are the exceptions the engine exists to
find - so what is asserted there is that the defects exist and stay a
minority, never that the month is perfect.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.calendar import add_working_days
from milan.domain.dataset import Dataset
from milan.domain.enums import CardType, EntityType
from milan.domain.money import apply_rate
from milan.domain.rates import RateCard

ORDERS = 200
GST = Decimal("0.18")
TDS = Decimal("0.01")


def month(difficulty: Difficulty, **extra: object) -> Dataset:
    return ChaosEngine(
        GenerationConfig(seed=42, difficulty=difficulty, order_count=ORDERS, **extra)  # type: ignore[arg-type]
    ).generate()


@pytest.fixture(scope="module")
def clean() -> Dataset:
    return month(Difficulty.CLEAN)


@pytest.fixture(scope="module")
def realistic() -> Dataset:
    return month(Difficulty.REALISTIC)


def payments_by_id(data: Dataset) -> dict[str, object]:
    return {payment.payment_id: payment for payment in data.payments}


# ----------------------------------------------------------- the track's bar


@pytest.mark.parametrize("difficulty", list(Difficulty))
def test_a_month_is_well_past_the_fifty_record_bar(difficulty: Difficulty) -> None:
    """Razorpay's Track 04 brief asks for a 50+ record batch.

    Asserted at the default order count rather than the one the demo uses,
    because the claim has to hold for the smallest month somebody might
    generate, not the largest.
    """
    small = ChaosEngine(
        GenerationConfig(seed=42, difficulty=difficulty, order_count=100)
    ).generate()
    assert small.record_count >= 50, f"{difficulty.value}: {small.record_count} records"


# ------------------------------------------------------------- the fee stack


def test_every_platform_fee_is_the_contracted_rate(clean: Dataset) -> None:
    """2% standard, 2.15% corporate card, 3% international.

    On the control tier only. A rate that does not match the contract is the
    `FEE_DEDUCTION` exception, and the harder tiers inject it on purpose.
    """
    rates = RateCard()
    payments = payments_by_id(clean)
    wrong = []
    for row in clean.settlement_rows:
        if row.type is not EntityType.PAYMENT:
            continue
        payment = payments.get(row.payment_id or "")
        if payment is None:
            continue
        expected = apply_rate(
            row.amount,
            rates.platform_rate(payment.method, payment.card_type),  # type: ignore[attr-defined]
        )
        if row.fee != expected:
            wrong.append(f"{row.entity_id}: {row.fee} is not {expected}")
    assert wrong == [], "\n".join(wrong[:5])


@pytest.mark.parametrize("difficulty", list(Difficulty))
def test_gst_is_charged_on_the_fee_and_never_on_the_transaction(
    difficulty: Difficulty,
) -> None:
    """18% of the platform fee, on every tier including the hostile ones.

    This one holds everywhere. A mischarged *rate* is a defect somebody has to
    find; GST computed against the wrong base would be a defect in our
    arithmetic, and would make the whole corpus describe a country that does
    not charge tax this way.
    """
    data = month(difficulty)
    wrong = [
        f"{row.entity_id}: tax {row.tax} is not 18% of fee {row.fee}"
        for row in data.settlement_rows
        if row.type is EntityType.PAYMENT and row.tax != apply_rate(row.fee, GST)
    ]
    assert wrong == [], "\n".join(wrong[:5])


def test_all_three_card_rates_actually_occur(clean: Dataset) -> None:
    """A rate implemented and never exercised is a rate nothing tested.

    Both of the unusual ones are rare by design - a merchant takes far more
    consumer cards than corporate or international ones - so this asserts they
    appear at all, not how often.
    """
    seen = Counter(payment.card_type for payment in clean.payments if payment.card_type is not None)
    assert set(seen) == set(CardType), f"only {sorted(kind.value for kind in seen)} occur"


def test_section_194o_withholds_one_percent_of_gross_when_it_applies() -> None:
    """The rule that is off by default because it is a fact about a merchant.

    An e-commerce operator has 1% of gross withheld; a merchant selling their
    own goods does not. Both are ordinary months, so this is a switch rather
    than a difficulty setting - and the reconciliation side is never told
    which, it infers the withholding from the gap.

    Checked against `credit`, not against a field of its own, because that is
    where a merchant would see it: the row is worth `amount - fee - tax` and
    credits one percent less than that.
    """
    withheld = month(Difficulty.REALISTIC, rates=RateCard(tds_applies=True))
    rows = [row for row in withheld.settlement_rows if row.type is EntityType.PAYMENT]
    assert rows

    for row in rows:
        gap = (row.amount - row.fee - row.tax) - row.credit
        assert gap == apply_rate(row.amount, TDS), (
            f"{row.entity_id}: withheld {gap}, not 1% of {row.amount}"
        )

    ordinary = month(Difficulty.REALISTIC)
    assert all(
        row.credit == row.amount - row.fee - row.tax
        for row in ordinary.settlement_rows
        if row.type is EntityType.PAYMENT
    ), "withholding leaked into a month that did not ask for it"


def test_route_charges_a_tenth_of_a_percent_on_what_it_passes_on() -> None:
    """Route is charged *on top of* the platform fee, not instead of it.

    The merchant pays 2% to accept the money and 0.1% again to pass part of it
    along, and both come out of the same payout. Off by default, because a
    merchant with no linked accounts never bought the product.
    """
    routed = month(Difficulty.REALISTIC, route_probability=0.30)
    transfers = [row for row in routed.settlement_rows if row.type is EntityType.TRANSFER]
    assert transfers, "no transfer rows at 30% route probability"

    rates = RateCard()
    for row in transfers:
        assert row.fee == rates.route_fee(row.amount), (
            f"{row.entity_id}: Route fee {row.fee} is not 0.1% of {row.amount}"
        )

    plain = month(Difficulty.REALISTIC)
    assert not [row for row in plain.settlement_rows if row.type is EntityType.TRANSFER]


def test_instant_settlement_pays_a_batch_out_once(clean: Dataset) -> None:
    """Settling sooner changes when money arrives, never how much.

    Whether the feature is *on* is covered thoroughly in
    `test_instant_settlement.py`, including the regression where drawing from
    the random stream at zero probability shifted every later draw. What is
    checked here is the arithmetic underneath it, on the control tier where it
    must be exact: no settlement row belongs to two batches, so no rupee can
    be paid out once inside a T+2 batch and again inside the instant one it
    was pulled from.

    Cross-checking two datasets would not show this. Turning the feature on
    shifts the draw, so the two months differ everywhere and a difference in
    totals says nothing about double-counting.
    """
    instant = month(Difficulty.CLEAN, instant_settlement_probability=0.40)
    assert len(instant.settlements) > len(clean.settlements)

    seen: dict[str, str] = {}
    for row in instant.settlement_rows:
        if row.settlement_id is None:
            continue
        assert row.entity_id not in seen, (
            f"{row.entity_id} is in {seen.get(row.entity_id)} and {row.settlement_id}"
        )
        seen[row.entity_id] = row.settlement_id

    nets: dict[str, int] = {}
    for row in instant.settlement_rows:
        if row.settlement_id:
            nets[row.settlement_id] = nets.get(row.settlement_id, 0) + row.credit - row.debit
    arrived = sum(credit.amount for credit in instant.bank_credits)
    payable = sum(
        nets.get(settlement.settlement_id, 0)
        for settlement in instant.settlements
        if any(credit.utr == settlement.settlement_utr for credit in instant.bank_credits)
    )
    assert arrived == payable, f"bank {arrived} against {payable} owed"


# ------------------------------------------------------ the settlement calendar


@pytest.mark.parametrize("difficulty", list(Difficulty))
def test_nothing_settles_before_it_is_due(difficulty: Difficulty) -> None:
    """T+2 working days domestic, T+7 international, T being the capture.

    Weekends are skipped, which is the part that gets written wrong: a payment
    captured on a Friday settles on Tuesday, not Sunday.
    """
    data = month(difficulty)
    payments = payments_by_id(data)
    early = []
    for row in data.settlement_rows:
        if row.type is not EntityType.PAYMENT or row.settled_at is None:
            continue
        payment = payments.get(row.payment_id or "")
        if payment is None:
            continue
        days = 7 if payment.card_type is CardType.INTERNATIONAL else 2  # type: ignore[attr-defined]
        due = add_working_days(payment.captured_at.date(), days)  # type: ignore[attr-defined]
        if row.settled_at.date() < due:
            early.append(f"{row.entity_id}: settled {row.settled_at.date()}, due {due}")
    assert early == [], "\n".join(early[:5])


def test_a_refund_comes_out_of_a_batch_that_is_not_its_sale(realistic: Dataset) -> None:
    """The first of the four facts that make this genuinely hard.

    Refunds are not paid as a separate debit. They land five to seven working
    days after they were started, netted into whichever batch happens to be
    running then - so a refund hits a batch that has nothing to do with the
    original sale, and reconciling by batch alone cannot explain it.
    """
    refunds = [row for row in realistic.settlement_rows if row.type is EntityType.REFUND]
    assert refunds

    sales = {
        row.entity_id: row.settlement_id
        for row in realistic.settlement_rows
        if row.type is EntityType.PAYMENT
    }
    detached = [
        row
        for row in refunds
        if row.payment_id in sales and sales[row.payment_id] != row.settlement_id
    ]
    assert detached, "every refund settled in the same batch as its sale, which is not how it works"


# ------------------------------------------------------ the identity we rely on


@pytest.mark.parametrize("difficulty", list(Difficulty))
def test_the_settlement_equation_holds_on_every_row_of_every_tier(
    difficulty: Difficulty,
) -> None:
    """`credit - debit == amount - fee - tax`, and its refund form.

    Load-bearing twice over. It is what a settlement report means, and since
    `ingest/identity.py` it is also how an unfamiliar export's money columns
    are recognised at all - so a generator that broke it would not produce a
    month with a defect in it, it would produce a month the importer cannot
    read.
    """
    data = month(difficulty)
    broken = [
        row.entity_id
        for row in data.settlement_rows
        if (row.credit - row.debit)
        not in (row.amount - row.fee - row.tax, -(row.amount + row.fee + row.tax))
    ]
    assert broken == [], f"{len(broken)} rows do not foot: {broken[:5]}"


def test_on_the_control_tier_every_batch_arrived_for_what_its_rows_say(
    clean: Dataset,
) -> None:
    """The control case, and the reason it exists.

    If the engine cannot score perfectly here, the engine is broken and not
    the data. So the data has to be perfect here: every batch that reached the
    bank reached it for exactly the sum of the rows behind it.
    """
    nets: dict[str, int] = {}
    for row in clean.settlement_rows:
        if row.settlement_id:
            nets[row.settlement_id] = nets.get(row.settlement_id, 0) + row.credit - row.debit

    short = []
    for settlement in clean.settlements:
        arrived = sum(
            credit.amount
            for credit in clean.bank_credits
            if credit.utr == settlement.settlement_utr
        )
        if arrived and arrived != nets.get(settlement.settlement_id, 0):
            rows = nets.get(settlement.settlement_id)
            short.append(f"{settlement.settlement_id}: bank {arrived}, rows {rows}")
    assert short == [], "\n".join(short[:5])
