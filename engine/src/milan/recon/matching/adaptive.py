"""The alternative control policy, built to be beaten or to win.

The cascade's own docstring makes an engineering claim in prose: that trying
the rungs in a fixed order, rung by rung across every credit, does as well as
choosing per credit would. Nothing in this project had ever tested that. A
claim no implementation contradicts is an opinion with good posture, and the
build order's cut rule 9 turns this particular opinion into a vocabulary
rule - until an adaptive matcher is measured against the cascade, this is a
cascade and never an agent.

So this is the adaptive matcher, and it is written to win if it can.

**What varies, and what is held fixed.** The rungs are the same objects, the
verifier is the same veto, the collision rule is the same function, and the
harness is the same scorer. The only difference is who decides what to try
next. If the two policies score differently, the difference is the policy.

**Credit-first, not rung-first.** That is the substance of being adaptive. The
policy looks at one credit, decides which rung its evidence points at, and
tries that one first. A credit still carrying a reference goes to rung one; a
credit larger than any single payout goes straight to the combination search
without paying for the two rungs in between; a credit with no reference at all
never pays for the reference rung, because that rung cannot succeed without
one.

**The router may only look at what is cheap.** This is the constraint that
makes the experiment honest, and it is the easiest thing here to get wrong. A
router that asks "does any candidate match this amount exactly" has
*performed* the amount rung in order to decide whether to run the amount rung,
and a policy that pays a rung's cost to route around that rung has saved
nothing while appearing to. The three features below are a regex over the
narration, one comparison against the largest candidate, and a date lookup -
each strictly cheaper than the rung it routes to.

**Collisions still have to be caught.** Walking credit-first loses that for
free: whichever credit is looked at first takes the settlement, and order of
iteration is not evidence. Rather than let the adaptive policy lose on a
technicality it could have fixed, it claims in rounds. A full pass over the
unresolved credits collects claims without consuming anything, collisions are
resolved at the end of the pass by the same function the cascade uses, and the
pass repeats while it keeps resolving something new.

That iteration is a real cost, and the benchmark counts it rather than hiding
it. A policy that ties on accuracy and does more work has lost.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from milan.domain.enums import MatchStrategy
from milan.domain.records import BankCredit
from milan.recon.batches import BatchGroup, GatewayBatch
from milan.recon.matching.base import Attempt, Strategy, Verdict, Verifier, always_valid
from milan.recon.matching.cascade import default_strategies
from milan.recon.matching.claims import keep_stronger, resolve_collisions
from milan.recon.matching.exact import extract_utr

DATE_WINDOW = timedelta(days=1)
"""How near a settlement date counts as "on" it, for routing only.

Deliberately the same tolerance the rungs themselves use. A router with a
wider view than the rung it routes to would send credits to a rung that
cannot accept them, which measures the router's optimism rather than the
policy.
"""

FALLBACK = MatchStrategy.SHORTFALL
"""The rung the router may never skip.

Every other rung can be ruled out cheaply, which means a credit with no
reference, no near date and no candidates could otherwise be routed to
nothing at all - and a policy that returns no attempt has no answer to
record. The shortfall rung is the right floor for that: it is the only rung
whose claims are withdrawn by design, so reaching it costs an attempt and can
never manufacture a match.
"""


EVIDENCE_RANK: dict[MatchStrategy, int] = {
    rung: rank
    for rank, rung in enumerate(
        (
            MatchStrategy.EXACT_UTR,
            MatchStrategy.AMOUNT_DATE,
            MatchStrategy.SUBSET_SUM,
            MatchStrategy.FUZZY_NARRATION,
            MatchStrategy.SHORTFALL,
        )
    )
}
"""How claims are ranked when two credits want the same settlement.

The cascade never needs this. Running rung by rung, a reference claim is
banked before an amount claim is ever made, so claims of unequal strength do
not meet - the ordering *is* the priority. Routing per credit destroys that
and manufactures those meetings, and refusing both claimants would score the
adaptive policy on a collision the fixed order was quietly preventing rather
than on the routing under test.

