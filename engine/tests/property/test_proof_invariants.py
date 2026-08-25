"""Invariants of the proof, and of the search that feeds it.

The existing property tests cover money arithmetic and batch arithmetic - the
layers below the interesting part. Day six pairs the waterfall with property
tests for a reason: the waterfall is where an off-by-one in an allowance stops
being a rounding question and becomes "this credit was declared proved".

Three things are asserted here that no example-based test can reach.

**A returned proof always balances.** Not usually, not within a tolerance -
`prove` either accounts for every paisa or returns an `UnprovenCredit`. That
is the definition of the output, so it has to hold for inputs nobody chose.

**The veto agrees with the proof.** `provable` is the cheap form the cascade
consults before accepting a rung's answer. If the two can ever disagree, a
claim is withdrawn on grounds it would have survived, or kept on grounds it
would have failed - and either way the cascade is deciding by a rule that is
not the one it reports.

**The combination search never claims a combination that does not add up.**
A subset-sum solver returning a set that sums to something else is the worst
failure available to this system: confident, specific, citing real settlement
ids, and wrong.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from milan.domain.enums import EntityType, MatchStrategy, PaymentMethod
from milan.domain.money import Paise
from milan.domain.rates import RateCard, compute_deductions
from milan.domain.records import BankCredit, SettlementRow
from milan.recon.batches import BatchGroup, rebuild_batches
from milan.recon.matching.base import Verdict
from milan.recon.matching.fuzzy import SIMILARITY_FLOOR, normalise, similarity
from milan.recon.matching.subset import SubsetSumStrategy
from milan.recon.waterfall import UnprovenCredit, provable, prove

SETTLED_ON = datetime(2026, 7, 3, 11, 0)
VALUE_DATE = date(2026, 7, 3)

amounts = st.integers(min_value=100_00, max_value=5_00_000_00).map(Paise)
references = st.text(alphabet="ABCDEFGHJKLMNPQRSTUVWXYZ23456789", min_size=12, max_size=14)


def _payment_row(entity_id: str, amount: Paise, settlement: str, rates: RateCard) -> SettlementRow:
    deductions = compute_deductions(amount, PaymentMethod.UPI, None, rates)
    return SettlementRow(
        entity_id=entity_id,
        type=EntityType.PAYMENT,
        debit=Paise(0),
        credit=deductions.net,
        amount=amount,
        fee=deductions.fee,
        tax=deductions.tax,
        created_at=SETTLED_ON - timedelta(days=2),
        settled_at=SETTLED_ON,
        settlement_id=settlement,
        settlement_utr=f"UTR{settlement}",
        payment_id=entity_id,
        method=PaymentMethod.UPI,
    )


def _refund_row(entity_id: str, amount: Paise, settlement: str) -> SettlementRow:
    """A refund recovered from this batch, at no processing charge."""
    return SettlementRow(
        entity_id=entity_id,
        type=EntityType.REFUND,
        debit=amount,
        credit=Paise(0),
        amount=amount,
        fee=Paise(0),
        tax=Paise(0),
        created_at=SETTLED_ON - timedelta(days=3),
        settled_at=SETTLED_ON,
        settlement_id=settlement,
        settlement_utr=f"UTR{settlement}",
        payment_id=entity_id,
    )


def _group(rows: tuple[SettlementRow, ...]) -> BatchGroup:
    return BatchGroup.of(*rebuild_batches(rows))


def _credit(amount: Paise, narration: str = "NEFT INWARD") -> BankCredit:
    return BankCredit(
        credit_id="bank_1",
        amount=amount,
        value_date=VALUE_DATE,
        narration=narration,
        utr=None,
    )


class TestAProofEitherHoldsOrIsNotReturned:
    @given(
        values=st.lists(amounts, min_size=1, max_size=15),
        withholding=st.booleans(),
        offset=st.integers(min_value=-500, max_value=500),
    )
    @settings(max_examples=120, suppress_health_check=[HealthCheck.too_slow])
    def test_a_returned_proof_accounts_for_every_paisa(
        self, values: list[Paise], withholding: bool, offset: int
    ) -> None:
        """Whatever arrives, `prove` returns a proof that balances or no proof.

        `offset` deliberately walks the credit across the allowance boundary
        in both directions, so the interesting inputs are the ones a
        hand-written test would not have picked: exactly on the edge, and one
        paisa past it.
        """
        rates = RateCard(tds_applies=withholding)
        rows = tuple(_payment_row(f"pay_{i}", v, "setl_a", rates) for i, v in enumerate(values))
        group = _group(rows)
        credit = _credit(Paise(group.expected_net + offset))

        result = prove(credit, group, MatchStrategy.EXACT_UTR, 1.0, rates)

        if isinstance(result, UnprovenCredit):
            assert abs(result.residual) > group.rounding_allowance
        else:
            assert result.balances
            assert result.residual == 0
            assert sum(line.amount for line in result.lines) == credit.amount

    @given(
        values=st.lists(amounts, min_size=1, max_size=12),
        offset=st.integers(min_value=-500, max_value=500),
    )
    @settings(max_examples=120, suppress_health_check=[HealthCheck.too_slow])
    def test_the_veto_and_the_proof_never_disagree(self, values: list[Paise], offset: int) -> None:
        """The cascade withdraws a claim on exactly the grounds it would
        later have failed on, rather than on a looser rule that happens to
        agree most of the time."""
        rates = RateCard()
        rows = tuple(_payment_row(f"pay_{i}", v, "setl_a", rates) for i, v in enumerate(values))
        group = _group(rows)
        credit = _credit(Paise(group.expected_net + offset))

        result = prove(credit, group, MatchStrategy.EXACT_UTR, 1.0, rates)
        assert provable(credit, group, rates) is not isinstance(result, UnprovenCredit)

    @given(values=st.lists(amounts, min_size=1, max_size=12))
    @settings(max_examples=60)
    def test_drift_never_exceeds_the_allowance_that_permitted_it(self, values: list[Paise]) -> None:
        """Drift is the paise a proof closed on the allowance rather than on
        the rows. A proof reporting more drift than its allowance would mean
        the total we publish is larger than the tolerance that justified it."""
        rates = RateCard()
        rows = tuple(_payment_row(f"pay_{i}", v, "setl_a", rates) for i, v in enumerate(values))
        group = _group(rows)
        result = prove(
            _credit(Paise(group.expected_net + 1)), group, MatchStrategy.EXACT_UTR, 1.0, rates
        )

        if not isinstance(result, UnprovenCredit):
            assert abs(result.drift) <= group.rounding_allowance

    @given(
        payments=st.lists(amounts, min_size=1, max_size=10),
        refunds=st.lists(amounts, min_size=1, max_size=4),
    )
    @settings(max_examples=60)
    def test_every_line_of_a_proof_points_at_a_source_row(
        self, payments: list[Paise], refunds: list[Paise]
    ) -> None:
        """A line with no refs is an assertion, not evidence. The exception
        is the drift line, which is about the rows collectively rather than
        about any one of them."""
        rates = RateCard()
        rows = tuple(
            [_payment_row(f"pay_{i}", v, "setl_a", rates) for i, v in enumerate(payments)]
            + [_refund_row(f"rfnd_{i}", v, "setl_a") for i, v in enumerate(refunds)]
        )
        group = _group(rows)
        result = prove(_credit(group.expected_net), group, MatchStrategy.EXACT_UTR, 1.0, rates)
        assume(not isinstance(result, UnprovenCredit))
        assert not isinstance(result, UnprovenCredit)

        for line in result.lines:
            assert line.refs or "rounding" in line.label.lower()


class TestTheCombinationSearchNeverLies:
    @given(
        totals=st.lists(amounts, min_size=2, max_size=5, unique=True),
        picked=st.integers(min_value=0, max_value=4),
        offset=st.integers(min_value=-20_00, max_value=20_00),
    )
    @settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
    def test_a_claimed_combination_always_sums_to_the_credit(
        self, totals: list[Paise], picked: int, offset: int
    ) -> None:
        """The invariant that makes the rung safe to run at all.

        The credit is built from *some* subset and then moved off it by up to
        twenty rupees. The offset is the whole point: a target that is exactly
        a subset sum cannot tell a correct solver from a sloppy one, because
        both find the same set. Only a target that sits *near* a combination
        without being it separates "this adds up" from "this is close enough".
        Verified by mutation - widening the solver's tolerance leaves the
        exact-target version of this test green and fails this one.
        """
        rates = RateCard()
        rows = tuple(
            _payment_row(f"pay_{i}", value, f"setl_{i}", rates) for i, value in enumerate(totals)
        )
        batches = rebuild_batches(rows)
        target = Paise(sum(b.expected_net for b in batches[: picked % (len(batches) + 1)]) + offset)
        if target <= 0:
            return

        attempt = SubsetSumStrategy().attempt(_credit(target), batches)
        if attempt.verdict is not Verdict.MATCHED:
            # Refusing is always a permitted answer. What is not permitted is
            # answering with a set that does not add up, so there is nothing
            # to check here - and asserting it via `assume` would filter out
            # every perturbed target and leave the test checking only the
            # exact ones, which is the version that missed the mutation.
            return

        chosen = BatchGroup.of(*(b for b in batches if b.settlement_id in attempt.settlement_ids))
        assert abs(chosen.expected_net - target) <= chosen.rounding_allowance

    @given(totals=st.lists(amounts, min_size=2, max_size=5, unique=True))
    @settings(max_examples=60)
    def test_an_amount_no_combination_reaches_is_refused(self, totals: list[Paise]) -> None:
        """Half a rupee below the smallest possible sum. Nothing can reach it,
        and the honest output is to say so rather than return the nearest."""
        rates = RateCard()
        rows = tuple(
            _payment_row(f"pay_{i}", value, f"setl_{i}", rates) for i, value in enumerate(totals)
        )
        batches = rebuild_batches(rows)
        floor = min(b.expected_net for b in batches)
        attempt = SubsetSumStrategy().attempt(_credit(Paise(floor // 2)), batches)

        assert attempt.verdict is not Verdict.MATCHED


class TestSimilarityBehavesLikeAMeasure:
    @given(reference=references)
    def test_a_reference_is_perfectly_similar_to_itself(self, reference: str) -> None:
        assert similarity(reference, reference) == 1.0

    @given(reference=references, prefix=st.text(alphabet="ABC ", max_size=20))
    def test_similarity_is_always_a_proportion(self, reference: str, prefix: str) -> None:
        """Confidence is derived from this number, and a confidence outside
        zero to one is rejected by the model rather than merely looking odd."""
        assert 0.0 <= similarity(reference, prefix + reference) <= 1.0

    @given(reference=references)
    def test_an_intact_reference_survives_the_bank_wrapping_it(self, reference: str) -> None:
        """The rung exists for damaged references. If an undamaged one buried
        in bank boilerplate cannot clear the floor, the floor is measuring the
        boilerplate."""
        narration = f"NEFT CR-RAZORPAY SOFTWARE PVT LTD-{reference}-SETTLEMENT"
        assert similarity(reference, narration) >= SIMILARITY_FLOOR

    @given(narration=st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -/", max_size=60))
    def test_normalising_only_ever_removes_characters(self, narration: str) -> None:
        """Normalisation must not invent characters a reference could match
        against, or the rung would be scoring against text the bank never
        sent."""
        assert len(normalise(narration)) <= len(narration)
        assert normalise(narration).isalnum() or normalise(narration) == ""
