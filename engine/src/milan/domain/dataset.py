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
        """Records the engine will actually read.

        Counts the three merchant-side files and nothing else. Refunds and
        chargebacks are excluded deliberately: they reach the engine as
        settlement report rows, so counting the underlying entities as well
        would inflate the figure by double-counting the same records.

        Razorpay's bar is a 50+ record batch and this is the number that
        claim is measured against, so it has to mean one thing everywhere.
        """
        return (
            len(self.orders)
            + len(self.payments)
            + len(self.settlement_rows)
            + len(self.bank_credits)
        )
