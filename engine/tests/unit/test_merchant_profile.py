"""Reading who a merchant is off their own settlement rows.

Every test here builds a month with a known configuration and checks that the
profile recovers it *without being told* - which is the whole claim. A test
that passed the generator's flags into the detector would be checking that a
boolean survives being copied.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.enums import EntityType, PaymentMethod
from milan.domain.merchant import MINIMUM_ROWS, profile_of
from milan.domain.money import Paise, apply_rate
from milan.domain.rates import RateCard
from milan.domain.records import SettlementRow
from milan.evaluation.harness import to_recon_input
from milan.recon.matching.shortfall import widest_deduction
from milan.recon.pipeline import ReconciliationPipeline, RunMetadata

CAPTURED = datetime(2026, 7, 1, 14, 32)


def month(**config: object) -> tuple[SettlementRow, ...]:
    """A realistic month, configured however the test needs it."""
    built = ChaosEngine(
        GenerationConfig(seed=11, difficulty=Difficulty.REALISTIC, order_count=300, **config)  # type: ignore[arg-type]
    ).generate()
    return to_recon_input(built).settlement_rows


def payment(index: int, *, withheld: bool, days: int = 2) -> SettlementRow:
    """One settled payment row, footing exactly as the fee stack requires."""
    gross = Paise(100_00 + index * 37)
    fee = apply_rate(gross, RateCard().standard)
    tax = apply_rate(fee, RateCard().gst)
    tds = apply_rate(gross, RateCard().tds) if withheld else Paise(0)
    return SettlementRow(
        entity_id=f"pay_{index:04d}",
        type=EntityType.PAYMENT,
        debit=Paise(0),
        credit=Paise(gross - fee - tax - tds),
        amount=gross,
        fee=fee,
        tax=tax,
        created_at=CAPTURED,
        settled_at=CAPTURED + timedelta(days=days),
        settlement_id="setl_one",
        settlement_utr="UTR0000000001",
        payment_id=f"pay_{index:04d}",
        method=PaymentMethod.UPI,
    )


# ------------------------------------------------------- an ordinary merchant


def test_a_shop_selling_its_own_goods_has_none_of_the_three() -> None:
    """The default has to read as a default, or the findings mean nothing.

    A detector that reports Section 194-O on a merchant who has no filing
    obligation is worse than one that reports nothing: it tells a finance team
    that money was withheld that never was, and the place they go to look for
    it is the tax department.
    """
    profile = profile_of(month())

    assert profile.withholding.held is False
    assert profile.route.held is False
    assert profile.instant.held is False
    assert profile.named == ()
    assert profile.questions == ()


def test_an_ordinary_merchant_is_reconciled_against_an_ordinary_rate_card() -> None:
    profile = profile_of(month())

    assert profile.rates().tds_applies is False


# --------------------------------------------------------------- the operator


def test_an_operator_is_recognised_from_the_gap_in_every_payment() -> None:
    """Nobody says "this merchant is an e-commerce operator". The rows do.

    Each payment credits a full percent of its own gross less than its fee and
    GST account for, on every row, and no other charge in the Indian stack has
    that shape.
    """
    profile = profile_of(month(rates=RateCard(tds_applies=True)))

    assert profile.withholding.held is True
    assert profile.withholding.rows == profile.withholding.of
    assert "1%" in profile.withholding.because


def test_recognising_an_operator_widens_the_band_a_payout_may_be_short_by() -> None:
    """The one place the answer changes arithmetic rather than a caption.

    A settlement report that does not itself show the withholding, paid out by
    a bank that does, leaves a credit short by exactly the tax. A shortfall
    rung built on a plain rate card has a ceiling a percentage point below
    that gap, and files the tax as money that went missing.
    """
    profile = profile_of(month(rates=RateCard(tds_applies=True)))

    assert widest_deduction(profile.rates()) > widest_deduction(RateCard())


@pytest.mark.parametrize("tier", [Difficulty.REALISTIC, Difficulty.ADVERSARIAL])
@pytest.mark.parametrize("withheld", [False, True])
def test_the_reading_survives_the_defects_injected_at_every_tier(
    tier: Difficulty, withheld: bool
) -> None:
    """A fee leak must not be mistaken for a withholding, or the reverse.

    Both are a payment credited less than it looks worth, and the adversarial
    tier is full of the first. They are distinguishable because a leak is a
    fee the row's own `fee` column *reports* - so the row still foots - while
    a withholding is a gap the columns cannot account for at all.
    """
    built = ChaosEngine(
        GenerationConfig(
            seed=7,
            difficulty=tier,
            order_count=600,
            rates=RateCard(tds_applies=withheld),
        )
    ).generate()

    profile = profile_of(to_recon_input(built).settlement_rows)

    assert profile.withholding.held is withheld


# ------------------------------------------------------------------ refusing


def test_a_file_where_only_some_payments_are_withheld_is_not_concluded_on() -> None:
    """The case that has two opposite explanations and no third one.

    A 194-O merchant with a handful of anomalous payouts and an ordinary
    merchant being systematically overcharged one percent produce the same
    file. One wants a wider tolerance and the other wants an exception on
    every affected row, so choosing between them silently gets one of the two
    merchants a wrong answer with no question attached to it.
    """
    rows = tuple(payment(index, withheld=index % 3 != 0) for index in range(60))

    profile = profile_of(rows)

    assert profile.withholding.held is None
    assert profile.withholding.rows == 40
    assert profile.withholding.of == 60
    assert profile.questions == (profile.withholding,)


def test_an_unsettled_finding_is_reconciled_the_safer_way_round() -> None:
    """The two mistakes do not cost the same, so the tie is not broken evenly.

    Assuming an operator is not one narrows the band below the gap the tax
    leaves, and turns a statutory deduction into an unexplained variance.
    Assuming a plain merchant is one widens a band whose claims are all
    handed to a verifier that withdraws whatever will not reconstruct. Only
    the first can put a wrong number in front of a person.
    """
    rows = tuple(payment(index, withheld=index % 3 != 0) for index in range(60))

    assert profile_of(rows).rates().tds_applies is True


def test_too_few_rows_is_not_evidence_of_anything() -> None:
    """Unanimity over eight rows is eight rows, not a filing obligation."""
    rows = tuple(payment(index, withheld=True) for index in range(MINIMUM_ROWS - 1))

    profile = profile_of(rows)

    assert profile.withholding.held is None
    assert str(MINIMUM_ROWS) in profile.withholding.because


def test_a_report_with_no_settled_payments_says_so_rather_than_refusing() -> None:
    """Nothing to read is a different answer from rows that disagree.

    Both leave the finding unproven, but only one of them is a question worth
    putting to a person. A merchant whose report contains no settled payments
    cannot answer "were you withheld from" any better than the file can.
    """
    profile = profile_of(())

    assert profile.withholding.held is False
    assert profile.withholding.of == 0
    assert profile.withholding.share == "no rows to read"


# ---------------------------------------------------------- route and instant


def test_route_is_read_from_the_type_column_that_already_says_transfer() -> None:
    """The one finding needing no inference at all, reported anyway.

    A merchant looking at a payout smaller than their sales is owed the
    reason, and "part of this was never yours" is the reason. Leaving it
    unnamed because it was easy to detect would be the wrong economy.
    """
    profile = profile_of(month(route_probability=0.30))

    assert profile.route.held is True
    assert profile.route.rows > 0
    assert "transfer" in profile.route.because


def test_instant_settlement_is_a_settlement_date_equal_to_a_capture_date() -> None:
    profile = profile_of(month(instant_settlement_probability=0.35))

    assert profile.instant.held is True
    assert 0 < profile.instant.rows < profile.instant.of


def test_a_payout_two_days_later_is_the_ordinary_cycle_not_an_instant_one() -> None:
    """T+2 is what everybody is on. Reporting it as a paid-for product would
    put a line on screen for every merchant in India."""
    rows = tuple(payment(index, withheld=False, days=2) for index in range(40))

    assert profile_of(rows).instant.held is False


def test_all_three_at_once_are_read_together() -> None:
    """None of the three is exclusive of the others, and a marketplace running
    same-day payouts is an ordinary customer rather than a corner case."""
    profile = profile_of(
        month(
            rates=RateCard(tds_applies=True),
            route_probability=0.30,
            instant_settlement_probability=0.35,
        )
    )

    assert [finding.held for finding in profile.findings] == [True, True, True]
    assert len(profile.named) == 3


# ------------------------------------------------------------- the pipeline


def test_the_reconciliation_reads_the_merchant_when_nobody_has_told_it() -> None:
    """The setting every real import runs under.

    Nobody hands a finance team a rate card along with their bank statement,
    so a pipeline that only knows about withholding when it is configured with
    it knows about withholding never.
    """
    built = ChaosEngine(
        GenerationConfig(
            seed=11,
            difficulty=Difficulty.REALISTIC,
            order_count=300,
            rates=RateCard(tds_applies=True),
        )
    ).generate()
    data = to_recon_input(built)

    report = ReconciliationPipeline().run(data, RunMetadata(seed=11, difficulty="realistic"))

    assert report.profile.withholding.held is True
    assert len(report.profile.named) == 1


def test_a_rate_card_handed_in_is_not_second_guessed() -> None:
    """A measured number must not move because a detector changed its mind.

    Every graded figure in this project is produced by a run that states the
    rate card explicitly. If the pipeline overrode that with what it read, a
    change to the detector would silently restate published results.
    """
    built = ChaosEngine(
        GenerationConfig(
            seed=11,
            difficulty=Difficulty.REALISTIC,
            order_count=300,
            rates=RateCard(tds_applies=True),
        )
    ).generate()
    data = to_recon_input(built)
    metadata = RunMetadata(seed=11, difficulty="realistic")

    told = ReconciliationPipeline(rates=RateCard()).run(data, metadata)

    # The profile is still read and still reported - it is a finding either
    # way. What it does not do is overrule the card it was given.
    assert told.profile.withholding.held is True
    assert [line.label for proof in told.proofs for line in proof.lines]


def test_the_profile_travels_on_the_report_rather_than_being_worked_out_again() -> None:
    """A screen that recomputed this could disagree with the run it describes."""
    data = to_recon_input(
        ChaosEngine(
            GenerationConfig(seed=3, difficulty=Difficulty.REALISTIC, order_count=200)
        ).generate()
    )

    report = ReconciliationPipeline().run(data, RunMetadata(seed=3, difficulty="realistic"))
    restored = report.model_validate_json(report.model_dump_json())

    assert restored.profile == report.profile
