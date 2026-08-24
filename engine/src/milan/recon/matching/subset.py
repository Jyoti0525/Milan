"""Rung three: one credit, several settlements.

Banks merge transfers. Two payouts initiated in the same cycle can leave the
gateway as two settlements and arrive at the merchant as one NEFT line, and
the statement then shows a single amount that matches no settlement at all.
Rung two looks for a batch of that size, finds nothing, and is right to.

So this rung asks a different question: is there a *combination* of unclaimed
settlements that adds up to what arrived? That is subset-sum, and it is the
first rung here that can genuinely be wrong, for two reasons worth naming.

**Coincidence.** Enough candidate batches and some subset will hit almost any
target by chance. The defence is not a cleverer search, it is a narrow
window: only settlements that could plausibly have been swept into the same
transfer are considered at all.

**Multiplicity.** When two different combinations both add up, the closer one
is not the answer - there is no answer. Both are reported and the credit goes
to a person. A single settlement that also fits counts as a competing
explanation too, which is why a lone batch of the right size makes this rung
refuse rather than reach for the pair.

The search is bounded on purpose. If it runs out of budget it says so and
declines, because a truncated search has not established that its answer is
unique, and uniqueness is the entire basis on which this rung is allowed to
claim anything.
"""

from __future__ import annotations

from datetime import timedelta

from milan.domain.enums import MatchStrategy
from milan.domain.money import Paise, format_inr
from milan.domain.records import BankCredit
from milan.recon.batches import BatchGroup, GatewayBatch
from milan.recon.matching.base import Attempt, Verdict

MERGE_WINDOW_BEFORE = timedelta(days=3)
"""How far back a settlement can have been initiated and still be swept into
the same transfer. Three days covers a weekend; wider than that and the
combinations stop being evidence and start being arithmetic."""

MERGE_WINDOW_AFTER = timedelta(days=1)
"""A cut-off miss can push a payout to the next day."""

MAX_MEMBERS = 3
"""Merged transfers in practice are two payouts, occasionally three. Allowing
four would roughly triple the search and, far worse, roughly triple the
number of coincidental sums that look like answers."""

SEARCH_BUDGET = 50_000
"""Nodes visited before the search gives up and refuses."""


class SubsetSumStrategy:
    """Find the set of settlements that together explain one credit."""

    name = MatchStrategy.SUBSET_SUM

    def __init__(self, max_members: int = MAX_MEMBERS, budget: int = SEARCH_BUDGET) -> None:
        self._max_members = max_members
        self._budget = budget

    def attempt(self, credit: BankCredit, candidates: tuple[GatewayBatch, ...]) -> Attempt:
        pool = self._pool(credit, candidates)
        if len(pool) < 2:
            return Attempt(
                strategy=self.name,
                verdict=Verdict.NO_CANDIDATE,
                note=(f"{len(pool)} settlements near {credit.value_date}; nothing to combine"),
            )

        solutions, truncated = self._search(credit.amount, pool)

        if truncated:
            return Attempt(
                strategy=self.name,
                verdict=Verdict.NO_CANDIDATE,
                note=(
                    f"search over {len(pool)} settlements exceeded its budget; "
                    "no combination can be called unique"
                ),
            )

        singles = [b for b in pool if abs(credit.amount - b.expected_net) <= b.rounding_allowance]
        competing = [*(BatchGroup.of(b) for b in singles), *solutions]

        if not competing:
            return Attempt(
                strategy=self.name,
                verdict=Verdict.NO_CANDIDATE,
                note=(
                    f"no combination of up to {self._max_members} settlements near "
                    f"{credit.value_date} totals {format_inr(credit.amount)}"
                ),
            )

        if len(competing) > 1:
            return Attempt(
                strategy=self.name,
                verdict=Verdict.AMBIGUOUS,
                candidates=tuple(sorted({sid for g in competing for sid in g.settlement_ids})),
                note=(
                    f"{len(competing)} different combinations total "
                    f"{format_inr(credit.amount)}; nothing distinguishes them"
                ),
            )

        group = competing[0]
        gap = Paise(abs(credit.amount - group.expected_net))
        return Attempt(
            strategy=self.name,
            verdict=Verdict.MATCHED,
            settlement_ids=group.settlement_ids,
            candidates=group.settlement_ids,
            confidence=self._confidence(gap, group),
            note=(
                f"{len(group.batches)} settlements totalling "
                f"{format_inr(group.expected_net)}, "
                f"{group.opened_on} to {group.settled_on}"
            ),
        )

    # ------------------------------------------------------------- internals

    def _pool(
        self, credit: BankCredit, candidates: tuple[GatewayBatch, ...]
    ) -> tuple[GatewayBatch, ...]:
        """Settlements that could have been swept into this transfer.

        Sorted by amount descending so the search is deterministic and so the
        largest batches - which prune hardest - are tried first.
        """
        earliest = credit.value_date - MERGE_WINDOW_BEFORE
        latest = credit.value_date + MERGE_WINDOW_AFTER
        near = [
            batch
            for batch in candidates
            if earliest <= batch.settled_on <= latest
            and batch.expected_net > 0
            and batch.expected_net <= credit.amount + batch.rounding_allowance
        ]
        near.sort(key=lambda batch: (-batch.expected_net, batch.settlement_id))
        return tuple(near)

    def _search(
        self, target: Paise, pool: tuple[GatewayBatch, ...]
    ) -> tuple[list[BatchGroup], bool]:
        """Depth-first over subsets of two or more, stopping at two answers.

        Two is enough. The question this rung has to answer is not "what is
        the best combination" but "is there exactly one", and a second answer
        settles that as conclusively as a hundred would.
        """
        remaining_after = self._suffix_sums(pool)
        slack = Paise(sum(batch.rounding_allowance for batch in pool))

        solutions: list[BatchGroup] = []
        visited = 0
        truncated = False

        def walk(index: int, chosen: list[GatewayBatch], outstanding: Paise) -> None:
            nonlocal visited, truncated
            if truncated or len(solutions) >= 2:
                return
            visited += 1
            if visited > self._budget:
                truncated = True
                return

            if len(chosen) >= 2:
                group = BatchGroup.of(*chosen)
                if abs(outstanding) <= group.rounding_allowance:
                    solutions.append(group)
                    return

            if len(chosen) >= self._max_members or index >= len(pool):
                return
            if outstanding <= -slack:
                return
            if outstanding > remaining_after[index] + slack:
                return

            for next_index in range(index, len(pool)):
                batch = pool[next_index]
                chosen.append(batch)
                walk(next_index + 1, chosen, Paise(outstanding - batch.expected_net))
                chosen.pop()
                if truncated or len(solutions) >= 2:
                    return

        walk(0, [], target)
        return solutions, truncated

    def _suffix_sums(self, pool: tuple[GatewayBatch, ...]) -> list[Paise]:
        """How much is still on the table from each position onward."""
        sums: list[Paise] = [Paise(0)] * (len(pool) + 1)
        for index in range(len(pool) - 1, -1, -1):
            sums[index] = Paise(sums[index + 1] + pool[index].expected_net)
        return sums

    def _confidence(self, gap: Paise, group: BatchGroup) -> float:
        """Deliberately capped below the single-batch rungs.

        A reference is proof of identity. A sum is proof of arithmetic, and
        arithmetic has coincidences. Reporting a merged match at the same
        confidence as a UTR match would make the two look interchangeable to
        anyone reading the queue, and they are not.
        """
        base = 0.75 if gap == 0 else 0.65
        return base - 0.05 * (len(group.batches) - 2)
