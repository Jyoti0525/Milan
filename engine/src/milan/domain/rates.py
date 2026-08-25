"""The Indian fee stack, as actually charged.

Sourced from Razorpay's published pricing and the Section 194-O guidance, not
from memory. See `docs/02-THE-MONEY-RULES.md` for the citations.

The subtle one is TDS: Section 194-O withholds 1% of the *gross* transaction
value, and it is calculated on the gross excluding the GST component. Getting
that wrong produces an error of roughly 0.0036% of gross — small enough to
look like rounding drift and large enough to never balance.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from milan.domain.enums import CardType, PaymentMethod
from milan.domain.money import PAISE_PER_RUPEE, Paise, apply_rate, from_rupees

GST_RATE: Final = Decimal("0.18")
"""GST charged on the platform fee. Not on the transaction value."""

TDS_194O_RATE: Final = Decimal("0.01")
"""Section 194-O withholding, on gross, excluding the GST component."""

INSTANT_REFUND_SLABS: Final = (
    (Decimal("1000"), Decimal("7.99")),
    (Decimal("25000"), Decimal("11.99")),
)
"""Instant refund pricing: Rs 7.99 up to Rs 1,000, Rs 11.99 to Rs 25,000.
Anything larger falls to `INSTANT_REFUND_TOP`. Flat amounts, not a rate -
which is why they are the one charge in this file that gets proportionally
more painful the smaller the refund."""

INSTANT_REFUND_TOP: Final = Decimal("14.99")


class RateCard(BaseModel):
    """What a given merchant is contracted to pay.

    Kept as data rather than constants because the whole point of the
    `FEE_DEDUCTION` exception category is that the rate a merchant is
    contracted to and the rate they are charged can differ.
    """

    model_config = ConfigDict(frozen=True)

    standard: Decimal = Field(default=Decimal("0.02"))
    corporate_card: Decimal = Field(default=Decimal("0.0215"))
    international_card: Decimal = Field(default=Decimal("0.03"))
    gst: Decimal = Field(default=GST_RATE)
    tds: Decimal = Field(default=TDS_194O_RATE)
    route: Decimal = Field(default=Decimal("0.001"))
    """Razorpay Route: 0.1% on the amount paid on to a linked account.

    Charged on top of the platform fee on the original payment, not instead
    of it - the merchant pays 2% to accept the money and 0.1% again to pass
    part of it along. Both are real and both come out of the same payout.
    """

    tds_applies: bool = Field(
        default=False,
        description="Section 194-O withholding is merchant-specific; off by default.",
    )

    def instant_refund_fee(self, amount: Paise) -> Paise:
        """What Razorpay charges to push a refund out immediately.

        An ordinary refund costs the merchant nothing to process - that is
        published and it is why refund rows normally carry a zero fee. An
        *instant* refund does not, and it is the only charge in this system
        that is a flat amount rather than a rate.

        That distinction matters for reconciliation: every other shortfall
        scales with the transaction, so a discrepancy of a few rupees on a
        large batch reads as rounding. This one does not scale, so it looks
        like noise on a big refund and like a real error on a small one,
        which is exactly the shape of thing that gets written off.
        """
        rupees = Decimal(amount) / PAISE_PER_RUPEE
        for ceiling, fee in INSTANT_REFUND_SLABS:
            if rupees <= ceiling:
                return from_rupees(fee)
        return from_rupees(INSTANT_REFUND_TOP)

    def route_fee(self, transferred: Paise) -> Paise:
        """What it costs to pass `transferred` on to a linked account."""
        return apply_rate(transferred, self.route)

    def platform_rate(self, method: PaymentMethod, card_type: CardType | None) -> Decimal:
        """The platform fee rate for one transaction.

        Only cards vary. UPI, netbanking, wallets, EMI and PayLater are all on
        the standard rate, so `card_type` is ignored for them.
        """
        if method is not PaymentMethod.CARD or card_type is None:
            return self.standard
        match card_type:
            case CardType.DOMESTIC_CORPORATE:
                return self.corporate_card
            case CardType.INTERNATIONAL:
                return self.international_card
            case CardType.DOMESTIC_CONSUMER:
                return self.standard


class Deductions(BaseModel):
    """The per-transaction deduction breakdown, and what is left.

    `net` is what the gateway owes the merchant for this transaction. The
    identity `gross - fee - tax - tds == net` is asserted at construction, so
    an inconsistent breakdown cannot exist as a value in this system.
    """

    model_config = ConfigDict(frozen=True)

    gross: Paise
    fee: Paise
    tax: Paise
    tds: Paise

    @property
    def net(self) -> Paise:
        return Paise(self.gross - self.fee - self.tax - self.tds)

    @property
    def total_deducted(self) -> Paise:
        return Paise(self.fee + self.tax + self.tds)


def compute_deductions(
    gross: Paise,
    method: PaymentMethod,
    card_type: CardType | None,
    rates: RateCard,
) -> Deductions:
    """Apply the full deduction waterfall to a single captured payment.

    Order matters and is not arbitrary: the fee comes off gross, GST is
    charged on the fee (never on gross), and TDS is withheld against gross
    (never against the GST). Reordering these changes the answer.
    """
    fee = apply_rate(gross, rates.platform_rate(method, card_type))
    tax = apply_rate(fee, rates.gst)
    tds = apply_rate(gross, rates.tds) if rates.tds_applies else Paise(0)
    return Deductions(gross=gross, fee=fee, tax=tax, tds=tds)
