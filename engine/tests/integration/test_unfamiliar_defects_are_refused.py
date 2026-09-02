"""What induction does with a shortfall nobody wrote a rule for.

The measurement that is not circular, and the reason it had to exist.

`test_causes_are_one_cause.py` grades induced causes against the generator's
answer key, and reads 99.5%. But the generator injects the defects this
project chose to model and the inducer names the causes this project chose to
recognise, and both were written by the same person in the same fortnight. A
high purity there means "these two modules agree with each other". It cannot
mean "the inducer is right about a merchant's books", because nothing in that
loop has ever met a defect from outside it.

The case that is certain to arrive first in production is the one that loop
cannot produce: money missing for a reason nobody wrote a rule for. So this
file generates four such reasons, deliberately gives the inducer no rule for
any of them, and measures the only thing that matters when a cause is
unknown - whether the system says so.

    108 unfamiliar shortfalls, 18 months, 3 tiers   100% left uncaused

Refusing is the whole result. A shortfall left in `uncaused` costs somebody
ten minutes reading one case. A shortfall given a name it did not earn costs
them an argument with Razorpay about a mechanism that was never involved -
and the named cause carries a `because` sentence with real arithmetic in it,
so nothing on the screen marks the story as invented.

**What this found.** The first run refused 105 of 108, and all three failures
came from one rule. `_one_counterparty_keeps_paying` groups unexplained
deposits by payer and concludes the money came from outside the gateway - and
it was firing on stems reading `ACH` and `RZPY`. The first is a clearing
system rather than a business, leaking through a noise list that stripped
NEFT and IMPS but not ACH. The second is Razorpay itself, which makes the
finding "confirm whether RZPY is money from outside Razorpay" - a cause
asking somebody to check a fact its own evidence states.

Both are now guarded, and the guard cost nothing: purity, coverage and queue
reduction are identical to the paisa on the familiar tiers. That is the
useful shape of this result. The rule was not made more cautious, it was
stopped from making a claim its own premise contradicted, and the only
outputs it lost were false ones.
"""

from __future__ import annotations

from collections import Counter

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.dataset import Dataset
from milan.evaluation.harness import to_recon_input
from milan.recon.causes import induce
from milan.recon.pipeline import ReconciliationPipeline, RunMetadata

UNFAMILIAR = frozenset({"BANK_CHARGE", "FX_MARKUP", "DISPUTE_PENALTY", "PROMO_FUNDING"})
"""The four mechanisms `milan.recon.causes` has no rule for.

Chosen by arithmetic rather than by story, because a rule can only match on
arithmetic. A flat bank charge is a constant number of paise where every
rate rule works in proportions; an FX markup moves between batches where
`_one_undisclosed_rate` holds its members to 0.02% of each other; a dispute
penalty is a recovery with no refund row anywhere to match it against; promo
funding is a rate over part of a batch rather than all of it.

All four are ordinary things that happen to Indian merchants. That matters -
the test would prove nothing if they were absurd. They stand in for the many
real mechanisms nobody has got round to writing a rule for.
"""

TIERS = (Difficulty.REALISTIC, Difficulty.MESSY, Difficulty.ADVERSARIAL)
SEEDS = (1, 2, 3, 42, 77, 101)
ORDERS = 600
PER_RUN = 6

MUST_REFUSE = 1.0
"""The share of unfamiliar shortfalls that must be left uncaused.

The one floor in this project set at exactly 1.0, and it belongs there. Every
other threshold here trades a little accuracy for a little coverage, because
both are useful. This one does not trade: a cause invented for a mechanism
the rules have never seen is not a slightly worse answer, it is a confident
sentence about something that did not happen, and there is no amount of
coverage worth buying with it.
"""


def origin(dataset: Dataset) -> dict[str, str]:
    """Which defect each credit actually carries, per the answer key.

    Compound labels are read by their last part, the way the purity
    measurement reads them: a credit can lose its reference *and* be short by
    an FX markup, and it is the shortfall this file is asking about.
    """
    return {
        truth.credit_id: (truth.defect or "CLEAN").split("+")[-1]
        for truth in dataset.answer_key.credits
    }


def unfamiliar_in_the_queue(tier: Difficulty, seed: int) -> tuple[list[str], list[str]]:
    """Run one month and split its unfamiliar shortfalls into named and not.

    Only credits that actually reached the queue are counted. A defect the
    matcher resolved anyway never became an exception, so induction was never
    asked about it and crediting the refusal would be counting a question
    nobody put.
    """
    dataset = ChaosEngine(
        GenerationConfig(
            seed=seed, difficulty=tier, order_count=ORDERS, unfamiliar_variances=PER_RUN
        )
    ).generate()
    truth = origin(dataset)
    report = ReconciliationPipeline().run(
        to_recon_input(dataset), RunMetadata(seed=seed, difficulty=tier.value)
    )
    result = induce(report.exceptions)

    named = {member: cause for cause in result.causes for member in cause.members}
    refused = set(result.uncaused)

    was_named = [s for s, d in truth.items() if d in UNFAMILIAR and s in named]
    was_refused = [s for s, d in truth.items() if d in UNFAMILIAR and s in refused]
    return was_named, was_refused


