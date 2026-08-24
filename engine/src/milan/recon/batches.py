"""Rebuilding the gateway's batches from the report rows.

A settlement report is a flat list of rows. What the merchant needs is the
batch: which rows were paid together, what they should have added up to, and
when. This module does that grouping and nothing else - no matching, no
judgment, just arithmetic that has one right answer.

`expected_net` here is what the rows say. What the bank credited can differ
from it by a few paise, because fees round per transaction and GST rounds
once on the batch total. That gap is not an error to be suppressed; it is the
thing the waterfall solver has to name.

Two shapes live here, and the difference matters. A `GatewayBatch` is one
settlement. A `BatchGroup` is the set of settlements that one bank credit
paid out - usually a group of one, but banks merge transfers and a merchant's
statement then shows a single line for two payouts. Everything downstream
works on groups, so the merged case is the normal path rather than a special
case bolted on beside it.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from pydantic import BaseModel, ConfigDict

from milan.domain.enums import EntityType
from milan.domain.money import ZERO, Paise
from milan.domain.records import SettlementRow


def _payments(rows: tuple[SettlementRow, ...]) -> tuple[SettlementRow, ...]:
    return tuple(row for row in rows if row.type is EntityType.PAYMENT)


def _debits(rows: tuple[SettlementRow, ...]) -> tuple[SettlementRow, ...]:
    return tuple(row for row in rows if row.type is not EntityType.PAYMENT)


def _allowance(rows: tuple[SettlementRow, ...]) -> Paise:
    """How far the bank may legitimately differ from one batch of rows.

    Each per-row GST rounding can be off by at most half a paisa, and the
    batch-level rounding by at most half a paisa more. So the widest honest
    gap on a batch of n taxed rows is (n + 1) / 2 paise.

    The allowance is deliberately derived rather than picked. A fixed "within
    a rupee" tolerance would swallow real errors on small batches and reject
    real drift on large ones.
    """
    taxed = sum(1 for row in rows if row.tax != 0)
    return Paise((taxed + 1) // 2 + 1)


class GatewayBatch(BaseModel):
    """One settlement, reconstructed from the rows that carry its id."""

    model_config = ConfigDict(frozen=True)

    settlement_id: str
    settlement_utr: str | None
    settled_on: date
    rows: tuple[SettlementRow, ...]

    @property
    def payment_rows(self) -> tuple[SettlementRow, ...]:
        return _payments(self.rows)

    @property
    def debit_rows(self) -> tuple[SettlementRow, ...]:
        return _debits(self.rows)

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
        return _allowance(self.rows)


class BatchGroup(BaseModel):
    """The settlements behind one bank credit.

    Almost always a group of one. The exception is the merged transfer, and
    it is the reason this type exists: a credit that covers two payouts
    cannot be proved against either of them alone, and proving it against
    "the closer one" is how a real shortfall gets filed as rounding.
    """

    model_config = ConfigDict(frozen=True)

    batches: tuple[GatewayBatch, ...]

    @classmethod
    def of(cls, *batches: GatewayBatch) -> BatchGroup:
        return cls(batches=tuple(sorted(batches, key=lambda b: b.settlement_id)))

    @property
    def settlement_ids(self) -> tuple[str, ...]:
        return tuple(batch.settlement_id for batch in self.batches)

    @property
    def settlement_set(self) -> frozenset[str]:
        return frozenset(self.settlement_ids)

    @property
    def merged(self) -> bool:
        return len(self.batches) > 1

    @property
    def rows(self) -> tuple[SettlementRow, ...]:
        return tuple(row for batch in self.batches for row in batch.rows)

    @property
    def payment_rows(self) -> tuple[SettlementRow, ...]:
        return _payments(self.rows)

    @property
    def debit_rows(self) -> tuple[SettlementRow, ...]:
        return _debits(self.rows)

    @property
    def gross(self) -> Paise:
        return Paise(sum(batch.gross for batch in self.batches))

    @property
    def fee(self) -> Paise:
        return Paise(sum(batch.fee for batch in self.batches))

    @property
    def tax(self) -> Paise:
        return Paise(sum(batch.tax for batch in self.batches))

    @property
    def debits(self) -> Paise:
        return Paise(sum(batch.debits for batch in self.batches))

    @property
    def expected_net(self) -> Paise:
        return Paise(sum(batch.expected_net for batch in self.batches))

    @property
    def settled_on(self) -> date:
        """The last of the payouts to leave. A merged credit cannot arrive
        before the latest settlement it contains."""
        return max(batch.settled_on for batch in self.batches)

    @property
    def opened_on(self) -> date:
        return min(batch.settled_on for batch in self.batches)

    @property
    def rounding_allowance(self) -> Paise:
        """Summed, not recomputed over the union of rows.

        Each settlement rounds its own GST once, so a group of three carries
        three batch-level roundings. Treating the group as one large batch
        would understate the allowance and turn honest drift into an
        exception.
        """
        return Paise(sum(batch.rounding_allowance for batch in self.batches))


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
