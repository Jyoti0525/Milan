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
    """Bank narration arrives without a usable UTR. Forces a fallback."""

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
        batch_tax_rounding=True,
        orphan_credits=1,
        missing_credits=1,
        merged_credits=2,
        unreported_payments=0.004,
    ),
    Difficulty.MESSY: DefectRates(
        utr_corrupted=0.25,
        batch_tax_rounding=True,
        rate_mismatch=0.15,
        orphan_credits=3,
        missing_credits=2,
        merged_credits=4,
        unreported_payments=0.010,
    ),
    Difficulty.ADVERSARIAL: DefectRates(
        utr_corrupted=0.35,
        batch_tax_rounding=True,
        rate_mismatch=0.25,
        orphan_credits=4,
        missing_credits=2,
        ambiguous_pairs=2,
        merged_credits=6,
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
    chargeback_probability: float = Field(default=0.015, ge=0.0, le=1.0)
    unpaid_probability: float = Field(default=0.04, ge=0.0, le=1.0)
    international_probability: float = Field(default=0.05, ge=0.0, le=1.0)
    corporate_card_probability: float = Field(default=0.10, ge=0.0, le=1.0)

    min_amount_rupees: Decimal = Decimal("199")
    max_amount_rupees: Decimal = Decimal("48000")

    rates: RateCard = Field(default_factory=RateCard)

    @property
    def defects(self) -> DefectRates:
        return defects_for(self.difficulty)
