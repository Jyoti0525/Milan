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


_TIERS: dict[Difficulty, DefectRates] = {
    Difficulty.CLEAN: DefectRates(),
    Difficulty.REALISTIC: DefectRates(
        utr_corrupted=0.10,
        batch_tax_rounding=True,
        orphan_credits=1,
        missing_credits=1,
    ),
    Difficulty.MESSY: DefectRates(
        utr_corrupted=0.25,
        batch_tax_rounding=True,
        rate_mismatch=0.15,
        orphan_credits=3,
        missing_credits=2,
    ),
    Difficulty.ADVERSARIAL: DefectRates(
        utr_corrupted=0.35,
        batch_tax_rounding=True,
        rate_mismatch=0.25,
        orphan_credits=4,
        missing_credits=2,
        ambiguous_pairs=2,
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
