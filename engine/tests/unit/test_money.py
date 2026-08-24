"""Money is integer paise, and rounding is half-up.

These tests exist because a one-paisa disagreement is not cosmetic here: it is
the difference between a batch that balances and an exception queue with a
hundred entries in it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from milan.domain.money import Paise, apply_rate, format_inr, from_rupees, to_rupees


class TestConversion:
    def test_rupees_to_paise_is_exact(self) -> None:
        assert from_rupees("90608.47") == 9_060_847

    def test_round_trip_preserves_value(self) -> None:
        assert to_rupees(from_rupees("1234.56")) == Decimal("1234.56")

    def test_whole_rupees(self) -> None:
        assert from_rupees(10_000) == 1_000_000

    def test_float_is_rejected(self) -> None:
        # A float amount means precision was already lost upstream.
        with pytest.raises((TypeError, ValueError)):
            from_rupees(1234.56)  # type: ignore[arg-type]


class TestRounding:
    def test_half_rounds_up_not_to_even(self) -> None:
        # Python's built-in round() gives 2 here. Indian financial systems
        # round half away from zero, so the gateway would say 3.
        assert apply_rate(Paise(5), Decimal("0.5")) == 3

    @pytest.mark.parametrize(
        ("base", "rate", "expected"),
        [
            (1_000_000, Decimal("0.02"), 20_000),  # Rs 10,000 at 2% = Rs 200
            (1_000_000, Decimal("0.0215"), 21_500),  # corporate card
            (20_000, Decimal("0.18"), 3_600),  # GST on the fee above
            (1_000_000, Decimal("0.01"), 10_000),  # 194-O withholding
        ],
    )
    def test_known_rates(self, base: int, rate: Decimal, expected: int) -> None:
        assert apply_rate(Paise(base), rate) == expected


class TestFormatting:
    @pytest.mark.parametrize(
        ("paise", "expected"),
        [
            (906_847, "Rs 9,068.47"),
            (100, "Rs 1.00"),
            (0, "Rs 0.00"),
            (-1_234_567, "-Rs 12,345.67"),
            (1_000_000_000, "Rs 1,00,00,000.00"),  # Indian grouping, one crore
        ],
    )
    def test_display(self, paise: int, expected: str) -> None:
        assert format_inr(Paise(paise)) == expected
