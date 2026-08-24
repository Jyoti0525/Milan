"""The answer key.

Because we generate the data, we know the correct answer for every row. That
is the whole reason our match rate is a measurement rather than an estimate.

The answer key is written once, by the generator, and is read-only from then
on. Nothing in `milan.recon` may import this module — the matcher must never
be able to see the answers, even accidentally. That import boundary is
enforced by a test, not by good intentions.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from milan.domain.money import Paise


class CreditTruth(BaseModel):
    """What is actually behind one bank credit."""

    model_config = ConfigDict(frozen=True)

    credit_id: str
    settlement_id: str | None
    """`None` when this credit genuinely has no settlement behind it."""

    entity_ids: tuple[str, ...]
    gross: Paise
    fee: Paise
    tax: Paise
    tds: Paise
    adjustments: Paise
    """Refunds and chargebacks netted out of this batch, as a positive number."""

    rounding_drift: Paise
    """Signed. Batch-level tax rounding disagreeing with per-row rounding."""

    matchable: bool
    """False when this credit was made impossible to resolve on purpose.

    These records are the point of the exercise. A system that scores well on
    matchable records and also forces answers onto these is worse than one
    that scores slightly lower and refuses. We measure both.
    """

    defect: str | None = None
    """Which defect was injected, if any. Used to report accuracy per defect."""


class LeakTruth(BaseModel):
    """A charge that balances perfectly and is still wrong.

    The batch adds up, the bank agrees, nothing is unmatched — and the
    merchant was charged at a rate they are not contracted to. Recorded here
    at generation time so that leak detection can be measured against ground
    truth rather than demonstrated on a hand-picked example.
    """

    model_config = ConfigDict(frozen=True)

    payment_id: str
    settlement_id: str
    contracted_fee: Paise
    charged_fee: Paise

    @property
    def overcharge(self) -> Paise:
        return Paise(self.charged_fee - self.contracted_fee)


class AnswerKey(BaseModel):
    """Ground truth for a generated dataset."""

    model_config = ConfigDict(frozen=True)

    seed: int
    credits: tuple[CreditTruth, ...]

    missing_settlement_ids: tuple[str, ...] = ()
    """Settlements the gateway reported that never reached the bank. The
    right answer is an exception against the settlement, not a forced match
    against some other credit of a similar size."""

    leaks: tuple[LeakTruth, ...] = ()

    def by_credit(self) -> dict[str, CreditTruth]:
        return {truth.credit_id: truth for truth in self.credits}

    @property
    def matchable_count(self) -> int:
        return sum(1 for truth in self.credits if truth.matchable)

    @property
    def impossible_count(self) -> int:
        return sum(1 for truth in self.credits if not truth.matchable)
