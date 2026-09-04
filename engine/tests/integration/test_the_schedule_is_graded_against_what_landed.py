"""What the forward schedule got right, marked against the month it could not see.

The schedule is built from payments captured on or before one day and payouts
already made by it. Everything after that day is withheld from it and then
used to mark it. That split is the entire measurement: a projection graded
against data it was allowed to read is not graded at all.

Three `as_of` days per month, so the same seed is asked the question from
three distances - standing at the end of the file, a week back, and a
fortnight back, where a fortnight back means dating money that will not move
for another two weeks.

    4 tiers x 6 seeds x 3 days, 600 orders each     72 schedules

**What it reads.**

* Every date the schedule gets wrong belongs to money that never settled at
  all. Across every tier, the count of mis-dated commitments equals the count
  of commitments the settlement report never mentions - which is the
  `unreported_payments` defect, not a timing error. On money that arrived,
  the date has been right every time.
* The amount error is not noise, and it is not the fee stack being
  approximate. It is the fee *leak*: on the tiers that inject rate
  mismatches, the schedule is short by exactly the overcharge plus the GST
  charged on it, and on the tiers that do not, it is short by nothing at all.
  `TestTheShortfallIsTheOvercharge` pins that to the paisa.

The second of those is the useful one, and it was not designed. The leak
detector reads settlement rows and compares charged rates against contracted
ones; the schedule reads payments and applies a rate card forward. They share
no code past `compute_deductions` and they arrive at the same number, which
makes each one evidence for the other.

**What it does not claim.** Three real mechanisms move a payout beyond the
fee stack, and the tiers above generate none of them, so those figures are
conditional on that. All three were then generated deliberately rather than
left as caveats, and two stopped being caveats:

* *Instant settlement* costs the schedule nothing, at 40% and at 80%. A payout
  pulled early carries a settlement row dated the day of capture, so it is
  already in the bank when the schedule is drawn and is omitted rather than
  mis-dated. The prediction written here first said the opposite.
* *Route* is now netted, and the reason it can be is that a transfer row is
  written when the payment is captured. The merchant holds it on `as_of`, so
  subtracting it reads no future row - and a split leaves in the same payout
  as the payment it came from, so it needs no date of its own. Exact through a
  60% share.
* *Refunds not yet raised* stay uncosted, permanently. A customer who has not
  asked for their money back is a decision, not a row, and reaching it would
  mean predicting - which is the one thing this module exists not to do.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.dataset import Dataset
from milan.domain.merchant import profile_of
from milan.domain.money import Paise, apply_rate
from milan.domain.rates import GST_RATE
from milan.evaluation.harness import to_recon_input
from milan.forecast import Accuracy, grade, last_capture, schedule_from

TIERS = (Difficulty.CLEAN, Difficulty.REALISTIC, Difficulty.MESSY, Difficulty.ADVERSARIAL)
SEEDS = (1, 2, 3, 42, 77, 101)
ORDERS = 600
STANDING_BACK = (0, 7, 14)
"""Days before the last capture to ask the question from.

Zero is the merchant looking at their own books today. Fourteen is the
interesting one: it dates money that will not move for another fortnight, and
it is where a schedule that was quietly reading the answer would still score
perfectly while an honest one has to work.
"""

DATED_RIGHT = 0.95
"""Share of commitments that must land on the day scheduled.

Below 1.0 on purpose, and the gap is not tolerance for a timing error. Some
of the money scheduled here is money the gateway never reports at all - the
`unreported_payments` defect - and a commitment that never settles cannot
land on the day it was due. It is counted as a date failure rather than
excused, because to a merchant it is one.
"""

AMOUNT_RIGHT = 0.85
"""Share of arrivals whose amount is right to the last paisa.

