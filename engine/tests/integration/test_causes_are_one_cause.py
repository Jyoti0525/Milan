"""Is a cause actually one cause?

The unit tests check that induction refuses to group things it should not.
They cannot check the thing that matters most, because they build their own
queues: whether a cause induced from a real run holds together.

This can, because the answer key knows which defect was injected against
each record. A cause claims its members share a reason. If two of them came
from different injected defects, the claim is false - and a false cause is
worse than no cause, because it reads as a finding and sends somebody to
argue a case the evidence does not support.

This measurement is why three rules in `milan.recon.causes` look the way
they do. Run against the first version of that module it returned 80.7%,
and every failure pointed at a rule that grouped on a coincidence: two
missing payouts sharing a date out of twenty-one, two unreported captures
sharing another, and a bucket that grouped deposits on the *absence* of
evidence. Rewriting those three to test something the arithmetic supports
took purity to 100% and - the part worth noticing - took coverage up as
well, from 33% to 72%. The honest rules were not the conservative ones.

Writing this then turned up something the tests were not looking for, which
is recorded in `origin` below: three quarters of the payouts the engine
reports as missing are not missing, and the deposit for them is sitting in
the same queue. `_the_same_money_counted_twice` came out of that. Coverage
now reads 69.5% rather than 72% because naming the duplication pulls those
payouts out of a larger cluster and sometimes leaves a single one behind -
which is a truer answer at a slightly worse number, and that trade is the
right way round.
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

TIERS = (Difficulty.REALISTIC, Difficulty.MESSY, Difficulty.ADVERSARIAL)
SEEDS = (1, 2, 3, 42)
ORDERS = 600

FLOOR = 0.95
"""The purity this must not drop below.

