"""Reconciliation behaviour, especially the refusals.

The easy assertions - correct matches produce correct proofs - are covered by
the oracle and end-to-end tests. What is tested here is the part that is easy
to get quietly wrong: what happens when the evidence does not support an
answer.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.enums import EntityType, ExceptionCode, MatchStrategy, PaymentMethod
from milan.domain.money import Paise, from_rupees
from milan.domain.rates import RateCard, compute_deductions
from milan.domain.records import BankCredit, SettlementRow
from milan.domain.results import UnprovenCredit
from milan.evaluation.harness import to_recon_input
from milan.recon.batches import BatchGroup, rebuild_batches
from milan.recon.matching.cascade import Cascade
from milan.recon.matching.exact import extract_utr
from milan.recon.pipeline import ReconciliationPipeline, RunMetadata
from milan.recon.waterfall import prove

SETTLED_AT = datetime(2026, 7, 8, 11, 0)
EXACT = MatchStrategy.EXACT_UTR


def payment_row(entity_id: str, rupees: str, settlement: str = "setl_1") -> SettlementRow:
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
        settled_at=SETTLED_AT,
        settlement_id=settlement,
        settlement_utr="UTR000000001",
        payment_id=entity_id,
        method=PaymentMethod.UPI,
    )


def credit(amount: Paise, utr: str | None = "UTR000000001") -> BankCredit:
    return BankCredit(
        credit_id="bank_1",
        amount=amount,
        value_date=date(2026, 7, 8),
        narration=f"NEFT-{utr}-RAZORPAY" if utr else "NEFT INWARD RAZORPAY",
        utr=utr,
    )


class TestUtrExtraction:
    @pytest.mark.parametrize(
        ("narration", "expected"),
        [
            ("NEFT-25CSMU6FGK88-RAZORPAY SOFTWARE PVT LTD", "25CSMU6FGK88"),
            ("IMPS/25CSMU6FGK88/RAZORPAY/SETTLEMENT", "25CSMU6FGK88"),
            ("UTR25CSMU6FGK88 RAZORPAY PAYOUT", "UTR25CSMU6FGK88"),
        ],
    )
    def test_pulls_the_reference_out_of_free_text(self, narration: str, expected: str) -> None:
        assert extract_utr(narration) == expected

    @pytest.mark.parametrize(
        "narration",
        [
            "NEFT INWARD RAZORPAY SOFTWARE PVT LTD",
            "IMPS/RZPY/SETTLEMENT",
            "UPI/CR/SUPPLIER REFUND",
        ],
    )
    def test_returns_nothing_when_there_is_nothing_to_find(self, narration: str) -> None:
        """Inventing a reference would be worse than admitting there is none."""
        assert extract_utr(narration) is None


class TestTheWaterfall:
    def test_a_clean_batch_reconstructs_to_zero(self) -> None:
        rows = (payment_row("pay_1", "10000"), payment_row("pay_2", "5000"))
        group = BatchGroup.of(rebuild_batches(rows)[0])
        result = prove(credit(group.expected_net), group, EXACT, 1.0, RateCard())
        assert not isinstance(result, UnprovenCredit)
        assert result.balances
        assert result.residual == 0

    def test_lines_carry_the_rows_that_justify_them(self) -> None:
        rows = (payment_row("pay_1", "10000"), payment_row("pay_2", "5000"))
        group = BatchGroup.of(rebuild_batches(rows)[0])
        result = prove(credit(group.expected_net), group, EXACT, 1.0, RateCard())
        assert not isinstance(result, UnprovenCredit)
        assert all(line.refs for line in result.lines)

    def test_a_credit_that_does_not_reconstruct_is_refused(self) -> None:
        """Not a low-confidence proof. Not a proof."""
        rows = (payment_row("pay_1", "10000"),)
        group = BatchGroup.of(rebuild_batches(rows)[0])
        short = Paise(group.expected_net - from_rupees("500"))
        result = prove(credit(short), group, EXACT, 1.0, RateCard())
        assert isinstance(result, UnprovenCredit)
        assert result.residual == -from_rupees("500")

    def test_drift_within_the_allowance_is_named_not_absorbed(self) -> None:
        rows = tuple(payment_row(f"pay_{i}", "999.99") for i in range(6))
        group = BatchGroup.of(rebuild_batches(rows)[0])
        drifted = Paise(group.expected_net - 2)
        result = prove(credit(drifted), group, EXACT, 1.0, RateCard())
        assert not isinstance(result, UnprovenCredit)
        assert result.balances
        assert any("Rounding drift" in line.label for line in result.lines)


class TestRefusal:
    def test_two_credits_cannot_claim_the_same_settlement(self) -> None:
        rows = (payment_row("pay_1", "10000"),)
        batches = rebuild_batches(rows)
        amount = batches[0].expected_net
        twins = (
            credit(amount, utr=None).model_copy(update={"credit_id": "bank_a"}),
            credit(amount, utr=None).model_copy(update={"credit_id": "bank_b"}),
        )
        attempts = Cascade().run(twins, batches)
        assert not attempts["bank_a"].resolved
        assert not attempts["bank_b"].resolved

    def test_ambiguity_survives_into_the_exception(self) -> None:
        """The reason has to reach the queue, or a person cannot act on it."""
        rows = (payment_row("pay_1", "10000"),)
        batches = rebuild_batches(rows)
        amount = batches[0].expected_net
        twins = (
            credit(amount, utr=None).model_copy(update={"credit_id": "bank_a"}),
            credit(amount, utr=None).model_copy(update={"credit_id": "bank_b"}),
        )
        attempt = Cascade().run(twins, batches)["bank_a"]
        assert "equally well" in attempt.note or "nothing distinguishes" in attempt.note


class TestEndToEnd:
    @pytest.mark.parametrize("difficulty", list(Difficulty))
    def test_every_credit_is_either_proved_or_explained(self, difficulty: Difficulty) -> None:
        """No credit may be silently dropped.

        A credit that is neither proved nor raised as an exception has left
        the merchant's books without anyone deciding anything about it.
        """
        dataset = ChaosEngine(
            GenerationConfig(seed=11, difficulty=difficulty, order_count=200)
        ).generate()
        report = ReconciliationPipeline().run(
            to_recon_input(dataset), RunMetadata(seed=11, difficulty=difficulty.value)
        )
        accounted = {proof.credit_id for proof in report.proofs} | {
            exception.subject_id for exception in report.exceptions
        }
        missing = [c.credit_id for c in dataset.bank_credits if c.credit_id not in accounted]
        assert not missing

    @pytest.mark.parametrize("difficulty", list(Difficulty))
    def test_every_reported_proof_balances(self, difficulty: Difficulty) -> None:
        dataset = ChaosEngine(
            GenerationConfig(seed=11, difficulty=difficulty, order_count=200)
        ).generate()
        report = ReconciliationPipeline().run(
            to_recon_input(dataset), RunMetadata(seed=11, difficulty=difficulty.value)
        )
        assert all(proof.balances for proof in report.proofs)

    def test_a_missing_payout_is_reported_against_the_settlement(self) -> None:
        dataset = ChaosEngine(
            GenerationConfig(seed=11, difficulty=Difficulty.REALISTIC, order_count=200)
        ).generate()
        report = ReconciliationPipeline().run(
            to_recon_input(dataset), RunMetadata(seed=11, difficulty="realistic")
        )
        flagged = {
            exception.subject_id
            for exception in report.exceptions
            if exception.code is ExceptionCode.MISSING_SETTLEMENT
        }
        assert set(dataset.answer_key.missing_settlement_ids) <= flagged

    def test_running_twice_gives_the_same_answer(self) -> None:
        """Determinism is a property of the pipeline, not only the generator."""
        dataset = ChaosEngine(
            GenerationConfig(seed=11, difficulty=Difficulty.ADVERSARIAL, order_count=200)
        ).generate()
        data = to_recon_input(dataset)
        metadata = RunMetadata(seed=11, difficulty="adversarial")
        first = ReconciliationPipeline().run(data, metadata)
        second = ReconciliationPipeline().run(data, metadata)
        assert first.proofs == second.proofs
        assert first.exceptions == second.exceptions


class TestMoneyThatNeverArrived:
    """Payments the settlement report never mentions.

    Every technique above this point starts from a bank credit and asks what
    explains it, which can only ever find money that arrived. This is the one
    exception that no amount of matching can reach: the credits all reconcile,
    nothing is unmatched, and the money is still gone.
    """

    def _dataset(self, difficulty: Difficulty) -> object:
        return ChaosEngine(
            GenerationConfig(seed=42, difficulty=difficulty, order_count=500)
        ).generate()

    def _run(self, dataset: object) -> object:
        return ReconciliationPipeline().run(
            to_recon_input(dataset),  # type: ignore[arg-type]
            RunMetadata(seed=dataset.seed, difficulty=dataset.difficulty),  # type: ignore[attr-defined]
        )

    def test_unreported_payments_are_flagged(self) -> None:
        dataset = self._dataset(Difficulty.MESSY)
        expected = set(dataset.answer_key.unreported_payment_ids)  # type: ignore[attr-defined]
        assert expected, "the messy tier is supposed to drop some payments"

        flagged = {
            exception.subject_id
            for exception in self._run(dataset).exceptions  # type: ignore[attr-defined]
            if exception.code is ExceptionCode.UNSETTLED_PAYMENT
        }
        assert flagged <= expected, (
            "flagged a payment the report does account for - a merchant told to chase "
            "settled money stops trusting the queue"
        )
        assert flagged, "found none of the payments the gateway never reported"

    def test_payments_still_within_their_settlement_cycle_are_left_alone(self) -> None:
        """T+2 has not elapsed yet. Pending is not missing.

        This is the assertion that keeps the exception queue usable. Every
        month ends with payments legitimately awaiting settlement, and a rule
        that flags them buries the real cases under the ordinary ones.
        """
        dataset = self._dataset(Difficulty.CLEAN)
        assert not dataset.answer_key.unreported_payment_ids  # type: ignore[attr-defined]

        flagged = [
            exception
            for exception in self._run(dataset).exceptions  # type: ignore[attr-defined]
            if exception.code is ExceptionCode.UNSETTLED_PAYMENT
        ]
        assert not flagged, [exception.subject_id for exception in flagged]
