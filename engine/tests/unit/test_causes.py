"""Turning a queue of exceptions into the few reasons behind it.

The risk this module carries is not that it fails to find a pattern. It is
that it finds one that is not there, states it confidently, and sends
somebody to argue a case the evidence does not support. Most of what is
below tests the refusals.
"""

from __future__ import annotations

import pytest

from milan.domain.enums import ExceptionCode
from milan.domain.money import Paise
from milan.domain.results import ReconException
from milan.recon.causes import PATTERN, induce


def exception(
    code: ExceptionCode,
    subject: str,
    amount: int = 10_000,
    **evidence: str,
) -> ReconException:
    return ReconException(
        code=code,
        subject_id=subject,
        amount=Paise(amount),
        summary=f"{subject} did not resolve",
        evidence=evidence,
    )


def fee(subject: str, rate: str, amount: int = 10_000) -> ReconException:
    return exception(ExceptionCode.FEE_DEDUCTION, subject, amount, implied_rate=rate)


def missing(subject: str, day: str, that_day: str) -> ReconException:
    return exception(
        ExceptionCode.MISSING_SETTLEMENT,
        subject,
        50_000,
        settled_on=day,
        batches_that_day=that_day,
    )


# --------------------------------------------------------------- refusals


class TestOneOfSomethingIsNotAPattern:
    def test_an_empty_queue_induces_nothing(self) -> None:
        found = induce(())

        assert found.causes == ()
        assert found.uncaused == ()
        assert found.reading == "Nothing to explain."

    def test_a_single_exception_stays_itself(self) -> None:
        found = induce([fee("bank_1", "0.150%")])

        assert found.causes == ()
        assert found.uncaused == ("bank_1",)

    def test_the_threshold_is_the_one_the_module_publishes(self) -> None:
        """A test that hard-codes 2 would pass while the constant said 3."""
        queue = [fee(f"bank_{index}", "0.150%") for index in range(PATTERN)]

        assert induce(queue).causes, f"{PATTERN} members should be a pattern"
        assert not induce(queue[: PATTERN - 1]).causes


class TestDifferentNumbersAreDifferentProblems:
    def test_two_unrelated_rates_do_not_become_one_deduction(self) -> None:
        """0.15% and 0.40% off two batches is two problems. Grouping them
        would put a number in front of an account manager that no payout in
        the report actually shows."""
        found = induce([fee("bank_1", "0.150%"), fee("bank_2", "0.400%")])

        assert found.causes == ()
        assert set(found.uncaused) == {"bank_1", "bank_2"}

    def test_rates_a_rounding_apart_are_one_deduction(self) -> None:
        found = induce([fee("bank_1", "0.150%"), fee("bank_2", "0.151%")])

        assert len(found.causes) == 1
        assert found.causes[0].size == 2

    def test_an_unreadable_rate_is_left_alone_rather_than_guessed(self) -> None:
        """If the categoriser ever stops writing a percentage, this must
        decline to group rather than group everything it cannot read."""
        found = induce([fee("bank_1", "about 0.15"), fee("bank_2", "about 0.15")])

        assert found.causes == ()


class TestADayIsOnlyACauseWhenTheWholeDayIsGone:
    """The rule that was wrong first time round.

    Two missing payouts sharing a date, out of twenty-one days, is what
    randomness produces - not a settlement run that failed.
    """

    def test_two_of_five_that_day_is_not_a_failed_run(self) -> None:
        queue = [missing("setl_1", "2026-07-21", "5"), missing("setl_2", "2026-07-21", "5")]

        found = induce(queue)

        assert len(found.causes) == 1
        assert "whole payout run" not in found.causes[0].name
        assert found.causes[0].name.startswith("Payouts the gateway reported")

    def test_all_of_that_day_is_a_failed_run(self) -> None:
        queue = [missing("setl_1", "2026-07-21", "2"), missing("setl_2", "2026-07-21", "2")]

        found = induce(queue)

        assert len(found.causes) == 1
        assert found.causes[0].name == "The whole payout run of 2026-07-21 is missing"

    def test_a_failed_run_outranks_the_general_rule(self) -> None:
        """Both rules match the failed run's members. If the general one ran
        first it would swallow them and the specific finding would vanish."""
        queue = [
            missing("setl_1", "2026-07-21", "2"),
            missing("setl_2", "2026-07-21", "2"),
            missing("setl_3", "2026-07-14", "4"),
            missing("setl_4", "2026-07-15", "4"),
        ]

        names = {cause.name for cause in induce(queue).causes}

        assert "The whole payout run of 2026-07-21 is missing" in names
        assert "Payouts the gateway reported that never reached the bank" in names

    def test_a_payout_with_no_day_population_recorded_still_groups(self) -> None:
        """An archived report written before the evidence carried the day's
        count must still induce something rather than crash or claim a run
        failed on no evidence."""
        queue = [
            exception(ExceptionCode.MISSING_SETTLEMENT, "setl_1", settled_on="2026-07-21"),
            exception(ExceptionCode.MISSING_SETTLEMENT, "setl_2", settled_on="2026-07-21"),
        ]

        found = induce(queue)

        assert len(found.causes) == 1
        assert "whole payout run" not in found.causes[0].name