The floor sits here rather than higher because the adversarial tier charges a
quarter of its card payments above contract, and a schedule built on the
contracted rate is *supposed* to disagree with those. Being right about them
would mean the rate card had been fitted to what was charged.
"""


def measure(dataset: Dataset, back: int) -> Accuracy:
    """Build a schedule `back` days before the last capture, and mark it."""
    data = to_recon_input(dataset)
    captured = last_capture(data.payments)
    assert captured is not None
    rates = profile_of(data.settlement_rows).rates()
    schedule = schedule_from(data, rates, as_of=captured - timedelta(days=back))
    return grade(schedule, data.settlement_rows)


def month(tier: Difficulty, seed: int) -> Dataset:
    return ChaosEngine(GenerationConfig(seed=seed, difficulty=tier, order_count=ORDERS)).generate()


@pytest.fixture(scope="module")
def graded() -> dict[tuple[Difficulty, int, int], Accuracy]:
    return {
        (tier, seed, back): measure(month(tier, seed), back)
        for tier in TIERS
        for seed in SEEDS
        for back in STANDING_BACK
    }


class TestTheDatesHold:
    def test_enough_money_was_dated_for_the_measurement_to_mean_anything(
        self, graded: dict[tuple[Difficulty, int, int], Accuracy]
    ) -> None:
        """The guard on the guard.

        Every floor below passes trivially over an empty schedule, and an
        empty schedule is exactly what a broken `as_of` cut produces. This
        fails first if the schedule ever stops scheduling anything.
        """
        for key, accuracy in graded.items():
            assert accuracy.total >= 20, f"{key}: only {accuracy.total} commitments"

    def test_the_scheduled_day_is_the_day_it_landed(
        self, graded: dict[tuple[Difficulty, int, int], Accuracy]
    ) -> None:
        for key, accuracy in graded.items():
            assert accuracy.dated_exactly >= DATED_RIGHT, (
                f"{key}: {accuracy.dated_exactly:.1%} dated exactly, "
                f"{len(accuracy.never_arrived)} never arrived"
            )

    def test_every_wrong_date_is_money_that_never_came(
        self, graded: dict[tuple[Difficulty, int, int], Accuracy]
    ) -> None:
        """The claim the date figures actually support.

        Not "the schedule is 98% accurate about timing" but the stronger and
        narrower "the schedule has never been wrong about when money that
        arrived would arrive". Every miss is a payout the gateway never
        reported, which is a different failure with its own exception.
        """
        for key, accuracy in graded.items():
            missed = [item for item in accuracy.checked if item.days_out != 0]
            assert all(not item.arrived for item in missed), (
                f"{key}: dates missed on money that did arrive - "
                f"{[(i.payment_id, i.due, i.landed_on) for i in missed if i.arrived]}"
            )

    def test_a_clean_month_is_dated_perfectly(
        self, graded: dict[tuple[Difficulty, int, int], Accuracy]
    ) -> None:
        """The control. With no defects there is nothing to be wrong about,
        and a schedule that cannot score 100% here is broken rather than
        cautious."""
        for back in STANDING_BACK:
            for seed in SEEDS:
                accuracy = graded[(Difficulty.CLEAN, seed, back)]

                assert accuracy.dated_exactly == 1.0
                assert accuracy.never_arrived == ()


class TestTheAmountsHold:
    def test_a_clean_month_is_right_to_the_paisa(
        self, graded: dict[tuple[Difficulty, int, int], Accuracy]
    ) -> None:
        for back in STANDING_BACK:
            for seed in SEEDS:
                accuracy = graded[(Difficulty.CLEAN, seed, back)]

                assert accuracy.to_the_paisa == 1.0
                assert accuracy.error == Paise(0)

    def test_arrivals_reconstruct_to_the_paisa_often_enough(
        self, graded: dict[tuple[Difficulty, int, int], Accuracy]
    ) -> None:
        for key, accuracy in graded.items():
            assert accuracy.to_the_paisa >= AMOUNT_RIGHT, (
                f"{key}: {accuracy.to_the_paisa:.1%} exact, error {accuracy.error}"
            )

    def test_the_schedule_never_promises_less_than_arrives(
        self, graded: dict[tuple[Difficulty, int, int], Accuracy]
    ) -> None:
        """Every error runs one way, and that is a fact about the world.

        A payout can be short - overcharged, or never sent - and it cannot be
        long, because a gateway does not pay a merchant more than it collected
        for them. An error in the other direction would mean the fee stack was
        wrong rather than the payout, and this is the assertion that would
        catch it.
        """
        for key, accuracy in graded.items():
            assert accuracy.error <= 0, f"{key}: schedule under-promised by {accuracy.error}"


class TestTheShortfallIsTheOvercharge:
    """Where the amount error comes from, named rather than tolerated.

    A floor saying "85% of amounts are exact" is a floor that would still pass
    if the fee arithmetic were subtly wrong. This says what the other 15% is:
    every rupee of it is a row charged above the merchant's contracted rate,
    plus the GST charged on that overcharge.

    It is checked against the generator's leak answer key rather than against
    the leak detector, so the two modules that agree here reached the number
    without either one reading the other.
    """

    @pytest.mark.parametrize("tier", [Difficulty.MESSY, Difficulty.ADVERSARIAL])
    def test_the_error_is_the_fee_gap_plus_its_gst(self, tier: Difficulty) -> None:
        dataset = month(tier, 42)
        accuracy = measure(dataset, back=14)
        overcharged = {truth.payment_id: truth for truth in dataset.answer_key.leaks}

        short = [item for item in accuracy.arrived if item.error != 0]
        assert short, "no amount error to explain on a tier that injects rate mismatches"
        assert all(item.payment_id in overcharged for item in short), (
            "an amount error on a row that was never overcharged"
        )

        # GST rounds half-up on each fee independently, so the tax gap is the
        # difference of two rounded numbers rather than the rounding of one
        # difference. The two disagree by a paisa often enough that summing
        # the shortcut over seven rows was already wrong by one.
        with_gst = 0
        for item in short:
            truth = overcharged[item.payment_id]
            charged = truth.charged_fee + apply_rate(truth.charged_fee, GST_RATE)
            contracted = truth.contracted_fee + apply_rate(truth.contracted_fee, GST_RATE)
            with_gst += charged - contracted

        assert accuracy.error_on_arrivals == Paise(-with_gst)

    @pytest.mark.parametrize("tier", [Difficulty.CLEAN, Difficulty.REALISTIC])
    def test_a_tier_with_no_rate_mismatch_has_no_amount_error(self, tier: Difficulty) -> None:
        for seed in SEEDS:
            accuracy = measure(month(tier, seed), back=14)

            assert accuracy.error_on_arrivals == Paise(0), f"{tier.value}/{seed}"


def instant_month(share: float) -> Dataset:
    return ChaosEngine(
        GenerationConfig(
            seed=42,
            difficulty=Difficulty.REALISTIC,
            order_count=ORDERS,
            instant_settlement_probability=share,
        )
    ).generate()


class TestInstantSettlementShrinksTheScheduleRatherThanSpoilingIt:
    """The blind spot that turned out not to be one.

    This class was written to bound a cost. A merchant who pulls a payout
    early gets the money the day it was captured, nothing in a payments file
    says which payouts they will pull, and so every instant payout should have
    been dated T+2 and been two days late. The docstring saying so was written
    before the numbers were.

    The numbers say otherwise, and the reason is structural rather than lucky.
    An instant payout carries a settlement row dated the day of capture, which
    is on or before any day a schedule is drawn from - so by the time the
    schedule exists that money is already in the bank, and the schedule leaves
    it out instead of dating it. What instant settlement changes is the *size*
    of the schedule, not its accuracy: at 80% instant the same month schedules
    a quarter as many payments, every one of them still on the right day.

    Kept rather than deleted along with the prediction, because the property
    it now pins is the first one that would break if the `as_of` cut were ever
    loosened to read rows the merchant does not yet have.
    """

    @pytest.mark.parametrize("share", [0.4, 0.8])
    def test_an_instant_payout_is_omitted_rather_than_dated_wrongly(self, share: float) -> None:
        accuracy = measure(instant_month(share), back=7)

        assert accuracy.total > 0
        assert accuracy.dated_exactly == 1.0
        assert accuracy.error_on_arrivals == Paise(0)

    def test_the_more_of_them_there_are_the_less_is_left_to_schedule(self) -> None:
        counts = [measure(instant_month(share), back=7).total for share in (0.0, 0.4, 0.8)]

        assert counts == sorted(counts, reverse=True)
        assert counts[-1] < counts[0]


def route_month(share: float) -> Dataset:
    return ChaosEngine(
        GenerationConfig(
            seed=42,
            difficulty=Difficulty.REALISTIC,
            order_count=ORDERS,
            route_probability=share,
        )
    ).generate()


class TestARouteSplitIsNettedRatherThanIgnored:
    """The blind spot that was reachable after all.

    A marketplace pays part of each sale straight on to a linked account, and
    that share was never the merchant's money. A schedule that ignores it
    tells a platform it is getting a payout that includes somebody else's
    revenue - and it overstates by more the better the marketplace does.

    It was listed as unreachable on the reasoning that the split is not
    knowable from the payment record. That was wrong, and the generator says
    so: a transfer row carries `created_at` of the *capture*, not of the
    payout. The merchant is holding it on the day, so netting it reads
    nothing about the future. Nor does it need a date invented for it - unlike
    a refund, which waits for a payout large enough to absorb it, a transfer
    leaves with the money it came from.

    So this is arithmetic on a row that already exists, which is the only kind
    of thing this module is allowed to do.
    """

    @pytest.mark.parametrize("share", [0.15, 0.30, 0.60])
    def test_the_amount_is_exact_at_every_share(self, share: float) -> None:
        accuracy = measure(route_month(share), back=7)

        assert accuracy.total > 0
        assert accuracy.error_on_arrivals == Paise(0)
        assert accuracy.dated_exactly == 1.0

    @pytest.mark.parametrize("share", [0.15, 0.30, 0.60])
    def test_the_split_is_reported_separately_from_the_fees(self, share: float) -> None:
        """A fee is the merchant's money going to the gateway. A Route split
        is a share of the sale that was never theirs. The proof layer keeps
        them on separate lines and so does this, because summing them would
        describe the platform's economics wrongly in both directions."""
        data = to_recon_input(route_month(share))
        rates = profile_of(data.settlement_rows).rates()

        schedule = schedule_from(data, rates)

        assert schedule.routed > 0
        assert schedule.deducted > 0
        assert schedule.gross == Paise(schedule.committed + schedule.deducted + schedule.routed)

    def test_a_merchant_with_no_linked_accounts_routes_nothing(self) -> None:
        data = to_recon_input(route_month(0.0))
        rates = profile_of(data.settlement_rows).rates()

        assert schedule_from(data, rates).routed == Paise(0)

    def test_the_more_is_routed_the_less_is_committed(self) -> None:
        """The direction that matters. Ignoring the split would leave this
        flat, which is exactly the failure - a platform reading the same
        payout however much of it belongs to its sellers."""
        committed = []
        for share in (0.0, 0.30, 0.60):
            data = to_recon_input(route_month(share))
            rates = profile_of(data.settlement_rows).rates()
            committed.append(schedule_from(data, rates).committed)

        assert committed == sorted(committed, reverse=True)
        assert committed[-1] < committed[0]


