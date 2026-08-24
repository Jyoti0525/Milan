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


class LedgerDirection(StrEnum):
    CREDIT = "credit"
    DEBIT = "debit"


class ExceptionCode(StrEnum):
    """Industry-standard exception categories.

    `UNEXPLAINED` is the honest bucket. It is not a failure of the system to
    put something here — it is the system refusing to guess. What would be a
    failure is a confident wrong answer in any of the other buckets.
    """

    FEE_DEDUCTION = "FEE_DEDUCTION"
    TAX_DEDUCTION = "TAX_DEDUCTION"
    ROUNDING = "ROUNDING"
    PARTIAL_PAYMENT = "PARTIAL_PAYMENT"
    MISSING_SETTLEMENT = "MISSING_SETTLEMENT"
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
