"""The rung that matches on a total being wrong.

This is the most permissive thing in the cascade and therefore the most
dangerous. Every other rung answers on exactness of some kind; this one
answers on a credit being *near* a settlement, which means it has far more
opportunity to be confidently wrong than any rung above it.

Three things keep it honest and all three are tested here.

**Its band is derived, not tuned.** The widest a payout can legitimately be
reduced is read off the rate card - the worst card rate, the GST on it, and
withholding if the merchant is subject to it. A band fitted to the generator
would be fitting to the defects somebody chose to write, which is circular in
a project whose accuracy figures are already conditional on that catalogue.

**It refuses ties.** A wide band collides more often than a narrow one, so it
has to be less willing to pick.

**Its claims do not survive proving, by design.** It matches on the total
being wrong, so the verifier withdraws every claim it makes and the credit
becomes a named exception rather than a match. That is the whole point: it
converts "no settlement behind it" into "this is settlement A and it is short
by exactly refund R", without ever adding to the match rate.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from milan.domain.enums import EntityType, MatchStrategy, PaymentMethod
from milan.domain.money import Paise, from_rupees
from milan.domain.rates import RateCard, compute_deductions
from milan.domain.records import BankCredit, SettlementRow
from milan.recon.batches import GatewayBatch, rebuild_batches
from milan.recon.matching.base import Verdict
from milan.recon.matching.shortfall import ShortfallStrategy, widest_deduction

SETTLED_ON = date(2026, 7, 8)


def row(entity_id: str, rupees: str, settlement: str, when: date = SETTLED_ON) -> SettlementRow:
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
        created_at=datetime(2026, 7, 6, 12, 0),
        settled_at=datetime(when.year, when.month, when.day, 11, 0),
        settlement_id=settlement,
        settlement_utr=f"UTR{settlement[-8:]:>08}",
        payment_id=entity_id,
        method=PaymentMethod.UPI,
    )


def batch(settlement: str, rupees: str = "100000", when: date = SETTLED_ON) -> GatewayBatch:
    return rebuild_batches((row(f"pay_{settlement}", rupees, settlement, when),))[0]


def credit(amount: Paise, when: date = SETTLED_ON) -> BankCredit:
    return BankCredit(
        credit_id="bank_1",
        amount=amount,
        value_date=when,
        narration="NEFT INWARD RAZORPAY SOFTWARE PVT LTD",
        utr=None,
    )


class TestTheBandIsDerivedRatherThanChosen:
    def test_it_comes_from_the_rate_card(self) -> None:
        """Worst card rate, plus GST on that fee. 3% * 1.18 = 3.54%."""
        band = widest_deduction(RateCard())
        assert band == Decimal("0.03") * Decimal("1.18")

    def test_withholding_widens_it_by_exactly_the_tds_rate(self) -> None:
        """Section 194-O takes 1% of gross before the payout leaves, so a
        merchant subject to it can legitimately be short by that much more."""
        plain = widest_deduction(RateCard())
        withheld = widest_deduction(RateCard(tds_applies=True))
        assert withheld - plain == RateCard().tds

    def test_a_different_contract_moves_the_band(self) -> None:
        """The band is a function of the merchant's rates, not a constant. A
        merchant on cheaper rates gets a tighter band, and should."""
        cheap = widest_deduction(RateCard(international_card=Decimal("0.015")))
        assert cheap < widest_deduction(RateCard())


class TestWhatItClaims:
    strategy = ShortfallStrategy()

    def test_a_credit_short_by_a_plausible_fee_is_claimed(self) -> None:
        found = batch("setl_a")
        short = Paise(found.expected_net - from_rupees("500"))  # 0.5% of a lakh
        attempt = self.strategy.attempt(credit(short), (found,))

        assert attempt.verdict is Verdict.MATCHED
        assert attempt.settlement_ids == ("setl_a",)
        assert attempt.strategy is MatchStrategy.SHORTFALL

    def test_it_reports_the_lowest_confidence_in_the_cascade(self) -> None:
        """It identifies a payout without explaining it. The queue has to be
        able to tell that from a reference that proves identity."""
        found = batch("setl_a")
        short = Paise(found.expected_net - from_rupees("500"))
        attempt = self.strategy.attempt(credit(short), (found,))
        assert 0.0 < attempt.confidence <= 0.5

    def test_the_note_says_what_the_gap_is(self) -> None:
        found = batch("setl_a")
        short = Paise(found.expected_net - from_rupees("500"))
        attempt = self.strategy.attempt(credit(short), (found,))
        assert "short of setl_a" in attempt.note


class TestWhatItRefuses:
    strategy = ShortfallStrategy()

    def test_a_credit_larger_than_the_payout_is_never_a_near_miss(self) -> None:
        """Nothing in the fee stack pays a merchant more than the payout.
        Accepting an overage would let this rung explain money that arrived
        from somewhere else entirely."""
        found = batch("setl_a")
        over = Paise(found.expected_net + from_rupees("500"))
        assert self.strategy.attempt(credit(over), (found,)).verdict is Verdict.NO_CANDIDATE

    def test_a_gap_wider_than_any_fee_stack_is_refused(self) -> None:
        """Ten percent of a payout is not a fee. It may well be a refund, but
        this rung has no way to tell that from a different payout entirely."""
        found = batch("setl_a")
        short = Paise(found.expected_net - from_rupees("10000"))
        assert self.strategy.attempt(credit(short), (found,)).verdict is Verdict.NO_CANDIDATE

    def test_an_exact_match_is_left_to_the_rung_that_can_prove_it(self) -> None:
        """A gap inside the rounding allowance is not a shortfall, and it
        belongs to `AmountDateStrategy` where it will be proved rather than
        merely claimed."""
        found = batch("setl_a")
        attempt = self.strategy.attempt(credit(found.expected_net), (found,))
        assert attempt.verdict is Verdict.NO_CANDIDATE

    def test_two_payouts_it_could_be_short_of_are_refused(self) -> None:
        """The risk a wide band creates. Two candidates is not a near miss,
        it is a coin flip."""
        first = batch("setl_a")
        second = batch("setl_b", rupees="100200")
        short = Paise(first.expected_net - from_rupees("400"))
        attempt = self.strategy.attempt(credit(short), (first, second))

        assert attempt.verdict is Verdict.AMBIGUOUS
        assert set(attempt.candidates) == {"setl_a", "setl_b"}
        assert not attempt.settlement_ids

    def test_the_right_amount_on_the_wrong_week_is_refused(self) -> None:
        found = batch("setl_a")
        short = Paise(found.expected_net - from_rupees("500"))
        far = date(2026, 7, 20)
        assert self.strategy.attempt(credit(short, far), (found,)).verdict is Verdict.NO_CANDIDATE

    def test_no_candidates_at_all_is_a_refusal_not_a_crash(self) -> None:
        found = batch("setl_a")
        short = Paise(found.expected_net - from_rupees("500"))
        attempt = self.strategy.attempt(credit(short), ())
        assert attempt.verdict is Verdict.NO_CANDIDATE
        assert "0 settlements" in attempt.note


class TestItRespectsTheContract:
    @pytest.mark.parametrize("withholding", [False, True])
    def test_a_withheld_merchants_band_admits_a_wider_gap(self, withholding: bool) -> None:
        """The same credit is a near miss under one contract and not under
        another, which is the band being a function of the rate card rather
        than a number somebody liked."""
        rates = RateCard(tds_applies=withholding)
        found = batch("setl_a")
        # 4% short: inside 4.54% with withholding, outside 3.54% without.
        short = Paise(found.expected_net - Paise(int(found.expected_net * 0.04)))
        attempt = ShortfallStrategy(rates).attempt(credit(short), (found,))

        expected = Verdict.MATCHED if withholding else Verdict.NO_CANDIDATE
        assert attempt.verdict is expected
