"""The contract every matching strategy implements.

A strategy answers one question about one bank credit: which settlements, if
any, is this. It is allowed to say "I don't know", and it is required to say
"more than one thing fits" rather than picking. Those are different answers
and they lead to different exceptions.

The answer is a *set* of settlements, not one. A bank that merges two
transfers produces one credit line covering two payouts, and a strategy that
can only ever name one settlement would have to be wrong about that credit by
construction.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from milan.domain.enums import MatchStrategy
from milan.domain.records import BankCredit
from milan.recon.batches import BatchGroup, GatewayBatch


class Verdict(StrEnum):
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    """Several settlements fit equally well. Choosing one would be a guess."""

    NO_CANDIDATE = "no_candidate"
    """Nothing fits. Either the payout is missing or this credit is not ours."""


class Attempt(BaseModel):
    """What one strategy concluded about one credit."""

    model_config = ConfigDict(frozen=True)

    strategy: MatchStrategy
    verdict: Verdict
    settlement_ids: tuple[str, ...] = ()
    """The settlements claimed. One for an ordinary payout, several when the
    credit is a merged transfer, none when nothing was claimed."""

    candidates: tuple[str, ...] = ()
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    note: str = ""

    @property
    def resolved(self) -> bool:
        return self.verdict is Verdict.MATCHED and bool(self.settlement_ids)

    @property
    def claim(self) -> frozenset[str]:
        return frozenset(self.settlement_ids)

    def rejected(self, reason: str) -> Attempt:
        """The same attempt, demoted because the proof would not stand up.

        A strategy proposes; the waterfall disposes. This keeps the strategy
        and the note so the exception queue can say which rung was wrong and
        what it thought it had found.
        """
        return self.model_copy(
            update={
                "verdict": Verdict.NO_CANDIDATE,
                "settlement_ids": (),
                "confidence": 0.0,
                "note": reason,
            }
        )


class Strategy(Protocol):
    """One rung of the cascade."""

    name: MatchStrategy

    def attempt(self, credit: BankCredit, candidates: tuple[GatewayBatch, ...]) -> Attempt:
        """Judge one credit against the batches still unclaimed."""
        ...


class Verifier(Protocol):
    """Checks a claim before the cascade accepts it.

    The pipeline passes the waterfall solver in here, which is what makes
    "proving vetoes matching" a property of the search rather than a
    post-hoc filter. A rung that produces an unprovable claim does not just
    fail; the credit falls through to the next rung, which is the only way a
    merged credit carrying one member's reference can ever be resolved.
    """

    def __call__(self, credit: BankCredit, group: BatchGroup) -> bool: ...


def always_valid(credit: BankCredit, group: BatchGroup) -> bool:
    """The default verifier: accept whatever a strategy proposes.

    Used when a cascade is exercised on its own, in tests and in the
    strategy-level benchmarks, where the question is what the rung finds
    rather than what survives proof.
    """
    del credit, group
    return True
