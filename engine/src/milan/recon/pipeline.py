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
from milan.domain.merchant import MerchantProfile, profile_of
from milan.domain.rates import RateCard
from milan.domain.records import Payment, SettlementRow
from milan.domain.results import Proof, ReconException, ReconReport, UnprovenCredit
from milan.leaks.detector import detect
from milan.recon.batches import BatchGroup, GatewayBatch, rebuild_batches
from milan.recon.inputs import ReconInput
from milan.recon.matching.base import Attempt, Matcher
from milan.recon.matching.cascade import Cascade, default_strategies
from milan.recon.triage import Categoriser
from milan.recon.waterfall import provable, prove


@dataclass(frozen=True, slots=True)
class Reading:
    """What one run decided about the merchant before it started matching.

    Bundled rather than passed as three arguments because they are one
    decision: the profile is what was read, the rate card is what that means
    for the arithmetic, and the categoriser is the thing that will explain a
    failure in those terms. Splitting them is how two of the three end up
    describing a different merchant from the third.
    """

    profile: MerchantProfile
    rates: RateCard
    categoriser: Categoriser


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

        `rates` left unset means "read the merchant off their own files", and
        that is the setting every real import runs under - nobody hands a
        finance team a rate card along with their bank statement. Passing one
        explicitly means "I know this merchant's contract", which is what
        every measured number in this project does, so that a graded figure
        cannot move because a detector changed its mind. That distinction is
        why this is `None` rather than a `RateCard()` default.
        """
        self._rates = rates
        self._cascade = cascade

    def run(self, data: ReconInput, metadata: RunMetadata) -> ReconReport:
        started = time.perf_counter()

        # Read before anything else runs. The shortfall rung derives its
        # tolerance from the rate card, so a merchant identified after the
        # cascade has finished would have been identified too late to matter.
        reading = self._read(data)

        batches = rebuild_batches(data.settlement_rows)
        by_id = {batch.settlement_id: batch for batch in batches}
        cascade = self._cascade_for(reading).with_verifier(
            lambda credit, group: provable(credit, group, reading.rates)
        )
        attempts = cascade.run(data.bank_credits, batches)

        proofs, exceptions, claimed, shortfalls = self._prove_matches(
            data, by_id, attempts, reading
        )
        withdrawn_explanations, withdrawn_shortfalls = self._explain_unmatched(
            data, batches, by_id, attempts, reading
        )
        exceptions.extend(withdrawn_explanations)
        shortfalls.extend(withdrawn_shortfalls)
        exceptions.extend(
            reading.categoriser.missing_settlement(batch, batches)
            for batch in batches
            if batch.settlement_id not in claimed
        )
        exceptions.extend(self._find_unsettled_payments(data, reading))

        return ReconReport(
            profile=reading.profile,
            # Run last and kept apart from the exceptions. Every row this
            # finds reconciled perfectly, which is the whole point of it -
            # filing these among the things that failed to reconcile would
            # bury the only finding that survives the books balancing.
            leaks=detect(data.settlement_rows, reading.rates),
            seed=metadata.seed,
            difficulty=metadata.difficulty,
            records_processed=data.record_count,
            proofs=tuple(proofs),
            exceptions=tuple(exceptions),
            shortfalls=tuple(shortfalls),
            duration_seconds=time.perf_counter() - started,
        )

    # ------------------------------------------------------------- internals

    def _read(self, data: ReconInput) -> Reading:
        """Identify the merchant, unless someone has already said who they are."""
        profile = profile_of(data.settlement_rows)
        rates = self._rates if self._rates is not None else profile.rates()
        return Reading(profile=profile, rates=rates, categoriser=Categoriser(rates))

    def _cascade_for(self, reading: Reading) -> Matcher:
        """The rungs, built against the rate card this run settled on.

        A cascade handed in from outside is used as it arrived. The benchmark
        builds one policy and compares it against another, and rebuilding it
        here would silently swap out the very thing being measured - so the
        one caller that supplies a cascade is also the one that supplies a
        rate card, and neither is second-guessed.
        """
        if self._cascade is not None:
            return self._cascade
        return Cascade(default_strategies(reading.rates))

    def _prove_matches(
        self,
        data: ReconInput,
        by_id: dict[str, GatewayBatch],
        attempts: dict[str, Attempt],
        reading: Reading,
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

            result = prove(credit, group, attempt.strategy, attempt.confidence, reading.rates)
            if isinstance(result, UnprovenCredit):
                shortfalls.append(result)
                exceptions.append(
                    reading.categoriser.unproven_credit(result, group, data.settlement_rows)
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
        reading: Reading,
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
                result = prove(credit, group, attempt.strategy, attempt.confidence, reading.rates)
                if isinstance(result, UnprovenCredit):
                    shortfalls.append(result)
                    explanations.append(
                        reading.categoriser.unproven_credit(result, group, data.settlement_rows)
                    )
                    continue

            explanations.append(reading.categoriser.unmatched_credit(credit, attempt, batches))
        return explanations, shortfalls

    def _find_unsettled_payments(self, data: ReconInput, reading: Reading) -> list[ReconException]:
        """Captured money the settlement report never accounts for."""
        cutoff = _report_complete_to(data.settlement_rows)
        if cutoff is None:
            return []

        reported = {
            row.payment_id for row in data.settlement_rows if row.payment_id is not None
        } | {row.entity_id for row in data.settlement_rows}

        return [
            reading.categoriser.unsettled_payment(payment, cutoff)
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
