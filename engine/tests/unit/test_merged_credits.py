"""One bank credit, several settlements.

The case that makes matching a search rather than a lookup, and the case
where being wrong is cheapest to hide: a merged credit matched to one of its
members looks like an ordinary resolved credit, and the settlement it left
behind looks like an ordinary missing payout. Two plausible-looking rows,
one real error.

What is tested here is mostly the refusing. A subset-sum that finds the right
answer is worth little if it also finds a wrong one whenever the arithmetic
allows, so the assertions below spend more effort on the combinations the
strategy must decline than on the one it must find.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.enums import EntityType, MatchStrategy, PaymentMethod
from milan.domain.money import Paise, from_rupees
from milan.domain.rates import RateCard, compute_deductions
from milan.domain.records import BankCredit, SettlementRow
from milan.recon.batches import BatchGroup, rebuild_batches
from milan.recon.matching.base import Attempt, Verdict
from milan.recon.matching.cascade import Cascade
from milan.recon.matching.subset import SubsetSumStrategy
from milan.recon.waterfall import provable, prove

ALL_TIERS = pytest.mark.parametrize("difficulty", list(Difficulty))


def row(entity_id: str, rupees: str, settlement: str, day: int, utr: str) -> SettlementRow:
    gross = from_rupees(rupees)
    deductions = compute_deductions(gross, PaymentMethod.UPI, None, RateCard())
    return SettlementRow(
        entity_id=entity_id,
        type=EntityType.PAYMENT,
        debit=Paise(0),
        credit=deductions.net,
        amount=gross,
        fee=deductions.fee,
        tax=deductions.tax,
        created_at=datetime(2026, 7, 1, 12, 0),
        settled_at=datetime(2026, 7, day, 11, 0),
        settlement_id=settlement,
        settlement_utr=utr,
        payment_id=entity_id,
        method=PaymentMethod.UPI,
    )


def bank_credit(amount: Paise, day: int = 8, utr: str | None = None) -> BankCredit:
    return BankCredit(
        credit_id="bank_1",
        amount=amount,
        value_date=date(2026, 7, day),
        narration=f"NEFT-{utr}-RAZORPAY" if utr else "NEFT INWARD RAZORPAY SOFTWARE",
        utr=utr,
    )


def batches_of(*rows: SettlementRow) -> tuple:
    return rebuild_batches(rows)


class TestSubsetSum:
    def test_it_finds_the_pair_that_adds_up(self) -> None:
        batches = batches_of(
            row("pay_1", "10000", "setl_a", 7, "UTRAAAAAAAAAA"),
            row("pay_2", "25000", "setl_b", 8, "UTRBBBBBBBBBB"),
        )
        total = Paise(sum(batch.expected_net for batch in batches))
        result = SubsetSumStrategy().attempt(bank_credit(total), batches)

        assert result.verdict is Verdict.MATCHED
        assert set(result.settlement_ids) == {"setl_a", "setl_b"}

    def test_it_refuses_when_a_single_settlement_also_fits(self) -> None:
        """A lone batch of the right size is a competing explanation.

        Not a weaker one to be overruled by the pair - a competing one. Two
        answers means no answer, and preferring the combination because it is
        the thing this rung knows how to find would be the search choosing
        its own conclusion.
        """
        first = row("pay_1", "10000", "setl_a", 7, "UTRAAAAAAAAAA")
        second = row("pay_2", "25000", "setl_b", 8, "UTRBBBBBBBBBB")
        pair_total = Paise(sum(batch.expected_net for batch in batches_of(first, second)))
        decoy = SettlementRow(
            **{
                **row("pay_3", "1", "setl_c", 8, "UTRCCCCCCCCCC").model_dump(),
                "amount": pair_total,
                "credit": pair_total,
                "fee": Paise(0),
                "tax": Paise(0),
            }
        )

        result = SubsetSumStrategy().attempt(
            bank_credit(pair_total), batches_of(first, second, decoy)
        )
        assert result.verdict is Verdict.AMBIGUOUS
        assert "setl_c" in result.candidates

    def test_it_refuses_when_two_combinations_add_up(self) -> None:
        """Identical amounts make identical sums. Nothing distinguishes them."""
        batches = batches_of(
            row("pay_1", "10000", "setl_a", 7, "UTRAAAAAAAAAA"),
            row("pay_2", "10000", "setl_b", 8, "UTRBBBBBBBBBB"),
            row("pay_3", "10000", "setl_c", 8, "UTRCCCCCCCCCC"),
        )
        total = Paise(batches[0].expected_net + batches[1].expected_net)
        result = SubsetSumStrategy().attempt(bank_credit(total), batches)
        assert result.verdict is Verdict.AMBIGUOUS

    def test_it_ignores_settlements_outside_the_merge_window(self) -> None:
        """Two payouts a fortnight apart did not leave in the same transfer.

        Without the window every rung-three answer would be arithmetic rather
        than evidence: given enough candidates, some combination hits any
        target.
        """
        batches = batches_of(
            row("pay_1", "10000", "setl_a", 1, "UTRAAAAAAAAAA"),
            row("pay_2", "25000", "setl_b", 20, "UTRBBBBBBBBBB"),
        )
        total = Paise(sum(batch.expected_net for batch in batches))
        result = SubsetSumStrategy().attempt(bank_credit(total, day=20), batches)
        assert result.verdict is Verdict.NO_CANDIDATE

    def test_a_found_pair_proves_to_zero(self) -> None:
        """Matching and proving must agree, or the match is worthless."""
        batches = batches_of(
            row("pay_1", "10000", "setl_a", 7, "UTRAAAAAAAAAA"),
            row("pay_2", "25000", "setl_b", 8, "UTRBBBBBBBBBB"),
        )
        group = BatchGroup.of(*batches)
        credit = bank_credit(group.expected_net)
        result = prove(credit, group, SubsetSumStrategy().name, 0.75, RateCard())

        assert not isinstance(result, type(None))
        assert result.balances  # type: ignore[union-attr]
        assert len(result.settlement_ids) == 2  # type: ignore[union-attr]


class TestProvingOverrulesMatching:
    def test_a_reference_match_that_cannot_be_proved_falls_through(self) -> None:
        """The trap a merged credit sets for the join key.

        The credit carries one member's UTR, so rung one matches it and is
        wrong: the amount covers both settlements. Without the veto the run
        ends there with a confident wrong answer and a reference number
        attached. With it, the claim is withdrawn and rung three finds the
        pair.
        """
        first = row("pay_1", "10000", "setl_a", 7, "UTRAAAAAAAAAA")
        second = row("pay_2", "25000", "setl_b", 8, "UTRBBBBBBBBBB")
        batches = batches_of(first, second)
        total = Paise(sum(batch.expected_net for batch in batches))
        credit = bank_credit(total, utr="UTRAAAAAAAAAA")

        def verify(candidate: BankCredit, group: BatchGroup) -> bool:
            return provable(candidate, group, RateCard())

        without_veto = Cascade().run((credit,), batches)[credit.credit_id]
        with_veto = Cascade().with_verifier(verify).run((credit,), batches)[credit.credit_id]

        assert without_veto.settlement_ids == ("setl_a",)
        assert set(with_veto.settlement_ids) == {"setl_a", "setl_b"}


class TestTheGeneratorProducesThem:
    @ALL_TIERS
    def test_merged_credits_equal_the_sum_of_their_settlements(
        self, difficulty: Difficulty
    ) -> None:
        """The answer key has to be arithmetic, not an assertion."""
        data = ChaosEngine(
            GenerationConfig(seed=42, difficulty=difficulty, order_count=400)
        ).generate()
        settlements = {s.settlement_id: s for s in data.settlements}
        credits = {c.credit_id: c for c in data.bank_credits}

        for truth in data.answer_key.credits:
            if not truth.is_merged:
                continue
            expected = sum(settlements[sid].amount for sid in truth.settlement_ids)
            assert credits[truth.credit_id].amount == expected

    def test_the_harder_tiers_actually_merge(self) -> None:
        """A knob that quietly does nothing is worse than no knob."""
        for difficulty in (Difficulty.REALISTIC, Difficulty.MESSY, Difficulty.ADVERSARIAL):
            data = ChaosEngine(
                GenerationConfig(seed=42, difficulty=difficulty, order_count=400)
            ).generate()
            assert data.answer_key.merged_count > 0, difficulty

    def test_the_clean_tier_does_not(self) -> None:
        """CLEAN stays the control case: one credit, one settlement, no search."""
        data = ChaosEngine(
            GenerationConfig(seed=42, difficulty=Difficulty.CLEAN, order_count=400)
        ).generate()
        assert data.answer_key.merged_count == 0

    @ALL_TIERS
    def test_several_settlements_land_on_the_same_day(self, difficulty: Difficulty) -> None:
        """Without this, a batch total is a unique fingerprint and rung two
        cannot be wrong - which makes its match rate meaningless."""
        data = ChaosEngine(
            GenerationConfig(seed=42, difficulty=difficulty, order_count=400)
        ).generate()
        per_day: dict[date, int] = {}
        for settlement in data.settlements:
            day = settlement.settled_at.date()
            per_day[day] = per_day.get(day, 0) + 1
        assert max(per_day.values()) > 1


class TestTheAnchoredSearch:
    """A withdrawn claim narrows the search that follows it.

    When rung one recognises a reference and the proof then comes up short,
    the settlement it named is not a dead end - it is the one part of the
    answer the bank stated outright. Carrying it forward turns "find any
    combination that adds up" into "find the combination containing this
    one", which is a smaller question and a much less coincidental one.

    Constructed rather than drawn from a tier, because the generator does not
    currently produce two disjoint groups with equal sums *and* a surviving
    reference on one of them. That makes this the only place the behaviour is
    exercised, which is exactly why it is written down.
    """

    def _four_settlements(self) -> tuple:
        # A + B == C + D, and the two pairs share no member.
        return batches_of(
            row("pay_a", "10000", "setl_a", 7, "UTRAAAAAAAAAA"),
            row("pay_b", "25000", "setl_b", 8, "UTRBBBBBBBBBB"),
            row("pay_c", "15000", "setl_c", 8, "UTRCCCCCCCCCC"),
            row("pay_d", "20000", "setl_d", 8, "UTRDDDDDDDDDD"),
        )

    def test_without_an_anchor_the_two_pairs_are_indistinguishable(self) -> None:
        """The refusal this rung is supposed to make."""
        batches = self._four_settlements()
        by_id = {b.settlement_id: b for b in batches}
        total = Paise(by_id["setl_a"].expected_net + by_id["setl_b"].expected_net)

        result = SubsetSumStrategy().attempt(bank_credit(total), batches)
        assert result.verdict is Verdict.AMBIGUOUS

    def test_a_withdrawn_reference_settles_it(self) -> None:
        """Same data, same rung. The bank named one member, so only
        combinations containing that member are answers."""
        batches = self._four_settlements()
        by_id = {b.settlement_id: b for b in batches}
        total = Paise(by_id["setl_a"].expected_net + by_id["setl_b"].expected_net)
        withdrawn = Attempt(
            strategy=MatchStrategy.EXACT_UTR,
            verdict=Verdict.MATCHED,
            settlement_ids=("setl_a",),
        ).rejected("did not reconstruct")

        result = SubsetSumStrategy().attempt(bank_credit(total), batches, withdrawn)

        assert result.verdict is Verdict.MATCHED
        assert set(result.settlement_ids) == {"setl_a", "setl_b"}

    def test_the_anchor_raises_confidence_because_it_is_not_arithmetic(self) -> None:
        """A named member is a different kind of evidence from a sum."""
        batches = batches_of(
            row("pay_a", "10000", "setl_a", 7, "UTRAAAAAAAAAA"),
            row("pay_b", "25000", "setl_b", 8, "UTRBBBBBBBBBB"),
        )
        total = Paise(sum(b.expected_net for b in batches))
        withdrawn = Attempt(
            strategy=MatchStrategy.EXACT_UTR,
            verdict=Verdict.MATCHED,
            settlement_ids=("setl_a",),
        ).rejected("did not reconstruct")

        plain = SubsetSumStrategy().attempt(bank_credit(total), batches)
        anchored = SubsetSumStrategy().attempt(bank_credit(total), batches, withdrawn)
        assert anchored.confidence > plain.confidence

    def test_an_anchor_naming_a_claimed_settlement_is_ignored(self) -> None:
        """The anchor is intersected with what is still available.

        A settlement claimed by another credit in an earlier rung is gone
        from the candidate pool, and insisting the answer contain it would
        make the search unsatisfiable rather than merely harder.
        """
        batches = batches_of(
            row("pay_a", "10000", "setl_a", 7, "UTRAAAAAAAAAA"),
            row("pay_b", "25000", "setl_b", 8, "UTRBBBBBBBBBB"),
        )
        total = Paise(sum(b.expected_net for b in batches))
        stale = Attempt(
            strategy=MatchStrategy.EXACT_UTR,
            verdict=Verdict.MATCHED,
            settlement_ids=("setl_gone",),
        ).rejected("did not reconstruct")

        result = SubsetSumStrategy().attempt(bank_credit(total), batches, stale)
        assert result.verdict is Verdict.MATCHED
        assert set(result.settlement_ids) == {"setl_a", "setl_b"}
