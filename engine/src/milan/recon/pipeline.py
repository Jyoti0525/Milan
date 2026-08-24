"""The reconciliation run, end to end.

Rebuild the batches, cascade the credits against them, prove each match to
the paisa, and sort whatever is left. Nothing here reaches for a model: this
whole path is deterministic, and it stays that way so the numbers it produces
are the same on every machine and in every run.

The order of operations encodes the design stance. Matching comes before
proving, and proving can veto matching: a credit the cascade claimed but the
waterfall could not reconstruct does not stay matched. It becomes an
exception, because a match nobody can check is worth less than an honest gap.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from milan.domain.rates import RateCard
from milan.domain.results import Proof, ReconException, ReconReport
from milan.recon.batches import GatewayBatch, rebuild_batches
from milan.recon.inputs import ReconInput
from milan.recon.matching.base import Attempt
from milan.recon.matching.cascade import Cascade
from milan.recon.triage import Categoriser
from milan.recon.waterfall import UnprovenCredit, prove


@dataclass(frozen=True, slots=True)
class RunMetadata:
    """Where this dataset came from. Carried through so a report can be traced."""

    seed: int
    difficulty: str


class ReconciliationPipeline:
    """Runs one reconciliation over one set of inputs."""

    def __init__(self, rates: RateCard | None = None, cascade: Cascade | None = None) -> None:
        self._rates = rates if rates is not None else RateCard()
        self._cascade = cascade if cascade is not None else Cascade()
        self._categoriser = Categoriser(self._rates)

    def run(self, data: ReconInput, metadata: RunMetadata) -> ReconReport:
        started = time.perf_counter()

        batches = rebuild_batches(data.settlement_rows)
        by_id = {batch.settlement_id: batch for batch in batches}
        attempts = self._cascade.run(data.bank_credits, batches)

        proofs, exceptions, claimed = self._prove_matches(data, by_id, attempts)
        exceptions.extend(self._explain_unmatched(data, batches, attempts))
        exceptions.extend(
            self._categoriser.missing_settlement(batch)
            for batch in batches
            if batch.settlement_id not in claimed
        )

        return ReconReport(
            seed=metadata.seed,
            difficulty=metadata.difficulty,
            records_processed=data.record_count,
            proofs=tuple(proofs),
            exceptions=tuple(exceptions),
            duration_seconds=time.perf_counter() - started,
        )

    def _prove_matches(
        self,
        data: ReconInput,
        by_id: dict[str, GatewayBatch],
        attempts: dict[str, Attempt],
    ) -> tuple[list[Proof], list[ReconException], set[str]]:
        """Reconstruct every claimed credit, and drop the ones that will not."""
        proofs: list[Proof] = []
        exceptions: list[ReconException] = []
        claimed: set[str] = set()

        for credit in data.bank_credits:
            attempt = attempts.get(credit.credit_id)
            if attempt is None or not attempt.resolved:
                continue
            assert attempt.settlement_id is not None
            batch = by_id[attempt.settlement_id]
            claimed.add(batch.settlement_id)

            result = prove(credit, batch, attempt.strategy, attempt.confidence, self._rates)
            if isinstance(result, UnprovenCredit):
                exceptions.append(
                    self._categoriser.unproven_credit(result, batch, data.settlement_rows)
                )
            else:
                proofs.append(result)

        return proofs, exceptions, claimed

    def _explain_unmatched(
        self,
        data: ReconInput,
        batches: tuple[GatewayBatch, ...],
        attempts: dict[str, Attempt],
    ) -> list[ReconException]:
        return [
            self._categoriser.unmatched_credit(credit, attempts[credit.credit_id], batches)
            for credit in data.bank_credits
            if credit.credit_id in attempts and not attempts[credit.credit_id].resolved
        ]
