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

from collections import Counter
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from milan.api.staging import Staged, StagingArea
from milan.chaos.config import Difficulty
from milan.domain.dataset import Dataset
from milan.domain.enums import EntityType, ExceptionCode
from milan.domain.money import Paise
from milan.domain.records import BankCredit
from milan.domain.results import Proof, ReconException, ReconReport
from milan.evaluation.harness import evaluate, to_recon_input
from milan.evaluation.metrics import Scorecard
from milan.ingest import archive, build
from milan.ingest.identity import proven
from milan.ingest.plan import to_saved
from milan.leaks.clusters import LeakCluster, LeakReport, summarise
from milan.persistence import store
from milan.persistence.store import StaleDatasetError
from milan.recon.batches import GatewayBatch, rebuild_batches
from milan.recon.inputs import ReconInput
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
    credited: Paise
    """Every rupee that reached the bank account this run covers.

    The first number a merchant asks for and the one this screen did not have
    for its first six days. Counts of credits proved are how a reconciliation
    engine thinks; how much money arrived is how the person paying for it
    thinks.
    """

    proved_amount: Paise
    """How much of that reconstructs to zero against the settlement rows."""

    awaited: Paise
    """Money the gateway says it sent that has not arrived, plus captured
    payments the settlement report never mentions.

    Kept strictly apart from the two above and never added to them. Those are
    about money in the account; this is about money that is not, and a screen
    that summed them would report a total the merchant does not have.
    """
    drift_gross: Paise
    drift_net: Paise
    proofs_with_drift: int
    match_rate: float
    resolvable_credits: int
    """How many credits the match rate was measured over.

    The denominator, carried beside its rate for the same reason the refusal
    count is. `100.0%` against a run of thirty-seven credits reads as
    thirty-seven credits resolved, and on the adversarial tier it means
    twenty-one - the rest being impossible by construction and correctly
    refused. A rate whose population is not on screen invites exactly that
    reading, and it is the flattering one.
    """

    precision: float
    refusal_rate: float
    refusals_expected: int
    """How many credits were impossible by construction.

    Carried because the rate alone is unreadable when this is zero: a clean
    tier has nothing to refuse, and `0.0%` in a card headed "refused" reads
    as a system that guessed at everything rather than one that was never
    asked to.

    This was wired to `unprovable_expected` for four days, which is a
    different population: credits that are identifiable but cannot be
    reconstructed. The screen therefore printed a rate measured over the
    impossible credits beside a count of the unprovable ones - on the
    adversarial tier, "100.0%" above "of 6 impossible" when the run had
    refused ten of ten. Both halves were true of something; together they
    described no run that ever existed. Caught by reading the CLI and the
    screen side by side, which is the only place a mislabel like this is
    visible at all."""

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


class ImportRef(BaseModel):
    """An imported folder, as the picker sees it."""

    model_config = ConfigDict(frozen=True)

    slug: str
    source_root: str
    files: tuple[str, ...]
    records: int
    credits: int
    consulted: str
    """Which provider proposed column mappings. `none` means the import ran
    on column names and value shapes alone, which is the configuration every
    claim about the ingest path should be checked in."""

    columns_proposed: int
    columns_checked: int = 0


class MappedColumn(BaseModel):
    """One field, and the column an import decided to read it from."""

    model_config = ConfigDict(frozen=True)

    field: str
    column: str | None
    pattern: str
    reason: str = ""
    """Why this column, in the resolver's own words.

    `certainty` stopped being a complete answer once the import could prove a
    mapping: `unconfirmed` covers both "a model suggested it" and "the file's
    own arithmetic settles it", and only this says which."""

    certainty: str
    """`confirmed`, `answered`, `unconfirmed` or `absent`.

    The most important string on the import screen. "Your header said so" and
    "a model thought so" produce identical-looking rows in a mapping table,
    and the difference is the entire question of whether these numbers can be
    trusted without checking the file.
    """

    proposed_by: str
    derived: bool


class MappedFile(BaseModel):
    """One of the merchant's files, and what every column in it was read as."""

    model_config = ConfigDict(frozen=True)

    file: str
    kind: str
    columns: tuple[MappedColumn, ...]


