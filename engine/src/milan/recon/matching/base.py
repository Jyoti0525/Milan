"""The contract every matching strategy implements.

A strategy answers one question about one bank credit: which settlement, if
any, is this. It is allowed to say "I don't know", and it is required to say
"more than one thing fits" rather than picking. Those are different answers
and they lead to different exceptions.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from milan.domain.enums import MatchStrategy
from milan.domain.records import BankCredit
from milan.recon.batches import GatewayBatch


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
    settlement_id: str | None = None
    candidates: tuple[str, ...] = ()
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    note: str = ""

    @property
    def resolved(self) -> bool:
        return self.verdict is Verdict.MATCHED and self.settlement_id is not None


class Strategy(Protocol):
    """One rung of the cascade."""

    name: MatchStrategy

    def attempt(self, credit: BankCredit, candidates: tuple[GatewayBatch, ...]) -> Attempt:
        """Judge one credit against the batches still unclaimed."""
        ...
