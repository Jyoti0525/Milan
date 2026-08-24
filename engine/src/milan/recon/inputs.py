"""What reconciliation is allowed to see.

Three files a merchant already has, and nothing else. In particular the
gateway's own settlement summary is not an input: the batch totals are
rebuilt from the report rows, the same way a finance team would have to.

That restriction is not pedantry. The gateway's summary already contains the
batch-level GST figure, and handing it over would quietly solve the rounding
problem that this system exists to explain.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from milan.domain.records import BankCredit, Order, Payment, SettlementRow


class ReconInput(BaseModel):
    """The three merchant-side files, normalised."""

    model_config = ConfigDict(frozen=True)

    orders: tuple[Order, ...]
    payments: tuple[Payment, ...]
    settlement_rows: tuple[SettlementRow, ...]
    bank_credits: tuple[BankCredit, ...]

    @property
    def record_count(self) -> int:
        return (
            len(self.orders)
            + len(self.payments)
            + len(self.settlement_rows)
            + len(self.bank_credits)
        )
