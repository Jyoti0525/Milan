"""Ask the same questions twice, and see whether the answers hold still.

The claim this project is built on is that a reconciliation is reproducible:
the same input produces the same books, and `milan reproduce` makes that
falsifiable rather than asserted. This is the other half of that argument -
what happens when the answers come from a model instead.

Nothing here touches a graded number. It cannot: the reconciliation runs
first and runs unchanged, and this asks a model about shortfalls afterwards.
What it measures is whether a system built the other way round - one that let
the model decide - could make the same promise.

**The cache is deliberately not in front of this.** Everywhere else, a cached
answer is what makes a run with a model reproducible. Here, replaying the
first answer is exactly the thing being tested, and a cache hit would prove
the point by refusing to run the experiment.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.rates import RateCard
from milan.evaluation.harness import to_recon_input
from milan.llm.provider import Provider
from milan.llm.triage import Hypothesis, LlmTriage
from milan.recon.batches import BatchGroup, rebuild_batches
from milan.recon.pipeline import ReconciliationPipeline, RunMetadata


class Answer(BaseModel):
    """One claim, reduced to what a reader would act on."""

    model_config = ConfigDict(frozen=True)

    kind: str
    entity_id: str | None = None

    def __str__(self) -> str:
        return f"{self.kind}{f' {self.entity_id}' if self.entity_id else ''}"


class Question(BaseModel):
    """One shortfall, answered twice."""

    model_config = ConfigDict(frozen=True)

    credit_id: str
    first: Answer
    second: Answer

    @property
    def changed(self) -> bool:
        return self.first != self.second

    @property
    def named_a_different_record(self) -> bool:
        """The expensive kind of disagreement.

        A model that says `recovery_gap` twice and blames two different
        refunds has not been vague, it has been confidently wrong once. That
        is a different failure from changing its mind about the category, and
        it is the one that would send somebody looking through a ledger.
        """
        return (
            self.first.entity_id is not None
            and self.second.entity_id is not None
            and self.first.entity_id != self.second.entity_id
        )


class Twice(BaseModel):
    """What two passes over the same questions produced."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    temperature: float
    seeds: tuple[int, ...]
    difficulty: str
    questions: tuple[Question, ...]

    @property
    def asked(self) -> int:
        return len(self.questions)

    @property
    def changed(self) -> int:
        return sum(1 for question in self.questions if question.changed)

    @property
    def different_records(self) -> int:
        return sum(1 for question in self.questions if question.named_a_different_record)

    @property
    def stable(self) -> bool:
        return self.changed == 0


def _answer(hypothesis: Hypothesis) -> Answer:
    return Answer(kind=hypothesis.kind.value, entity_id=hypothesis.entity_id)


def run_twice(
    provider: Provider,
    seeds: tuple[int, ...] = (42,),
    difficulty: Difficulty = Difficulty.ADVERSARIAL,
    orders: int = 600,
    temperature: float = 0.0,
    limit: int = 0,
    model: str = "",
) -> Twice:
    """Put shortfalls to the model twice each, and compare the two answers.

    A handful of seeds rather than all twenty. The question here is not how
    often a model is right - the ablation answers that over every seed - but
    whether it says the same thing twice, and every question costs two calls
    to a laptop GPU.
    """
    rates = RateCard()
    first_pass = LlmTriage(provider, temperature=temperature)
    second_pass = LlmTriage(provider, temperature=temperature)
    questions: list[Question] = []

    for seed in seeds:
        config = GenerationConfig(seed=seed, difficulty=difficulty, order_count=orders)
        data = to_recon_input(ChaosEngine(config).generate())
        report = ReconciliationPipeline(rates=rates).run(
            data, RunMetadata(seed=seed, difficulty=difficulty.value)
        )
        by_id = {batch.settlement_id: batch for batch in rebuild_batches(data.settlement_rows)}

        for shortfall in report.shortfalls:
            if limit and len(questions) >= limit:
                break
            group = BatchGroup.of(*(by_id[sid] for sid in shortfall.settlement_ids))
            questions.append(
                Question(
                    credit_id=shortfall.credit_id,
                    first=_answer(first_pass.propose(shortfall, group, data.settlement_rows)),
                    second=_answer(second_pass.propose(shortfall, group, data.settlement_rows)),
                )
            )

    return Twice(
        provider=provider.name,
        model=model,
        temperature=temperature,
        seeds=seeds,
        difficulty=difficulty.value,
        questions=tuple(questions),
    )