Measured at 100% over thirty-six 600-order months and 98.2% over thirty-six
2,000-order months. The floor sits below both on purpose: the shortfall
between them is not a defect but a genuine ambiguity - a refund recovery and
a 28% GST deduction that fit the same shortfall to the paisa - and it gets
commoner as the refund pool grows. Pinning this at 1.0 would make an honest
"the evidence does not choose" into a test failure.
"""


def origin(dataset: Dataset) -> dict[str, str]:
    """What each exception subject actually was, per the answer key.

    A credit can carry two defects at once - its reference destroyed *and* a
    payout variance - and the generator records that as `UTR_CORRUPTED+FEE`.
    Only the second half is a reason the payout was short; the first decides
    how the credit was matched. Comparing whole labels counted those as
    different causes and understated purity by twelve points, which is worth
    recording because the first reading of that measurement was wrong.

    Settlements are labelled by mechanism rather than by injection, and that
    is a deliberate limit on what this measures. Writing it the other way
    round is what turned up the finding below, so it is worth stating.

    Of eighty payouts raised as missing across these months, twenty were
    injected as missing and sixty were not - for those sixty the deposit is
    on the statement and this queue holds it, matched to the right
    settlement and short by an amount the report cannot account for. The
    engine cannot tell the two apart, because the only evidence separating
    them is the answer key, which reconciliation is not allowed to read.
    Grading a cause on a distinction the evidence does not contain would be
    grading it on ground truth. `_the_same_money_counted_twice` is what came
    out of the finding instead.
    """
    key = dataset.answer_key
    found: dict[str, str] = {}
    for truth in key.credits:
        label = truth.defect or ("ORPHAN_CREDIT" if not truth.matchable else "CLEAN")
        found[truth.credit_id] = label.split("+")[-1]
    for row in dataset.settlement_rows:
        if row.settlement_id:
            found[row.settlement_id] = "SETTLEMENT_UNMATCHED"
    for payment_id in key.unreported_payment_ids:
        found[payment_id] = "UNREPORTED_PAYMENT"
    return found


def run(tier: Difficulty, seed: int) -> tuple[Dataset, object]:
    dataset = ChaosEngine(
        GenerationConfig(seed=seed, difficulty=tier, order_count=ORDERS)
    ).generate()
    report = ReconciliationPipeline().run(
        to_recon_input(dataset), RunMetadata(seed=seed, difficulty=tier.value)
    )
    return dataset, report


@pytest.fixture(scope="module")
def measured() -> tuple[Counter[str], list[str], list[float], list[tuple[int, int]]]:
    verdicts: Counter[str] = Counter()
    impure: list[str] = []
    coverage: list[float] = []
    shapes: list[tuple[int, int]] = []

    for tier in TIERS:
        for seed in SEEDS:
            dataset, report = run(tier, seed)
            truth = origin(dataset)
            found = induce(report.exceptions)  # type: ignore[attr-defined]
            coverage.append(found.share)
            shapes.append((len(report.exceptions), len(found.causes)))  # type: ignore[attr-defined]

            for cause in found.causes:
                reasons = {truth[member] for member in cause.members if member in truth}
                if len(reasons) <= 1:
                    verdicts["one reason"] += 1
                else:
                    verdicts["several"] += 1
                    impure.append(f"{tier.value}/{seed}: {cause.name} -> {sorted(reasons)}")

    return verdicts, impure, coverage, shapes


class TestACauseHoldsTogether:
    def test_a_cause_is_not_two_defects_wearing_one_name(
        self, measured: tuple[Counter[str], list[str], list[float], list[tuple[int, int]]]
    ) -> None:
        verdicts, impure, _, _ = measured
        total = sum(verdicts.values())

        assert total, "no causes were induced at all - the measurement is empty"
        assert verdicts["one reason"] / total >= FLOOR, "\n".join(impure)

    def test_every_subject_in_every_cause_is_one_the_answer_key_knows(
        self, measured: tuple[Counter[str], list[str], list[float], list[tuple[int, int]]]
    ) -> None:
        """Guards the measurement itself.

        If a subject id stops appearing in the answer key - a renamed field,
        a new exception kind - the purity check above would silently start
        comparing empty sets and pass at 100% while measuring nothing.
        """
        for tier in TIERS:
            dataset, report = run(tier, SEEDS[0])
            truth = origin(dataset)

            for cause in induce(report.exceptions).causes:  # type: ignore[attr-defined]
                for member in cause.members:
                    assert member in truth, f"{tier.value}: {member} is in no answer key"


class TestTheQueueActuallyGetsShorter:
    """The point of the whole module. A queue that induces as many causes as
    it had exceptions has reorganised the work rather than reduced it."""

    def test_most_of_the_queue_turns_out_to_be_a_pattern(
        self, measured: tuple[Counter[str], list[str], list[float], list[tuple[int, int]]]
    ) -> None:
        _, _, coverage, _ = measured
        mean = sum(coverage) / len(coverage)

        assert mean >= 0.60, f"coverage fell to {mean:.1%}"

    def test_the_causes_are_far_fewer_than_the_exceptions(
        self, measured: tuple[Counter[str], list[str], list[float], list[tuple[int, int]]]
    ) -> None:
        _, _, _, shapes = measured
        exceptions = sum(count for count, _ in shapes) / len(shapes)
        causes = sum(count for _, count in shapes) / len(shapes)

        assert causes * 3 <= exceptions, f"{exceptions:.1f} exceptions -> {causes:.1f} causes"


class TestInductionChangesNothingItReads:
    def test_inducing_twice_gives_the_same_answer(self) -> None:
        _, report = run(Difficulty.ADVERSARIAL, 42)

        first = induce(report.exceptions)  # type: ignore[attr-defined]
        second = induce(report.exceptions)  # type: ignore[attr-defined]

        assert first == second

    def test_the_order_exceptions_arrive_in_does_not_change_the_causes(self) -> None:
        """Reversed input must give the same causes.

        Not a theoretical worry: the rules iterate dictionaries built from
        the queue, so an ordering dependence would be invisible on generated
        data and appear on a merchant's own file, where the rows are in
        whatever order their bank exported them.
        """
        _, report = run(Difficulty.MESSY, 3)
        forward = induce(report.exceptions)  # type: ignore[attr-defined]
        backward = induce(tuple(reversed(report.exceptions)))  # type: ignore[attr-defined]

        assert {(cause.name, frozenset(cause.members)) for cause in forward.causes} == {
            (cause.name, frozenset(cause.members)) for cause in backward.causes
        }
        assert set(forward.uncaused) == set(backward.uncaused)


class TestTheRateSeamHoldsTogether:
    """The categoriser writes a rate for people; induction reads it back.

    A seam that can rot silently: reword the format and every deduction
    cluster stops forming, with no error - just a coverage figure that
    drifts down and a finding that quietly stops being made.
    """

    def test_a_rate_the_categoriser_wrote_is_a_rate_induction_can_read(self) -> None:
        from milan.recon.causes import _rate

        seen = 0
        for tier in TIERS:
            _, report = run(tier, 42)
            for item in report.exceptions:  # type: ignore[attr-defined]
                written = item.evidence.get("implied_rate")
                if written is None:
                    continue
                seen += 1

                assert _rate(written) is not None, f"{tier.value}: cannot read {written!r}"

        assert seen, "no exception carried a rate - the seam is untested"
