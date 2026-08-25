"""What the model is actually worth, measured rather than claimed.

Every other number in this project is scored against the answer key. This one
is scored against the rules, because the question is not "is the model right"
but "does the model add anything the arithmetic did not already have".

Two populations, two different questions:

**Agreement** runs on shortfalls the deterministic checks already named. The
right answer is known, so this measures whether the model is competent at the
task at all. A model that cannot reproduce an answer the rules found has no
business proposing one they missed.

**Contribution** runs on shortfalls the rules could not name. This is the only
number that could justify a model being in the pipeline, and it is honest
about zero: if the rules already name everything the engine reaches, the model
proposes into an empty set and the measured contribution is nought. That is a
publishable result, not a failed experiment - but it has to be measured with a
model actually running, because "the rules already win" inferred from a model
never being switched on is an argument from silence.

Nothing here can change a graded figure. The ablation reads the report the
pipeline already produced; it does not feed anything back into it.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict

from milan.domain.enums import EntityType, ExceptionCode
from milan.domain.rates import RateCard
from milan.domain.records import SettlementRow
from milan.domain.results import UnprovenCredit
from milan.llm.triage import Hypothesis, HypothesisKind, LlmTriage
from milan.recon.batches import BatchGroup
from milan.recon.triage import Categoriser

_CODE_FOR: dict[ExceptionCode, HypothesisKind] = {
    ExceptionCode.PARTIAL_PAYMENT: HypothesisKind.RECOVERY_GAP,
    ExceptionCode.TAX_DEDUCTION: HypothesisKind.TAX_VARIANCE,
    ExceptionCode.FEE_DEDUCTION: HypothesisKind.FEE_VARIANCE,
}
"""What the rules concluded, expressed in the model's vocabulary, so the two
can be compared at all."""


class Ablation(BaseModel):
    """One provider, measured against the rules it is meant to improve on."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str

    asked: int
    answered: int
    """Questions put, and questions a model actually responded to. These
    differ when a daemon is down, and the gap is the honest reason a
    contribution figure might be zero."""

    agreement_cases: int
    agreement_hits: int
    """Of the shortfalls the rules named, how many the model named the same
    way. Verified, not taken on trust: a `recovery_gap` naming the wrong
    refund is a miss even though the kind is right."""

    open_cases: int
    contributions: int
    """Of the shortfalls the rules could not name, how many the model
    proposed something for that then survived arithmetic verification."""

    invented_ids: int
    """Proposals naming a record that is not in the report. The number worth
    watching: a hallucinated id sends a finance team looking through their
    ledger for a refund that never existed."""

    rejected: int
    """Proposals that claimed something and failed the arithmetic.

    Counted on both populations, which took a wrong measurement to notice: it
    was only being incremented on cases the rules had *not* named, so six
    proposals blaming the wrong refund on cases the rules had solved were
    reported as a plain disagreement rather than as arithmetic catching a
    wrong answer. These cost nothing, because they were discarded before
    anything was printed, and they are the whole reason a model is allowed to
    propose at all."""

    kinds: dict[str, int]

    @property
    def agreement_rate(self) -> float:
        return self.agreement_hits / self.agreement_cases if self.agreement_cases else 0.0

    @property
    def contribution_rate(self) -> float:
        return self.contributions / self.open_cases if self.open_cases else 0.0


def _verified(
    hypothesis: Hypothesis,
    unproven: UnprovenCredit,
    group: BatchGroup,
    rows: tuple[SettlementRow, ...],
    rates: RateCard,
) -> ExceptionCode | None:
    """Run the model's claim through the arithmetic the rules use.

    Deliberately the same `Categoriser`, not a parallel implementation. A
    verifier written separately for the model would eventually disagree with
    the one used for the rules, and the comparison between them would stop
    meaning anything.

    A `recovery_gap` is verified by handing the categoriser *only* the row the
    model named. If that row alone explains the shortfall the answer stands;
    if it does not, the claim is rejected. This is what makes a wrong proposal
    free.
    """
    if hypothesis.kind is HypothesisKind.UNKNOWN:
        return None

    categoriser = Categoriser(rates)
    if hypothesis.kind is HypothesisKind.RECOVERY_GAP:
        named = [
            row
            for row in rows
            if row.entity_id == hypothesis.entity_id
            and row.type in (EntityType.REFUND, EntityType.ADJUSTMENT)
        ]
        if not named:
            return None
        found = categoriser.unproven_credit(unproven, group, (*group.rows, *named))
        return found.code if found.code is ExceptionCode.PARTIAL_PAYMENT else None

    found = categoriser.unproven_credit(unproven, group, rows)
    expected = _CODE_FOR.get(found.code)
    return found.code if expected is hypothesis.kind else None


class AblationRun:
    """Accumulates one provider's results across however many datasets."""

    def __init__(self, triage: LlmTriage, rates: RateCard, provider: str, model: str) -> None:
        self._triage = triage
        self._rates = rates
        self.provider = provider
        self.model = model
        self._kinds: Counter[str] = Counter()
        self._agreement_cases = 0
        self._agreement_hits = 0
        self._open_cases = 0
        self._contributions = 0
        self._invented = 0
        self._rejected = 0

    def consider(
        self,
        unproven: UnprovenCredit,
        group: BatchGroup,
        rows: tuple[SettlementRow, ...],
        settled_code: ExceptionCode,
    ) -> None:
        """One shortfall, put to the model and then checked."""
        hypothesis = self._triage.propose(unproven, group, rows)
        self._kinds[hypothesis.kind.value] += 1

        rules_named = settled_code is not ExceptionCode.UNEXPLAINED
        verified = _verified(hypothesis, unproven, group, rows, self._rates)

        if hypothesis.invented_id is not None:
            self._invented += 1
        if hypothesis.kind is not HypothesisKind.UNKNOWN and verified is None:
            self._rejected += 1

        if rules_named:
            self._agreement_cases += 1
            if verified is settled_code:
                self._agreement_hits += 1
            return

        self._open_cases += 1
        if verified is not None:
            self._contributions += 1

    def result(self) -> Ablation:
        return Ablation(
            provider=self.provider,
            model=self.model,
            asked=self._triage.asked,
            answered=self._triage.answered,
            agreement_cases=self._agreement_cases,
            agreement_hits=self._agreement_hits,
            open_cases=self._open_cases,
            contributions=self._contributions,
            invented_ids=self._invented,
            rejected=self._rejected,
            kinds=dict(self._kinds),
        )
