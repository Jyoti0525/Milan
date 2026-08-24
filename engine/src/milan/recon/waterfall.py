"""The waterfall solver: turning a matched batch into a proof.

A match says "this credit is that settlement". That is a claim, not evidence.
This module tries to turn it into evidence by rebuilding the credited amount
from its parts - orders in, fee out, GST out, withholding out, refunds and
chargebacks out - and checking that what is left is nothing.

If a rupee cannot be placed, the proof fails and the credit becomes an
exception. A proof that ends with an unexplained remainder is not a weaker
proof; it is not a proof.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from milan.domain.enums import EntityType, MatchStrategy
from milan.domain.money import Paise, apply_rate, format_inr
from milan.domain.rates import RateCard
from milan.domain.records import BankCredit, SettlementRow
from milan.domain.results import Proof, ProofLine
from milan.recon.batches import GatewayBatch


class UnprovenCredit(BaseModel):
    """A match that could not be reconstructed to the paisa."""

    model_config = ConfigDict(frozen=True)

    credit_id: str
    settlement_id: str
    residual: Paise
    lines: tuple[ProofLine, ...]
    reason: str


def prove(
    credit: BankCredit,
    batch: GatewayBatch,
    strategy: MatchStrategy,
    confidence: float,
    rates: RateCard,
) -> Proof | UnprovenCredit:
    """Rebuild a bank credit from the rows that should compose it."""
    lines = _build_lines(batch, rates)
    explained = Paise(sum(line.amount for line in lines))
    gap = Paise(credit.amount - explained)

    if gap != 0:
        if abs(gap) > batch.rounding_allowance:
            return UnprovenCredit(
                credit_id=credit.credit_id,
                settlement_id=batch.settlement_id,
                residual=gap,
                lines=lines,
                reason=(
                    f"{format_inr(Paise(abs(gap)))} of this credit is not explained by "
                    f"its {len(batch.rows)} settlement rows"
                ),
            )
        lines = (*lines, _drift_line(gap, batch))

    return Proof(
        credit_id=credit.credit_id,
        settlement_id=batch.settlement_id,
        credit_amount=credit.amount,
        lines=lines,
        strategy=strategy,
        confidence=confidence,
    )


def _build_lines(batch: GatewayBatch, rates: RateCard) -> tuple[ProofLine, ...]:
    """One line per thing that happened to the money, in the order it happened."""
    lines: list[ProofLine] = [_settled_payments(batch)]

    if batch.fee:
        lines.append(
            ProofLine(
                label="Platform fee",
                amount=Paise(-batch.fee),
                refs=tuple(row.entity_id for row in batch.payment_rows if row.fee),
            )
        )
    if batch.tax:
        lines.append(
            ProofLine(
                label=f"GST on platform fee @{rates.gst:.0%}",
                amount=Paise(-batch.tax),
                refs=tuple(row.entity_id for row in batch.payment_rows if row.tax),
            )
        )

    withheld = _withholding(batch, rates)
    if withheld is not None:
        lines.append(withheld)

    lines.extend(_recovered(batch, EntityType.REFUND, "Refunds recovered"))
    lines.extend(_recovered(batch, EntityType.ADJUSTMENT, "Chargebacks and adjustments"))
    return tuple(lines)


def _settled_payments(batch: GatewayBatch) -> ProofLine:
    rows = batch.payment_rows
    return ProofLine(
        label=f"Settled payments ({len(rows)})",
        amount=batch.gross,
        refs=tuple(row.entity_id for row in rows),
    )


def _withholding(batch: GatewayBatch, rates: RateCard) -> ProofLine | None:
    """Recover any per-row deduction the fee and GST columns do not account for.

    A settlement report has a fee column and a tax column and nothing else, so
    a withholding shows up only as the gap between what a row was worth and
    what it credited. That gap is named only when it matches the statutory
    rate on every affected row; otherwise it stays unexplained, because
    labelling an unknown deduction "TDS" would be a guess wearing a citation.
    """
    implied = {row.entity_id: _implied_deduction(row) for row in batch.payment_rows}
    withheld = {entity_id: amount for entity_id, amount in implied.items() if amount}
    if not withheld:
        return None

    by_id = {row.entity_id: row for row in batch.payment_rows}
    statutory = all(
        amount == apply_rate(by_id[entity_id].amount, rates.tds)
        for entity_id, amount in withheld.items()
    )
    label = (
        f"TDS under Section 194-O @{rates.tds:.0%}"
        if statutory
        else "Unattributed per-transaction deduction"
    )
    return ProofLine(
        label=label,
        amount=Paise(-sum(withheld.values())),
        refs=tuple(sorted(withheld)),
    )


def _implied_deduction(row: SettlementRow) -> Paise:
    """What came off this row beyond the fee and the GST on it."""
    return Paise(row.amount - row.fee - row.tax - row.credit)


def _recovered(batch: GatewayBatch, kind: EntityType, label: str) -> list[ProofLine]:
    rows = [row for row in batch.debit_rows if row.type is kind]
    if not rows:
        return []
    return [
        ProofLine(
            label=f"{label} ({len(rows)})",
            amount=Paise(-sum(row.debit for row in rows)),
            refs=tuple(row.entity_id for row in rows),
        )
    ]


def _drift_line(gap: Paise, batch: GatewayBatch) -> ProofLine:
    """Name the paise that per-row and batch-level rounding disagree about.

    This line is the difference between a report that foots and a bank that
    agrees. Merchants are routinely told to ignore it. It is written down
    here, with the rows it came from, because an amount nobody can explain is
    how a real loss stays invisible.
    """
    return ProofLine(
        label="Rounding drift (per-transaction fee vs batch-level GST)",
        amount=gap,
        refs=tuple(row.entity_id for row in batch.payment_rows if row.tax),
    )
