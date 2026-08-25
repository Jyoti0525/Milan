"""The waterfall solver: turning a matched batch group into a proof.

A match says "this credit is that settlement". That is a claim, not evidence.
This module tries to turn it into evidence by rebuilding the credited amount
from its parts - orders in, fee out, GST out, withholding out, refunds and
chargebacks out - and checking that what is left is nothing.

If a rupee cannot be placed, the proof fails and the credit becomes an
exception. A proof that ends with an unexplained remainder is not a weaker
proof; it is not a proof.
"""

from __future__ import annotations

from milan.domain.enums import EntityType, MatchStrategy
from milan.domain.money import Paise, apply_rate, format_inr
from milan.domain.rates import RateCard
from milan.domain.records import BankCredit, SettlementRow
from milan.domain.results import Proof, ProofLine, UnprovenCredit
from milan.recon.batches import BatchGroup


def residual(credit: BankCredit, group: BatchGroup, rates: RateCard) -> Paise:
    """What is left over after rebuilding this credit from the group's rows."""
    lines = _build_lines(group, rates)
    return Paise(credit.amount - sum(line.amount for line in lines))


def provable(credit: BankCredit, group: BatchGroup, rates: RateCard) -> bool:
    """Whether this claim would survive being proved.

    The cheap form of `prove`, for the cascade to consult before it accepts a
    rung's answer. Same arithmetic, same allowance, no proof object built -
    a claim is withdrawn on exactly the grounds it would later have failed
    on, rather than on a looser rule that happens to agree most of the time.
    """
    return abs(residual(credit, group, rates)) <= group.rounding_allowance


def prove(
    credit: BankCredit,
    group: BatchGroup,
    strategy: MatchStrategy,
    confidence: float,
    rates: RateCard,
) -> Proof | UnprovenCredit:
    """Rebuild a bank credit from the rows that should compose it."""
    lines = _build_lines(group, rates)
    explained = Paise(sum(line.amount for line in lines))
    gap = Paise(credit.amount - explained)

    if gap != 0:
        if abs(gap) > group.rounding_allowance:
            return UnprovenCredit(
                credit_id=credit.credit_id,
                settlement_ids=group.settlement_ids,
                residual=gap,
                lines=lines,
                reason=(
                    f"{format_inr(Paise(abs(gap)))} of this credit is not explained by "
                    f"its {len(group.rows)} settlement rows"
                ),
            )
        lines = (*lines, _drift_line(gap, group))

    return Proof(
        credit_id=credit.credit_id,
        settlement_ids=group.settlement_ids,
        credit_amount=credit.amount,
        lines=lines,
        strategy=strategy,
        confidence=confidence,
        drift=gap,
    )


def _build_lines(group: BatchGroup, rates: RateCard) -> tuple[ProofLine, ...]:
    """One line per thing that happened to the money, in the order it happened.

    A merged credit gets one set of lines covering every settlement in it,
    not one set per settlement. The merchant received one amount and the
    proof has to reconstruct that amount; splitting it into per-settlement
    sections would produce sub-totals that match nothing on the statement.
    """
    lines: list[ProofLine] = [_settled_payments(group)]

    if group.fee:
        lines.append(
            ProofLine(
                label="Platform fee",
                amount=Paise(-group.fee),
                refs=tuple(row.entity_id for row in group.payment_rows if row.fee),
            )
        )
    if group.tax:
        lines.append(
            ProofLine(
                label=f"GST on platform fee @{rates.gst:.0%}",
                amount=Paise(-group.tax),
                refs=tuple(row.entity_id for row in group.payment_rows if row.tax),
            )
        )

    withheld = _withholding(group, rates)
    if withheld is not None:
        lines.append(withheld)

    lines.extend(_recovered(group, EntityType.REFUND, "Refunds recovered"))
    lines.extend(_recovered(group, EntityType.ADJUSTMENT, "Chargebacks and adjustments"))

    charges = _refund_charges(group)
    if charges is not None:
        lines.append(charges)
    return tuple(lines)


def _settled_payments(group: BatchGroup) -> ProofLine:
    rows = group.payment_rows
    return ProofLine(
        label=_payments_label(group, len(rows)),
        amount=group.gross,
        refs=tuple(row.entity_id for row in rows),
    )


def _payments_label(group: BatchGroup, count: int) -> str:
    """Say when a single credit is covering more than one payout.

    Someone reading a proof needs to see that immediately. A merged credit
    that looks like an ordinary one is the case where a reader checks the
    total against the wrong settlement and concludes the system is wrong.
    """
    if not group.merged:
        return f"Settled payments ({count})"
    return f"Settled payments ({count}) across {len(group.batches)} settlements"


def _withholding(group: BatchGroup, rates: RateCard) -> ProofLine | None:
    """Recover any per-row deduction the fee and GST columns do not account for.

    A settlement report has a fee column and a tax column and nothing else, so
    a withholding shows up only as the gap between what a row was worth and
    what it credited. That gap is named only when it matches the statutory
    rate on every affected row; otherwise it stays unexplained, because
    labelling an unknown deduction "TDS" would be a guess wearing a citation.
    """
    implied = {row.entity_id: _implied_deduction(row) for row in group.payment_rows}
    withheld = {entity_id: amount for entity_id, amount in implied.items() if amount}
    if not withheld:
        return None

    by_id = {row.entity_id: row for row in group.payment_rows}
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


def _recovered(group: BatchGroup, kind: EntityType, label: str) -> list[ProofLine]:
    """The refunds themselves, with any charge on them stripped back out.

    A refund row's debit is the whole cash impact, so it includes the flat
    fee for an instant refund. Reporting that total here would leave the
    charge invisible - folded into a number the merchant reads as "money
    returned to customers" - which is precisely how a fee nobody agreed to
    stops being noticed.
    """
    rows = [row for row in group.debit_rows if row.type is kind]
    if not rows:
        return []
    return [
        ProofLine(
            label=f"{label} ({len(rows)})",
            amount=Paise(-sum(row.debit - row.fee - row.tax for row in rows)),
            refs=tuple(row.entity_id for row in rows),
        )
    ]


def _refund_charges(group: BatchGroup) -> ProofLine | None:
    """What it cost to send the refunds, as its own line.

    Instant refunds carry a flat charge - Rs 7.99, Rs 11.99 or Rs 14.99 by
    size - while an ordinary refund is free. Flat is the important word. Every
    other deduction in this waterfall scales with the transaction, so a few
    rupees adrift on a large batch reads as rounding; this one does not scale,
    and on a small refund it is a real percentage. Giving it a line of its own
    is the difference between a merchant seeing a charge and seeing noise.
    """
    charged = [row for row in group.debit_rows if row.fee or row.tax]
    if not charged:
        return None
    total = Paise(sum(row.fee + row.tax for row in charged))
    return ProofLine(
        label=f"Instant refund charges ({len(charged)}), incl. GST",
        amount=Paise(-total),
        refs=tuple(row.entity_id for row in charged),
    )


def _drift_line(gap: Paise, group: BatchGroup) -> ProofLine:
    """Name the paise that per-row and batch-level rounding disagree about.

    This line is the difference between a report that foots and a bank that
    agrees. Merchants are routinely told to ignore it. It is written down
    here, with the rows it came from, because an amount nobody can explain is
    how a real loss stays invisible.
    """
    return ProofLine(
        label="Rounding drift (per-transaction fee vs batch-level GST)",
        amount=gap,
        refs=tuple(row.entity_id for row in group.payment_rows if row.tax),
    )