So the adaptive arm is handed the same priority the cascade gets for free.
That it has to be handed it at all is worth noticing: the repair for
credit-first routing is to reintroduce, as an explicit tie-break, the exact
ordering that credit-first routing threw away.
"""


class Router(Protocol):
    """Chooses which rung to try next for one credit."""

    name: str

    def following(
        self,
        credit: BankCredit,
        candidates: tuple[GatewayBatch, ...],
        tried: frozenset[MatchStrategy],
    ) -> MatchStrategy | None:
        """The next rung worth trying, or `None` when the credit is spent."""
        ...


class HeuristicRouter:
    """Routes on three cheap features of the credit.

    Deterministic on purpose. The question this benchmark exists to answer is
    whether *choosing* helps, and putting a model in the chooser would confound
    that with whether the model is any good - two variables, one number. If
    routing turns out to be worth something here, a model-driven router is the
    obvious next experiment. If it is worth nothing, that experiment is
    answered before it is run.
    """

    name = "heuristic"

    def following(
        self,
        credit: BankCredit,
        candidates: tuple[GatewayBatch, ...],
        tried: frozenset[MatchStrategy],
    ) -> MatchStrategy | None:
        for choice in self.preference(credit, candidates):
            if choice not in tried:
                return choice
        return None

    def preference(
        self, credit: BankCredit, candidates: tuple[GatewayBatch, ...]
    ) -> tuple[MatchStrategy, ...]:
        """The rungs this credit's evidence points at, best first.

        Two decisions rather than one. Which rungs are worth trying at all -
        skipping a rung that cannot succeed is where an adaptive policy saves
        real work - and in what order to try the survivors.
        """
        if not candidates:
            return (FALLBACK,)

        has_reference = credit.utr is not None or extract_utr(credit.narration) is not None
        largest = max(batch.expected_net for batch in candidates)
        exceeds_any_single = credit.amount > largest
        near_a_settlement = any(
            abs(batch.settled_on - credit.value_date) <= DATE_WINDOW for batch in candidates
        )

        head: list[MatchStrategy] = []
        if has_reference:
            # The strongest evidence there is, and the cheapest to check.
            head.append(MatchStrategy.EXACT_UTR)
        if exceeds_any_single:
            # Bigger than any one payout, so it is either several of them or
            # none. The amount rung cannot resolve it and would be pure cost.
            head.append(MatchStrategy.SUBSET_SUM)
        elif near_a_settlement:
            head.append(MatchStrategy.AMOUNT_DATE)

        rest = [
            rung
            for rung in (
                MatchStrategy.AMOUNT_DATE,
                MatchStrategy.SUBSET_SUM,
                MatchStrategy.FUZZY_NARRATION,
            )
            if rung not in head and self._worth_trying(rung, has_reference, near_a_settlement)
        ]
        return (*head, *rest, FALLBACK)

    @staticmethod
    def _worth_trying(rung: MatchStrategy, has_reference: bool, near_a_settlement: bool) -> bool:
        """Whether a rung could succeed on this credit at all.

        Not a guess about likelihood - a statement about what each rung reads.
        The reference rung returns nothing without a reference, and the amount
        rung will not look outside its date window, so skipping either when the
        credit cannot satisfy it is a saving the fixed order cannot make.

        The similarity rung is deliberately never skipped, and the first draft
        of this method skipped it whenever no reference could be extracted.
        That reads plausibly and is backwards: that rung scores the raw
        narration against each candidate's reference, so the case it exists for
        - a reference damaged past the point where the extractor recognises one
        - is exactly the case the gate was removing. It cost the adaptive arm
        nine matches, which would have been published as a fact about
        adaptivity rather than about a bug in one router.
        """
        del has_reference
        if rung is MatchStrategy.AMOUNT_DATE:
            return near_a_settlement
        return True


class AdaptiveMatcher:
    """Chooses a rung per credit, then reconciles the claims."""

    def __init__(
        self,
        strategies: tuple[Strategy, ...] | None = None,
        verifier: Verifier | None = None,
        router: Router | None = None,
    ) -> None:
        self._strategies = strategies if strategies is not None else default_strategies()
        self._by_name = {strategy.name: strategy for strategy in self._strategies}
        self._verify = verifier if verifier is not None else always_valid
        self._router = router if router is not None else HeuristicRouter()

    @property
    def router(self) -> Router:
        return self._router

    def with_verifier(self, verifier: Verifier) -> AdaptiveMatcher:
        """The same policy, now answerable to a proof."""
        return AdaptiveMatcher(self._strategies, verifier, self._router)

    def run(
        self, credits: tuple[BankCredit, ...], batches: tuple[GatewayBatch, ...]
    ) -> dict[str, Attempt]:
        """Return the final attempt for every credit, resolved or not."""
        by_id = {batch.settlement_id: batch for batch in batches}
        outcome: dict[str, Attempt] = {}
        unresolved = list(credits)
        claimed: set[str] = set()
        blocked: dict[str, set[MatchStrategy]] = {}

        while unresolved:
            available = tuple(b for b in batches if b.settlement_id not in claimed)
            attempts = {
                credit.credit_id: self._route(
                    credit, available, by_id, frozenset(blocked.get(credit.credit_id, ()))
                )
                for credit in unresolved
            }
            settled = resolve_collisions(attempts, EVIDENCE_RANK)

            still_unresolved: list[BankCredit] = []
            progressed = False
            learned = False
            for credit in unresolved:
                attempt = settled[credit.credit_id]
                if attempt.resolved:
                    claimed.update(attempt.settlement_ids)
                    outcome[credit.credit_id] = attempt
                    progressed = True
                    continue

                if attempt.verdict is Verdict.AMBIGUOUS:
                    # This credit lost a settlement to another claimant, so
                    # the rung that produced the claim is spent for it. A
                    # policy that keeps making the losing claim is not
                    # adapting; it is looping. Blocking the rung is what lets
                    # the credit reach a different one on the next pass, which
                    # is the whole reason there is a next pass.
                    spent = blocked.setdefault(credit.credit_id, set())
                    if attempt.strategy not in spent:
                        spent.add(attempt.strategy)
                        learned = True

                outcome[credit.credit_id] = keep_stronger(outcome.get(credit.credit_id), attempt)
                still_unresolved.append(credit)

            unresolved = still_unresolved
            if not progressed and not learned:
                # Nothing was claimed and nothing was ruled out, so the next
                # pass would see the same candidates and make the same
                # choices. Continuing would be an infinite loop wearing the
                # costume of a search.
                break

        return outcome

    # ------------------------------------------------------------- internals

    def _route(
        self,
        credit: BankCredit,
        available: tuple[GatewayBatch, ...],
        by_id: dict[str, GatewayBatch],
        blocked: frozenset[MatchStrategy] = frozenset(),
    ) -> Attempt:
        """Try rungs in the router's order until one survives the verifier.

        The verification happens here rather than after the pass, which is the
        second half of being adaptive: a withdrawn claim sends *this* credit to
        *its* next rung immediately, instead of waiting for every other credit
        to finish the rung it is on.
        """
        tried: set[MatchStrategy] = set(blocked)
        best: Attempt | None = None

        while True:
            choice = self._router.following(credit, available, frozenset(tried))
            if choice is None:
                break
            tried.add(choice)
            strategy = self._by_name.get(choice)
            if strategy is None:
                continue

            attempt = strategy.attempt(credit, available)
            if attempt.resolved:
                group = BatchGroup.of(*(by_id[sid] for sid in attempt.settlement_ids))
                if self._verify(credit, group):
                    return attempt
                attempt = attempt.rejected(
                    f"{attempt.strategy.value} proposed "
                    f"{', '.join(attempt.settlement_ids)}, which does not reconstruct "
                    "this credit"
                )
            best = keep_stronger(best, attempt)

        if best is None:
            return Attempt(strategy=FALLBACK, verdict=Verdict.NO_CANDIDATE, note="no rung applied")
        return best
