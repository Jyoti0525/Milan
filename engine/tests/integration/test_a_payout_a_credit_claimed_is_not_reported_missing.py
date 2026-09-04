"""The overclaim decision 242 named, closed and graded.

`MISSING_SETTLEMENT` means the gateway said it paid and no credit was
concluded for it. Decision 242 found that most of what the rule reported was
not that: a bank credit *had* been matched to the payout, the prover refused
to close the arithmetic, the cascade withdrew the claim, and nothing carried
that fact as far as the exception. So the queue said "no bank credit matches
it" about a payout a bank credit plainly matched, and carried the full net as
an amount - showing a merchant one short payout twice and roughly double the
exposure they had.

242 refused to suppress the exception, and that was right: suppressing means
asserting a match the prover declined to assert, which is the trade this
project does not make. What it left open was the sentence and the amount,
neither of which requires asserting anything.

Both are fixed by passing the cascade's own `withdrawn_ids` through to the
categoriser. The exception still exists and still says no credit was
concluded. It now names the credit that came up short, and carries no amount,
because the money that did not arrive is the shortfall and the shortfall
exception is already reporting it.

**Measured over 36 months, 3 tiers, 600 orders each:**

    really missing, correctly left alone          60
    really missing, wrongly named as spoken-for    0
    not missing, correctly named as spoken-for   144
    not missing, still says no credit matches it  36

The zero is the load-bearing figure. A payout that genuinely went astray must
never be softened into "some credit probably covers this", because that is the
one message that would stop somebody chasing money that is gone.

The remaining 36 are not a residue of the same bug. They are payouts no credit
ever claimed, not even provisionally - the cascade never identified a
candidate - so "no bank credit matches it" is exactly what happened to them.
"""

from __future__ import annotations

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.enums import ExceptionCode
from milan.domain.money import ZERO
from milan.domain.results import ReconException
from milan.evaluation.harness import to_recon_input
from milan.recon.pipeline import ReconciliationPipeline, RunMetadata

TIERS = (Difficulty.REALISTIC, Difficulty.MESSY, Difficulty.ADVERSARIAL)
SEEDS = tuple(range(1, 13))
ORDERS = 600

NEVER_SOFTEN_A_REAL_ONE = 0
"""How many genuinely missing payouts may be named as spoken for.

The one hard limit in this file. Every other figure here trades one true
statement for a truer one; this does not trade. A payout that never arrived,
labelled as already accounted for by a credit in the queue, is the single
message in this system most likely to stop somebody chasing money that is
gone - and unlike a wrong match, nothing downstream would ever contradict it.
"""

CLOSE_MOST_OF_THE_OVERCLAIM = 0.75
"""Share of the overclaimed payouts that must now name their credit.

Below 1.0 because the population it is measured over is not all reachable:
some payouts were never claimed by any credit at all, and for those the
original sentence is correct rather than overclaiming.
"""


@pytest.fixture(scope="module")
def graded() -> dict[str, int]:
    """Every `MISSING_SETTLEMENT` in 36 months, split four ways."""
    tally = {"real_kept": 0, "real_softened": 0, "overclaim_closed": 0, "overclaim_left": 0}
    for tier in TIERS:
        for seed in SEEDS:
            dataset = ChaosEngine(
                GenerationConfig(seed=seed, difficulty=tier, order_count=ORDERS)
            ).generate()
            gone = set(dataset.answer_key.missing_settlement_ids)
            data = to_recon_input(dataset)
            report = ReconciliationPipeline().run(
                data, RunMetadata(seed=seed, difficulty=tier.value)
            )
            for item in _missing(report.exceptions):
                spoken_for = "claimed_by" in item.evidence
                really_gone = item.subject_id in gone
                if really_gone:
                    tally["real_softened" if spoken_for else "real_kept"] += 1
                else:
                    tally["overclaim_closed" if spoken_for else "overclaim_left"] += 1
    return tally


def _missing(exceptions: tuple[ReconException, ...]) -> list[ReconException]:
    return [item for item in exceptions if item.code is ExceptionCode.MISSING_SETTLEMENT]