# ------------------------------------------------------------- the findings


class TestWhatACauseSays:
    def test_a_deduction_cause_names_the_rate_and_asks_about_it(self) -> None:
        found = induce([fee("bank_1", "0.150%"), fee("bank_2", "0.150%"), fee("bank_3", "0.150%")])

        cause = found.causes[0]

        assert cause.size == 3
        assert "0.150%" in cause.because
        assert "0.150%" in cause.ask
        assert cause.actionable

    def test_the_money_is_the_sum_of_the_members(self) -> None:
        found = induce([fee("bank_1", "0.150%", 12_345), fee("bank_2", "0.150%", 54_321)])

        assert found.causes[0].total == 66_666

    def test_a_negative_amount_still_adds_to_the_total(self) -> None:
        """Exception amounts are unsigned by convention, but a report read
        back from an archive is not a place to assume conventions held."""
        found = induce([fee("bank_1", "0.150%", -10_000), fee("bank_2", "0.150%", 10_000)])

        assert found.causes[0].total == 20_000

    def test_refunds_recovered_elsewhere_ask_for_nothing(self) -> None:
        """The most valuable thing this can say about nine items somebody
        was about to spend an afternoon on."""
        queue = [
            exception(ExceptionCode.PARTIAL_PAYMENT, f"bank_{index}", recovered_by="setl_other")
            for index in range(4)
        ]

        cause = induce(queue).causes[0]

        assert cause.ask == ""
        assert not cause.actionable
        assert "accounted for" in cause.because

    def test_a_recurring_payer_is_named(self) -> None:
        queue = [
            exception(
                ExceptionCode.UNEXPLAINED,
                f"bank_{index}",
                reason="no candidate",
                narration=f"NEFT CR ACME LOGISTICS PVT UTRSBIN{index:012d}",
            )
            for index in range(3)
        ]

        cause = induce(queue).causes[0]

        assert "ACME LOGISTICS PVT" in cause.name
        assert cause.size == 3

    def test_two_different_payers_do_not_become_one(self) -> None:
        queue = [
            exception(
                ExceptionCode.UNEXPLAINED,
                "bank_1",
                reason="no candidate",
                narration="NEFT CR ACME LOGISTICS UTRSBIN000000000001",
            ),
            exception(
                ExceptionCode.UNEXPLAINED,
                "bank_2",
                reason="no candidate",
                narration="NEFT CR BHARAT TRADERS UTRSBIN000000000002",
            ),
        ]

        assert induce(queue).causes == ()

    def test_a_contested_settlement_asks_for_the_one_reference(self) -> None:
        queue = [
            exception(
                ExceptionCode.UNEXPLAINED,
                f"bank_{index}",
                reason="contested settlement",
                settlement="setl_abc",
            )
            for index in range(2)
        ]

        cause = induce(queue).causes[0]

        assert "setl_abc" in cause.ask
        assert "UTR" in cause.ask

    def test_unsettled_payments_report_their_method_when_it_is_one(self) -> None:
        queue = [
            exception(ExceptionCode.UNSETTLED_PAYMENT, f"pay_{index}", method="upi")
            for index in range(3)
        ]

        cause = induce(queue).causes[0]

        assert "all taken by upi" in cause.because

    def test_unsettled_payments_do_not_claim_a_method_when_they_are_mixed(self) -> None:
        queue = [
            exception(ExceptionCode.UNSETTLED_PAYMENT, "pay_1", method="upi"),
            exception(ExceptionCode.UNSETTLED_PAYMENT, "pay_2", method="card"),
        ]

        cause = induce(queue).causes[0]

        assert "all taken by" not in cause.because


# ---------------------------------------------------------- the arithmetic


