"""The answer key.

Because we generate the data, we know the correct answer for every row. That
is the whole reason our match rate is a measurement rather than an estimate.

The answer key is written once, by the generator, and is read-only from then
on. Nothing in `milan.recon` may import this module - the matcher must never
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

    settlement_ids: tuple[str, ...] = ()
    """Every settlement this one credit paid out. Empty when nothing is
    behind it.

    A tuple rather than a single id because banks merge transfers. Two payouts
    initiated in the same cycle can arrive as one NEFT credit, and the
    merchant's statement shows a single line for both. Modelling that as
    "one credit, one settlement" would have quietly defined away the case the
    matching design exists for.

    This is a fact about the world, and it is not the same question as
    `matchable`. A credit can have settlements behind it and still be
    impossible to attribute from the evidence a merchant holds."""

    entity_ids: tuple[str, ...]
    gross: Paise
    fee: Paise
    tax: Paise
    tds: Paise
    adjustments: Paise
    """Refunds and chargebacks netted out of these batches, as a positive number."""

    rounding_drift: Paise
    """Signed. Batch-level tax rounding disagreeing with per-row rounding."""

    matchable: bool
    """Whether the evidence in the three files can single this credit out.

    False when the credit was made unresolvable on purpose. These records are
    the point of the exercise. A system that scores well on resolvable
    records and also forces answers onto these is worse than one that scores
    slightly lower and refuses, so both are measured.

    Distinct from `settlement_ids`: those say what is true, this says what is
    knowable. Scoring uses this one.
    """

    provable: bool = True
    """Whether the report's rows reconstruct this credit exactly.

    A third state, and it took a payout variance to notice it was missing.
    `matchable` says the evidence can single the credit out; this says the
    arithmetic then closes. A credit can be perfectly identifiable and still
    unprovable - the gateway deducted a fee the report does not show, or took
    a refund out of a different batch - and for those the correct output is
    not a match at all. It is an exception that names the shortfall.

    Counting them against the match rate would penalise exactly the refusal
    this system is built to make, so they are scored separately: not as
    matches missed, but as shortfalls explained or not explained."""

    defect: str | None = None
    """Which defect was injected, if any. Used to report accuracy per defect."""

    @property
    def settlement_set(self) -> frozenset[str]:
        """The claim to score against. Order of ids is not part of the answer."""
        return frozenset(self.settlement_ids)

    @property
    def is_merged(self) -> bool:
        """One bank line covering more than one payout."""
        return len(self.settlement_ids) > 1


class LeakTruth(BaseModel):
    """A charge that balances perfectly and is still wrong.

    The batch adds up, the bank agrees, nothing is unmatched - and the
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

    unreported_payment_ids: tuple[str, ...] = ()
    """Payments the merchant captured that the settlement report never
    mentions. The money left the customer and never came back, and no amount
    of matching bank credits will find it - the only way to notice is to read
    the payments file and ask what is missing from the report."""

    leaks: tuple[LeakTruth, ...] = ()

    def by_credit(self) -> dict[str, CreditTruth]:
        return {truth.credit_id: truth for truth in self.credits}

    @property
    def resolvable_count(self) -> int:
        """Credits a correct system should match AND prove."""
        return sum(1 for truth in self.credits if truth.matchable and truth.provable)

    @property
    def unprovable_count(self) -> int:
        """Identifiable credits that no honest proof can close."""
        return sum(1 for truth in self.credits if truth.matchable and not truth.provable)

    @property
    def matchable_count(self) -> int:
        return sum(1 for truth in self.credits if truth.matchable)

    @property
    def impossible_count(self) -> int:
        return sum(1 for truth in self.credits if not truth.matchable)

    @property
    def merged_count(self) -> int:
        """Credits covering more than one settlement."""
        return sum(1 for truth in self.credits if truth.is_merged)