class TestNothingIsDatedThatShouldNotBe:
    def test_overdue_money_is_never_counted_as_coming(self) -> None:
        """The headline total is what is coming, and only what is coming.

        A payment captured three weeks ago with no payout behind it is an
        exception, not cash flow, and the two must not be summed. Checked on
        the adversarial tier because it is the one that produces the most of
        them.
        """
        data = to_recon_input(month(Difficulty.ADVERSARIAL, 42))
        captured = last_capture(data.payments)
        assert captured is not None
        rates = profile_of(data.settlement_rows).rates()

        schedule = schedule_from(data, rates, as_of=captured)

        assert schedule.overdue, "no overdue money on a tier that drops payouts"
        due = {item.payment_id for item in schedule.overdue}
        scheduled = {
            item.payment_id for landing in schedule.landings for item in landing.commitments
        }
        assert not due & scheduled
        assert all(item.due <= schedule.as_of for item in schedule.overdue)
        assert all(landing.on > schedule.as_of for landing in schedule.landings)

    def test_the_dated_total_is_the_sum_of_the_days(self) -> None:
        data = to_recon_input(month(Difficulty.MESSY, 77))
        rates = profile_of(data.settlement_rows).rates()

        schedule = schedule_from(data, rates)
        horizon = schedule.horizon
        assert horizon is not None

        assert schedule.through(horizon) == schedule.committed
        assert schedule.through(date.min) == Paise(0)
        assert schedule.committed == Paise(
            sum(item.net for landing in schedule.landings for item in landing.commitments)
        )
