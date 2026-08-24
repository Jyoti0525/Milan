"""Rung one: the UTR.

When the bank narration still carries the gateway's reference, this is not a
probability problem and should not be treated as one. Two strings are equal
or they are not.

Most of a real month resolves here. The interesting engineering is entirely
in what happens when this rung comes back empty-handed - but a system that
reached for a clever technique before trying the join key would be picking a
tool because it looks impressive.
"""

from __future__ import annotations

import re

from milan.domain.enums import MatchStrategy
from milan.domain.records import BankCredit
from milan.recon.batches import GatewayBatch
from milan.recon.matching.base import Attempt, Verdict

_UTR_PATTERN = re.compile(r"\b([A-Z0-9]{12,22})\b")

_NARRATION_NOISE = frozenset(
    {
        "RAZORPAY",
        "RAZORPAYSOFTWARE",
        "SETTLEMENT",
        "PAYOUT",
        "INWARD",
        "SOFTWARE",
    }
)


def extract_utr(narration: str) -> str | None:
    """Pull a plausible UTR out of free-text narration.

    Bank narrations are not a format, they are a habit. The reference can be
    delimited by hyphens, slashes, or nothing at all, and the surrounding
    words are not stable. What is stable is the shape: a long run of capitals
    and digits that is not an ordinary word.
    """
    for candidate in _UTR_PATTERN.findall(narration.upper()):
        if candidate in _NARRATION_NOISE:
            continue
        if candidate.isalpha():
            continue
        return str(candidate)
    return None


class ExactUtrStrategy:
    """Match on the settlement reference, when the bank kept it."""

    name = MatchStrategy.EXACT_UTR

    def attempt(self, credit: BankCredit, candidates: tuple[GatewayBatch, ...]) -> Attempt:
        reference = credit.utr or extract_utr(credit.narration)
        if reference is None:
            return Attempt(
                strategy=self.name,
                verdict=Verdict.NO_CANDIDATE,
                note="no settlement reference in the bank narration",
            )

        hits = [batch for batch in candidates if batch.settlement_utr == reference]
        if not hits:
            return Attempt(
                strategy=self.name,
                verdict=Verdict.NO_CANDIDATE,
                note=f"reference {reference} matches no unclaimed settlement",
            )
        if len(hits) > 1:
            # Two settlements sharing a reference means the gateway export is
            # malformed. Better to say so than to pick the first one.
            return Attempt(
                strategy=self.name,
                verdict=Verdict.AMBIGUOUS,
                candidates=tuple(batch.settlement_id for batch in hits),
                note=f"reference {reference} appears on {len(hits)} settlements",
            )

        return Attempt(
            strategy=self.name,
            verdict=Verdict.MATCHED,
            settlement_id=hits[0].settlement_id,
            candidates=(hits[0].settlement_id,),
            confidence=1.0,
            note=f"settlement reference {reference}",
        )
