"""What the import decided, what it could not, and what it is going to cost.

An import plan is not a mapping. A mapping is what you get once every open
question has an answer; a plan is the honest intermediate state, where some
columns are settled, some are a model's suggestion that nothing has confirmed,
and some are a question with the merchant's name on it.

Keeping those three apart in the type is the whole point. A design that
returned only `dict[str, str]` would have to pick something for the uncertain
cases, and picking is exactly what this is built not to do.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from milan.ingest.reading import SourceFile
from milan.ingest.schema import RecordKind, TargetField

ABSENT = "-"
"""The answer meaning "this column is not in my file". A first-class answer:
for an optional field it is often the true one, and for a required one it
tells the merchant immediately that the file cannot be used as it stands."""

DERIVE = "derive"
"""The answer meaning "work it out from the other columns". Offered only for
the settlement debit and credit split, where a report that carries a single
signed amount instead is common enough to deserve an answer rather than a
rejection."""


class Certainty(StrEnum):
    """How a column came to be attached to a field.

    Printed on every line of the mapping table, because the difference
    between "your header said so" and "a model thought so" is the single most
    important thing a person reviewing an import needs to see.
    """

    CONFIRMED = "confirmed"
    """The header name is one this schema knows, and the values agree with it.
    Nothing was guessed."""

    UNCONFIRMED = "unconfirmed"
    """A model proposed it and the values permit it, but no name confirms it.
    Correct often enough to be worth offering and never enough to apply
    without somebody looking."""

    ANSWERED = "answered"
    """A person chose it."""

    OPEN = "open"
    """Nothing can proceed until this is answered."""

    ABSENT = "absent"
    """Not in this file. Fine for an optional field, fatal for a required one."""


class QuestionKind(StrEnum):
    RECORD_KIND = "record_kind"
    COLUMN = "column"
    DATE_FORMAT = "date_format"


@dataclass(frozen=True, slots=True)
class Choice:
    """One answer a question will accept."""

    value: str
    label: str


@dataclass(frozen=True, slots=True)
class Question:
    """Something the import refuses to decide on its own."""

    kind: QuestionKind
    file: str
    subject: str
    """The field name, or the file name for a record-kind question."""

    asks: str
    choices: tuple[Choice, ...]
    suggested: str = ""
    """The answer a model proposed, when one did. Empty otherwise.

    Carried as its own field rather than left as "the first choice", because
    a caller cannot tell those apart and the difference is the whole point.
    A person being asked fifteen questions needs to see which ones already
    have a candidate and who put it there - fifteen identical lists of columns
    is not more consent than one reviewed suggestion, it is less, because
    nobody reads the fifteenth.
    """

    blocking: bool = True
    """Whether the import refuses to proceed until this is answered.

    Nearly every question here blocks, because nearly every question is about
    a required field and guessing at one changes a balance. The exception is
    being asked what an unplaced file is: a merchant's folder legitimately
    holds an invoice register nobody needs, and demanding an answer about it
    would turn "we left your other file alone" into an error message.

    So that one is an offer rather than a demand - shown, answerable, and
    ignored if the person moves on.
    """

    @property
    def key(self) -> str:
        """How an answer is addressed on the command line: `file:subject`."""
        return f"{self.file}:{self.subject}"


@dataclass(frozen=True, slots=True)
class FieldResolution:
    """One target field, and how far the import got with it."""

    target: TargetField
    certainty: Certainty
    column: str | None = None
    pattern: str = ""
    """The date format chosen for this column, for temporal fields only."""

    candidates: tuple[str, ...] = ()
    reason: str = ""
    proposed_by: str = ""
    """The provider that suggested this column, when one did. This field
    aggregated across an import is the entire "the model did something here"
    claim, and it is a count of columns rather than an adjective."""

    derived: bool = False

    @property
    def settled(self) -> bool:
        return self.certainty is not Certainty.OPEN

    @property
    def mapped(self) -> bool:
        return self.column is not None or self.derived


@dataclass(frozen=True, slots=True)
class Rejection:
    """A proposal the values refused.

    Kept and reported rather than dropped. A model that suggests the balance
    column for the credit amount is the interesting case in this whole
    package, and an import that silently discarded it would leave nobody any
    way to know how often the check earns its place.
    """

    file: str
    target: str
    column: str
    reason: str
    proposed_by: str


@dataclass(frozen=True, slots=True)
class FileMapping:
    """One source file and everything decided about it."""

    source: SourceFile
    kind: RecordKind | None
    kind_reason: str
    resolutions: tuple[FieldResolution, ...] = ()
    questions: tuple[Question, ...] = ()
    rejections: tuple[Rejection, ...] = ()

    @property
    def name(self) -> str:
        return self.source.name

    @property
    def ready(self) -> bool:
        return self.kind is not None and not self.questions

    @property
    def columns(self) -> dict[str, str]:
        """The settled mapping, field name to column name."""
        return {
            resolution.target.name: resolution.column
            for resolution in self.resolutions
            if resolution.column is not None
        }

    @property
    def patterns(self) -> dict[str, str]:
        return {
            resolution.target.name: resolution.pattern
            for resolution in self.resolutions
            if resolution.pattern
        }

    @property
    def derived(self) -> tuple[str, ...]:
        return tuple(r.target.name for r in self.resolutions if r.derived)

    @property
    def unconfirmed(self) -> tuple[FieldResolution, ...]:
        return tuple(r for r in self.resolutions if r.certainty is Certainty.UNCONFIRMED)

    def missing(self) -> tuple[TargetField, ...]:
        """Optional fields this file does not have, so their cost can be reported."""
        return tuple(
            r.target for r in self.resolutions if r.certainty is Certainty.ABSENT and r.target.costs
        )


@dataclass(frozen=True, slots=True)
class Unreadable:
    path: Path
    reason: str


@dataclass(frozen=True, slots=True)
class IngestPlan:
    """Everything an import knows before it is allowed to run."""

    root: Path
    files: tuple[FileMapping, ...] = ()
    unreadable: tuple[Unreadable, ...] = ()
    consulted: str = "none"
    """Which provider was asked to propose mappings. `none` means the import
    ran on column names and value shapes alone, which is the configuration
    every claim about this package should be checked in."""

    @property
    def questions(self) -> tuple[Question, ...]:
        return tuple(question for mapping in self.files for question in mapping.questions)

    @property
    def rejections(self) -> tuple[Rejection, ...]:
        return tuple(rejection for mapping in self.files for rejection in mapping.rejections)

    @property
    def ready(self) -> bool:
        """Whether the plan can be built, ignoring whether anyone approved it."""
        return not self.blockers()

    @property
    def placed(self) -> tuple[FileMapping, ...]:
        return tuple(mapping for mapping in self.files if mapping.kind is not None)

    @property
    def unplaced(self) -> tuple[FileMapping, ...]:
        """Files nothing could place, each still carrying the reason.

        Kept in `files` rather than reduced to a list of names. A merchant's
        folder legitimately contains an invoice register we have no use for,
        and reading it as a settlement report would be far worse than leaving
        it alone - but "we left it alone" and "a model called it a settlement
        report and the columns said otherwise" are different facts, and the
        second one is the one worth reading.
        """
        return tuple(mapping for mapping in self.files if mapping.kind is None)

    def all_of(self, kind: RecordKind) -> tuple[FileMapping, ...]:
        """Every file placed as this record kind.

        Plural because a merchant with two bank accounts hands over two
        statements, and the reconciliation is over both of them. Nothing here
        assumes one file per kind.
        """
        return tuple(mapping for mapping in self.files if mapping.kind is kind)

    def of(self, kind: RecordKind) -> FileMapping | None:
        return next(iter(self.all_of(kind)), None)

    def blockers(self) -> tuple[str, ...]:
        """Everything standing between this plan and a run, in plain words.

        The two structural ones come first. A folder with no settlement report
        or no bank statement is not a reconciliation waiting on a detail - it
        is the wrong folder, and saying so beats answering nine column
        questions and then producing an empty run.
        """
        found: list[str] = []
        if not self.all_of(RecordKind.SETTLEMENT_ROWS):
            found.append(
                "no settlement or recon report was found: there is nothing to "
                "reconcile the bank against"
            )
        if not self.all_of(RecordKind.BANK_CREDITS):
            found.append(
                "no bank statement was found: there is nothing to prove the "
                "settlement report against"
            )
        found.extend(
            f"{question.file}: {question.subject} is unanswered"
            for question in self.questions
            if question.blocking
        )
        return tuple(found)

    def limitations(self) -> tuple[str, ...]:
        """What this import cannot do, given what the folder actually contained.

        Assembled from two places: record kinds nobody supplied, and optional
        fields whose absence costs something. Both are printed before the run
        rather than after, so a merchant reading a clean exception list knows
        which checks were switched off before they trust it.
        """
        found: list[str] = []
        present = {mapping.kind for mapping in self.files}

        if RecordKind.PAYMENTS not in present:
            found.append(
                "no payments file: captured money the settlement report never "
                "mentions cannot be raised, so the exception list covers bank "
                "credits only"
            )
        if RecordKind.ORDERS not in present:
            found.append("no orders file: nothing to check the sale side against")

        for mapping in self.placed:
            for target in mapping.missing():
                found.append(f"{mapping.name} has no {target.name} column: {target.costs}")
        return tuple(found)


class SavedColumn(BaseModel):
    """One field-to-column decision, as written to disk."""

    model_config = ConfigDict(frozen=True)

    field: str
    column: str | None = None
    pattern: str = ""
    certainty: str = Certainty.ANSWERED.value
    proposed_by: str = ""
    derived: bool = False
    reason: str = ""
    """Why this column, in the words the resolver settled on.

    Saved because `certainty` alone stopped being enough to describe a
    decision: `unconfirmed` now covers both a model's suggestion and a
    mapping the file's own arithmetic proved, and the difference between
    those two is the sentence. Defaulted for mappings written before it
    existed - an older run shows the certainty and no account of it, which
    is what it actually has."""


class SavedFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    kind: str
    columns: tuple[SavedColumn, ...]


class SavedMapping(BaseModel):
    """A confirmed mapping, kept so the same folder imports the same way twice.

    Written beside the run. Re-importing a folder that already has one of
    these asks nothing and consults no model - which is what makes an import
    reproducible, and what stops a demo from depending on a daemon being up.
    """

    model_config = ConfigDict(frozen=True)

    source_root: str
    consulted: str
    files: tuple[SavedFile, ...]


def to_saved(plan: IngestPlan) -> SavedMapping:
    return SavedMapping(
        source_root=str(plan.root),
        consulted=plan.consulted,
        files=tuple(
            SavedFile(
                file=mapping.name,
                kind=mapping.kind.value if mapping.kind else "",
                columns=tuple(
                    SavedColumn(
                        field=resolution.target.name,
                        column=resolution.column,
                        pattern=resolution.pattern,
                        certainty=resolution.certainty.value,
                        proposed_by=resolution.proposed_by,
                        derived=resolution.derived,
                        reason=resolution.reason,
                    )
                    for resolution in mapping.resolutions
                    if resolution.mapped
                ),
            )
            for mapping in plan.placed
        ),
    )
