"""What a run looks like to something outside the engine.

The queue needs more than the engine's own output. A `ReconException` names
its subject by id, which is all the pipeline needs and nothing a person can
act on: "bank_x9f2 is short Rs 812" is a row in a spreadsheet, not a case to
work. So exceptions are joined back to the record they are about, and carry
the amount, the date and the narration the bank actually sent.

This module is also where the answer key stops. The API serves what a real
merchant would hold - orders, the settlement report, the bank statement - and
never the ground truth, for the same reason `milan.recon` may not import it:
a queue that can see the answers is a demo, not a system. Scores come from the
evaluation package on its own route, computed rather than peeked at.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from milan.chaos.config import Difficulty
from milan.domain.dataset import Dataset
from milan.domain.enums import EntityType, ExceptionCode
from milan.domain.money import Paise
from milan.domain.records import BankCredit
from milan.domain.results import Proof, ReconException, ReconReport
from milan.evaluation.harness import evaluate, to_recon_input
from milan.evaluation.metrics import Scorecard
from milan.leaks.clusters import LeakCluster, LeakReport, summarise
from milan.persistence import store
from milan.persistence.store import StaleDatasetError
from milan.recon.batches import GatewayBatch, rebuild_batches
from milan.recon.pipeline import ReconciliationPipeline, RunMetadata


class RunRef(BaseModel):
    """A stored run, as the picker sees it."""

    model_config = ConfigDict(frozen=True)

    seed: int
    difficulty: str
    orders: int
    records: int
    credits: int

    stale: bool = False
    """Whether this run predates the current generator.

    Reported rather than hidden. A stale run is still a real thing sitting in
    the merchant's data directory, and a picker that silently omitted it would
    leave somebody wondering where their run went. Opening it is what fails;
    listing it is how they find out why.
    """


class Subject(BaseModel):
    """The record an exception is about, in the terms a person reads it in."""

    model_config = ConfigDict(frozen=True)

    kind: str
    """`credit`, `settlement`, or `payment`. What sort of thing went wrong."""

    id: str
    amount: Paise | None = None
    occurred_on: date | None = None
    narration: str | None = None
    """The bank's own text, verbatim. Shown unaltered because the whole
    question in half these cases is what the bank did or did not send."""


class QueueItem(BaseModel):
    """One case in the exception queue."""

    model_config = ConfigDict(frozen=True)

    code: ExceptionCode
    summary: str
    amount: Paise
    evidence: dict[str, str]
    categorised_by: str
    subject: Subject


class ProofLineView(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    amount: Paise
    refs: tuple[str, ...]


class ProofView(BaseModel):
    """A credit rebuilt from its parts, with the running total shown.

    The direction matters for reading it. The lines do not count a credit
    down to nothing; they build it up from the sale and take the deductions
    off, and the proof is that what they build equals what the bank actually
    paid. So `running` ends at `credit_amount`, and `residual` - the gap
    between the two - is the number that must be zero.

    Both are computed here rather than in the browser. A reader is being
    invited to check that these lines close, and arithmetic that matters
    belongs on the side of the wire that has tests.
    """

    model_config = ConfigDict(frozen=True)

    credit_id: str
    credit_amount: Paise
    settlement_ids: tuple[str, ...]
    value_date: date
    narration: str
    strategy: str
    confidence: float
    drift: Paise
    lines: tuple[ProofLineView, ...]
    running: tuple[Paise, ...]
    """Cumulative total after each line. Ends at `credit_amount`."""

    residual: Paise
    """What the lines failed to account for. Zero, or it is not a proof."""


class LeakFinding(BaseModel):
    """One overcharge pattern, as a screen shows it.

    Rates cross the wire already formatted, unlike every amount here. A rate
    is not money and nothing in the browser does arithmetic with one, so the
    choice is between sending `0.0215` and letting two implementations agree
    on how to turn it into `2.15%`, or sending the string the CLI already
    prints. The second is one place where a percentage is written, and it is
    the place with tests.
    """

    model_config = ConfigDict(frozen=True)

    label: str
    """What was charged wrongly, in a merchant's words: `domestic consumer`,
    `netbanking`. The card type when there is one, because that is the field
    the mispricing is actually about, and the method when there is not."""

    contracted_rate: str
    charged_rate: str
    excess_rate: str

    method: str
    card_type: str | None

    payments: int
    overcharge: Paise
    gst: Paise
    cash_impact: Paise
    gross_affected: Paise

    first_seen: str
    last_seen: str
    networks: tuple[str, ...]

    payment_ids: tuple[str, ...]
    """Every row behind the claim, untruncated. What gets shown is the
    browser's decision; what can be checked is not."""


class LeakFindings(BaseModel):
    """What the leak pass found, whole.

    Carried beside the queue and never inside it. An exception is something
    that did not reconcile; every one of these reconciled perfectly, and
    filing them together would bury the only finding in the run that survives
    the books balancing.
    """

    model_config = ConfigDict(frozen=True)

    headline: str
    rows_examined: int
    payments: int
    overcharge: Paise
    gst: Paise
    cash_impact: Paise
    findings: tuple[LeakFinding, ...]