class ImportProvenance(BaseModel):
    """Where an imported run's numbers came from.

    This is what stands in place of a scorecard. A generated run can be
    scored because its answer key was generated alongside it; a merchant's
    own files cannot, and inventing a number that looks like accuracy would
    be the single most dishonest thing this project could put on a screen.

    So the screen shows the audit trail instead: which files were read, which
    model was asked about the columns, how many columns it contributed, what
    it proposed that the values refused, and which checks were switched off
    for want of a file.
    """

    model_config = ConfigDict(frozen=True)

    source_root: str
    files: tuple[str, ...]
    consulted: str
    columns_proposed: int
    columns_checked: int = 0
    rejections: tuple[str, ...]
    limitations: tuple[str, ...]
    dropped: int
    withdrawals: int
    counts: dict[str, int]
    mappings: tuple[MappedFile, ...]
    """Every column decision, exactly as it was saved.

    Read from the mapping the import wrote rather than recomputed. Recomputing
    would consult the column names again, and possibly a model again, and
    could then show a different answer from the one the run on this screen was
    actually produced with."""


class ImportSummary(BaseModel):
    """The headline for an imported run.

    Deliberately shorter than `RunSummary`. Every field that one carries and
    this one does not - match rate, precision, refusal rate, explained rate -
    is measured against ground truth, and there is none here. An omission
    that the screen explains is honest; a zero in its place would not be.
    """

    model_config = ConfigDict(frozen=True)

    slug: str
    records_processed: int
    duration_seconds: float
    credits_total: int
    proofs_balanced: int
    exceptions_total: int
    exceptions_by_code: dict[str, int]
    rules_share: float
    credited: Paise
    """Every rupee that reached the bank account this run covers.

    The first number a merchant asks for and the one this screen did not have
    for its first six days. Counts of credits proved are how a reconciliation
    engine thinks; how much money arrived is how the person paying for it
    thinks.
    """

    proved_amount: Paise
    """How much of that reconstructs to zero against the settlement rows."""

    awaited: Paise
    """Money the gateway says it sent that has not arrived, plus captured
    payments the settlement report never mentions.

    Kept strictly apart from the two above and never added to them. Those are
    about money in the account; this is about money that is not, and a screen
    that summed them would report a total the merchant does not have.
    """
    drift_gross: Paise
    drift_net: Paise
    proofs_with_drift: int


class ImportView(BaseModel):
    """One imported run, on the same terms as a generated one minus the score."""

    model_config = ConfigDict(frozen=True)

    summary: ImportSummary
    provenance: ImportProvenance
    queue: tuple[QueueItem, ...]
    proofs: tuple[ProofView, ...]
    leaks: LeakFindings


class ChoiceView(BaseModel):
    """One answer a question will accept."""

    model_config = ConfigDict(frozen=True)

    value: str
    label: str


class QuestionView(BaseModel):
    """Something the import refuses to decide on its own."""

    model_config = ConfigDict(frozen=True)

    key: str
    kind: str
    file: str
    subject: str
    asks: str
    choices: tuple[ChoiceView, ...]
    suggested: str
    blocking: bool


class ResolutionView(BaseModel):
    """One target field, and how far the import got with it."""

    model_config = ConfigDict(frozen=True)

    field: str
    describes: str
    required: bool
    column: str | None
    pattern: str
    certainty: str
    reason: str
    proposed_by: str
    derived: bool


class StagedFileView(BaseModel):
    """One uploaded file, and what the import made of it."""

    model_config = ConfigDict(frozen=True)

    file: str
    kind: str | None
    kind_reason: str
    rows: int
    headers: tuple[str, ...]
    resolutions: tuple[ResolutionView, ...]


