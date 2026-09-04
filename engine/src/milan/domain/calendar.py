"""Settlement timing.

Domestic payments settle T+2 working days, international T+7, where T is the
day the payment was captured. Working days exclude weekends.

Bank holidays are deliberately not modelled. A real deployment would take a
holiday calendar as configuration; inventing one here would make our
synthetic data agree with an assumption we made up, which is the opposite of
what the data is for. The consequence is documented rather than hidden: our
generated settlement dates can fall on an Indian bank holiday.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Final

from milan.domain.enums import CardType

SATURDAY: Final = 5
DOMESTIC_SETTLEMENT_DAYS: Final = 2
INTERNATIONAL_SETTLEMENT_DAYS: Final = 7
REFUND_CLEARING_DAYS_MIN: Final = 5
REFUND_CLEARING_DAYS_MAX: Final = 7


def is_working_day(day: date) -> bool:
    return day.weekday() < SATURDAY


def add_working_days(start: date, count: int) -> date:
    """Advance `count` working days from `start`, skipping weekends."""
    if count < 0:
        raise ValueError("count must not be negative")
    current = start
    remaining = count
    while remaining > 0:
        current += timedelta(days=1)
        if is_working_day(current):
            remaining -= 1
    return current


def next_working_day(day: date) -> date:
    return day if is_working_day(day) else add_working_days(day, 1)


def working_days_between(start: date, end: date) -> int:
    """Signed working days from `start` to `end`.

    Negative when `end` is the earlier of the two, so a settlement that
    arrived a day early and one that arrived a day late do not read the same.
    Both endpoints are treated the way `add_working_days` treats them: the
    count is of days advanced, so a Friday to the following Monday is one.
    """
    if end == start:
        return 0
    step = 1 if end > start else -1
    current, count = start, 0
    while current != end:
        current += timedelta(days=step)
        if is_working_day(current):
            count += 1
    return count * step


def settlement_due(captured_on: date, card_type: CardType | None) -> date:
    """When a payment captured on `captured_on` is due to reach the bank.

    T+2 working days domestic, T+7 for international cards. This is the
    published cycle rather than a tolerance anybody here chose, which is the
    only reason it can be used to date money forward: the answer is Razorpay's
    schedule applied to the merchant's own capture timestamp, not a guess
    about what usually happens.

    It lives here rather than in either caller because both the
    reconciliation - deciding whether an unreported payment is late or merely
    pending - and the forward schedule are asking the identical question, and
    two copies of this would be two answers the day one of them was corrected.
    """
    lag = (
        INTERNATIONAL_SETTLEMENT_DAYS
        if card_type is CardType.INTERNATIONAL
        else DOMESTIC_SETTLEMENT_DAYS
    )
    return add_working_days(captured_on, lag)
