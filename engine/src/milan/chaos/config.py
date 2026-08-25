"""Generation settings.

Difficulty and repeatability are independent axes. Every tier below is fully
seeded and reproducible; ADVERSARIAL is no less repeatable than CLEAN, it is
just harder. Saying "seeded" is not the same as saying "easy", and the
distinction matters when reporting a match rate.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from milan.domain.rates import RateCard


class Difficulty(StrEnum):
    CLEAN = "clean"
    """No defects. Every credit resolves on its UTR. The control case: if the
    engine cannot score 100% here, the engine is broken, not the data."""

    REALISTIC = "realistic"
    """What a real merchant's month actually looks like."""

    MESSY = "messy"
    """A bad month. Rate mismatches, heavier UTR loss, more orphan credits."""

    ADVERSARIAL = "adversarial"
    """Contains credits that are impossible to resolve by design. The correct
    behaviour on those is to refuse, and we measure whether we do."""


class DefectRates(BaseModel):
    """Per-tier knobs. All probabilities are per-record unless noted."""

    model_config = ConfigDict(frozen=True)

    utr_corrupted: float = 0.0
    """Bank narration arrives without a usable UTR at all. Forces a fallback."""

    utr_damaged: float = 0.0
    """The reference survives into the narration and arrives altered.

    A distinct case from `utr_corrupted`, and for a long time this file
    conflated them: a reference was either perfect or absent, which is not
    how bank narrations behave. Real ones truncate at a field width,
    transpose a pair of characters when re-keyed, confuse O for 0 and I for
    1, pick up a prefix from an adjacent column, or get split by a delimiter.

    Exact matching requires string equality, so every one of these is a total
    miss for the first rung - and unlike a deleted reference, a damaged one
    still *looks* like evidence. It is the input probabilistic linkage exists
    to handle, and until this knob existed we had never generated it, so any
    conclusion about whether such a technique is needed was a conclusion
    about the generator."""

    batch_tax_rounding: bool = False
    """Fees round per transaction, GST rounds once on the batch. The two
    disagree by paise. A real, named exception category — not a bug."""

    rate_mismatch: float = 0.0
    """Charged at a rate other than the contracted one."""

    orphan_credits: int = 0
    """Bank credits with no settlement behind them. Unresolvable by design."""

    missing_credits: int = 0
    """Settlements the gateway reported that never arrived in the bank."""

    ambiguous_pairs: int = 0
    """Pairs of settlements with identical amount and date, both with their
    UTR destroyed. Genuinely indistinguishable. Refusing is the right answer."""

    merged_credits: int = 0
    """Bank credits that pay out two or three settlements at once.

    Not a gateway defect at all - it is what banks do with transfers in the
    same cycle. It sits here because it is a difficulty knob: a merged credit
    matches no single settlement, so every rung that compares one amount to
    one batch is wrong about it by construction. Half of them carry one
    member's reference, which is worse than carrying none: the join key finds
    a settlement, the proof comes up short by the rest, and a system that does
    not let proving overrule matching will report a confident wrong answer."""

    payout_variances: int = 0
    """Batches where the money that left does not match the report that
    describes it.

    Distinct from `rate_mismatch`, and the distinction is the whole point.
    A rate mismatch balances perfectly: the report and the bank agree, and
    only the *contract* disagrees, so nothing is ever unmatched and the loss
    is invisible. A payout variance does not balance - the credit is short by
    an amount the report cannot account for, and the correct output is not a
    match at all but an exception that names the shortfall.

    Three forms, all real: the gateway deducted a fee at a rate the report
    does not show, GST came off at something other than the statutory rate,
    or a refund was taken out of a different batch than the one the report
    files it under."""

    unreported_payments: float = 0.0
    """Captured payments the settlement report never mentions.

    The one defect on this list that no amount of bank-side matching can find.
    The money never arrived, so nothing is unmatched and every credit still
    reconciles perfectly. It is only visible by reading the payments file and
    asking what the report leaves out."""