class PlanView(BaseModel):
    """A reading of an upload, before anybody has agreed to it.

    The shape the import wizard is built on. It is deliberately the whole
    state rather than a delta: every answer re-plans from scratch on the
    server, and a browser holding a patched-up copy of an older plan is a
    browser that can show somebody a mapping the engine is not going to use.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    consulted: str
    files: tuple[StagedFileView, ...]
    questions: tuple[QuestionView, ...]
    rejections: tuple[str, ...]
    limitations: tuple[str, ...]
    blockers: tuple[str, ...]
    ready: bool
    unreadable: tuple[str, ...]


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
        self._staging = StagingArea(self._root)

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
        data = to_recon_input(dataset)
        report = ReconciliationPipeline().run(
            data, RunMetadata(seed=dataset.seed, difficulty=dataset.difficulty)
        )
        credits, batches = _index(data)

        return RunView(
            summary=self._summary(dataset, data, report),
            queue=self._queue(report, data, credits, batches),
            proofs=self._proofs(report, credits),
            leaks=self._leaks(data, report),
        )

    def _queue(
        self,
        report: ReconReport,
        data: ReconInput,
        credits: dict[str, BankCredit],
        batches: dict[str, GatewayBatch],
    ) -> tuple[QueueItem, ...]:
        return tuple(
            self._queue_item(exception, data, credits, batches) for exception in report.exceptions
        )

    def _proofs(self, report: ReconReport, credits: dict[str, BankCredit]) -> tuple[ProofView, ...]:
        return tuple(
            self._proof_view(proof, credits[proof.credit_id])
            for proof in report.proofs
            if proof.credit_id in credits
        )

    # ------------------------------------------------------------- imports

    def imports(self) -> tuple[ImportRef, ...]:
        """Every folder that has been imported, in name order."""
        found: list[ImportRef] = []
        for slug in archive.imports(self._root):
            record = archive.load_record(self._root, slug)
            report = archive.load_report(self._root, slug)
            if record is None or report is None:
                continue
            found.append(
                ImportRef(
                    slug=slug,
                    source_root=record.source_root,
                    files=record.files,
                    records=report.records_processed,
                    credits=record.counts.get("bank_credits", 0),
                    consulted=record.consulted,
                    columns_proposed=record.columns_proposed,
                    columns_checked=record.columns_checked,
                )
            )
        return tuple(found)

    # --------------------------------------------------------- staged uploads

    def stage(self, files: list[tuple[str, bytes]]) -> PlanView:
        return _plan_view(self._staging.open(files))

    def add_to(self, staged_id: str, files: list[tuple[str, bytes]]) -> PlanView:
        """More files for an upload already open, keeping the answers given."""
        return _plan_view(self._staging.add(staged_id, files))

    def staged(self, staged_id: str) -> PlanView:
        return _plan_view(self._staging.get(staged_id))

    def answer(self, staged_id: str, answers: dict[str, str]) -> PlanView:
        staged = self._staging.get(staged_id)
        for key, value in answers.items():
            staged.answer(key, value)
        return _plan_view(staged)

    def discard(self, staged_id: str) -> None:
        self._staging.discard(staged_id)

    def commit(self, staged_id: str, name: str) -> str:
        """Reconcile a staged upload and archive it. Returns the new slug.

        The upload directory is deleted afterwards, and the normalised records
        kept instead. Holding on to the merchant's original files would leave
        a second copy of their settlement data in a directory nobody manages,
        for no benefit - the mapping records how they were read, and the
        records themselves are what any later screen reads.
        """
        staged = self._staging.get(staged_id)
        plan = staged.plan()
        imported = build.build(plan)
        report = ReconciliationPipeline().run(
            imported.data, RunMetadata(seed=0, difficulty=IMPORTED_TIER)
        )

        slug = archive.slug_for(Path(name)) if name.strip() else f"upload-{staged_id[:6]}"
        checked = sum(
            1
            for mapping in plan.placed
            for resolution in mapping.resolutions
            if resolution.column is not None and proven(resolution.reason)
        )
        proposed = sum(
            1
            for mapping in plan.placed
            for resolution in mapping.resolutions
            if resolution.proposed_by
        )
        archive.save(
            self._root,
            slug,
            record=archive.ImportRecord(
                slug=slug,
                source_root=f"uploaded: {', '.join(mapping.name for mapping in plan.placed)}",
                consulted=plan.consulted,
                files=tuple(mapping.name for mapping in plan.placed),
                counts=imported.counts,
                dropped=len(imported.dropped),
                withdrawals=imported.withdrawals,
                limitations=plan.limitations(),
                rejections=tuple(
                    f"{rejection.file}:{rejection.target} <- {rejection.column} "
                    f"({rejection.reason})"
                    for rejection in plan.rejections
                ),
                columns_proposed=proposed,
                columns_checked=checked,
            ),
            mapping=to_saved(plan),
            data=imported.data,
            report=report,
        )
        self._staging.discard(staged_id)
        return slug

    def _mappings(self, slug: str) -> tuple[MappedFile, ...]:
        saved = archive.load_mapping(self._root, slug)
        if saved is None:
            return ()
        return tuple(
            MappedFile(
                file=entry.file,
                kind=entry.kind,
                columns=tuple(
                    MappedColumn(
                        field=column.field,
                        column=column.column,
                        pattern=column.pattern,
                        certainty=column.certainty,
                        proposed_by=column.proposed_by,
                        derived=column.derived,
                        reason=column.reason,
                    )
                    for column in entry.columns
                ),
            )
            for entry in saved.files
        )

    def import_view(self, slug: str) -> ImportView:
        """One imported run, with no scorecard and a provenance instead.

        The absent scorecard is the honest part. A generated run is scored
        against an answer key; a merchant's own files come with no answer
        key and never will, so every accuracy figure on the other screen is
        unavailable here. Rather than compute something that looks like one,
        this returns where the numbers came from - which files, which
        columns, which model, what it refused, and what the run could not
        check for want of a file.
        """
        record = archive.load_record(self._root, slug)
        report = archive.load_report(self._root, slug)
        data = archive.load_input(self._root, slug)
        # Loaded before the guard below rather than inside it, so a mapping
        # file that has gone missing is a mapping table with nothing in it
        # rather than a 404 on a run that is otherwise perfectly readable.
        if record is None or report is None or data is None:
            raise RunNotFoundError(
                f"no import called {slug!r}. Import a folder first: milan import --from <folder>"
            )

        credits, batches = _index(data)
        return ImportView(
            summary=_import_summary(slug, record, data, report),
            provenance=ImportProvenance(
                source_root=record.source_root,
                files=record.files,
                consulted=record.consulted,
                columns_proposed=record.columns_proposed,
                columns_checked=record.columns_checked,
                rejections=record.rejections,
                limitations=record.limitations,
                dropped=record.dropped,
                withdrawals=record.withdrawals,
                counts=record.counts,
                mappings=self._mappings(slug),
            ),
            queue=self._queue(report, data, credits, batches),
            proofs=self._proofs(report, credits),
            leaks=self._leaks(data, report),
        )

    def _summary(self, dataset: Dataset, data: ReconInput, report: ReconReport) -> RunSummary:
        # The scorecard is the one thing here that reads ground truth, which
        # is why it is computed through the evaluation package rather than
        # assembled from anything the queue can see.
        card: Scorecard = evaluate(dataset, headline_only=True).headline
        credited, proved_amount, awaited = _position(data, report)
        return RunSummary(
            credited=credited,
            proved_amount=proved_amount,
            awaited=awaited,
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
            resolvable_credits=card.matchable,
            precision=card.precision,
            refusal_rate=card.refusal_rate,
            refusals_expected=card.impossible,
            explained_rate=card.explained_rate,
        )

    def _queue_item(
        self,
        exception: ReconException,
        data: ReconInput,
        credits: dict[str, BankCredit],
        batches: dict[str, GatewayBatch],
    ) -> QueueItem:
        return QueueItem(
            code=exception.code,
            summary=exception.summary,
            amount=exception.amount,
            evidence=exception.evidence,
            categorised_by=exception.categorised_by,
            subject=self._subject(exception.subject_id, data, credits, batches),
        )

    def _subject(
        self,
        subject_id: str,
        data: ReconInput,
        credits: dict[str, BankCredit],
        batches: dict[str, GatewayBatch],
    ) -> Subject:
        """Join an id back to the thing it names.

        Takes the merchant-side inputs rather than the dataset, because that
        is all it ever read. Narrowing the parameter is what lets an imported
        run - which has no answer key and never will - reuse this screen
        instead of getting a second, quietly divergent one.

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

        for payment in data.payments:
            if payment.payment_id == subject_id:
                return Subject(
                    kind="payment",
                    id=subject_id,
                    amount=payment.amount,
                    occurred_on=_as_date(payment.captured_at),
                )
        return Subject(kind="unknown", id=subject_id)

    @staticmethod
    def _leaks(data: ReconInput, report: ReconReport) -> LeakFindings:
        """Group what the pipeline already detected.

        The detection ran inside the pipeline, so this reads `report.leaks`
        rather than calling the detector again. Two call sites on the same
        rows would eventually be given two different rate cards, and the
        screen would then disagree with the score for reasons nobody could
        see.
        """
        examined = sum(1 for row in data.settlement_rows if row.type is EntityType.PAYMENT)
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


