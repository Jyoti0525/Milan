"""Rebuilding the gateway's batches from the report rows.

A settlement report is a flat list of rows. What the merchant needs is the
batch: which rows were paid together, what they should have added up to, and
when. This module does that grouping and nothing else - no matching, no
judgment, just arithmetic that has one right answer.

`expected_net` here is what the rows say. What the bank credited can differ
from it by a few paise, because fees round per transaction and GST rounds
once on the batch total. That gap is not an error to be suppressed; it is the
thing the waterfall solver has to name.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from pydantic import BaseModel, ConfigDict

from milan.domain.enums import EntityType
from milan.domain.money import ZERO, Paise
from milan.domain.records import SettlementRow


class GatewayBatch(BaseModel):
    """One settlement, reconstructed from the rows that carry its id."""

    model_config = ConfigDict(frozen=True)

    settlement_id: str
    settlement_utr: str | None
    settled_on: date
    rows: tuple[SettlementRow, ...]

    @property
    def payment_rows(self) -> tuple[SettlementRow, ...]:
        return tuple(row for row in self.rows if row.type is EntityType.PAYMENT)

    @property
    def debit_rows(self) -> tuple[SettlementRow, ...]:
        return tuple(row for row in self.rows if row.type is not EntityType.PAYMENT)

    @property
    def gross(self) -> Paise:
        return Paise(sum(row.amount for row in self.payment_rows))

    @property
    def fee(self) -> Paise:
        return Paise(sum(row.fee for row in self.rows))

    @property
    def tax(self) -> Paise:
        """GST as the rows report it, summed. Not necessarily what was charged."""
        return Paise(sum(row.tax for row in self.rows))

    @property
    def debits(self) -> Paise:
        return Paise(sum(row.debit for row in self.debit_rows))

    @property
    def expected_net(self) -> Paise:
        return Paise(sum(row.signed_net for row in self.rows))

    @property
    def rounding_allowance(self) -> Paise:
        """How far the bank may legitimately differ from the rows.

        Each per-row GST rounding can be off by at most half a paisa, and the
        batch-level rounding by at most half a paisa more. So the widest
        honest gap on a batch of n taxed rows is (n + 1) / 2 paise.

        The allowance is deliberately derived rather than picked. A fixed
        "within a rupee" tolerance would swallow real errors on small batches
        and reject real drift on large ones.
        """
        taxed_rows = sum(1 for row in self.rows if row.tax != 0)
        return Paise((taxed_rows + 1) // 2 + 1)


def rebuild_batches(rows: tuple[SettlementRow, ...]) -> tuple[GatewayBatch, ...]:
    """Group report rows into batches, in settlement date order.

    Rows with no settlement id are pending: a refund raised but not yet
    recovered from any batch. They belong to no batch and are handled
    separately, because treating them as a discrepancy would flag ordinary
    gateway behaviour as an error.
    """
    grouped: dict[str, list[SettlementRow]] = defaultdict(list)
    for row in rows:
        if row.settlement_id is not None:
            grouped[row.settlement_id].append(row)

    batches: list[GatewayBatch] = []
    for settlement_id, batch_rows in grouped.items():
        ordered = tuple(sorted(batch_rows, key=lambda row: row.entity_id))
        settled_at = next((row.settled_at for row in ordered if row.settled_at), None)
        if settled_at is None:
            continue
        batches.append(
            GatewayBatch(
                settlement_id=settlement_id,
                settlement_utr=next(
                    (row.settlement_utr for row in ordered if row.settlement_utr), None
                ),
                settled_on=settled_at.date(),
                rows=ordered,
            )
        )
    batches.sort(key=lambda batch: (batch.settled_on, batch.settlement_id))
    return tuple(batches)


def pending_rows(rows: tuple[SettlementRow, ...]) -> tuple[SettlementRow, ...]:
    """Rows the gateway has not recovered from any batch yet."""
    return tuple(row for row in rows if row.settlement_id is None)


def total_pending(rows: tuple[SettlementRow, ...]) -> Paise:
    return Paise(sum(row.debit for row in pending_rows(rows))) or ZERO