class RunSummary(BaseModel):
    """The headline, and the counts behind it."""

    model_config = ConfigDict(frozen=True)

    seed: int
    difficulty: str
    records_processed: int
    duration_seconds: float
    credits_total: int
    proofs_balanced: int
    exceptions_total: int
    exceptions_by_code: dict[str, int]
    rules_share: float
    drift_gross: Paise
    drift_net: Paise
    proofs_with_drift: int
    match_rate: float
    precision: float
    refusal_rate: float
    refusals_expected: int
    """How many credits were impossible by construction.

    Carried because the rate alone is unreadable when this is zero: a clean
    tier has nothing to refuse, and `0.0%` in a card headed "refused" reads
    as a system that guessed at everything rather than one that was never
    asked to."""

    explained_rate: float


class RunView(BaseModel):
    """Everything one screen needs, in one response.

    Deliberately not three round trips. The queue, the proofs and the summary
    are one consistent picture of one run, and fetching them separately would
    let a redeploy hand the browser two halves of different runs.
    """

    model_config = ConfigDict(frozen=True)

    summary: RunSummary
    queue: tuple[QueueItem, ...]
    proofs: tuple[ProofView, ...]
    leaks: LeakFindings
    """Charges above contract, on rows that reconciled. Always present, and
    empty on a clean tier - a run that found none has to be able to say so,
    or the only evidence of a working detector is the runs where it fired."""


class RunNotFoundError(LookupError):
    """No such run on disk."""


