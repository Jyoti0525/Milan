"""The oracle: a matcher that already knows the answers.

It is not a competitor to the real cascade and it is never wired into a run.
It exists to test the *generator*.

Give the oracle the answer key and it matches everything perfectly by
definition. Then run the waterfall solver over its matches. If any credit
fails to reconstruct to zero, the fault cannot be in the matching - the
matcher was handed the right settlement. It means the generated data and the
solver disagree about the money, and every accuracy figure downstream is
being scored against an answer key that is itself wrong.

That failure is the dangerous kind: it does not look like a bug, it looks
like a slightly lower match rate. The oracle is what turns it into a failing
test.
"""

from __future__ import annotations

from milan.domain.enums import MatchStrategy
from milan.domain.records import BankCredit
from milan.domain.truth import AnswerKey
from milan.recon.batches import GatewayBatch
from milan.recon.matching.base import Attempt, Verdict


class OracleStrategy:
    """Matches by reading the answer key. Only ever used to check the data."""

    name = MatchStrategy.EXACT_UTR

    def __init__(self, answers: AnswerKey) -> None:
        self._truth = answers.by_credit()

    def attempt(self, credit: BankCredit, candidates: tuple[GatewayBatch, ...]) -> Attempt:
        expected = self._truth.get(credit.credit_id)
        if expected is None or not expected.settlement_ids:
            return Attempt(
                strategy=self.name,
                verdict=Verdict.NO_CANDIDATE,
                note="nothing behind this credit",
            )
        if not expected.matchable:
            # The oracle models the best *honest* behaviour, not omniscience.
            # A credit can have settlements behind it as a matter of fact and
            # still be unidentifiable from the evidence in the three files -
            # two payouts of the same size on the same day, neither carrying a
            # reference. Knowing which is which is not skill, it is the answer
            # key. Refusing is the ceiling here, so the ceiling is what the
            # oracle reports.
            return Attempt(
                strategy=self.name,
                verdict=Verdict.AMBIGUOUS,
                note="behind this credit are settlements no evidence could single out",
            )
        available = {batch.settlement_id for batch in candidates}
        if not expected.settlement_set <= available:
            return Attempt(
                strategy=self.name,
                verdict=Verdict.NO_CANDIDATE,
                note="a settlement behind this credit is not in the report",
            )
        return Attempt(
            strategy=self.name,
            verdict=Verdict.MATCHED,
            settlement_ids=expected.settlement_ids,
            candidates=expected.settlement_ids,
            confidence=1.0,
            note="oracle",
        )
