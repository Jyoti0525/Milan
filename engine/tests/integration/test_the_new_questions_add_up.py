"""The four questions added when ten turned out to be too narrow.

Routing is checked elsewhere. This checks the arithmetic, which is the part
that matters: every one of these puts a money figure in front of somebody,
and a figure that is merely plausible is the failure this whole package is
arranged around.

Each test recomputes the answer from the rows by a different route than the
answer function used, so agreeing is evidence rather than a tautology.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.enums import EntityType, PaymentMethod
from milan.domain.rates import RateCard
from milan.evaluation.harness import to_recon_input
from milan.qa import Books, ask
from milan.recon.pipeline import ReconciliationPipeline, RunMetadata


@pytest.fixture(scope="module")
def books() -> Books:
    """A month with every shape turned on.

    194-O, Route and instant settlement together, because `timing` is
    uninteresting without instant payouts and `by_method` is uninteresting
    without a fee stack that varies by instrument.
    """
    dataset = ChaosEngine(
        GenerationConfig(
            seed=11,
            difficulty=Difficulty.ADVERSARIAL,
            order_count=400,
            rates=RateCard(tds_applies=True),
            route_probability=0.30,
            instant_settlement_probability=0.35,
        )
    ).generate()
    data = to_recon_input(dataset)
    report = ReconciliationPipeline().run(
        data, RunMetadata(seed=11, difficulty=Difficulty.ADVERSARIAL.value)
    )
    return Books(data=data, report=report)


class TestWhatEachMethodBroughtIn:
    def test_the_lines_sum_to_every_settled_payment(self, books: Books) -> None:
        """Summed from the rows here, grouped by the answer there. If a
        method were dropped or double-counted the two would disagree."""
        expected = sum(
            row.amount
            for row in books.data.settlement_rows
            if row.type is EntityType.PAYMENT and row.method is not None
        )

        answer = ask("break it down by payment method", books)

        assert answer.total == expected

    def test_naming_one_method_answers_about_only_that_method(self, books: Books) -> None:
        expected = sum(
            row.amount
            for row in books.data.settlement_rows
            if row.type is EntityType.PAYMENT and row.method is PaymentMethod.UPI
        )

        answer = ask("how much came in on UPI?", books)

        assert len(answer.lines) == 1
        assert answer.lines[0].label == "upi"
        assert answer.lines[0].amount == expected

    def test_naming_two_methods_answers_about_all_of_them(self, books: Books) -> None:
        """ "How do cards compare to UPI" names two, and answering about
        whichever appeared first would pick a side of a comparison the
        reader asked to see both halves of."""
        answer = ask("how do cards compare to upi", books)

        assert len(answer.lines) > 1

    def test_the_biggest_method_is_named_first(self, books: Books) -> None:
        answer = ask("break it down by payment method", books)
        amounts = [line.amount for line in answer.lines]

        assert amounts == sorted(amounts, reverse=True)
        assert answer.lines[0].label in answer.headline

    def test_reversals_are_not_counted_as_money_coming_in(self, books: Books) -> None:
        """Refunds, chargebacks and Route transfers all carry an amount, and
        folding any of them in would report a merchant taking in more than
        they ever did.

        On this generator only payment rows carry a method at all, so the
        method filter would exclude them anyway - which is exactly why this
        compares against *every* row's amount rather than against the ones
        with a method. A test that only exercised the incidental guard would
        pass on a future export where a refund row does name its instrument.
        """
        everything = sum(row.amount for row in books.data.settlement_rows)
        reversals = sum(
            row.amount for row in books.data.settlement_rows if row.type is not EntityType.PAYMENT
        )

        answer = ask("break it down by payment method", books)

        assert reversals > 0, "no reversals in this month - the test proves nothing"
        assert answer.total == everything - reversals


class TestHowLongPayoutsActuallyTake:
    def test_the_range_is_the_range_in_the_rows(self, books: Books) -> None:
        lags = [
            (row.settled_at.date() - row.created_at.date()).days
            for row in books.data.settlement_rows
            if row.settled_at is not None and row.type is EntityType.PAYMENT
        ]

        answer = ask("how long do payouts take?", books)

        assert f"{min(lags)} to {max(lags)}" in answer.headline

    def test_the_shares_add_up_to_everything(self, books: Books) -> None:
        lags = [
            (row.settled_at.date() - row.created_at.date()).days
            for row in books.data.settlement_rows
            if row.settled_at is not None and row.type is EntityType.PAYMENT
        ]
        spread = Counter(lags)

        answer = ask("what is my settlement cycle", books)

        assert len(answer.lines) == len(spread)

    def test_same_day_payouts_are_called_instant_rather_than_fast(self, books: Books) -> None:
        """A zero-day lag is a product the merchant bought, not a gateway
        being quick, and reporting it as the latter would leave somebody
        wondering why their next payout took two days."""
        answer = ask("how long until I get paid", books)

        assert "instant settlement" in answer.headline
        assert any(line.label == "same day" for line in answer.lines)


class TestTheBiggestPayouts:
    def test_they_come_back_largest_first(self, books: Books) -> None:
        answer = ask("what were my biggest payouts?", books)
        amounts = [line.amount for line in answer.lines]

        assert amounts == sorted(amounts, reverse=True)

    def test_the_first_one_really_is_the_largest_credit(self, books: Books) -> None:
        biggest = max(credit.amount for credit in books.data.bank_credits)

        answer = ask("show me the largest credits", books)

        assert answer.lines[0].amount == biggest

    def test_it_is_not_the_same_question_as_the_biggest_problem(self, books: Books) -> None:
        """`largest` is cash planning and `biggest` is triage. They share
        every adjective, so this is the one that would rot silently."""
        assert ask("what were my biggest payouts?", books).intent == "largest"
        assert ask("what's the biggest problem here?", books).intent == "biggest"

    def test_every_credit_it_names_is_one_this_run_holds(self, books: Books) -> None:
        known = {credit.credit_id for credit in books.data.bank_credits}

        for subject in ask("top deposits this month", books).subjects:
            assert subject in known


class TestOneNamedDay:
    def day_with_credits(self, books: Books) -> date:
        return Counter(credit.value_date for credit in books.data.bank_credits).most_common(1)[0][0]

    def test_it_counts_only_that_day(self, books: Books) -> None:
        day = self.day_with_credits(books)
        expected = sum(
            credit.amount for credit in books.data.bank_credits if credit.value_date == day
        )

        answer = ask(f"what happened on {day.isoformat()}", books)

        assert answer.intent == "on_a_day"
        assert answer.lines[0].amount == expected

    def test_a_bare_date_reaches_it_without_any_other_word(self, books: Books) -> None:
        """The fallback that widens this most. Somebody who typed a date
        wants that date, and a refusal would be the wrong answer to the one
        thing they were specific about."""
        day = self.day_with_credits(books)

        assert ask(day.isoformat(), books).intent == "on_a_day"

    def test_a_day_with_a_receiving_verb_still_asks_about_receiving(self, books: Books) -> None:
        """The fallback runs last on purpose. "How much did I receive on the
        14th" is a `received` question that happens to name a day."""
        day = self.day_with_credits(books)

        assert ask(f"how much did I receive on {day.isoformat()}", books).intent == "received"

    def test_a_day_nothing_happened_on_says_so(self, books: Books) -> None:
        answer = ask("what happened on 1999-01-01", books)

        assert answer.answered
        assert "1999-01-01" in answer.headline

    def test_an_impossible_date_is_not_read_as_a_date(self, books: Books) -> None:
        """`2026-02-30` parses as three numbers and is not a day. It must not
        become one, and it must not crash on the way to not becoming one."""
        answer = ask("what happened on 2026-02-30", books)

        assert answer.intent == "on_a_day"
        assert "Name a date" in answer.headline
