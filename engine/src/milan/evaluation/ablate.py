"""Driving the ablation over generated datasets.

Kept apart from `ablation.py`, which holds the counting and the verification.
This is the part that decides which datasets to run and puts the questions;
that is the part that decides whether an answer is worth anything.
"""

from __future__ import annotations

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.rates import RateCard
from milan.evaluation.ablation import Ablation, AblationRun
from milan.evaluation.harness import to_recon_input
from milan.llm.provider import Provider
from milan.llm.triage import LlmTriage
from milan.recon.batches import BatchGroup, rebuild_batches
from milan.recon.pipeline import ReconciliationPipeline, RunMetadata


def ablate(
    provider: Provider,
    difficulty: Difficulty,
    seeds: tuple[int, ...],
    orders: int = 600,
    model: str = "",
    max_tokens: int = 96,
) -> Ablation:
    """Put every shortfall in every seed to the model, and check the answers.

    The pipeline runs first and runs unchanged. Its report is the rules'
    answer, and the model is asked afterwards about the same shortfalls - so
    nothing the model says can reach a graded number, and the comparison is
    between two answers to one question rather than between two pipelines.

    `max_tokens` is a property of the model rather than of the question. The
    answer is one small JSON object either way, but a reasoning model spends
    a few hundred tokens thinking before it writes one - and a budget that is
    generous for a 3B instruct model truncates a frontier model mid-thought,
    which is measured as an unanswered question rather than as a
    misconfiguration. It is also part of the cache key, so raising it for one
    provider cannot silently reuse another's answers.
    """
    rates = RateCard()
    triage = LlmTriage(provider, max_tokens=max_tokens)
    run = AblationRun(triage, rates, provider.name, model)

    for seed in seeds:
        config = GenerationConfig(seed=seed, difficulty=difficulty, order_count=orders)
        dataset = ChaosEngine(config).generate()
        data = to_recon_input(dataset)

        report = ReconciliationPipeline(rates=rates).run(
            data, RunMetadata(seed=seed, difficulty=difficulty.value)
        )
        by_id = {batch.settlement_id: batch for batch in rebuild_batches(data.settlement_rows)}
        settled = {exception.subject_id: exception.code for exception in report.exceptions}

        for shortfall in report.shortfalls:
            code = settled.get(shortfall.credit_id)
            if code is None:
                # Every shortfall is categorised, so this cannot happen - and
                # skipping rather than asserting keeps a future change to the
                # exception list from turning into a crash in a measurement.
                continue
            group = BatchGroup.of(*(by_id[sid] for sid in shortfall.settlement_ids))
            run.consider(shortfall, group, data.settlement_rows, code)

    return run.result()
