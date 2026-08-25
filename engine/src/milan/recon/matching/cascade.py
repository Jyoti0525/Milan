"""Running the strategies in order.

This is a cascade, not an agent. It tries rung one on every credit, then rung
two on whatever is left, and stops. There is no state, no planning, and no
choice about what to try next - so calling it an agent would be a nicer word
for the same fixed sequence.

Three details matter more than they look:

**Rung by rung, not credit by credit.** Every credit gets rung one before any
credit gets rung two. Exact matches consume their settlements first, which
removes them from the candidate pool and makes the weaker rung's job easier.
Walking credit-first would let a tolerance match claim a settlement that a
later credit could have proved exactly.

**A claim is provisional until it is proved.** Each rung's answer is handed
to the verifier - in a real run, the waterfall solver - before it is
accepted. A claim that will not reconstruct to zero is withdrawn and the
credit falls through to the next rung. This is what makes a merged credit
carrying one member's reference resolvable at all: rung one recognises the
reference, the proof comes up short by the other settlement, and the credit
goes on to the rung that can find the pair.

**Two credits cannot claim the same settlement.** If they collide inside a
rung, every credit involved is marked ambiguous rather than resolved
first-come. Order of iteration is not evidence.
"""

from __future__ import annotations

from collections import defaultdict

from milan.domain.records import BankCredit
from milan.recon.batches import BatchGroup, GatewayBatch
from milan.recon.matching.base import Attempt, Strategy, Verdict, Verifier, always_valid
from milan.recon.matching.exact import ExactUtrStrategy
from milan.recon.matching.subset import SubsetSumStrategy
from milan.recon.matching.tolerance import AmountDateStrategy


def default_strategies() -> tuple[Strategy, ...]:
    """The rungs, cheapest and most certain first.

    Order is a claim about evidence, not about cost. A reference identifies a
    payout; an amount and a date describe one; a sum of amounts merely
    permits one. Trying them in any other order would let the weakest kind of
    evidence claim settlements the strongest kind could have proved.
    """
    return (ExactUtrStrategy(), AmountDateStrategy(), SubsetSumStrategy())


class Cascade:
    """Applies each strategy to everything still unresolved."""

    def __init__(
        self,
        strategies: tuple[Strategy, ...] | None = None,
        verifier: Verifier | None = None,
    ) -> None:
        self._strategies = strategies if strategies is not None else default_strategies()
        self._verify = verifier if verifier is not None else always_valid

    def with_verifier(self, verifier: Verifier) -> Cascade:
        """The same rungs, now answerable to a proof.

        A copy rather than a mutation: the harness builds one cascade and
        hands it to several runs, and a cascade that quietly acquired a
        verifier from whoever used it last would make those runs depend on
        their order.
        """
        return Cascade(self._strategies, verifier)

    def run(
        self, credits: tuple[BankCredit, ...], batches: tuple[GatewayBatch, ...]
    ) -> dict[str, Attempt]:
        """Return the final attempt for every credit, resolved or not."""
        by_id = {batch.settlement_id: batch for batch in batches}
        outcome: dict[str, Attempt] = {}
        unresolved = list(credits)
        claimed: set[str] = set()

        for strategy in self._strategies:
            if not unresolved:
                break
            available = tuple(b for b in batches if b.settlement_id not in claimed)
            attempts = {c.credit_id: strategy.attempt(c, available) for c in unresolved}
            attempts = self._withdraw_unprovable(attempts, unresolved, by_id)
            settled = self._resolve_collisions(attempts)

            still_unresolved: list[BankCredit] = []
            for credit in unresolved:
                attempt = settled[credit.credit_id]
                if attempt.resolved:
                    claimed.update(attempt.settlement_ids)
                    outcome[credit.credit_id] = attempt
                else:
                    outcome[credit.credit_id] = self._keep_stronger(
                        outcome.get(credit.credit_id), attempt
                    )
                    still_unresolved.append(credit)
            unresolved = still_unresolved

        return outcome

    # ------------------------------------------------------------- internals

    def _withdraw_unprovable(
        self,
        attempts: dict[str, Attempt],
        credits: list[BankCredit],
        by_id: dict[str, GatewayBatch],
    ) -> dict[str, Attempt]:
        """Drop any claim the verifier will not stand behind.

        The withdrawal is recorded on the attempt rather than thrown away. A
        credit that reached the last rung having had two claims withdrawn is
        a different situation from one that never matched anything, and the
        exception queue should be able to tell them apart.
        """
        checked = dict(attempts)
        for credit in credits:
            attempt = attempts[credit.credit_id]
            if not attempt.resolved:
                continue
            group = BatchGroup.of(*(by_id[sid] for sid in attempt.settlement_ids))
            if not self._verify(credit, group):
                checked[credit.credit_id] = attempt.rejected(
                    f"{attempt.strategy.value} proposed "
                    f"{', '.join(attempt.settlement_ids)}, which does not reconstruct "
                    "this credit"
                )
        return checked

    def _resolve_collisions(self, attempts: dict[str, Attempt]) -> dict[str, Attempt]:
        """Demote every credit involved in a contested settlement."""
        contested: dict[str, list[str]] = defaultdict(list)
        for credit_id, attempt in attempts.items():
            for settlement_id in attempt.settlement_ids if attempt.resolved else ():
                contested[settlement_id].append(credit_id)

        disputed = {
            settlement_id: credit_ids
            for settlement_id, credit_ids in contested.items()
            if len(credit_ids) > 1
        }
        if not disputed:
            return dict(attempts)

        blamed: dict[str, str] = {}
        for settlement_id, credit_ids in sorted(disputed.items()):
            for credit_id in credit_ids:
                blamed.setdefault(credit_id, settlement_id)

        resolved = dict(attempts)
        for credit_id, settlement_id in blamed.items():
            rivals = len(disputed[settlement_id])
            resolved[credit_id] = attempts[credit_id].model_copy(
                update={
                    "verdict": Verdict.AMBIGUOUS,
                    "settlement_ids": (),
                    "confidence": 0.0,
                    "note": f"{rivals} credits fit settlement {settlement_id} equally well",
                }
            )
        return resolved

    def _keep_stronger(self, previous: Attempt | None, current: Attempt) -> Attempt:
        """Prefer the failure that says the most.

        "Two settlements fit this" is a more useful thing to report than
        "nothing fit", and it comes from a later rung that looked harder. The
        exception queue reads better when the reason survives the cascade.

        A withdrawn claim outranks both. It names a specific settlement, which
        is what lets the categoriser say *why* the credit is short instead of
        reporting that nothing matched.
        """
        if previous is None:
            return current
        merged = self._carry_withdrawal(previous, current)
        if current.verdict is Verdict.AMBIGUOUS:
            return merged
        if previous.verdict is Verdict.AMBIGUOUS:
            return previous.model_copy(update={"withdrawn_ids": merged.withdrawn_ids})
        return merged

    def _carry_withdrawal(self, previous: Attempt, current: Attempt) -> Attempt:
        """Withdrawals survive later rungs.

        A credit rejected at rung one and then failing rung three has still
        been identified once, and that identification is the most specific
        thing known about it.
        """
        if current.withdrawn_ids or not previous.withdrawn_ids:
            return current
        return current.model_copy(update={"withdrawn_ids": previous.withdrawn_ids})
