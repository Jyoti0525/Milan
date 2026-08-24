"""What reconciliation produces.

The output of this system is not a list of matches. It is a set of *proofs*:
for each bank credit, a breakdown whose lines sum exactly to the amount that
arrived, with every line pointing at the source record that justifies it.

A match that cannot be proved is not reported as a match. It becomes an
exception, and the exception says what was missing.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from milan.domain.enums import ExceptionCode, MatchStrategy
from milan.domain.money import Paise


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


class ReconReport(BaseModel):
    """The result of one reconciliation run."""

    model_config = ConfigDict(frozen=True)

    seed: int
    difficulty: str
    records_processed: int
    proofs: tuple[Proof, ...]
    exceptions: tuple[ReconException, ...]
    duration_seconds: float

    @property
    def credits_resolved(self) -> int:
        return sum(1 for proof in self.proofs if proof.balances)

    @property
    def records_per_second(self) -> float:
        if self.duration_seconds <= 0:
            return 0.0
        return self.records_processed / self.duration_seconds
