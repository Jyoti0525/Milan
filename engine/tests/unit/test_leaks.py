"""Finding a charge that is wrong while everything balances.

The one test in this file that carries the whole idea is
`test_a_leak_is_found_in_a_batch_that_balances_perfectly`. Every other
detection in this project starts from something failing to agree with
something else; this one starts from a report that agrees with itself, agrees
with the bank, and proves to zero - and is still wrong.

The rest is about not crying wolf. A false leak is the most expensive mistake
this project can make: a missed one costs a merchant money they were already
losing, but a false one sends them to their account manager to complain about
an overcharge that never happened. So most of what is tested here is what must
*not* be reported.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.enums import CardType, EntityType, PaymentMethod
from milan.domain.money import Paise, apply_rate, from_rupees
from milan.domain.rates import RateCard, compute_deductions
from milan.domain.records import SettlementRow
from milan.evaluation.harness import to_recon_input
from milan.leaks.clusters import cluster, summarise
from milan.leaks.detector import detect
from milan.recon.batches import BatchGroup, rebuild_batches
from milan.recon.pipeline import ReconciliationPipeline, RunMetadata
from milan.recon.waterfall import prove

SETTLED = datetime(2026, 7, 8, 11, 0)


def payment_row(
    entity_id: str,
    rupees: str,
    *,
    method: PaymentMethod = PaymentMethod.CARD,
    declared: CardType | None = CardType.DOMESTIC_CONSUMER,
    charged_as: CardType | None = None,
    settlement: str = "setl_a",
) -> SettlementRow:
    """A row declaring one card type and charged at another's rate.

    `declared` is what the report says the card was; `charged_as` is the rate
    it was actually billed at. Equal means an honest row.
    """
    gross = from_rupees(rupees)
    billed = compute_deductions(gross, method, charged_as or declared, RateCard())
    return SettlementRow(
        entity_id=entity_id,
        type=EntityType.PAYMENT,
        debit=Paise(0),
        credit=billed.net,
        amount=gross,
        fee=billed.fee,
        tax=billed.tax,
        created_at=datetime(2026, 7, 6, 12, 0),
        settled_at=SETTLED,
        settlement_id=settlement,
        settlement_utr="UTR000000001",
        payment_id=entity_id,
        method=method,
        card_type=declared,
        card_network="Visa",
        card_issuer="HDFC Bank",
    )


class TestTheThingNoMatcherCanSee:
    def test_a_leak_is_found_in_a_batch_that_balances_perfectly(self) -> None:
        """The whole idea, in one assertion.

        The batch foots, the credit reconstructs to zero, the proof closes -
        and the merchant was charged the corporate rate on a consumer card.
        There is nothing unmatched to notice, which is why this class of error
        survives in real accounts for years.
        """
        rows = (
            payment_row("pay_1", "10000", charged_as=CardType.DOMESTIC_CORPORATE),
            payment_row("pay_2", "5000"),
        )
        group = BatchGroup.of(rebuild_batches(rows)[0])

        from milan.domain.enums import MatchStrategy
        from milan.domain.records import BankCredit

        credit = BankCredit(
            credit_id="bank_1",
            amount=group.expected_net,
            value_date=date(2026, 7, 8),
            narration="NEFT-UTR000000001-RAZORPAY",
            utr="UTR000000001",
        )
        proof = prove(credit, group, MatchStrategy.EXACT_UTR, 1.0, RateCard())

        assert not isinstance(proof, tuple)
        assert proof.balances, "the batch must reconcile, or this proves nothing"
        assert proof.residual == 0

        found = detect(rows)
        assert len(found) == 1
        assert found[0].payment_id == "pay_1"

    def test_the_overcharge_is_the_difference_in_fee(self) -> None:
        rows = (payment_row("pay_1", "10000", charged_as=CardType.DOMESTIC_CORPORATE),)
        leak = detect(rows)[0]
        gross = from_rupees("10000")
        expected = apply_rate(gross, Decimal("0.0215")) - apply_rate(gross, Decimal("0.02"))
        assert leak.overcharge == expected

    def test_the_gst_on_the_overcharge_is_reported_separately(self) -> None:
        """It is real cash out of the account and it comes back as input tax
        credit. Rolling it into the headline overstates the permanent loss by
        18%, and overstating harm is the same failure as understating it."""
        leak = detect((payment_row("pay_1", "100000", charged_as=CardType.DOMESTIC_CORPORATE),))[0]
        assert leak.gst_on_overcharge > 0
        assert leak.cash_impact == leak.overcharge + leak.gst_on_overcharge
        assert leak.cash_impact > leak.overcharge


class TestWhatMustNeverBeCalledALeak:
    def test_an_honestly_charged_row_is_silent(self) -> None:
        assert detect((payment_row("pay_1", "10000"),)) == ()

    @pytest.mark.parametrize(
        "method",
        [PaymentMethod.UPI, PaymentMethod.NETBANKING, PaymentMethod.WALLET],
    )
    def test_every_non_card_method_on_the_standard_rate_is_silent(
        self, method: PaymentMethod
    ) -> None:
        rows = (payment_row("pay_1", "10000", method=method, declared=None),)
        assert detect(rows) == ()

    def test_an_international_card_at_three_percent_is_not_a_leak(self) -> None:
        """It is contracted at 3%. A detector that flagged the highest rate in
        the card would report every foreign customer as theft."""
        rows = (payment_row("pay_1", "10000", declared=CardType.INTERNATIONAL),)
        assert detect(rows) == ()

    def test_a_refund_row_is_never_examined(self) -> None:
        """A refund carries a flat instant-refund charge rather than a rate.
        Reading a percentage off one would manufacture leaks out of correctly
        charged refunds."""
        row = payment_row("rfnd_1", "10000").model_copy(
            update={"type": EntityType.REFUND, "fee": from_rupees("11.99")}
        )
        assert detect((row,)) == ()

    def test_being_undercharged_is_not_a_finding(self) -> None:
        """The merchant is not out of pocket. It is the gateway's money, and
        reporting it in a queue about missing money would be noise."""
        row = payment_row("pay_1", "10000")
        cheaper = row.model_copy(update={"fee": Paise(row.fee - 500)})
        assert detect((cheaper,)) == ()

    def test_a_row_with_no_method_is_skipped_rather_than_guessed(self) -> None:
        """No method means no contracted rate to compare against, and guessing
        one would be inventing the contract this check exists to enforce."""
        row = payment_row("pay_1", "10000").model_copy(update={"method": None})
        assert detect((row,)) == ()

    def test_the_contracted_rate_is_read_from_the_card_not_assumed(self) -> None:
        """The same row is a leak under one contract and not under another.

        A merchant contracted at 2.15% is not being overcharged when billed
        2.15%, and the only thing that can decide that is the rate card. This
        is the reason it is data rather than a set of constants.
        """
        rows = (payment_row("pay_1", "10000", charged_as=CardType.DOMESTIC_CORPORATE),)
        assert len(detect(rows, RateCard())) == 1
        assert detect(rows, RateCard(standard=Decimal("0.0215"))) == ()


class TestTheFindingRatherThanTheList:
    def test_rows_sharing_a_cause_become_one_finding(self) -> None:
        rows = tuple(
            payment_row(f"pay_{n}", "10000", charged_as=CardType.DOMESTIC_CORPORATE)
            for n in range(12)
        )
        groups = cluster(detect(rows))
        assert len(groups) == 1
        assert groups[0].payments == 12

    def test_the_finding_carries_both_rates_and_the_money(self) -> None:
        """The rate pair is the finding. Every surface writes the sentence its
        own layout needs - the CLI a table row, the queue a list row - so what
        the cluster owes them is the fields, and a canned sentence none of
        them could use verbatim was deleted rather than kept."""
        rows = tuple(
            payment_row(f"pay_{n}", "10000", charged_as=CardType.DOMESTIC_CORPORATE)
            for n in range(12)
        )
        found = cluster(detect(rows))[0]
        assert f"{found.charged_rate:.2%}" == "2.15%"
        assert f"{found.contracted_rate:.2%}" == "2.00%"
        assert f"{found.excess_rate:.2%}" == "0.15%"
        assert found.card_type == "domestic_consumer"

    def test_every_row_behind_a_finding_is_kept(self) -> None:
        """A claim about money that cannot be drilled into is a claim nobody
        should act on."""
        rows = tuple(
            payment_row(f"pay_{n}", "10000", charged_as=CardType.DOMESTIC_CORPORATE)
            for n in range(12)
        )
        assert len(cluster(detect(rows))[0].payment_ids) == 12

    def test_findings_are_ordered_by_money_not_by_count(self) -> None:
        """Ten rows costing a rupee each are not the finding; one costing a
        thousand is."""
        many_small = tuple(
            payment_row(f"pay_s{n}", "100", charged_as=CardType.DOMESTIC_CORPORATE)
            for n in range(10)
        )
        one_large = (
            payment_row(
                "pay_big",
                "500000",
                method=PaymentMethod.CARD,
                declared=CardType.DOMESTIC_CONSUMER,
                charged_as=CardType.INTERNATIONAL,
            ),
        )
        groups = cluster(detect(many_small + one_large))
        assert groups[0].payments == 1
        assert groups[0].overcharge > groups[1].overcharge

    def test_a_clean_report_says_so_plainly(self) -> None:
        rows = tuple(payment_row(f"pay_{n}", "10000") for n in range(20))
        report = summarise(detect(rows), len(rows))
        assert report.clean
        assert "contracted rate" in report.headline()


class TestAgainstGroundTruth:
    """Measured against the answer key rather than demonstrated on a fixture."""

    @pytest.mark.parametrize("difficulty", list(Difficulty))
    def test_every_injected_leak_is_found_and_no_others(self, difficulty: Difficulty) -> None:
        dataset = ChaosEngine(
            GenerationConfig(seed=7, difficulty=difficulty, order_count=600)
        ).generate()
        found = {leak.payment_id for leak in detect(dataset.settlement_rows)}
        expected = {leak.payment_id for leak in dataset.answer_key.leaks}

        assert found == expected, (
            f"{len(expected - found)} missed, {len(found - expected)} invented"
        )

    @pytest.mark.parametrize("difficulty", [Difficulty.CLEAN, Difficulty.REALISTIC])
    def test_the_quiet_tiers_report_nothing_at_all(self, difficulty: Difficulty) -> None:
        """A detector that finds something everywhere is a detector that has
        learned to find nothing."""
        dataset = ChaosEngine(
            GenerationConfig(seed=7, difficulty=difficulty, order_count=600)
        ).generate()
        assert detect(dataset.settlement_rows) == ()

    def test_the_money_matches_the_answer_key_to_the_paisa(self) -> None:
        dataset = ChaosEngine(
            GenerationConfig(seed=7, difficulty=Difficulty.ADVERSARIAL, order_count=600)
        ).generate()
        found = summarise(detect(dataset.settlement_rows), rows_examined=0)
        expected = sum(leak.overcharge for leak in dataset.answer_key.leaks)
        assert found.overcharge == expected

    def test_the_pipeline_reports_them_without_disturbing_the_reconciliation(
        self,
    ) -> None:
        """Leaks ride alongside the exceptions, never among them. Every row
        here reconciled perfectly."""
        dataset = ChaosEngine(
            GenerationConfig(seed=7, difficulty=Difficulty.ADVERSARIAL, order_count=600)
        ).generate()
        report = ReconciliationPipeline().run(
            to_recon_input(dataset), RunMetadata(seed=7, difficulty="adversarial")
        )
        assert report.leaks
        leaked = {leak.payment_id for leak in report.leaks}
        flagged = {exception.subject_id for exception in report.exceptions}
        assert not (leaked & flagged), "a leak was also filed as an exception"


class TestTheTotalsAddUp:
    """The reporting arithmetic, which the queue and the CLI both read.

    Left uncovered on the first pass because every other test in this file
    asserts on individual leaks, and a summary that quietly summed the wrong
    field would have looked correct in all of them.

    Written against `LeakReport` rather than a second summing helper. Day 9
    shipped `total()` beside it, computing the same four figures from the same
    leaks, and nothing outside this file ever called it - two implementations
    of one sum, one of them exercised only by its own test.
    """

    def _leaked(self, count: int) -> tuple[SettlementRow, ...]:
        return tuple(
            payment_row(f"pay_{n}", "10000", charged_as=CardType.DOMESTIC_CORPORATE)
            for n in range(count)
        )

    def test_a_total_is_the_sum_of_its_leaks(self) -> None:
        leaks = detect(self._leaked(7))
        summed = summarise(leaks, rows_examined=40)
        assert summed.payments == 7
        assert summed.overcharge == sum(leak.overcharge for leak in leaks)
        assert summed.gst == sum(leak.gst_on_overcharge for leak in leaks)
        assert summed.cash_impact == summed.overcharge + summed.gst

    def test_an_empty_total_says_nothing_was_wrong(self) -> None:
        summed = summarise((), rows_examined=40)
        assert summed.clean
        assert summed.payments == 0
        assert "charged at its contracted rate" in summed.headline()

    def test_the_headline_names_both_figures_and_which_is_recoverable(self) -> None:
        """The GST is stated apart from the overcharge because it comes back
        as input tax credit. Rolling it into the headline would overstate the
        permanent loss by 18%, which is the same failure as understating it."""
        said = summarise(detect(self._leaked(7)), rows_examined=40).headline()
        assert "input tax credit" in said
        assert "in 1 pattern" in said

    def test_the_report_rolls_its_clusters_up(self) -> None:
        report = summarise(detect(self._leaked(9)), rows_examined=100)
        assert report.payments == 9
        assert report.overcharge == sum(g.overcharge for g in report.clusters)
        assert report.gst == sum(g.gst for g in report.clusters)
        assert report.cash_impact == report.overcharge + report.gst
        assert not report.clean

    def test_a_cluster_reports_its_own_cash_impact(self) -> None:
        group = cluster(detect(self._leaked(4)))[0]
        assert group.cash_impact == group.overcharge + group.gst
        assert group.excess_rate > 0

    def test_the_headline_counts_the_rows_it_examined(self) -> None:
        report = summarise(detect(self._leaked(3)), rows_examined=1500)
        assert "1,500" in report.headline()

    def test_a_zero_amount_row_cannot_divide_by_zero(self) -> None:
        """`_rate_of` guards it, and nothing generated reaches the guard - so
        it is reached here instead of being trusted."""
        row = payment_row("pay_1", "10000").model_copy(
            update={"amount": Paise(0), "fee": Paise(500)}
        )
        assert detect((row,)) == ()
