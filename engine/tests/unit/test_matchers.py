"""The first two rungs, tested for the thing they exist to get right.

Both were only ever exercised transitively - through the cascade, the oracle
test and the eval harness ladder - and no test named either of them. That
looked fine on a coverage report until the two uncovered lines were read: the
branch in each where *more than one* settlement fits, and the strategy refuses
rather than picking one.

Those two branches are the project's central claim, and neither had ever
executed. The generator does not produce a duplicated settlement reference and
does not often produce two batches with an identical total on the same day, so
no amount of running the pipeline reaches them. They are constructed here.

A refusal that has never been observed is a refusal nobody should believe.
"""

from __future__ import annotations

from datetime import date, datetime

from milan.domain.enums import EntityType, MatchStrategy, PaymentMethod
from milan.domain.money import Paise, from_rupees
from milan.domain.rates import RateCard, compute_deductions
from milan.domain.records import BankCredit, SettlementRow
from milan.recon.batches import GatewayBatch, rebuild_batches
from milan.recon.matching.base import Verdict
from milan.recon.matching.exact import ExactUtrStrategy
from milan.recon.matching.tolerance import SETTLEMENT_DATE_WINDOW, AmountDateStrategy

SETTLED_ON = date(2026, 7, 8)


def row(entity_id: str, rupees: str, settlement: str, utr: str, when: date) -> SettlementRow:
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
        settlement_utr=utr,
        payment_id=entity_id,
        method=PaymentMethod.UPI,
    )


def batch(
    settlement: str, utr: str, rupees: str = "10000", when: date = SETTLED_ON
) -> GatewayBatch:
    return rebuild_batches((row(f"pay_{settlement}", rupees, settlement, utr, when),))[0]


def credit(
    amount: Paise,
    *,
    utr: str | None = None,
    narration: str = "NEFT INWARD RAZORPAY SOFTWARE PVT LTD",
    when: date = SETTLED_ON,
) -> BankCredit:
    return BankCredit(
        credit_id="bank_1",
        amount=amount,
        value_date=when,
        narration=narration,
        utr=utr,
    )


class TestTheReferenceRung:
    strategy = ExactUtrStrategy()

    def test_it_resolves_on_a_matching_reference(self) -> None:
        found = batch("setl_a", "UTR000000001")
        attempt = self.strategy.attempt(credit(found.expected_net, utr="UTR000000001"), (found,))
        assert attempt.verdict is Verdict.MATCHED
        assert attempt.settlement_ids == ("setl_a",)
        assert attempt.strategy is MatchStrategy.EXACT_UTR

    def test_it_reads_the_reference_out_of_the_narration(self) -> None:
        found = batch("setl_a", "25CSMU6FGK88")
        attempt = self.strategy.attempt(
            credit(found.expected_net, narration="NEFT-25CSMU6FGK88-RAZORPAY"), (found,)
        )
        assert attempt.verdict is Verdict.MATCHED

    def test_no_reference_anywhere_is_a_refusal_not_a_guess(self) -> None:
        """One candidate, and it would obviously be right. The rung still
        declines, because this rung's evidence is the reference and it does
        not have one - the next rung's evidence is the amount."""
        found = batch("setl_a", "UTR000000001")
        attempt = self.strategy.attempt(credit(found.expected_net), (found,))
        assert attempt.verdict is Verdict.NO_CANDIDATE
        assert not attempt.settlement_ids

    def test_a_reference_matching_nothing_is_a_refusal(self) -> None:
        found = batch("setl_a", "UTR000000001")
        attempt = self.strategy.attempt(credit(found.expected_net, utr="UTR999999999"), (found,))
        assert attempt.verdict is Verdict.NO_CANDIDATE

    def test_two_settlements_sharing_a_reference_are_refused(self) -> None:
        """Never executed before this test.

        A duplicated settlement reference means the gateway export is
        malformed, and the generator does not produce one - so running the
        pipeline for a month of data never reaches this branch. Picking the
        first of the two would be silent and wrong, and would look exactly
        like a correct match.
        """
        first = batch("setl_a", "UTR000000001")
        second = batch("setl_b", "UTR000000001", rupees="7500")
        attempt = self.strategy.attempt(
            credit(first.expected_net, utr="UTR000000001"), (first, second)
        )
        assert attempt.verdict is Verdict.AMBIGUOUS
        assert set(attempt.candidates) == {"setl_a", "setl_b"}
        assert not attempt.settlement_ids, "an ambiguous attempt must claim nothing"
        assert "2 settlements" in attempt.note


class TestTheAmountAndDateRung:
    strategy = AmountDateStrategy()

    def test_it_resolves_on_an_exact_total(self) -> None:
        found = batch("setl_a", "UTR000000001")
        attempt = self.strategy.attempt(credit(found.expected_net), (found,))
        assert attempt.verdict is Verdict.MATCHED
        assert attempt.settlement_ids == ("setl_a",)

    def test_it_accepts_a_payout_that_lands_the_next_day(self) -> None:
        """A cut-off miss pushes a payout to the following day, which is
        ordinary rather than suspicious."""
        found = batch("setl_a", "UTR000000001")
        late = SETTLED_ON + SETTLEMENT_DATE_WINDOW
        attempt = self.strategy.attempt(credit(found.expected_net, when=late), (found,))
        assert attempt.verdict is Verdict.MATCHED

    def test_it_refuses_outside_the_window(self) -> None:
        found = batch("setl_a", "UTR000000001")
        far = SETTLED_ON + SETTLEMENT_DATE_WINDOW * 3
        attempt = self.strategy.attempt(credit(found.expected_net, when=far), (found,))
        assert attempt.verdict is Verdict.NO_CANDIDATE

    def test_a_wrong_amount_on_the_right_day_is_a_refusal(self) -> None:
        found = batch("setl_a", "UTR000000001")
        wrong = Paise(found.expected_net - from_rupees("500"))
        attempt = self.strategy.attempt(credit(wrong), (found,))
        assert attempt.verdict is Verdict.NO_CANDIDATE
        assert "none totalling" in attempt.note

    def test_two_settlements_of_the_same_size_that_day_are_refused(self) -> None:
        """The other branch that had never run.

        Batch totals are effectively unique - they are the sum of dozens of
        arbitrary order values - so this is rare in generated data and
        catastrophic when it happens, because the second-best fit being exact
        is precisely when picking wrong is least visible.
        """
        first = batch("setl_a", "UTR000000001")
        second = batch("setl_b", "UTR000000002")
        assert first.expected_net == second.expected_net, "the fixture must be a real tie"

        attempt = self.strategy.attempt(credit(first.expected_net), (first, second))
        assert attempt.verdict is Verdict.AMBIGUOUS
        assert set(attempt.candidates) == {"setl_a", "setl_b"}
        assert not attempt.settlement_ids
        assert "nothing distinguishes them" in attempt.note

    def test_a_tie_across_the_date_window_is_still_a_tie(self) -> None:
        """Two payouts of equal size, one on the day and one the day before.
        Both are inside the window, so both fit, so neither is claimed."""
        first = batch("setl_a", "UTR000000001")
        second = batch("setl_b", "UTR000000002", when=SETTLED_ON - SETTLEMENT_DATE_WINDOW)
        attempt = self.strategy.attempt(credit(first.expected_net), (first, second))
        assert attempt.verdict is Verdict.AMBIGUOUS
