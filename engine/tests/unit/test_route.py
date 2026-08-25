"""Route splits: part of a payment paid on to a linked account.

The first deferred item that turned out to be more than another rate. The
0.1% commission is indeed just a rate; the *transfer* is a debit against the
payout that is not a reversal, and every debit this engine had seen before was
money coming back.
"""

from __future__ import annotations

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.enums import EntityType
from milan.domain.money import Paise
from milan.domain.rates import RateCard
from milan.evaluation.harness import evaluate, to_recon_input
from milan.persistence.store import content_hash
from milan.recon.pipeline import ReconciliationPipeline, RunMetadata


def _dataset(share: float, seed: int = 4, difficulty: Difficulty = Difficulty.ADVERSARIAL):
    return ChaosEngine(
        GenerationConfig(
            seed=seed,
            difficulty=difficulty,
            order_count=250,
            route_probability=share,
        )
    ).generate()


def _transfers(dataset):
    return [row for row in dataset.settlement_rows if row.type is EntityType.TRANSFER]


class TestTheProductOffChangesNothing:
    def test_a_zero_share_reproduces_the_default_dataset(self) -> None:
        default = ChaosEngine(
            GenerationConfig(seed=4, difficulty=Difficulty.ADVERSARIAL, order_count=250)
        ).generate()
        assert content_hash(_dataset(0.0)) == content_hash(default)

    def test_no_transfer_rows_at_all(self) -> None:
        assert not _transfers(_dataset(0.0))


class TestTheRowsAreShapedLikeRazorpayReportsThem:
    def test_a_transfer_settles_with_the_payment_it_came_from(self) -> None:
        """Not like a refund, which lands in whichever later batch fits.

        A refund is a reversal and can be recovered from any batch big enough.
        A transfer is a share of the sale, so it leaves with the money it was
        taken from, and a matcher that assumed otherwise would be looking for
        it in the wrong payout.
        """
        dataset = _dataset(0.5)
        by_payment = {p.payment_id: p for p in dataset.payments}
        payment_settlements = {
            row.payment_id: row.settlement_id
            for row in dataset.settlement_rows
            if row.type is EntityType.PAYMENT
        }
        transfers = _transfers(dataset)
        assert transfers
        for transfer in transfers:
            assert transfer.payment_id in by_payment
            assert transfer.settlement_id == payment_settlements[transfer.payment_id]

    def test_the_debit_column_is_the_whole_cash_impact(self) -> None:
        """`credit - debit` has to stay the row's true effect on the payout."""
        for transfer in _transfers(_dataset(0.5)):
            assert transfer.debit == transfer.amount + transfer.fee + transfer.tax
            assert transfer.credit == Paise(0)

    def test_the_commission_is_the_contracted_rate(self) -> None:
        rates = RateCard()
        for transfer in _transfers(_dataset(0.5)):
            assert transfer.fee == rates.route_fee(transfer.amount)


class TestTheProofNamesThemSeparately:
    """A marketplace told its Route commission was an instant refund charge
    has been given a confident wrong answer, which is the one thing this
    engine claims never to do."""

    @staticmethod
    def _proof_with_route():
        dataset = ChaosEngine(
            GenerationConfig(
                seed=4,
                difficulty=Difficulty.REALISTIC,
                order_count=200,
                route_probability=0.4,
            )
        ).generate()
        report = ReconciliationPipeline(rates=RateCard()).run(
            to_recon_input(dataset), RunMetadata(seed=4, difficulty="realistic")
        )
        return next(
            proof
            for proof in report.proofs
            if proof.balances and any("Routed" in line.label for line in proof.lines)
        )

    def test_the_transfer_and_its_commission_are_two_lines(self) -> None:
        labels = [line.label for line in self._proof_with_route().lines]
        assert any(label.startswith("Routed to linked accounts") for label in labels)
        assert any(label.startswith("Route commission") for label in labels)

    def test_the_commission_is_never_called_a_refund_charge(self) -> None:
        proof = self._proof_with_route()
        charges = [line for line in proof.lines if "Instant refund charges" in line.label]
        transfers = {
            row
            for line in proof.lines
            if line.label.startswith("Route commission")
            for row in line.refs
        }
        assert not (transfers & {ref for line in charges for ref in line.refs})

    def test_the_credit_still_reconstructs_to_zero(self) -> None:
        assert self._proof_with_route().residual == Paise(0)


class TestTheEngineHoldsUnderIt:
    """The regression this feature actually found.

    Emitting the rows without reducing what the batch had left to pay out put
    the report and the payout on two different batches: every affected credit
    came up short by exactly the amount routed, and no rung could match it.
    Match rate fell to 4.7% at a 60% Route share while precision stayed at
    100% - the engine refusing rather than guessing, which is why the bug
    looked like difficult data instead of a defect.
    """

    @pytest.mark.parametrize("share", [0.0, 0.25, 0.6])
    def test_match_rate_and_precision_do_not_move(self, share: float) -> None:
        card = evaluate(_dataset(share), headline_only=True).headline
        assert card.match_rate == 1.0
        assert card.precision == 1.0

    def test_every_claimed_proof_balances(
        self,
    ) -> None:
        card = evaluate(_dataset(0.6), headline_only=True).headline
        assert card.proofs_claimed == card.proofs_balanced