_TIERS: dict[Difficulty, DefectRates] = {
    Difficulty.CLEAN: DefectRates(),
    Difficulty.REALISTIC: DefectRates(
        utr_corrupted=0.10,
        utr_damaged=0.08,
        batch_tax_rounding=True,
        orphan_credits=1,
        missing_credits=1,
        merged_credits=2,
        payout_variances=3,
        unreported_payments=0.004,
    ),
    Difficulty.MESSY: DefectRates(
        utr_corrupted=0.25,
        utr_damaged=0.15,
        batch_tax_rounding=True,
        rate_mismatch=0.15,
        orphan_credits=3,
        missing_credits=2,
        merged_credits=4,
        payout_variances=4,
        unreported_payments=0.010,
    ),
    Difficulty.ADVERSARIAL: DefectRates(
        utr_corrupted=0.35,
        utr_damaged=0.20,
        batch_tax_rounding=True,
        rate_mismatch=0.25,
        orphan_credits=4,
        missing_credits=2,
        ambiguous_pairs=2,
        merged_credits=6,
        payout_variances=6,
        unreported_payments=0.015,
    ),
}


def defects_for(difficulty: Difficulty) -> DefectRates:
    return _TIERS[difficulty]


class GenerationConfig(BaseModel):
    """One reproducible dataset."""

    model_config = ConfigDict(frozen=True)

    seed: int = 42
    difficulty: Difficulty = Difficulty.REALISTIC
    order_count: int = Field(default=100, ge=1)

    start_date: str = "2026-07-01"
    span_days: int = Field(default=21, ge=1)

    settlement_cycles: int = Field(default=2, ge=1, le=6)
    """Payout runs per day. A gateway settles on cut-offs, not once at
    midnight, and international cards settle on their own cycle entirely.

    This is the single most important difficulty knob in the file and it is
    not a defect. With one cycle a day, a batch total is the sum of dozens of
    arbitrary order values and is therefore unique across the month - so
    amount-plus-date resolves nearly everything, and a match rate measured on
    that data says almost nothing. Several batches a day is both what really
    happens and what makes the second rung have to earn its answer."""

    refund_probability: float = Field(default=0.06, ge=0.0, le=1.0)
    instant_refund_probability: float = Field(default=0.20, ge=0.0, le=1.0)
    """Share of refunds pushed out immediately, at a flat charge.

    Not a defect and not a difficulty knob - a merchant choosing to pay for
    speed. It earns a place here because it is the only charge in the whole
    fee stack that does not scale with the transaction, which makes it the
    one shortfall that looks like noise on a large refund and like a real
    error on a small one."""
    chargeback_probability: float = Field(default=0.015, ge=0.0, le=1.0)
    unpaid_probability: float = Field(default=0.04, ge=0.0, le=1.0)
    international_probability: float = Field(default=0.05, ge=0.0, le=1.0)
    corporate_card_probability: float = Field(default=0.10, ge=0.0, le=1.0)

    min_amount_rupees: Decimal = Decimal("199")
    max_amount_rupees: Decimal = Decimal("48000")

    rates: RateCard = Field(default_factory=RateCard)
    """The fee stack this merchant is contracted to.

    Also the switch for Section 194-O withholding, via `tds_applies`. It lives
    here rather than in `DefectRates` on purpose: withholding is not a defect
    and not a difficulty setting, it is a fact about who the merchant is. An
    e-commerce operator has 1% of gross withheld and a merchant selling their
    own goods does not, and both are entirely ordinary months.

    The reconciliation side is never told which. It infers a withholding from
    the gap between what a row was worth and what it credited, and is only
    allowed to call that gap TDS when it matches the statutory rate on every
    affected row."""

    @property
    def defects(self) -> DefectRates:
        return defects_for(self.difficulty)
