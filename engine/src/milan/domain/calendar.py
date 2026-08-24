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
