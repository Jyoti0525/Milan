"""Learning the fee stack, and the circularity that kept it unbuilt.

Rule induction was named in the original build plan on day one and was still
open on day twelve, listed as "the one remaining item that would change a
graded number". It stayed open for a real reason rather than for want of time.

Learning a rate from the rows and then checking the rows against it is
circular. Whatever the gateway charged becomes, by construction, what it was
contracted to charge - and `milan.leaks`, which exists to find fees above
contract, would go silent on every merchant it was pointed at. Building it
badly would not have added a feature; it would have quietly removed the best
one.

**The resolution is a stated condition, not a trick: an overcharge is a
minority.** A merchant contracted at 2% and overcharged on some cards has most
of their rows at 2%, so the modal rate over a band is the contract and the
rows that disagree are the leak. Where that does not hold - a band genuinely
split between two rates - the induction refuses and says which two.

**Measured over 48 months, 4 tiers, 600 orders each:**

    contract recovered exactly            48 / 48
    leaks still found                    693 / 693
    leaks missed                               0
    false accusations                          0

The last two lines are the ones that decide whether this was safe to build.
The adversarial tier charges a quarter of its consumer cards above contract,
and the induced card still separates them perfectly - it hands over the
majority rate and leaves the minority to be reported, rather than absorbing
them into a contract that would explain them away.

It is wired into the path that had no rate card and never into the path that
does. Every graded figure in this project passes an explicit card, so nothing
measured can move because a detector changed its mind; the import path, which
was checking real merchants against Razorpay list price, now reads their own.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.dataset import Dataset
from milan.domain.enums import CardType, PaymentMethod
from milan.domain.money import apply_rate
from milan.domain.rates import RateCard
from milan.leaks.detector import detect
from milan.rules import induce_rates
from milan.rules.induction import DOMINANT, MINIMUM_ROWS

TIERS = (Difficulty.CLEAN, Difficulty.REALISTIC, Difficulty.MESSY, Difficulty.ADVERSARIAL)
SEEDS = tuple(range(1, 13))
ORDERS = 600
GST = RateCard().gst

RECOVER_EVERY_CONTRACT = 1.0
"""How many months must yield back the exact rate card they were built with.

At 1.0 because there is nothing to trade here. A rate card is not a score, it
is the standard every fee in the run is then measured against - so a card that
is nearly right does not produce nearly-right leak findings, it produces
confident wrong ones on every row of the band it got wrong.
"""

NEVER_A_FALSE_ACCUSATION = 0
"""Leaks the induced card may invent. The limit `milan.leaks` already holds.

