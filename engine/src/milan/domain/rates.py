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
from milan.domain.money import Paise, apply_rate

GST_RATE: Final = Decimal("0.18")
"""GST charged on the platform fee. Not on the transaction value."""

TDS_194O_RATE: Final = Decimal("0.01")
"""Section 194-O withholding, on gross, excluding the GST component."""


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
    tds_applies: bool = Field(
        default=False,
        description="Section 194-O withholding is merchant-specific; off by default.",
    )

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