class Service:
    """Loads runs, reconciles them, and remembers the result.

    Reconciling is fast enough to do per request - a few milliseconds at six
    hundred orders - but the freshness check regenerates the dataset to
    compare digests, and doing that on every keystroke of a UI is wasteful for
    no gain. The cache is keyed by what identifies a run, and is dropped
    whenever the process restarts, so a regenerated dataset is never served
    from a stale entry in a long-lived process.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root if root is not None else store.default_root()
        self._cache: dict[tuple[str, int], RunView] = {}

    @property
    def root(self) -> Path:
        return self._root

    def runs(self) -> tuple[RunRef, ...]:
        """Every stored run, in tier order so the picker reads easy to hard.

        Loaded without the freshness check, then checked separately. Listing
        is metadata and opening is the thing that has to be trustworthy - and
        a single stale run in the data directory taking down the whole picker
        with a 500 is how a person ends up unable to see the very run they
        need to be told to regenerate.
        """
        directory = self._root / "runs"
        if not directory.is_dir():
            return ()

        found: list[RunRef] = []
        for tier in Difficulty:
            for path in sorted(directory.glob(f"{tier.value}-seed*")):
                if not (path / store.DATASET_FILE).exists():
                    continue
                seed = int(path.name.rsplit("seed", 1)[1])
                dataset = store.load_dataset(self._root, seed, tier.value, verify=False)
                found.append(
                    RunRef(
                        seed=seed,
                        difficulty=tier.value,
                        orders=len(dataset.orders),
                        records=dataset.record_count,
                        credits=len(dataset.bank_credits),
                        stale=self._is_stale(dataset, path),
                    )
                )
        return tuple(found)

    @staticmethod
    def _is_stale(dataset: Dataset, directory: Path) -> bool:
        try:
            store.check_current(dataset, directory)
        except StaleDatasetError:
            return True
        return False

    def view(self, difficulty: str, seed: int) -> RunView:
        key = (difficulty, seed)
        if key not in self._cache:
            self._cache[key] = self._build(difficulty, seed)
        return self._cache[key]

    # ------------------------------------------------------------- internals

    def _dataset(self, difficulty: str, seed: int) -> Dataset:
        try:
            return store.load_dataset(self._root, seed, difficulty)
        except FileNotFoundError as missing:
            raise RunNotFoundError(str(missing)) from missing

    def _build(self, difficulty: str, seed: int) -> RunView:
        dataset = self._dataset(difficulty, seed)
        report = ReconciliationPipeline().run(
            to_recon_input(dataset),
            RunMetadata(seed=dataset.seed, difficulty=dataset.difficulty),
        )
        credits = {credit.credit_id: credit for credit in dataset.bank_credits}
        batches = {batch.settlement_id: batch for batch in rebuild_batches(dataset.settlement_rows)}

        return RunView(
            summary=self._summary(dataset, report),
            queue=tuple(
                self._queue_item(exception, dataset, credits, batches)
                for exception in report.exceptions
            ),
            proofs=tuple(
                self._proof_view(proof, credits[proof.credit_id])
                for proof in report.proofs
                if proof.credit_id in credits
            ),
            leaks=self._leaks(dataset, report),
        )

    def _summary(self, dataset: Dataset, report: ReconReport) -> RunSummary:
        # The scorecard is the one thing here that reads ground truth, which
        # is why it is computed through the evaluation package rather than
        # assembled from anything the queue can see.
        card: Scorecard = evaluate(dataset, headline_only=True).headline
        return RunSummary(
            seed=report.seed,
            difficulty=report.difficulty,
            records_processed=report.records_processed,
            duration_seconds=report.duration_seconds,
            credits_total=len(dataset.bank_credits),
            proofs_balanced=sum(1 for proof in report.proofs if proof.balances),
            exceptions_total=len(report.exceptions),
            exceptions_by_code=card.exceptions_by_code,
            rules_share=card.rules_share,
            drift_gross=card.drift_gross,
            drift_net=card.drift_net,
            proofs_with_drift=card.proofs_with_drift,
            match_rate=card.match_rate,
            precision=card.precision,
            refusal_rate=card.refusal_rate,
            refusals_expected=card.unprovable_expected,
            explained_rate=card.explained_rate,
        )

    def _queue_item(
        self,
        exception: ReconException,
        dataset: Dataset,
        credits: dict[str, BankCredit],
        batches: dict[str, GatewayBatch],
    ) -> QueueItem:
        return QueueItem(
            code=exception.code,
            summary=exception.summary,
            amount=exception.amount,
            evidence=exception.evidence,
            categorised_by=exception.categorised_by,
            subject=self._subject(exception.subject_id, dataset, credits, batches),
        )

    def _subject(
        self,
        subject_id: str,
        dataset: Dataset,
        credits: dict[str, BankCredit],
        batches: dict[str, GatewayBatch],
    ) -> Subject:
        """Join an id back to the thing it names.

        Three kinds reach the queue, and they are genuinely different cases:
        a bank credit that arrived and could not be explained, a settlement
        the gateway reported that never arrived, and a payment the merchant
        captured that the report never mentions. Showing all three as "an id
        and an amount" would flatten the one distinction that decides who has
        to chase what.
        """
        credit = credits.get(subject_id)
        if credit is not None:
            return Subject(
                kind="credit",
                id=subject_id,
                amount=credit.amount,
                occurred_on=credit.value_date,
                narration=credit.narration,
            )

        batch = batches.get(subject_id)
        if batch is not None:
            return Subject(
                kind="settlement",
                id=subject_id,
                amount=batch.expected_net,
                occurred_on=batch.settled_on,
            )

        for payment in dataset.payments:
            if payment.payment_id == subject_id:
                return Subject(
                    kind="payment",
                    id=subject_id,
                    amount=payment.amount,
                    occurred_on=_as_date(payment.captured_at),
                )
        return Subject(kind="unknown", id=subject_id)

    @staticmethod
    def _leaks(dataset: Dataset, report: ReconReport) -> LeakFindings:
        """Group what the pipeline already detected.

        The detection ran inside the pipeline, so this reads `report.leaks`
        rather than calling the detector again. Two call sites on the same
        rows would eventually be given two different rate cards, and the
        screen would then disagree with the score for reasons nobody could
        see.
        """
        examined = sum(1 for row in dataset.settlement_rows if row.type is EntityType.PAYMENT)
        grouped: LeakReport = summarise(report.leaks, examined)
        return LeakFindings(
            headline=grouped.headline(),
            rows_examined=grouped.rows_examined,
            payments=grouped.payments,
            overcharge=grouped.overcharge,
            gst=grouped.gst,
            cash_impact=grouped.cash_impact,
            findings=tuple(_finding(group) for group in grouped.clusters),
        )

    def _proof_view(self, proof: Proof, credit: BankCredit) -> ProofView:
        running: list[Paise] = []
        balance = Paise(0)
        for line in proof.lines:
            balance = Paise(balance + line.amount)
            running.append(balance)

        return ProofView(
            credit_id=proof.credit_id,
            credit_amount=proof.credit_amount,
            settlement_ids=proof.settlement_ids,
            value_date=credit.value_date,
            narration=credit.narration,
            strategy=proof.strategy.value,
            confidence=proof.confidence,
            drift=proof.drift,
            lines=tuple(
                ProofLineView(label=line.label, amount=line.amount, refs=line.refs)
                for line in proof.lines
            ),
            running=tuple(running),
            residual=proof.residual,
        )


def _finding(group: LeakCluster) -> LeakFinding:
    return LeakFinding(
        label=(group.card_type or group.method).replace("_", " "),
        contracted_rate=f"{group.contracted_rate:.2%}",
        charged_rate=f"{group.charged_rate:.2%}",
        excess_rate=f"{group.excess_rate:.2%}",
        method=group.method,
        card_type=group.card_type,
        payments=group.payments,
        overcharge=group.overcharge,
        gst=group.gst,
        cash_impact=group.cash_impact,
        gross_affected=group.gross_affected,
        first_seen=group.first_seen,
        last_seen=group.last_seen,
        networks=group.networks,
        payment_ids=group.payment_ids,
    )


def _as_date(moment: datetime | date) -> date:
    return moment.date() if isinstance(moment, datetime) else moment