IMPORTED_TIER = "imported"
"""The tier an imported run carries. Not one of the generated difficulties,
and deliberately not pretending to be."""


def _plan_view(staged: Staged) -> PlanView:
    """One reading of an upload, in the terms the wizard shows it."""
    plan = staged.plan()
    return PlanView(
        id=staged.id,
        consulted=plan.consulted,
        files=tuple(
            StagedFileView(
                file=mapping.name,
                kind=mapping.kind.value if mapping.kind else None,
                kind_reason=mapping.kind_reason,
                rows=len(mapping.source.rows),
                headers=mapping.source.headers,
                resolutions=tuple(
                    ResolutionView(
                        field=resolution.target.name,
                        describes=resolution.target.describes,
                        required=resolution.target.required,
                        column=resolution.column,
                        pattern=resolution.pattern,
                        certainty=resolution.certainty.value,
                        reason=resolution.reason,
                        proposed_by=resolution.proposed_by,
                        derived=resolution.derived,
                    )
                    for resolution in mapping.resolutions
                ),
            )
            for mapping in plan.files
        ),
        questions=tuple(
            QuestionView(
                key=question.key,
                kind=question.kind.value,
                file=question.file,
                subject=question.subject,
                asks=question.asks,
                suggested=question.suggested,
                blocking=question.blocking,
                choices=tuple(
                    ChoiceView(value=choice.value, label=choice.label)
                    for choice in question.choices
                ),
            )
            for question in plan.questions
        ),
        rejections=tuple(
            f"{rejection.file}:{rejection.target} <- {rejection.column} ({rejection.reason})"
            for rejection in plan.rejections
        ),
        limitations=plan.limitations(),
        blockers=plan.blockers(),
        ready=plan.ready,
        # Two sources, one list. The reader reports a PDF it opened and could
        # not parse; the staging area reports a file it never wrote to disk at
        # all. To the person who dropped a folder they are the same fact -
        # "this one was not read, and here is why".
        unreadable=(
            *(f"{item.path.name}: {item.reason}" for item in plan.unreadable),
            *staged.skipped,
        ),
    )


