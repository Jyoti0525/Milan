"""The records a real merchant already has, plus the ones the gateway produces.

Field names follow Razorpay's actual settlement recon report rather than
names we invented, so that the mapping from our synthetic data to a real
export is a rename at most. See `docs/02-THE-MONEY-RULES.md`.

Everything here is frozen. Reconciliation reads facts and writes conclusions;
it never edits the facts. Immutability makes that structural instead of a
convention people remember to follow.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from milan.domain.enums import CardType, EntityType, PaymentMethod
from milan.domain.money import Paise


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True)


class Order(_Record):
    """What the merchant sold. Source of truth for the sale side."""

    order_id: str
    order_receipt: str
    amount: Paise
    currency: str = "INR"
    created_at: datetime


class Payment(_Record):
    """A captured payment against an order."""

    payment_id: str
    order_id: str
    amount: Paise
    method: PaymentMethod
    card_type: CardType | None = None
    card_network: str | None = None
    captured_at: datetime


class Refund(_Record):
    """A refund against a payment.

    Refunds are not paid out as their own debit. They are netted into
    whichever settlement batch is running when they clear — typically 5-7
    working days later, which is usually a batch with no other relationship
    to the original sale. That lag is the single most common reason a naive
    matcher reports a variance it cannot explain.
    """

    refund_id: str
    payment_id: str
    amount: Paise
    created_at: datetime


class Adjustment(_Record):
    """A chargeback or gateway adjustment netted out of a batch."""

    adjustment_id: str
    payment_id: str | None
    amount: Paise
    reason: str
    created_at: datetime


class SettlementRow(_Record):
    """One line of the gateway's settlement recon report.

    A row is either a credit (a payment being settled) or a debit (a refund
    or adjustment being recovered). `amount` is always positive; direction
    lives in `debit` / `credit`.
    """

    entity_id: str
    type: EntityType
    debit: Paise
    credit: Paise
    amount: Paise
    currency: str = "INR"
    fee: Paise
    tax: Paise
    on_hold: bool = False
    settled: bool = True
    created_at: datetime
    settled_at: datetime | None
    settlement_id: str | None
    settlement_utr: str | None
    order_id: str | None = None
    order_receipt: str | None = None
    payment_id: str | None = None
    method: PaymentMethod | None = None
    card_network: str | None = None
    card_type: CardType | None = None
    dispute_id: str | None = None

    @property
    def signed_net(self) -> Paise:
        """This row's contribution to the batch payout, sign included."""
        return Paise(self.credit - self.debit)


class Settlement(_Record):
    """A payout batch the gateway says it has sent.

    `settlement_utr` is the join key to the bank statement. When it survives
    intact, reconciliation is trivial. Half of this problem exists because it
    frequently does not.
    """

    settlement_id: str
    settlement_utr: str
    amount: Paise
    fee: Paise
    tax: Paise
    settled_at: datetime
    entity_ids: tuple[str, ...]


class BankCredit(_Record):
    """A credit line on the merchant's bank statement — what actually arrived.

    The bank does not know about orders, fees or GST. It knows an amount, a
    date, and a narration string that may or may not still contain a usable
    UTR. This is the record everything else has to be proved against.
    """

    credit_id: str
    amount: Paise
    value_date: date
    narration: str
    utr: str | None
    """Parsed out of the narration. `None` when the narration was unusable."""
