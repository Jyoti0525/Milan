"""Vocabulary shared by every layer.

The names here are deliberately not invented. Payment methods and card types
mirror Razorpay's settlement report fields; exception codes mirror the names
the reconciliation industry already uses, so a finance person reading our
output does not have to learn our private jargon.
"""

from __future__ import annotations

from enum import StrEnum


class PaymentMethod(StrEnum):
    CARD = "card"
    UPI = "upi"
    NETBANKING = "netbanking"
    WALLET = "wallet"
    EMI = "emi"
    PAYLATER = "paylater"


class CardType(StrEnum):
    """Drives the fee rate. Corporate and international cards cost more."""

    DOMESTIC_CONSUMER = "domestic_consumer"
    DOMESTIC_CORPORATE = "domestic_corporate"
    INTERNATIONAL = "international"


class EntityType(StrEnum):
    """The `type` column of a Razorpay settlement recon report."""

    PAYMENT = "payment"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"

    TRANSFER = "transfer"
    """A Route split: part of a payment paid on to a linked account.

    The only debit here that is not money coming back. A refund returns a
    sale and an adjustment claws one back, so both are reversals; a transfer
    is a share of a sale that was never the merchant's to begin with. It
    reduces the payout exactly like the other two and means something
    completely different, which is why it gets its own line in the proof
    rather than being folded in with them.
    """


class ExceptionCode(StrEnum):
    """Industry-standard exception categories.

    `UNEXPLAINED` is the honest bucket. It is not a failure of the system to
    put something here — it is the system refusing to guess. What would be a
    failure is a confident wrong answer in any of the other buckets.
    """

    # There is deliberately no ROUNDING code. Drift inside the derived
    # allowance is explained as a named line inside the proof, not raised -
    # a credit that reconstructs to zero has no exception to report. A code
    # that nothing ever emits reads as a category the system supports.
    FEE_DEDUCTION = "FEE_DEDUCTION"
    TAX_DEDUCTION = "TAX_DEDUCTION"
    PARTIAL_PAYMENT = "PARTIAL_PAYMENT"
    MISSING_SETTLEMENT = "MISSING_SETTLEMENT"
    """A payout the gateway reported that never reached the bank."""

    UNSETTLED_PAYMENT = "UNSETTLED_PAYMENT"
    """A captured payment that never appears in the settlement report at
    all. Distinct from MISSING_SETTLEMENT: there the gateway says it paid
    and the bank disagrees; here the gateway never says anything."""

    UNEXPLAINED = "UNEXPLAINED"


class MatchStrategy(StrEnum):
    """Which rung of the cascade produced a match.

    Recorded on every match so the eval harness can report accuracy per
    strategy, not just overall — an aggregate number hides which rung is
    carrying the result and which is contributing noise.
    """

    EXACT_UTR = "exact_utr"
    AMOUNT_DATE = "amount_date"
    SUBSET_SUM = "subset_sum"
    FUZZY_NARRATION = "fuzzy_narration"

    SHORTFALL = "shortfall"
    """A payout identified by date and near-total, when it arrived light.

    The weakest rung and the only one that never expects its own claim to
    survive proving. It exists so a credit that is one settlement minus an
    unexplained deduction gets named as that, rather than reported as having
    no settlement behind it at all."""