class TestAPayoutThatReallyWentAstrayStillSaysSo:
    def test_no_missing_payout_is_named_as_covered_by_a_credit(
        self, graded: dict[str, int]
    ) -> None:
        assert graded["real_softened"] == NEVER_SOFTEN_A_REAL_ONE

    def test_there_were_enough_of_them_to_mean_anything(self, graded: dict[str, int]) -> None:
        """The guard on the guard. Zero softened is trivially true of a run
        that produced no missing payouts at all."""
        assert graded["real_kept"] >= 40

    def test_a_really_missing_payout_keeps_its_full_amount(self) -> None:
        """The amount is what a merchant chases. Zeroing it on a payout that
        genuinely did not arrive would remove the money from the one figure
        that says money is elsewhere."""
        dataset = ChaosEngine(
            GenerationConfig(seed=42, difficulty=Difficulty.ADVERSARIAL, order_count=ORDERS)
        ).generate()
        gone = set(dataset.answer_key.missing_settlement_ids)
        data = to_recon_input(dataset)
        report = ReconciliationPipeline().run(data, RunMetadata(seed=42, difficulty="adversarial"))

        real = [item for item in _missing(report.exceptions) if item.subject_id in gone]

        assert real, "no genuinely missing payout on the tier that injects them"
        for item in real:
            assert item.amount > ZERO
            assert "No bank credit matches it" in item.summary


class TestAPayoutACreditClaimedSaysThatInstead:
    def test_most_of_the_overclaim_is_closed(self, graded: dict[str, int]) -> None:
        reachable = graded["overclaim_closed"] + graded["overclaim_left"]

        assert reachable > 0
        assert graded["overclaim_closed"] / reachable >= CLOSE_MOST_OF_THE_OVERCLAIM

    def test_it_names_the_credit_rather_than_denying_one_exists(self) -> None:
        dataset = ChaosEngine(
            GenerationConfig(seed=42, difficulty=Difficulty.ADVERSARIAL, order_count=ORDERS)
        ).generate()
        data = to_recon_input(dataset)
        report = ReconciliationPipeline().run(data, RunMetadata(seed=42, difficulty="adversarial"))

        spoken = [item for item in _missing(report.exceptions) if "claimed_by" in item.evidence]

        assert spoken
        credits = {credit.credit_id for credit in data.bank_credits}
        for item in spoken:
            named = item.evidence["claimed_by"]
            assert named in credits, named
            assert named in item.summary
            assert "No bank credit matches it" not in item.summary

    def test_it_carries_no_amount_because_the_shortfall_already_does(self) -> None:
        """The double count, removed without asserting a match.

        `ReconException.amount` is the unexplained amount, and this payout's
        unexplained amount is the shortfall on the credit that claimed it -
        which is in the same queue, under its own code, with its own figure.
        Reporting it twice showed the merchant twice their exposure.
        """
        dataset = ChaosEngine(
            GenerationConfig(seed=42, difficulty=Difficulty.ADVERSARIAL, order_count=ORDERS)
        ).generate()
        data = to_recon_input(dataset)
        report = ReconciliationPipeline().run(data, RunMetadata(seed=42, difficulty="adversarial"))

        spoken = [item for item in _missing(report.exceptions) if "claimed_by" in item.evidence]

        assert spoken
        assert all(item.amount == ZERO for item in spoken)

    def test_the_exception_is_still_raised(self) -> None:
        """Not suppressed, which is the trade decision 242 refused.

        Suppressing would mean the pipeline asserting that the credit and the
        payout are the same money - which is exactly the claim the prover
        declined to make. The exception stays; only its sentence and its
        amount stop saying more than the evidence does.
        """
        dataset = ChaosEngine(
            GenerationConfig(seed=42, difficulty=Difficulty.ADVERSARIAL, order_count=ORDERS)
        ).generate()
        data = to_recon_input(dataset)
        report = ReconciliationPipeline().run(data, RunMetadata(seed=42, difficulty="adversarial"))

        subjects = {item.subject_id for item in _missing(report.exceptions)}
        spoken = {
            item.subject_id for item in _missing(report.exceptions) if "claimed_by" in item.evidence
        }

        assert spoken <= subjects
        assert spoken


class TestTheSameCreditIsNamedEveryRun:
    def test_two_runs_of_one_seed_name_the_same_credit(self) -> None:
        """A message naming a different credit on a rerun is a message
        nobody can check against their own files."""
        config = GenerationConfig(seed=7, difficulty=Difficulty.ADVERSARIAL, order_count=ORDERS)
        data = to_recon_input(ChaosEngine(config).generate())

        named = [
            {
                item.subject_id: item.evidence.get("claimed_by")
                for item in _missing(
                    ReconciliationPipeline()
                    .run(data, RunMetadata(seed=7, difficulty="adversarial"))
                    .exceptions
                )
            }
            for _ in range(2)
        ]

        assert named[0] == named[1]