@pytest.fixture(scope="module")
def measured() -> tuple[list[tuple[str, int, str]], int]:
    """Every unfamiliar shortfall across every month, named or refused."""
    wrongly_named: list[tuple[str, int, str]] = []
    refused = 0
    for tier in TIERS:
        for seed in SEEDS:
            named, left = unfamiliar_in_the_queue(tier, seed)
            wrongly_named.extend((tier.value, seed, subject) for subject in named)
            refused += len(left)
    return wrongly_named, refused


class TestACauseIsNotInventedForAMechanismNobodyModelled:
    def test_every_unfamiliar_shortfall_is_left_uncaused(
        self, measured: tuple[list[tuple[str, int, str]], int]
    ) -> None:
        wrongly_named, refused = measured
        total = len(wrongly_named) + refused

        assert total > 0, "no unfamiliar defect reached the queue - the test proves nothing"

        share = refused / total
        detail = "\n".join(f"  {tier}/{seed}: {subject}" for tier, seed, subject in wrongly_named)

        assert share >= MUST_REFUSE, f"{share:.1%} refused, {len(wrongly_named)} named:\n{detail}"

    def test_enough_of_them_reached_the_queue_to_mean_something(
        self, measured: tuple[list[tuple[str, int, str]], int]
    ) -> None:
        """A guard on the guard.

        If the generator stopped placing these, or the matcher started
        resolving them, the assertion above would pass by having nothing to
        check - the quietest way for a measurement to stop measuring.
        """
        wrongly_named, refused = measured

        assert len(wrongly_named) + refused >= 50


class TestTheRuleThatHadToBeFixedToGetThere:
    """The three failures the first run produced, pinned as cases.

    Kept separate from the measurement because they are the finding rather
    than the score, and because a future rule could reintroduce either
    mistake without moving the share above off 100%.
    """

    def test_a_clearing_system_is_not_a_counterparty(self) -> None:
        """ACH, NACH and ECS are rails, exactly as NEFT and IMPS are.

        Missing from the noise list, ACH survived into the stem and became
        the payer, producing "Repeated deposits from ACH" - a finding that
        names a clearing system as a business that pays this merchant.
        """
        from milan.recon.causes import _stem

        for rail in ("ACH", "NACH", "ECS", "NEFT", "IMPS", "RTGS"):
            assert _stem(f"{rail} CR-SOMEBANK0001-ACME LOGISTICS") == "ACME LOGISTICS", rail

    def test_a_gateway_payout_is_never_money_from_outside_the_gateway(self) -> None:
        """The premise guard.

        `_one_counterparty_keeps_paying` exists to say a recurring deposit is
        not a gateway payout. A narration reading RAZORPAY SETTLEMENT has
        answered that question already, and firing anyway produced "confirm
        whether RZPY is money from outside Razorpay".
        """
        from milan.recon.causes import _GATEWAY, _stem

        for narration in (
            "IMPS/RZPY/SETTLEMENT",
            "NEFT CR-RATN0000088-RAZORPAY-SETTLEMENT",
            "UTRA52PGKNGUVVC RAZORPAY PAYOUT",
        ):
            assert _GATEWAY & set(_stem(narration).split()), narration

    def test_a_real_outside_payer_still_reaches_the_rule(self) -> None:
        """The cost of the guard, bounded.

        The rule is worth having. A logistics partner paying every Tuesday
        into a queue that only knows about gateway payouts is exactly the
        case it turns from six failures into one fact, and neither guard
        touches it.
        """
        from milan.recon.causes import _GATEWAY, _stem

        stem = _stem("ACH CR-HDFC0000123-BLUEDART EXPRESS")

        assert stem == "BLUEDART EXPRESS"
        assert not _GATEWAY & set(stem.split())


class TestTheseDefectsAreOffUnlessAskedFor:
    def test_no_tier_generates_them(self) -> None:
        """The knob is a config field rather than a fifth difficulty, and it
        has to stay off everywhere else - every seed in every other test in
        this suite depends on these months not changing."""
        for tier in (Difficulty.CLEAN, *TIERS):
            config = GenerationConfig(seed=1, difficulty=tier, order_count=100)

            assert config.defects.unfamiliar_variances == 0

    def test_a_default_month_carries_none_of_these_labels(self) -> None:
        dataset = ChaosEngine(
            GenerationConfig(seed=42, difficulty=Difficulty.ADVERSARIAL, order_count=ORDERS)
        ).generate()

        assert not UNFAMILIAR & set(Counter(origin(dataset).values()))

    def test_asking_for_them_actually_places_them(self) -> None:
        dataset = ChaosEngine(
            GenerationConfig(
                seed=42,
                difficulty=Difficulty.ADVERSARIAL,
                order_count=ORDERS,
                unfamiliar_variances=PER_RUN,
            )
        ).generate()

        assert UNFAMILIAR & set(Counter(origin(dataset).values()))
