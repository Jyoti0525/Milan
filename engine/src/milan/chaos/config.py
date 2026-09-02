"""Generation settings.

Difficulty and repeatability are independent axes. Every tier below is fully
seeded and reproducible; ADVERSARIAL is no less repeatable than CLEAN, it is
just harder. Saying "seeded" is not the same as saying "easy", and the
distinction matters when reporting a match rate.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

    ambiguous_with_reference: int = 0
    """Twin credits where only a damaged reference tells them apart.

    Two credits, identical amount, same day - so the amount says nothing and
    the combination search says nothing either. One of them carries a
    reference that survived into the narration in damaged form, and that is
    the only evidence in the entire dataset that separates them.

    This is the case a similarity rung exists for, and it is injected
    deliberately rather than waited for. Left to chance the combination of
    "reference damaged" and "amount ambiguous" occurs on some seeds and not
    others, which would make the rung tested only on some runs."""

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

    unfamiliar_variances: int = 0
    """Shortfalls caused by mechanisms `milan.recon.causes` has no rule for.

    Off in every tier, and that is the point of it. Everything else on this
    list is a defect the inducer was built against, which makes purity a
    measurement of whether two modules written by the same person agree with
    each other. It says nothing about the case that is certain to arrive
    first in production: a merchant whose money went missing for a reason
    nobody thought to write a rule for.

    So these four break the arithmetic in shapes no rule tests. A flat bank
    charge is a constant number of paise rather than a proportion; an FX
    markup moves between batches rather than holding to one rate; a dispute
    penalty is a recovery with no refund row anywhere behind it; promotional
    funding is a rate applied to part of a batch rather than all of it. Any
    rule that claims one of these is claiming something it did not test.

    The right output for all four is `uncaused` - named as nothing, left in
    the queue to be read individually. Being unable to explain a shortfall is
    a state this system can report. Explaining it wrongly is not, because a
    named cause carries a `because` sentence with real arithmetic in it and
    nothing on the screen says the story attached is invented."""

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
        ambiguous_with_reference=1,
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
        ambiguous_with_reference=2,
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
        ambiguous_with_reference=2,
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
    instant_settlement_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    """Payouts the merchant asked for in minutes instead of T+2 working days.

    A merchant attribute, not a defect, which is why it sits here beside the
    refund settings rather than in `DefectRates`. Razorpay offers it on
    request and our sourced pricing does not record what it charges, so this
    models the *timing* only. Inventing a fee would put a number in the
    generator that no citation supports, and every accuracy figure this
    project reports is already conditional on the defect catalogue being
    honest.

    It was deferred once on the reasoning that the date window already
    tolerates a day either side, which was an assumption about the matcher
    that nothing had tested. It has now been tested, and the deferral was
    right for a reason nobody had stated.

    The prediction written here first was that it would make matching harder:
    a payment captured today settles today, into the same date bucket as
    payments captured two working days ago, so more batches share a date and
    amount-plus-date has more ways to be ambiguous. Measured over ten
    adversarial seeds at 400 orders, that is wrong. It produces 59% more
    batches (344 to 546) and barely moves the batches-per-date figure (2.05
    to 2.22), and it creates **zero** new same-date same-total collisions,
    because an instant batch holds only that day's instant payments and its
    total therefore looks nothing like a scheduled run's.

    Match rate and precision hold at 100% from 0% instant through 60%. So it
    is volume rather than difficulty - which is worth generating anyway,
    since a shape a merchant really has should not be one the engine has
    never seen, but it is recorded here as a measurement rather than left
    looking like a difficulty knob it is not.
    """
    route_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    """Share of payments split to a linked account through Razorpay Route.

    A marketplace shape rather than a defect: the platform takes an order,
    Razorpay settles it, and part of it is paid on to whoever actually
    fulfilled it. Off by default, because a merchant selling their own goods
    has no linked accounts and Route would be a product they never bought.

    This is the one deferred item that turned out to be more than another
    rate. Route charges 0.1% on the transferred amount, which is indeed just
    a rate - but the *transfer* is a debit against the payout that is not a
    reversal. Every debit the engine had ever seen was money coming back: a
    refund returning a sale, an adjustment clawing one back. A transfer is a
    share of a sale that was never the merchant's, and it reduces the payout
    identically while meaning something else entirely.
    """

    route_share: Decimal = Field(default=Decimal("0.30"), gt=Decimal(0), lt=Decimal(1))
    """How much of a routed payment goes to the linked account."""

    chargeback_probability: float = Field(default=0.015, ge=0.0, le=1.0)
    unpaid_probability: float = Field(default=0.04, ge=0.0, le=1.0)
    international_probability: float = Field(default=0.05, ge=0.0, le=1.0)
    corporate_card_probability: float = Field(default=0.10, ge=0.0, le=1.0)

    min_amount_rupees: Decimal = Decimal("199")
    max_amount_rupees: Decimal = Decimal("48000")
    """The merchant's price window. Equal values mean a single-price
    merchant, which is a real shape and the one that makes batch totals
    collide."""

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

    unfamiliar_variances: int = 0
    """Adds shortfalls no cause rule was written against, on top of the tier.

    A config field rather than a fifth difficulty, because it is not a
    harder month - it is the *same* month with defects the inducer has never
    been shown. Left at zero everywhere except the measurement that exists to
    ask what happens then, so no tier and no existing seed changes."""

    @property
    def defects(self) -> DefectRates:
        tier = defects_for(self.difficulty)
        if self.unfamiliar_variances <= 0:
            return tier
        return tier.model_copy(update={"unfamiliar_variances": self.unfamiliar_variances})

    @model_validator(mode="after")
    def _price_window_is_a_window(self) -> GenerationConfig:
        """A window with the ends the wrong way round is not a slow config.

        Before the amount draw was rewritten it was a hang: rejection
        sampling looking for a value inside an empty range, with no error and
        no progress. Caught here so an impossible request fails at the point
        it is made.
        """
        if self.min_amount_rupees > self.max_amount_rupees:
            raise ValueError(
                f"min_amount_rupees ({self.min_amount_rupees}) is above "
                f"max_amount_rupees ({self.max_amount_rupees})"
            )
        if self.min_amount_rupees <= 0:
            raise ValueError("min_amount_rupees must be positive")
        return self
