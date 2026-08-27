"""What reconciliation produces.

The output of this system is not a list of matches. It is a set of *proofs*:
for each bank credit, a breakdown whose lines sum exactly to the amount that
arrived, with every line pointing at the source record that justifies it.

A match that cannot be proved is not reported as a match. It becomes an
exception, and the exception says what was missing.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from milan.domain.enums import ExceptionCode, MatchStrategy
from milan.domain.merchant import MerchantProfile, profile_of
from milan.domain.money import ZERO, Paise


class ProofLine(BaseModel):
    """One line of a credit's breakdown.

    `amount` is signed from the merchant's point of view: settled payments
    are positive, deductions negative. The lines of a valid proof sum to the
    amount the bank actually credited.
    """

    model_config = ConfigDict(frozen=True)

    label: str
    amount: Paise
    refs: tuple[str, ...] = ()
    """Source record ids. This is what makes a line clickable in the UI and
    auditable outside it. A line with no refs is an assertion, not evidence."""


class Proof(BaseModel):
    """A complete, checked explanation of one bank credit."""

    model_config = ConfigDict(frozen=True)

    credit_id: str
    settlement_ids: tuple[str, ...]
    """Every settlement this credit paid out. Usually one; more when the
    bank merged separate payouts into a single transfer."""

    credit_amount: Paise
    lines: tuple[ProofLine, ...]
    strategy: MatchStrategy
    confidence: float = Field(ge=0.0, le=1.0)

    drift: Paise = ZERO
    """The paise this proof closed on the allowance rather than on the rows.

    Signed, from the merchant's point of view. Zero for almost every credit.
    It is a field rather than a search for the drift line because it is a
    figure a merchant is owed a total of, and a total assembled by matching
    on a label is a total that silently goes to zero the day the label is
    reworded."""

    @property
    def explained(self) -> Paise:
        return Paise(sum(line.amount for line in self.lines))

    @property
    def residual(self) -> Paise:
        """What the proof failed to account for. Zero, or it is not a proof."""
        return Paise(self.credit_amount - self.explained)

    @property
    def balances(self) -> bool:
        return self.residual == 0

    @property
    def settlement_set(self) -> frozenset[str]:
        return frozenset(self.settlement_ids)


class ReconException(BaseModel):
    """Something the system could not resolve, stated plainly.

    The exception list is a first-class deliverable, not an error log. It is
    the honest half of the result, and a system that produces a short
    exception list by guessing is worse than one that produces a long
    exception list truthfully.
    """

    model_config = ConfigDict(frozen=True)

    code: ExceptionCode
    subject_id: str
    """The bank credit, settlement or order the exception is about."""

    amount: Paise
    """The unexplained amount. Zero when the exception is structural."""

    summary: str
    evidence: dict[str, str] = Field(default_factory=dict)
    """What the system looked at before giving up. Populated by the
    deterministic categoriser; enriched by triage when an LLM is available."""

    categorised_by: str = "rules"
    """`rules` or the LLM provider name. Recorded so the eval harness can
    report how much of the categorisation was deterministic."""


class Leak(BaseModel):
    """One row charged at a rate the merchant is not contracted to.

    A result shape, so it lives here beside `Proof` rather than in the module
    that finds it - `ReconReport` carries these, and the domain cannot import
    from the packages that are supposed to depend on it. The arithmetic that
    produces one stays in `milan.leaks.detector`.
    """

    model_config = ConfigDict(frozen=True)

    payment_id: str
    settlement_id: str

    gross: Paise
    charged_fee: Paise
    contracted_fee: Paise

    charged_rate: Decimal
    contracted_rate: Decimal

    method: str
    card_type: str | None
    card_network: str | None
    card_issuer: str | None
    settled_on: str

    @property
    def overcharge(self) -> Paise:
        """The fee difference. What the merchant loses permanently."""
        return Paise(self.charged_fee - self.contracted_fee)

    @property
    def gst_on_overcharge(self) -> Paise:
        """The tax charged on money that should never have been charged.

        Real cash out of the account, and separately reported because for a
        GST-registered merchant it comes back as input tax credit. Rolling it
        into the headline would overstate the permanent loss by 18%, and
        overstating harm is the same failure as understating it.
        """
        return Paise(self.cash_impact - self.overcharge)

    @property
    def cash_impact(self) -> Paise:
        """Fee difference plus the GST charged on it. What actually left."""
        return Paise(round(self.overcharge * Decimal("1.18")))


class UnprovenCredit(BaseModel):
    """A match that could not be reconstructed to the paisa.

    `Proof`'s sibling, and it lives here for the same reason `Proof` does: it
    describes an outcome rather than the algorithm that produced one. It sat
    in `recon.waterfall` until `ReconReport` needed to carry these, at which
    point keeping it there would have meant the domain importing from the
    package that is supposed to depend on it.
    """

    model_config = ConfigDict(frozen=True)

    credit_id: str
    settlement_ids: tuple[str, ...]
    residual: Paise
    lines: tuple[ProofLine, ...]
    reason: str

    strategy: MatchStrategy = MatchStrategy.EXACT_UTR
    confidence: float = 0.0
    """Which rung identified this settlement, and how sure it was.

    `Proof` has carried these from the start and this did not, which left the
    queue presenting every named shortfall with equal authority. It does not
    deserve equal authority: a shortfall named against a settlement the
    reference rung identified is a fact, and one named against a settlement
    the shortfall rung merely found nearby on the right date is an argument.
    A reader deciding whether to chase a payout needs to know which."""


class ReconReport(BaseModel):
    """The result of one reconciliation run."""

    model_config = ConfigDict(frozen=True)

    seed: int
    difficulty: str
    records_processed: int
    proofs: tuple[Proof, ...]
    exceptions: tuple[ReconException, ...]
    duration_seconds: float

    profile: MerchantProfile = Field(default_factory=lambda: profile_of(()))
    """Who the merchant turned out to be, read off their own settlement rows.

    Carried on the report rather than recomputed by whoever displays it,
    because it is not a presentation detail: the withholding finding decides
    how wide a legitimate shortfall may be, so a screen that worked it out
    again could disagree with the run it is describing.

    It defaults to a profile of no rows, so a report deserialised from an
    archive written before this existed still loads. Every finding in that
    default is `False` over a population of zero, which reads as "nothing was
    read" rather than as a conclusion - the count is printed beside every
    finding for exactly this reason."""

    leaks: tuple[Leak, ...] = ()
    """Rows charged above the merchant's contracted rate.

    Not exceptions, and deliberately a separate field. An exception is
    something that did not reconcile; every one of these reconciled perfectly.
    Filing them together would bury the only finding in the report that
    survives everything balancing."""

    shortfalls: tuple[UnprovenCredit, ...] = ()
    """Credits that were matched and then would not reconstruct.

    Each of these already appears in `exceptions`, categorised. What is kept
    here is the reconstruction itself - the group of settlements and the
    residual - because the categorised exception is a conclusion and this is
    the evidence it was drawn from.

    It exists so the ablation can put the same shortfall to a model and check
    the answer against the same arithmetic, without a second copy of the
    matching pipeline that would drift out of step with this one."""

    @property
    def credits_resolved(self) -> int:
        return sum(1 for proof in self.proofs if proof.balances)

    @property
    def records_per_second(self) -> float:
        if self.duration_seconds <= 0:
            return 0.0
        return self.records_processed / self.duration_seconds
