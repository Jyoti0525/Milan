"""Naming a shortfall as the refund that caused it.

This one check was, on its own, most of the difference between explaining
55% of shortfalls and explaining 64%. It looked for a refund whose debit
*equalled* the shortfall, and a residual carries the same per-row against
batch-level tax rounding that every other figure in this engine carries - so
a credit short by one paisa more than a refund got no explanation at all,
while the prover two modules away was already calling that same paisa drift.

The tests here fence both directions of that fix. Widening a tolerance is the
easiest way in the world to turn a refusal into a confident wrong answer, so
what is tested is not only that the near-miss is now named, but that a
genuine miss is still refused and that a shortfall two refunds could explain
is refused as well.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from milan.domain.enums import EntityType, ExceptionCode, PaymentMethod
from milan.domain.money import Paise, from_rupees
from milan.domain.rates import RateCard, compute_deductions
from milan.domain.records import SettlementRow
from milan.recon.batches import BatchGroup, rebuild_batches
from milan.recon.triage import Categoriser
from milan.recon.waterfall import UnprovenCredit

GROUP_SETTLEMENT = "setl_here"
OTHER_SETTLEMENT = "setl_elsewhere"


def payment_row(entity_id: str, rupees: str, settlement: str = GROUP_SETTLEMENT) -> SettlementRow:
    gross = from_rupees(rupees)
    deductions = compute_deductions(gross, PaymentMethod.UPI, None, RateCard())
    return SettlementRow(
        entity_id=entity_id,
        type=EntityType.PAYMENT,
        debit=Paise(0),
        credit=deductions.net,
        amount=gross,
        fee=deductions.fee,
        tax=deductions.tax,
        created_at=datetime(2026, 7, 6, 12, 0),
        settled_at=datetime(2026, 7, 8, 11, 0),
        settlement_id=settlement,
        settlement_utr="UTR000000001",
        payment_id=entity_id,
        method=PaymentMethod.UPI,
    )


def refund_row(entity_id: str, debit: Paise, settlement: str = OTHER_SETTLEMENT) -> SettlementRow:
    """A refund netted out of some other batch entirely."""
    return SettlementRow(
        entity_id=entity_id,
        type=EntityType.REFUND,
        debit=debit,
        credit=Paise(0),
        amount=debit,
        fee=Paise(0),
        tax=Paise(0),
        created_at=datetime(2026, 7, 10, 9, 0),
        settled_at=datetime(2026, 7, 14, 11, 0),
        settlement_id=settlement,
        settlement_utr="UTR000000002",
        payment_id=None,
        method=PaymentMethod.UPI,
    )


def group_of(*rows: SettlementRow) -> BatchGroup:
    return BatchGroup.of(rebuild_batches(rows)[0])


def short_by(group: BatchGroup, shortfall: Paise) -> UnprovenCredit:
    return UnprovenCredit(
        credit_id="bank_1",
        settlement_ids=(GROUP_SETTLEMENT,),
        residual=Paise(-shortfall),
        lines=(),
        reason=f"{shortfall} paise of this credit is not explained by its rows",
    )


def categorise(
    group: BatchGroup, shortfall: Paise, *refunds: SettlementRow
) -> tuple[ExceptionCode, str, dict[str, str]]:
    found = Categoriser(RateCard()).unproven_credit(
        short_by(group, shortfall), group, (*group.rows, *refunds)
    )
    return found.code, found.summary, found.evidence


@pytest.fixture
def group() -> BatchGroup:
    """A batch big enough to carry a real allowance.

    Six taxed payment rows give (6 + 1) // 2 + 1 = 4 paise, which is wide
    enough to test either side of the boundary without contriving the number.
    """
    return group_of(*(payment_row(f"pay_{n}", "10000") for n in range(6)))


class TestTheAllowanceIsTheSameOneTheProverUses:
    def test_the_allowance_is_derived_from_the_rows(self, group: BatchGroup) -> None:
        """Not a constant. Six taxed rows, so four paise."""
        assert group.rounding_allowance == 4

    def test_an_exact_refund_is_named(self, group: BatchGroup) -> None:
        """The behaviour that already worked, kept working."""
        shortfall = from_rupees("500")
        code, summary, evidence = categorise(group, shortfall, refund_row("rfnd_x", shortfall))
        assert code is ExceptionCode.PARTIAL_PAYMENT
        assert "rfnd_x" in summary
        assert evidence["rounding_drift"] == "Rs 0.00"

    @pytest.mark.parametrize("drift", [-4, -1, 1, 4])
    def test_a_refund_inside_the_allowance_is_named(self, group: BatchGroup, drift: int) -> None:
        """The fix. One paisa either way used to mean no explanation at all."""
        shortfall = Paise(from_rupees("500") + drift)
        code, summary, evidence = categorise(
            group, shortfall, refund_row("rfnd_x", from_rupees("500"))
        )
        assert code is ExceptionCode.PARTIAL_PAYMENT
        assert "rfnd_x" in summary
        assert evidence["rounding_drift"] == f"{'-' if drift < 0 else ''}Rs 0.0{abs(drift)}"

    def test_the_drift_is_stated_rather_than_papered_over(self, group: BatchGroup) -> None:
        """A reader checking this against their own export will see two
        different numbers, and a sentence claiming they are the same figure
        would read as the tool being wrong."""
        shortfall = Paise(from_rupees("500") + 2)
        _, summary, _ = categorise(group, shortfall, refund_row("rfnd_x", from_rupees("500")))
        assert "Rs 0.02 more than refund rfnd_x" in summary
        assert "rounding drift" in summary

    def test_the_direction_of_the_drift_is_right(self, group: BatchGroup) -> None:
        shortfall = Paise(from_rupees("500") - 2)
        _, summary, _ = categorise(group, shortfall, refund_row("rfnd_x", from_rupees("500")))
        assert "Rs 0.02 less than refund rfnd_x" in summary


class TestWideningATolerancePutsRefusalsAtRisk:
    """These assert on `PARTIAL_PAYMENT` rather than on `UNEXPLAINED`.

    Declining to name a refund is not the same as having nothing to say. When
    this check passes, the tax and fee checks behind it get their turn, and on
    a shortfall that happens to read as a plausible surcharge one of them will
    answer - correctly, and for reasons that have nothing to do with the code
    under test here. Asserting the final code would tie every test in this
    class to the behaviour of two others.
    """

    def test_a_refund_outside_the_allowance_is_not_named(self, group: BatchGroup) -> None:
        """Five paise on a four-paise allowance is not rounding. It is a
        different number, and calling it a refund would be a guess dressed as
        a finding."""
        shortfall = Paise(from_rupees("500") + 5)
        code, _, _ = categorise(group, shortfall, refund_row("rfnd_x", from_rupees("500")))
        assert code is not ExceptionCode.PARTIAL_PAYMENT

    def test_two_candidates_inside_the_window_name_neither(self, group: BatchGroup) -> None:
        """The evidence does not say which, so neither does the report.

        This is the case a wider tolerance actually creates, and refusing it
        is the whole reason the tolerance can be widened at all.
        """
        shortfall = Paise(from_rupees("500") + 1)
        code, _, _ = categorise(
            group,
            shortfall,
            refund_row("rfnd_x", from_rupees("500")),
            refund_row("rfnd_y", Paise(from_rupees("500") + 2)),
        )
        assert code is not ExceptionCode.PARTIAL_PAYMENT

    def test_a_refund_already_inside_this_group_is_not_the_culprit(self, group: BatchGroup) -> None:
        """It was netted out here, so the rows already account for it. Naming
        it would explain the shortfall with money that is not missing."""
        shortfall = from_rupees("500")
        code, _, _ = categorise(
            group, shortfall, refund_row("rfnd_x", shortfall, settlement=GROUP_SETTLEMENT)
        )
        assert code is not ExceptionCode.PARTIAL_PAYMENT

    def test_a_surplus_is_never_a_recovery_gap(self, group: BatchGroup) -> None:
        """More money arrived than the rows account for. A refund taken
        elsewhere cannot explain being paid too much."""
        over = Paise(-from_rupees("500"))
        code, _, _ = categorise(group, over, refund_row("rfnd_x", from_rupees("500")))
        assert code is not ExceptionCode.PARTIAL_PAYMENT
