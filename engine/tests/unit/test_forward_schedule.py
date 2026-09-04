"""The schedule's arithmetic, and the three things it refuses to date.

Built from hand-written rows rather than a generated month, so that each case
states one fact and fails for one reason. The measured version - a schedule
built from half a month and marked against the other half - is in
`tests/integration/test_the_schedule_is_graded_against_what_landed.py`.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from milan.domain.calendar import settlement_due, working_days_between
from milan.domain.enums import CardType, EntityType, PaymentMethod
from milan.domain.money import Paise
from milan.domain.rates import RateCard, compute_deductions
from milan.domain.records import Payment, SettlementRow
from milan.forecast import last_capture, schedule_from
from milan.recon.inputs import ReconInput

RATES = RateCard()

MONDAY = date(2026, 7, 6)
FRIDAY = date(2026, 7, 10)


def payment(
    identifier: str,
    on: date,
    rupees: int,
    method: PaymentMethod = PaymentMethod.UPI,
    card_type: CardType | None = None,
) -> Payment:
    return Payment(
        payment_id=identifier,
        order_id=f"order_{identifier}",
        amount=Paise(rupees * 100),
        method=method,
        card_type=card_type,
        captured_at=datetime.combine(on, datetime.min.time()).replace(hour=11),
    )


def row(
    entity_id: str,
    kind: EntityType,
    created: date,
    settled: date | None,
    credit: int = 0,
    debit: int = 0,
    payment_id: str | None = None,
    on_hold: bool = False,
) -> SettlementRow:
    return SettlementRow(
        entity_id=entity_id,
        type=kind,
        debit=Paise(debit),
        credit=Paise(credit),
        amount=Paise(max(credit, debit)),
        fee=Paise(0),
        tax=Paise(0),
        on_hold=on_hold,
        settled=settled is not None,
        created_at=datetime.combine(created, datetime.min.time()),
        settled_at=(datetime.combine(settled, datetime.min.time()) if settled else None),
        settlement_id="setl_1" if settled else None,
        settlement_utr="UTR1" if settled else None,
        payment_id=payment_id,
    )


def inputs(payments: tuple[Payment, ...] = (), rows: tuple[SettlementRow, ...] = ()) -> ReconInput:
    return ReconInput(orders=(), payments=payments, settlement_rows=rows, bank_credits=())


class TestTheDateComesFromThePublishedCycle:
    def test_a_domestic_capture_is_due_two_working_days_later(self) -> None:
        assert settlement_due(MONDAY, None) == date(2026, 7, 8)

    def test_a_friday_capture_skips_the_weekend(self) -> None:
        assert settlement_due(FRIDAY, None) == date(2026, 7, 14)

    def test_an_international_card_is_due_seven_working_days_later(self) -> None:
        assert settlement_due(MONDAY, CardType.INTERNATIONAL) == date(2026, 7, 15)

    def test_the_schedule_dates_a_payment_by_that_cycle(self) -> None:
        data = inputs(payments=(payment("pay_1", MONDAY, 1000),))

        schedule = schedule_from(data, RATES, as_of=MONDAY)

        assert [landing.on for landing in schedule.landings] == [date(2026, 7, 8)]
        assert schedule.payments == 1


class TestTheAmountComesFromTheFeeStack:
    def test_the_net_is_gross_less_the_deductions(self) -> None:
        one = payment("pay_1", MONDAY, 1000)
        expected = compute_deductions(one.amount, one.method, one.card_type, RATES)

        schedule = schedule_from(inputs(payments=(one,)), RATES, as_of=MONDAY)

        assert schedule.committed == expected.net
        assert schedule.gross == one.amount
        assert schedule.deducted == expected.total_deducted

    def test_withholding_widens_the_deduction(self) -> None:
        """An operator's schedule is a percentage point lighter, and the
        difference is not a rounding one - it is the tax the government took.
        """
        one = payment("pay_1", MONDAY, 1000)
        operator = RATES.model_copy(update={"tds_applies": True})

        plain = schedule_from(inputs(payments=(one,)), RATES, as_of=MONDAY)
        withheld = schedule_from(inputs(payments=(one,)), operator, as_of=MONDAY)

        assert withheld.committed < plain.committed
        assert plain.committed - withheld.committed == Paise(1000)


class TestItOnlyReadsWhatTheMerchantWouldHave:
    def test_a_payment_captured_after_the_day_is_not_in_the_schedule(self) -> None:
        data = inputs(payments=(payment("pay_1", FRIDAY, 1000),))

        assert schedule_from(data, RATES, as_of=MONDAY).payments == 0

    def test_a_payout_already_made_is_not_scheduled_again(self) -> None:
        data = inputs(
            payments=(payment("pay_1", MONDAY, 1000),),
            rows=(row("pay_1", EntityType.PAYMENT, MONDAY, date(2026, 7, 8), credit=97640),),
        )

        assert schedule_from(data, RATES, as_of=date(2026, 7, 9)).payments == 0

    def test_a_settlement_row_dated_after_the_day_is_not_read(self) -> None:
        """The load-bearing restriction.

        The row saying this payment settles on Wednesday exists in the file
        the schedule is handed, and a merchant standing on Monday does not
        have it. Reading it would make the schedule a copy of the answer, and
        every accuracy figure downstream a tautology.
        """
        data = inputs(
            payments=(payment("pay_1", MONDAY, 1000),),
            rows=(row("pay_1", EntityType.PAYMENT, MONDAY, date(2026, 7, 8), credit=97640),),
        )

        assert schedule_from(data, RATES, as_of=MONDAY).payments == 1

    def test_a_refund_does_not_mark_its_payment_as_paid_out(self) -> None:
        """A refund row carries the `payment_id` of the sale it reverses.

        Indexing every row by that column drops the refunded payment from the
        schedule entirely - and a payment large enough to have been refunded
        is the one a merchant most wants dated.
        """
        data = inputs(
            payments=(payment("pay_1", MONDAY, 1000),),
            rows=(
                row(
                    "rfnd_1",
                    EntityType.REFUND,
                    MONDAY,
                    date(2026, 7, 7),
                    debit=50000,
                    payment_id="pay_1",
                ),
            ),
        )

        assert schedule_from(data, RATES, as_of=MONDAY).payments == 1


class TestWhatItWillNotDate:
    def test_money_already_due_is_overdue_rather_than_coming(self) -> None:
        """The bucket that keeps the headline honest.

        A payment captured a fortnight ago with no payout behind it is not
        cash flow, it is a reconciliation exception seen from the other side.
        Summing it into "coming" would report money as arriving that has
        already failed to.
        """
        data = inputs(payments=(payment("pay_1", MONDAY, 1000),))

        schedule = schedule_from(data, RATES, as_of=date(2026, 7, 20))

        assert schedule.payments == 0
        assert [item.payment_id for item in schedule.overdue] == ["pay_1"]
        assert schedule.committed == Paise(0)
        assert schedule.overdue_net > 0

    def test_an_unsettled_refund_is_undated_rather_than_guessed(self) -> None:
        """It lands in whichever payout is next large enough to absorb it,
        and which one that is depends on sales nobody has made."""
        data = inputs(
            rows=(row("rfnd_1", EntityType.REFUND, MONDAY, None, debit=50000, payment_id="pay_9"),)
        )

        schedule = schedule_from(data, RATES, as_of=MONDAY)

        assert [item.subject_id for item in schedule.undated] == ["rfnd_1"]
        assert schedule.undated_net == Paise(-50000)
        assert "not yet known" in schedule.undated[0].because

    def test_a_held_row_says_it_is_held(self) -> None:
        data = inputs(
            rows=(row("pay_9", EntityType.PAYMENT, MONDAY, None, credit=90000, on_hold=True),)
        )

        schedule = schedule_from(data, RATES, as_of=MONDAY)

        assert schedule.undated_net == Paise(90000)
        assert "on hold" in schedule.undated[0].because

    def test_an_undated_refund_is_never_added_to_the_dated_total(self) -> None:
        data = inputs(
            payments=(payment("pay_1", MONDAY, 1000),),
            rows=(row("rfnd_1", EntityType.REFUND, MONDAY, None, debit=50000),),
        )

        schedule = schedule_from(data, RATES, as_of=MONDAY)

        assert schedule.committed > 0
        assert schedule.undated_net < 0
        assert schedule.committed == schedule.landings[0].net


class TestTheRunningTotal:
    def test_through_is_cumulative(self) -> None:
        data = inputs(
            payments=(
                payment("pay_1", MONDAY, 1000),
                payment("pay_2", date(2026, 7, 7), 2000),
            )
        )

        schedule = schedule_from(data, RATES, as_of=date(2026, 7, 7))

        first, second = date(2026, 7, 8), date(2026, 7, 9)
        assert schedule.through(date(2026, 7, 7)) == Paise(0)
        assert schedule.through(first) == schedule.landings[0].net
        assert schedule.through(second) == schedule.committed
        assert schedule.horizon == second

    def test_an_empty_schedule_says_so_rather_than_failing(self) -> None:
        schedule = schedule_from(inputs(), RATES)

        assert schedule.landings == ()
        assert schedule.horizon is None
        assert schedule.committed == Paise(0)

    def test_the_default_day_is_the_last_capture(self) -> None:
        payments = (payment("pay_1", MONDAY, 1000), payment("pay_2", FRIDAY, 1000))

        assert last_capture(payments) == FRIDAY
        assert schedule_from(inputs(payments=payments), RATES).as_of == FRIDAY


class TestWorkingDaysBetween:
    @pytest.mark.parametrize(
        ("start", "end", "expected"),
        [
            (MONDAY, MONDAY, 0),
            (MONDAY, date(2026, 7, 8), 2),
            (date(2026, 7, 8), MONDAY, -2),
            (FRIDAY, date(2026, 7, 13), 1),
            (date(2026, 7, 13), FRIDAY, -1),
        ],
    )
    def test_the_count_is_signed(self, start: date, end: date, expected: int) -> None:
        """Signed, because a payout that came early and one that came late
        are not the same fact and a merchant only complains about one."""
        assert working_days_between(start, end) == expected