A false exception costs somebody five minutes. A false accusation of
overcharging costs them a call with their account manager and some of their
credibility, and inducing the contract is the change most likely to cause one.
"""


def month(
    tier: Difficulty, seed: int, orders: int = ORDERS, rates: RateCard | None = None
) -> Dataset:
    config = GenerationConfig(seed=seed, difficulty=tier, order_count=orders)
    if rates is not None:
        config = config.model_copy(update={"rates": rates})
    return ChaosEngine(config).generate()


@pytest.fixture(scope="module")
def graded() -> dict[str, int]:
    tally = {"months": 0, "recovered": 0, "found": 0, "missed": 0, "invented": 0}
    for tier in TIERS:
        for seed in SEEDS:
            dataset = month(tier, seed)
            contracted = GenerationConfig(seed=seed, difficulty=tier, order_count=ORDERS).rates
            induced = induce_rates(dataset.settlement_rows).card()

            tally["months"] += 1
            tally["recovered"] += int(_same(induced, contracted))

            truth = {leak.payment_id for leak in dataset.answer_key.leaks}
            found = {leak.payment_id for leak in detect(dataset.settlement_rows, induced)}
            tally["found"] += len(truth & found)
            tally["missed"] += len(truth - found)
            tally["invented"] += len(found - truth)
    return tally


def _same(induced: RateCard, contracted: RateCard) -> bool:
    return (
        induced.standard == contracted.standard
        and induced.corporate_card == contracted.corporate_card
        and induced.international_card == contracted.international_card
        and induced.gst == contracted.gst
    )


class TestTheContractComesBackOutOfTheRows:
    def test_every_month_recovers_the_card_it_was_built_with(self, graded: dict[str, int]) -> None:
        assert graded["recovered"] / graded["months"] >= RECOVER_EVERY_CONTRACT

    def test_enough_months_were_read_to_mean_anything(self, graded: dict[str, int]) -> None:
        assert graded["months"] >= 40

    def test_a_non_standard_contract_is_recovered_too(self) -> None:
        """The test that stops this passing by knowing the published rates.

        Every tier above is generated on Razorpay's list pricing, so an
        induction that ignored the rows and returned `RateCard()` would score
        a perfect 48 out of 48. This merchant is on a negotiated contract
        none of the defaults would produce.
        """
        negotiated = RateCard(
            standard=Decimal("0.0175"),
            corporate_card=Decimal("0.0240"),
            international_card=Decimal("0.0350"),
        )
        dataset = month(Difficulty.MESSY, 42, rates=negotiated)

        induced = induce_rates(dataset.settlement_rows).card()

        assert induced.standard == Decimal("0.0175")
        assert induced.corporate_card == Decimal("0.0240")
        assert induced.international_card == Decimal("0.0350")
        assert induced != RateCard()


class TestItDoesNotExplainAwayTheOverchargesItLearnsFrom:
    """The circularity, measured rather than argued about."""

    def test_no_leak_is_lost(self, graded: dict[str, int]) -> None:
        assert graded["missed"] == 0

    def test_no_leak_is_invented(self, graded: dict[str, int]) -> None:
        assert graded["invented"] == NEVER_A_FALSE_ACCUSATION

    def test_there_were_leaks_to_lose(self, graded: dict[str, int]) -> None:
        """Without this, the two assertions above pass on a run with no
        overcharges in it - which is the exact shape the circularity would
        take if the induction had absorbed them."""
        assert graded["found"] >= 500

    def test_the_band_it_learns_from_is_the_band_that_is_overcharged(self) -> None:
        """Pinning the mechanism, not just the outcome.

        The adversarial tier promotes a quarter of domestic consumer cards to
        the corporate rate while leaving the card-type column saying consumer.
        So the band the induction reads is the band the leak lives in, and it
        still comes back with the contracted rate and counts the rest as
        disagreeing.
        """
        dataset = month(Difficulty.ADVERSARIAL, 42)

        consumer = induce_rates(dataset.settlement_rows).consumer_card

        assert consumer.settled
        assert consumer.rate == RateCard().standard
        assert consumer.disagreeing > 0
        assert consumer.rows > consumer.disagreeing


class TestItRefusesRatherThanPickingTheMorePopularRate:
    def test_a_band_split_between_two_rates_is_a_question(self) -> None:
        """A merchant genuinely on two rates has not said which is the
        contract, and the more popular one is not the answer - it is a guess
        wearing a majority.
        """
        split = []
        seen = 0
        for row in month(Difficulty.CLEAN, 42).settlement_rows:
            international = (
                row.method is PaymentMethod.CARD and row.card_type is CardType.INTERNATIONAL
            )
            if not international:
                split.append(row)
                continue
            seen += 1
            # Every other international card moved to a different rate, so the
            # band divides evenly and neither half is the contract.
            if seen % 2:
                split.append(row)
                continue
            fee = apply_rate(row.amount, Decimal("0.0400"))
            split.append(row.model_copy(update={"fee": fee, "tax": apply_rate(fee, GST)}))

        induced = induce_rates(tuple(split))

        assert not induced.international_card.settled
        assert "do not agree" in induced.international_card.because
        assert induced.international_card in induced.questions

    def test_a_refused_band_keeps_the_published_rate(self) -> None:
        """Falling back rather than leaving a hole. The published rate is
        what a merchant is most likely contracted to, and using it means the
        leak check on that band behaves exactly as it did before any of this
        existed."""
        thin = month(Difficulty.CLEAN, 42, orders=8)

        induced = induce_rates(thin.settlement_rows)

        assert induced.questions
        assert induced.card().international_card == RateCard().international_card

    def test_a_band_too_thin_to_read_says_so_with_its_count(self) -> None:
        thin = month(Difficulty.CLEAN, 42, orders=8)

        finding = induce_rates(thin.settlement_rows).international_card

        assert not finding.settled
        assert finding.of < MINIMUM_ROWS
        assert str(MINIMUM_ROWS) in finding.because

    def test_the_dominance_threshold_is_above_a_bare_majority(self) -> None:
        """A rate holding 51% of its band is not a contract, it is the larger
        half of a disagreement."""
        assert Decimal("0.5") < DOMINANT


class TestEveryFindingCarriesItsPopulation:
    def test_a_rate_is_never_reported_without_the_rows_behind_it(self) -> None:
        induced = induce_rates(month(Difficulty.MESSY, 42).settlement_rows)

        assert induced.settled
        for finding in induced.findings:
            assert finding.share
            assert finding.because
            if finding.settled:
                assert finding.rows > 0
                assert f"{finding.rows} of {finding.of}" == finding.share

    def test_gst_is_read_against_the_fee_and_not_the_amount(self) -> None:
        """GST is charged on the platform fee and never on the transaction
        value. Reading it against the amount would produce a number that is
        not a rate of anything - and it would be about 0.36%, which is small
        enough to look plausible on a screen."""
        induced = induce_rates(month(Difficulty.REALISTIC, 42).settlement_rows)

        assert induced.gst.rate == RateCard().gst
        assert "of the fee" in induced.gst.because
