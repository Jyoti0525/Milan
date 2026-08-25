"""The reconciliation run, end to end.

Rebuild the batches, cascade the credits against them, prove each match to
the paisa, and sort whatever is left. Nothing here reaches for a model: this
whole path is deterministic, and it stays that way so the numbers it produces
are the same on every machine and in every run.

The order of operations encodes the design stance. Matching comes before
proving, and proving can veto matching: a credit the cascade claimed but the
waterfall could not reconstruct does not stay matched. The veto is handed to
the cascade rather than applied afterwards, so a withdrawn claim sends the
credit down to the next rung instead of straight to the exception queue.

The last step looks in the opposite direction from all the others. Everything
above starts from a bank credit and asks what explains it. That can only ever
find money that arrived. A payment the gateway never reported did not arrive
and never will, and no amount of matching credits will notice it - so the run
finishes by reading the payments file and asking what the settlement report
is missing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date

from milan.domain.calendar import (
    DOMESTIC_SETTLEMENT_DAYS,
    INTERNATIONAL_SETTLEMENT_DAYS,
    add_working_days,
)
from milan.domain.enums import CardType
from milan.domain.rates import RateCard
from milan.domain.records import BankCredit, Payment, SettlementRow
from milan.domain.results import Proof, ReconException, ReconReport, UnprovenCredit
from milan.leaks.detector import detect
from milan.recon.batches import BatchGroup, GatewayBatch, rebuild_batches
from milan.recon.inputs import ReconInput
from milan.recon.matching.base import Attempt, Matcher
from milan.recon.matching.cascade import Cascade
from milan.recon.triage import Categoriser
from milan.recon.waterfall import provable, prove


@dataclass(frozen=True, slots=True)
class RunMetadata:
    """Where this dataset came from. Carried through so a report can be traced."""

    seed: int
    difficulty: str


class ReconciliationPipeline:
    """Runs one reconciliation over one set of inputs."""

    def __init__(self, rates: RateCard | None = None, cascade: Matcher | None = None) -> None:
        """The pipeline takes any control policy, and defaults to the cascade.

        Typed as `Matcher` rather than `Cascade` so the benchmark can hand it
        an adaptive policy and have every number downstream produced by the
        same code. A benchmark that reimplements the pipeline to run its
        alternative arm is measuring two pipelines.
        """
        self._rates = rates if rates is not None else RateCard()
        self._cascade = cascade if cascade is not None else Cascade()
        self._categoriser = Categoriser(self._rates)

    def run(self, data: ReconInput, metadata: RunMetadata) -> ReconReport:
        started = time.perf_counter()

        batches = rebuild_batches(data.settlement_rows)
        by_id = {batch.settlement_id: batch for batch in batches}
        cascade = self._cascade.with_verifier(self._provable)
        attempts = cascade.run(data.bank_credits, batches)

        proofs, exceptions, claimed, shortfalls = self._prove_matches(data, by_id, attempts)
        withdrawn_explanations, withdrawn_shortfalls = self._explain_unmatched(
            data, batches, by_id, attempts
        )
        exceptions.extend(withdrawn_explanations)
        shortfalls.extend(withdrawn_shortfalls)
        exceptions.extend(
            self._categoriser.missing_settlement(batch)
            for batch in batches
            if batch.settlement_id not in claimed
        )
        exceptions.extend(self._find_unsettled_payments(data))

        return ReconReport(
            # Run last and kept apart from the exceptions. Every row this
            # finds reconciled perfectly, which is the whole point of it -
            # filing these among the things that failed to reconcile would
            # bury the only finding that survives the books balancing.
            leaks=detect(data.settlement_rows, self._rates),
            seed=metadata.seed,
            difficulty=metadata.difficulty,
            records_processed=data.record_count,
            proofs=tuple(proofs),
            exceptions=tuple(exceptions),
            shortfalls=tuple(shortfalls),
            duration_seconds=time.perf_counter() - started,
        )

    # ------------------------------------------------------------- internals

    def _provable(self, credit: BankCredit, group: BatchGroup) -> bool:
        """The veto the cascade consults before accepting any rung's claim."""
        return provable(credit, group, self._rates)

    def _prove_matches(
        self,
        data: ReconInput,
        by_id: dict[str, GatewayBatch],
        attempts: dict[str, Attempt],
    ) -> tuple[list[Proof], list[ReconException], set[str], list[UnprovenCredit]]:
        """Reconstruct every claimed credit, and drop the ones that will not.

        The cascade has already checked each claim against the same
        arithmetic, so a failure here is rare rather than routine. It is still
        checked, because the version of this that trusts the earlier check is
        the version where a change to one of them silently stops mattering.
        """
        proofs: list[Proof] = []
        exceptions: list[ReconException] = []
        claimed: set[str] = set()
        # Kept rather than discarded. The categorised exception below is a
        # conclusion; this is the evidence it was drawn from, and the ablation
        # needs the evidence to put the same question to a model.
        shortfalls: list[UnprovenCredit] = []

        for credit in data.bank_credits:
            attempt = attempts.get(credit.credit_id)
            if attempt is None or not attempt.resolved:
                continue
            group = BatchGroup.of(*(by_id[sid] for sid in attempt.settlement_ids))
            claimed.update(group.settlement_ids)

            result = prove(credit, group, attempt.strategy, attempt.confidence, self._rates)
            if isinstance(result, UnprovenCredit):
                shortfalls.append(result)
                exceptions.append(
                    self._categoriser.unproven_credit(result, group, data.settlement_rows)
                )
            else:
                proofs.append(result)

        return proofs, exceptions, claimed, shortfalls

    def _explain_unmatched(
        self,
        data: ReconInput,
        batches: tuple[GatewayBatch, ...],
        by_id: dict[str, GatewayBatch],
        attempts: dict[str, Attempt],
    ) -> tuple[list[ReconException], list[UnprovenCredit]]:
        """Say what is wrong with each credit nothing could claim.

        A credit whose claim was withdrawn is not the same as one nothing
        recognised. The veto identified a settlement and then found the
        arithmetic did not close, and that is far more actionable than "no
        candidate" - it is the difference between "this is settlement A and
        it is short by exactly refund R" and a shrug.

        Reconstructing the withdrawn claim here rather than caching it from
        the cascade keeps the categoriser reading the same proof the run
        would have reported, instead of a summary of it.
        """
        explanations: list[ReconException] = []
        # Nearly every shortfall in the system is found here rather than in
        # `_prove_matches`, and that is the architecture working: proving
        # vetoes matching *inside* the cascade, so a credit that will not
        # reconstruct has its claim withdrawn before it is ever reported as
        # matched. The reconstruction still happened, and it is what the
        # categoriser reads.
        shortfalls: list[UnprovenCredit] = []
        for credit in data.bank_credits:
            attempt = attempts.get(credit.credit_id)
            if attempt is None or attempt.resolved:
                continue

            withdrawn = [by_id[sid] for sid in attempt.withdrawn_ids if sid in by_id]
            if withdrawn:
                group = BatchGroup.of(*withdrawn)
                result = prove(credit, group, attempt.strategy, attempt.confidence, self._rates)
                if isinstance(result, UnprovenCredit):
                    shortfalls.append(result)
                    explanations.append(
                        self._categoriser.unproven_credit(result, group, data.settlement_rows)
                    )
                    continue

            explanations.append(self._categoriser.unmatched_credit(credit, attempt, batches))
        return explanations, shortfalls

    def _find_unsettled_payments(self, data: ReconInput) -> list[ReconException]:
        """Captured money the settlement report never accounts for."""
        cutoff = _report_complete_to(data.settlement_rows)
        if cutoff is None:
            return []

        reported = {
            row.payment_id for row in data.settlement_rows if row.payment_id is not None
        } | {row.entity_id for row in data.settlement_rows}

        return [
            self._categoriser.unsettled_payment(payment, cutoff)
            for payment in data.payments
            if payment.payment_id not in reported and _due_by(payment) <= cutoff
        ]


def _report_complete_to(rows: tuple[SettlementRow, ...]) -> date | None:
    """The last day the settlement report has anything to say about.

    Beyond this date the report is not wrong, it is merely not written yet,
    and a payment due to settle after it is pending rather than missing. Using
    the report's own horizon rather than a clock read keeps the answer the
    same however long after generation the run happens.
    """
    settled = [row.settled_at.date() for row in rows if row.settled_at is not None]
    return max(settled) if settled else None


def _due_by(payment: Payment) -> date:
    """When this payment should have appeared in a settlement.

    T+2 working days domestic, T+7 for international cards, which is the
    published cycle rather than a tolerance we chose.
    """
    lag = (
        INTERNATIONAL_SETTLEMENT_DAYS
        if payment.card_type is CardType.INTERNATIONAL
        else DOMESTIC_SETTLEMENT_DAYS
    )
    return add_working_days(payment.captured_at.date(), lag)
