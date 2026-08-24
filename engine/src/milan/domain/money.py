"""Money handling.

Every monetary value in this system is an integer number of paise. Floating
point is never used for money: 0.1 + 0.2 != 0.3 is not an acceptable property
for a reconciliation engine whose entire claim is that the books balance.

Rates (fee percentages, tax percentages) are `Decimal`, and every rate
application goes through `apply_rate`, which rounds half-up. Half-up is the
convention Indian financial systems use; Python's built-in `round` is
banker's rounding and would quietly disagree with the gateway by one paisa.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Final, NewType

Paise = NewType("Paise", int)
"""An integer number of paise. 100 paise = 1 rupee."""

PAISE_PER_RUPEE: Final = 100

ZERO: Final = Paise(0)


def from_rupees(rupees: str | int | Decimal) -> Paise:
    """Convert a rupee amount to paise.

    Accepts `str` and `Decimal` exactly; `int` is treated as whole rupees.
    `float` is deliberately not accepted — if a caller has a float amount,
    the precision loss already happened upstream and should be fixed there.
    """
    if isinstance(rupees, float):
        raise TypeError("float amounts are not accepted: pass a str or Decimal")
    value = rupees if isinstance(rupees, Decimal) else Decimal(rupees)
    scaled = (value * PAISE_PER_RUPEE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return Paise(int(scaled))


def to_rupees(paise: Paise) -> Decimal:
    """Convert paise to an exact rupee `Decimal`. Never lossy."""
    return Decimal(paise) / PAISE_PER_RUPEE


def apply_rate(base: Paise, rate: Decimal) -> Paise:
    """Apply a rate to an amount, rounding half-up to the nearest paisa.

    This is the only sanctioned way to compute a fee or a tax. Rounding is
    concentrated here so that "where did the paisa go" always has one answer.
    """
    product = Decimal(base) * rate
    return Paise(int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))


def format_inr(paise: Paise) -> str:
    """Render paise as a display string: `Rs 90,608.47`.

    Uses the Indian grouping convention (last three digits, then pairs), so
    1,00,000 rather than 100,000.
    """
    sign = "-" if paise < 0 else ""
    whole, fraction = divmod(abs(paise), PAISE_PER_RUPEE)
    digits = str(whole)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups: list[str] = []
        while len(head) > 2:
            head, group = head[:-2], head[-2:]
            groups.insert(0, group)
        if head:
            groups.insert(0, head)
        digits = ",".join([*groups, tail])
    return f"{sign}Rs {digits}.{fraction:02d}"