ELSEWHERE = frozenset({ExceptionCode.MISSING_SETTLEMENT, ExceptionCode.UNSETTLED_PAYMENT})
"""The two exception codes that are about money which never arrived.

Every other code is about a credit that did arrive and would not reconstruct.
The distinction decides which half of the cash position an exception belongs
to, and getting it wrong would report money as both missing from the account
and sitting in it.
"""


def _position(data: ReconInput, report: ReconReport) -> tuple[Paise, Paise, Paise]:
    """What arrived, how much of it is explained, and what has not arrived.

    Three sums off the run, and no answer key involved in any of them - which
    is why an imported run reports the same three. A credit that reconstructs
    to zero has proved itself; nothing external had to agree.
    """
    credited = Paise(sum(credit.amount for credit in data.bank_credits))
    proved = Paise(sum(proof.credit_amount for proof in report.proofs if proof.balances))
    awaited = Paise(
        sum(exception.amount for exception in report.exceptions if exception.code in ELSEWHERE)
    )
    return credited, proved, awaited


def _index(
    data: ReconInput,
) -> tuple[dict[str, BankCredit], dict[str, GatewayBatch]]:
    """The two lookups every screen needs, built once."""
    return (
        {credit.credit_id: credit for credit in data.bank_credits},
        {batch.settlement_id: batch for batch in rebuild_batches(data.settlement_rows)},
    )


def _import_summary(
    slug: str,
    record: archive.ImportRecord,
    data: ReconInput,
    report: ReconReport,
) -> ImportSummary:
    """Everything an imported run can honestly say about itself.

    Every figure here is read off the report. Nothing is scored, because
    nothing can be - and the drift totals in particular are worth keeping,
    since they are the one accuracy-shaped number that needs no answer key:
    a credit that reconstructs to zero has proved itself.
    """
    balanced = [proof for proof in report.proofs if proof.balances]
    categorised = Counter(exception.categorised_by for exception in report.exceptions)
    total = sum(categorised.values())
    credited, proved_amount, awaited = _position(data, report)
    return ImportSummary(
        credited=credited,
        proved_amount=proved_amount,
        awaited=awaited,
        slug=slug,
        records_processed=report.records_processed,
        duration_seconds=report.duration_seconds,
        credits_total=record.counts.get("bank_credits", 0),
        proofs_balanced=len(balanced),
        exceptions_total=len(report.exceptions),
        exceptions_by_code=dict(Counter(e.code.value for e in report.exceptions)),
        rules_share=(categorised.get("rules", 0) / total) if total else 0.0,
        drift_gross=Paise(sum(abs(proof.drift) for proof in balanced)),
        drift_net=Paise(sum(proof.drift for proof in balanced)),
        proofs_with_drift=sum(1 for proof in balanced if proof.drift),
    )


def _as_date(moment: datetime | date) -> date:
    return moment.date() if isinstance(moment, datetime) else moment
