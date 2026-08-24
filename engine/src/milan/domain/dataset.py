"""A generated dataset: the three merchant-side inputs, plus the answer key."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from milan.domain.records import (
    Adjustment,
    BankCredit,
    Order,
    Payment,
    Refund,
    Settlement,
    SettlementRow,
)
from milan.domain.truth import AnswerKey


class Dataset(BaseModel):
    """Everything one seeded run produces.

    Held together in one object so a run is a single value that can be
    written, re-read, and hashed. Two runs at the same seed must produce
    byte-identical output; `milan reproduce` checks exactly that.
    """

    model_config = ConfigDict(frozen=True)

    seed: int
    difficulty: str

    orders: tuple[Order, ...]
    payments: tuple[Payment, ...]
    refunds: tuple[Refund, ...]
    adjustments: tuple[Adjustment, ...]
    settlement_rows: tuple[SettlementRow, ...]
    settlements: tuple[Settlement, ...]
    bank_credits: tuple[BankCredit, ...]

    answer_key: AnswerKey

    @property
    def record_count(self) -> int:
        """Total records the run had to process.

        Razorpay's bar is a 50+ record batch, so this is the number that
        claim is measured against. Counting only orders would flatter us.
        """
        return (
            len(self.orders)
            + len(self.payments)
            + len(self.refunds)
            + len(self.adjustments)
            + len(self.settlement_rows)
            + len(self.bank_credits)
        )
