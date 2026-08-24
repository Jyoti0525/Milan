"""Running the strategies in order.

This is a cascade, not an agent. It tries rung one on every credit, then rung
two on whatever is left, and stops. There is no state, no planning, and no
choice about what to try next - so calling it an agent would be a nicer word
for the same fixed sequence.

Two details matter more than they look:

**Rung by rung, not credit by credit.** Every credit gets rung one before any
credit gets rung two. Exact matches consume their settlements first, which
removes them from the candidate pool and makes the weaker rung's job easier.
Walking credit-first would let a tolerance match claim a settlement that a
later credit could have proved exactly.

**Two credits cannot claim the same settlement.** If they collide inside a
rung, both are marked ambiguous rather than resolved first-come. Order of
iteration is not evidence.
"""

from __future__ import annotations

from collections import defaultdict

from milan.domain.records import BankCredit
from milan.recon.batches import GatewayBatch
from milan.recon.matching.base import Attempt, Strategy, Verdict
from milan.recon.matching.exact import ExactUtrStrategy
from milan.recon.matching.tolerance import AmountDateStrategy


def default_strategies() -> tuple[Strategy, ...]:
    """The rungs, cheapest and most certain first."""
    return (ExactUtrStrategy(), AmountDateStrategy())


class Cascade:
    """Applies each strategy to everything still unresolved."""

    def __init__(self, strategies: tuple[Strategy, ...] | None = None) -> None:
        self._strategies = strategies if strategies is not None else default_strategies()

    def run(
        self, credits: tuple[BankCredit, ...], batches: tuple[GatewayBatch, ...]
    ) -> dict[str, Attempt]:
        """Return the final attempt for every credit, resolved or not."""
        outcome: dict[str, Attempt] = {}
        unresolved = list(credits)
        claimed: set[str] = set()

        for strategy in self._strategies:
            if not unresolved:
                break
            available = tuple(b for b in batches if b.settlement_id not in claimed)
            attempts = {c.credit_id: strategy.attempt(c, available) for c in unresolved}
            settled = self._resolve_collisions(attempts)

            still_unresolved: list[BankCredit] = []
            for credit in unresolved:
                attempt = settled[credit.credit_id]
                if attempt.resolved:
                    assert attempt.settlement_id is not None
                    claimed.add(attempt.settlement_id)
                    outcome[credit.credit_id] = attempt
                else:
                    outcome[credit.credit_id] = self._keep_stronger(
                        outcome.get(credit.credit_id), attempt
                    )
                    still_unresolved.append(credit)
            unresolved = still_unresolved

        return outcome

    def _resolve_collisions(self, attempts: dict[str, Attempt]) -> dict[str, Attempt]:
        """Demote every side of a contested settlement to ambiguous."""
        contested: dict[str, list[str]] = defaultdict(list)
        for credit_id, attempt in attempts.items():
            if attempt.resolved:
                assert attempt.settlement_id is not None
                contested[attempt.settlement_id].append(credit_id)

        resolved = dict(attempts)
        for settlement_id, credit_ids in contested.items():
            if len(credit_ids) == 1:
                continue
            for credit_id in credit_ids:
                resolved[credit_id] = attempts[credit_id].model_copy(
                    update={
                        "verdict": Verdict.AMBIGUOUS,
                        "settlement_id": None,
                        "confidence": 0.0,
                        "note": (
                            f"{len(credit_ids)} credits fit settlement {settlement_id} equally well"
                        ),
                    }
                )
        return resolved

    def _keep_stronger(self, previous: Attempt | None, current: Attempt) -> Attempt:
        """Prefer the failure that says the most.

        "Two settlements fit this" is a more useful thing to report than
        "nothing fit", and it comes from a later rung that looked harder. The
        exception queue reads better when the reason survives the cascade.
        """
        if previous is None:
            return current
        if current.verdict is Verdict.AMBIGUOUS:
            return current
        if previous.verdict is Verdict.AMBIGUOUS:
            return previous
        return current
