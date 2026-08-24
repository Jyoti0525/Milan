"""The fee stack, checked against Razorpay's own published example."""

from __future__ import annotations

from decimal import Decimal

import pytest

from milan.domain.enums import CardType, PaymentMethod
from milan.domain.money import from_rupees
from milan.domain.rates import RateCard, compute_deductions


class TestPublishedExample:
    def test_ten_thousand_rupee_card_payment(self) -> None:
        """Razorpay's documented worked example: Rs 10,000 settles Rs 9,764."""
        result = compute_deductions(
            from_rupees("10000"),
            PaymentMethod.CARD,
            CardType.DOMESTIC_CONSUMER,
            RateCard(),
        )
        assert result.fee == from_rupees("200")
        assert result.tax == from_rupees("36")
        assert result.net == from_rupees("9764")


class TestRateSelection:
    @pytest.mark.parametrize(
        ("card_type", "expected_rate"),
        [
            (CardType.DOMESTIC_CONSUMER, Decimal("0.02")),
            (CardType.DOMESTIC_CORPORATE, Decimal("0.0215")),
            (CardType.INTERNATIONAL, Decimal("0.03")),
        ],
    )
    def test_card_rates_differ(self, card_type: CardType, expected_rate: Decimal) -> None:
        assert RateCard().platform_rate(PaymentMethod.CARD, card_type) == expected_rate

    @pytest.mark.parametrize(
        "method",
        [
            PaymentMethod.UPI,
            PaymentMethod.NETBANKING,
            PaymentMethod.WALLET,
            PaymentMethod.PAYLATER,
        ],
    )
    def test_non_card_methods_use_the_standard_rate(self, method: PaymentMethod) -> None:
        assert RateCard().platform_rate(method, None) == Decimal("0.02")


class TestWithholding:
    def test_tds_is_off_by_default(self) -> None:
        result = compute_deductions(from_rupees("10000"), PaymentMethod.UPI, None, RateCard())
        assert result.tds == 0

    def test_tds_is_charged_on_gross_not_on_the_gst(self) -> None:
        """Section 194-O withholds 1% of gross, excluding the GST component.

        Charging it on gross-plus-GST instead would be wrong by about
        0.0036% of gross - small enough to look like rounding drift, and
        large enough that the books never close.
        """
        gross = from_rupees("10000")
        result = compute_deductions(
            gross, PaymentMethod.CARD, CardType.DOMESTIC_CONSUMER, RateCard(tds_applies=True)
        )
        assert result.tds == from_rupees("100")
        assert result.tds != from_rupees("100.36")


class TestInvariants:
    def test_the_breakdown_always_reconstructs_the_gross(self) -> None:
        for rupees in ("1", "199", "999.99", "10000", "47999.55"):
            result = compute_deductions(
                from_rupees(rupees),
                PaymentMethod.CARD,
                CardType.INTERNATIONAL,
                RateCard(tds_applies=True),
            )
            assert result.net + result.total_deducted == result.gross