class TestTheCoverageFigureIsHonest:
    def test_every_exception_is_either_caused_or_uncaused_exactly_once(self) -> None:
        """The one invariant that makes the coverage figure mean anything.

        Two rules both matching an exception and both counting it would give
        a coverage above the size of the queue, which is a number that reads
        as a strong result and is arithmetically impossible.
        """
        queue = [
            fee("bank_1", "0.150%"),
            fee("bank_2", "0.150%"),
            missing("setl_1", "2026-07-21", "2"),
            missing("setl_2", "2026-07-21", "2"),
            missing("setl_3", "2026-07-14", "9"),
            exception(ExceptionCode.UNSETTLED_PAYMENT, "pay_1", method="upi"),
            exception(ExceptionCode.UNSETTLED_PAYMENT, "pay_2", method="upi"),
            exception(ExceptionCode.UNEXPLAINED, "bank_9", reason="ambiguous"),
        ]

        found = induce(queue)
        placed = [member for cause in found.causes for member in cause.members]

        assert len(placed) == len(set(placed)), "an exception was counted twice"
        assert set(placed) | set(found.uncaused) == {item.subject_id for item in queue}
        assert found.total == len(queue)
        assert found.covered + len(found.uncaused) == len(queue)

    def test_causes_come_back_biggest_money_first(self) -> None:
        queue = [
            fee("bank_1", "0.150%", 100),
            fee("bank_2", "0.150%", 100),
            missing("setl_1", "2026-07-21", "9"),
            missing("setl_2", "2026-07-22", "9"),
        ]

        totals = [cause.total for cause in induce(queue).causes]

        assert totals == sorted(totals, reverse=True)

    def test_a_queue_with_no_pattern_says_so(self) -> None:
        queue = [
            exception(ExceptionCode.UNEXPLAINED, "bank_1", reason="ambiguous"),
            exception(ExceptionCode.UNEXPLAINED, "bank_2", reason="ambiguous"),
        ]

        found = induce(queue)

        assert found.causes == ()
        assert "no two of them the same" in found.reading

    @pytest.mark.parametrize("count", [0, 1, 2, 5])
    def test_the_share_never_exceeds_one(self, count: int) -> None:
        queue = [fee(f"bank_{index}", "0.150%") for index in range(count)]

        assert 0.0 <= induce(queue).share <= 1.0


class TestOneEventIsNotTwoExceptions:
    """The queue holds a payout reported missing and, three rows down, the
    deposit that was matched to it and came up short. Both sentences are
    true; the total is double what the merchant is actually exposed to."""

    def queue(self) -> list[ReconException]:
        return [
            exception(
                ExceptionCode.PARTIAL_PAYMENT,
                "bank_1",
                settlements="setl_a",
                recovered_by="setl_z",
            ),
            exception(
                ExceptionCode.FEE_DEDUCTION,
                "bank_2",
                settlements="setl_b",
                implied_rate="0.150%",
            ),
            missing("setl_a", "2026-07-21", "9"),
            missing("setl_b", "2026-07-22", "9"),
        ]

    def test_the_duplicated_payouts_are_named(self) -> None:
        causes = {cause.name: cause for cause in induce(self.queue()).causes}

        duplicated = causes["Payouts reported missing that a deposit here already accounts for"]
        assert set(duplicated.members) == {"setl_a", "setl_b"}

    def test_it_tells_the_reader_which_side_to_work(self) -> None:
        causes = {cause.name: cause for cause in induce(self.queue()).causes}

        ask = causes["Payouts reported missing that a deposit here already accounts for"].ask
        assert "shortfalls" in ask
        assert "half" in ask

    def test_a_duplicated_payout_is_not_also_filed_as_never_arriving(self) -> None:
        """The general missing-payout rule would happily take these, and
        would tell a merchant the money never arrived while the deposit sat
        three rows below in the same queue."""
        names = {cause.name for cause in induce(self.queue()).causes}

        assert "Payouts the gateway reported that never reached the bank" not in names

    def test_a_payout_no_deposit_names_is_left_to_the_general_rule(self) -> None:
        queue = [
            *self.queue(),
            missing("setl_c", "2026-07-23", "9"),
            missing("setl_d", "2026-07-24", "9"),
        ]

        names = {cause.name for cause in induce(queue).causes}

        assert "Payouts the gateway reported that never reached the bank" in names

    def test_a_settlement_named_by_nothing_does_not_duplicate(self) -> None:
        queue = [
            exception(ExceptionCode.PARTIAL_PAYMENT, "bank_1", settlements="setl_x"),
            missing("setl_a", "2026-07-21", "9"),
            missing("setl_b", "2026-07-22", "9"),
        ]

        names = {cause.name for cause in induce(queue).causes}

        assert "Payouts reported missing that a deposit here already accounts for" not in names
