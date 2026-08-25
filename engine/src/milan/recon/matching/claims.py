"""What to do with claims once the rungs have made them.

Two rules that have nothing to do with which rung produced a claim, and
everything to do with whether a claim may be believed:

**Two credits cannot claim the same settlement.** If they collide, every
credit involved is marked ambiguous rather than resolved first-come. Order of
iteration is not evidence.

**Prefer the failure that says the most.** "Two settlements fit this" is more
useful to a human than "nothing fit", and a withdrawn claim - one that named a
settlement before the prover refused it - outranks both, because it is the
most specific thing anyone knows about the credit.

Extracted from the cascade when a second control policy needed them. Leaving
them where they were would have meant the adaptive matcher either imported
private methods off a class it does not extend, or grew its own copy - and a
benchmark whose two arms disagree about what a collision is measures the
disagreement rather than the policies.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from milan.domain.enums import MatchStrategy
from milan.recon.matching.base import Attempt, Verdict


def resolve_collisions(
    attempts: dict[str, Attempt],
    priority: Mapping[MatchStrategy, int] | None = None,
) -> dict[str, Attempt]:
    """Demote every credit involved in a contested settlement.

    `priority` awards a contested settlement to the claim resting on the
    strongest evidence, instead of refusing every claimant. The cascade does
    not need it: running rung by rung means a reference claim is already
    banked before an amount claim is ever made, so claims of unequal strength
    never meet. A policy that walks credit-first manufactures exactly those
    meetings, and refusing both would penalise it for a collision the ordering
    was preventing rather than for the routing under test.

    A tie in strength is still refused. Two credits whose claims rest on the
    same rung are genuinely indistinguishable, and picking one would be
    order of iteration wearing a rule's clothing.
    """
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

    blamed: dict[str, tuple[str, tuple[str, ...], bool]] = {}
    for settlement_id, credit_ids in sorted(disputed.items()):
        losers, on_strength = _losers(credit_ids, attempts, priority)
        for credit_id in losers:
            rivals = tuple(other for other in credit_ids if other != credit_id)
            blamed.setdefault(credit_id, (settlement_id, rivals, on_strength))

    resolved = dict(attempts)
    for credit_id, (settlement_id, rivals, on_strength) in blamed.items():
        resolved[credit_id] = attempts[credit_id].model_copy(
            update={
                "verdict": Verdict.AMBIGUOUS,
                "settlement_ids": (),
                "candidates": (settlement_id,),
                "confidence": 0.0,
                "contested_by": rivals,
                "note": (
                    f"settlement {settlement_id} was claimed on stronger evidence by {rivals[0]}"
                    if on_strength
                    else f"{len(rivals) + 1} credits fit settlement {settlement_id} equally well"
                ),
            }
        )
    return resolved


def _losers(
    credit_ids: list[str],
    attempts: dict[str, Attempt],
    priority: Mapping[MatchStrategy, int] | None,
) -> tuple[list[str], bool]:
    """Which claimants give way, and whether evidence decided it.

    With no priority nobody gives way and everybody is demoted - the cascade's
    rule, where a collision means the evidence does not distinguish the
    claimants. With a priority a single strongest claim survives and the rest
    give way to it; a tie at the top is still a genuine ambiguity and every
    claimant is demoted, because picking one would be order of iteration
    wearing a rule's clothing.
    """
    if priority is None:
        return list(credit_ids), False

    unknown = len(priority)
    ranked = [(priority.get(attempts[cid].strategy, unknown), cid) for cid in credit_ids]
    strongest = min(rank for rank, _ in ranked)
    leaders = [cid for rank, cid in ranked if rank == strongest]
    if len(leaders) > 1:
        return list(credit_ids), False
    return [cid for _, cid in ranked if cid not in leaders], True


def keep_stronger(previous: Attempt | None, current: Attempt) -> Attempt:
    """Prefer the failure that says the most.

    "Two settlements fit this" is a more useful thing to report than
    "nothing fit", and it comes from a rung that looked harder. The exception
    queue reads better when the reason survives the search.

    A withdrawn claim outranks both. It names a specific settlement, which is
    what lets the categoriser say *why* the credit is short instead of
    reporting that nothing matched.
    """
    if previous is None:
        return current
    merged = carry_withdrawal(previous, current)
    if current.verdict is Verdict.AMBIGUOUS:
        return merged
    if previous.verdict is Verdict.AMBIGUOUS:
        return previous.model_copy(update={"withdrawn_ids": merged.withdrawn_ids})
    return merged


def carry_withdrawal(previous: Attempt, current: Attempt) -> Attempt:
    """Withdrawals survive later rungs.

    A credit rejected at one rung and then failing another has still been
    identified once, and that identification is the most specific thing known
    about it.
    """
    if current.withdrawn_ids or not previous.withdrawn_ids:
        return current
    return current.model_copy(update={"withdrawn_ids": previous.withdrawn_ids})
