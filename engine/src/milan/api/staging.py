"""Files a merchant has handed over but not yet agreed a reading of.

The command line has a folder to point at. A browser has a person with a
handful of CSVs and no idea what a data root is, so the upload has to become
that folder - written somewhere the importer can read, held while the
questions are answered, and then either committed or thrown away.

Three properties this is built around, and each one is a decision:

**The upload is not the import.** Files landing on disk changes nothing. A
staged folder has a plan, that plan may have open questions, and until they
are answered nothing is reconciled and nothing is archived. That is the same
refuse-and-ask contract the command line has, moved behind HTTP.

**The importer is held, not rebuilt.** Every answer re-plans from scratch,
and re-planning means re-profiling every column and possibly re-asking a
model. Keeping the `Importer` for the life of the staging area makes an
answer cost nothing and - more importantly - makes the second plan consistent
with the first, rather than a fresh reading that could differ.

**Nothing here is trusted.** These bytes arrived over HTTP from a browser. A
filename is reduced to its last component before it touches the filesystem,
the count and the total size are capped, and the suffix has to be one this
reader handles. The engine binds to loopback and has no authentication, so
this is the only boundary there is.
"""

from __future__ import annotations

import secrets
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from milan.ingest import workbook
from milan.ingest.plan import ABSENT, IngestPlan
from milan.ingest.reading import UnreadableFileError
from milan.ingest.resolver import Decisions, Importer
from milan.ingest.schema import RecordKind
from milan.llm.provider import NullProvider
from milan.llm.registry import resolve

UPLOADS = "uploads"

MAX_FILES = 12
"""A reconciliation reads four kinds of file. Twelve leaves room for a
merchant who splits a statement by month and still refuses a folder dump."""

MAX_BYTES = 32 * 1024 * 1024
"""Total across the upload. A year of settlement rows at six hundred orders a
month is about four megabytes of CSV, so this is generous rather than tight -
but it is a number, and an upload endpoint without one is a way to fill a
disk."""

ALLOWED = workbook.DISCOVERABLE
"""What an upload will take in, which is wider than what can be read.

Taken from the reader rather than restated here. These two lists were separate
for a day and that was long enough for them to disagree.

`DISCOVERABLE` rather than `READABLE`, and the difference is a bug this cost.
A PDF, a legacy `.xls`, a JSON dump and a zip are all things somebody could
reasonably believe they had just handed their books over in, and each has
advice attached. Refusing them **at the door** meant a merchant who selected
their whole folder - statement, report, and the PDF they downloaded first -
had the entire upload rejected because of the PDF, with every good file in it
thrown away. Six files in, one error out, nothing staged.

So they come in, and the reader diagnoses them exactly as it does when the
command line walks a folder: read what can be read, and report the rest with
the sentence that gets the person unstuck.
"""

STALE_SECONDS = 60 * 60
"""How long an unanswered upload is kept.

Someone opens the import dialog, drops three files, gets asked which column
is the value date, and closes the tab. Those files are then a merchant's
settlement data sitting in a directory nobody will ever look at, so they are
swept on the next upload rather than kept forever.
"""

FORMAT_SUFFIX = ".format"
RECORD_SUBJECT = "record"


class StagingError(RuntimeError):
    """The upload was refused. The message is for the person who sent it."""


class UnknownStagingError(LookupError):
    """No such staged upload - expired, committed, or never existed."""


def safe_name(raw: str) -> str:
    """The last component of a filename, and nothing that could escape a folder.

    `PurePath(...).name` alone is not enough on a server that may see either
    separator regardless of its own platform, so both are cut explicitly. A
    name that survives all of that and is still empty, hidden, or of a suffix
    this reader does not handle is refused rather than corrected - silently
    renaming a merchant's file is how the wrong file gets reconciled.
    """
    name = raw.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name.startswith("."):
        raise StagingError(f"{raw!r} is not a usable file name")
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED:
        # Named rather than listed, where there is something useful to say.
        # "Allowed: .csv, .tsv, .txt, .xlsx" is a true sentence that leaves
        # somebody holding a PDF bank statement no better off.
        raise StagingError(f"{name}: {_why_not(suffix)}")
    return name


def _sort(files: list[tuple[str, bytes]]) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Split an upload into what can be staged and what cannot, with reasons.

    Nothing here refuses the batch. A folder legitimately holds a logo, a
    `.DS_Store` and last quarter's zip alongside the two files that matter,
    and an upload endpoint that rejects all of it because of one of them is
    an endpoint a merchant cannot use their own folder with.
    """
    kept: list[tuple[str, bytes]] = []
    skipped: list[str] = []
    for raw, body in files:
        try:
            kept.append((safe_name(raw), body))
        except StagingError as refused:
            skipped.append(str(refused))
    return kept, skipped


def _why_not(suffix: str) -> str:
    """What to do about a file this upload cannot take at all.

    Short, because almost nothing reaches it any more. The formats somebody
    could plausibly mistake for their books - PDF, legacy `.xls`, a JSON dump,
    a zip - are taken in and diagnosed by the reader, which is the one place
    that decides those things and the one place whose advice is tested.

    What is left is a logo, a `.DS_Store`, a spreadsheet macro: files nobody
    expected us to read. They are named and set aside, and the folder they
    came in is staged regardless.
    """
    allowed = ", ".join(sorted(workbook.READABLE))
    return f"not read - {suffix or 'that'} is not a table. This takes {allowed}."


@dataclass
class Staged:
    """One upload, its importer, and every answer given about it so far."""

    id: str
    root: Path
    importer: Importer
    opened: float
    decisions: dict[str, Decisions] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    """Files that never reached disk, and why.

    A folder holds a logo, a `.DS_Store`, last quarter's zip. None of them is
    an error and none of them can be staged, so they are set aside here and
    reported beside the files that were read - the same way the reader reports
    a PDF it cannot open. Silence would be worse: a merchant who selected
    eight files and sees six has a right to know which two, and why.
    """

    def answer(self, key: str, value: str) -> None:
        """Record one answer, addressed the way the question was: `file:subject`.

        Unknown files and unknown record types are refused here rather than
        absorbed. An answer that names a file which was not uploaded is not a
        harmless no-op - it is a browser and a server disagreeing about what
        is on screen, and the next thing that happens is somebody approving a
        mapping they cannot see.
        """
        file, separator, subject = key.partition(":")
        if not separator or not subject:
            raise StagingError(f'an answer is addressed "file:field", not {key!r}')
        if file not in {source.name for source in self.importer.sources}:
            raise StagingError(f"{file} is not one of the files you uploaded")

        current = self.decisions.get(file, Decisions())
        if subject == RECORD_SUBJECT:
            if value == ABSENT:
                # "Do not use this file", recorded as a decision rather than
                # as the absence of one. Dropping the answer was right while
                # this could only be said about a file nothing had placed -
                # it went back to being unplaced, which is where it started.
                #
                # It is now offered on placed files too, and there dropping
                # the answer means the placement rules run again and place it
                # again. The merchant says "that is not my order book" and
                # watches nothing happen.
                self.decisions[file] = current.ignoring()
                return
            try:
                self.decisions[file] = current.with_kind(RecordKind(value))
            except ValueError as failure:
                named = ", ".join(kind.value for kind in RecordKind)
                raise StagingError(f"{value!r} is not a record type. One of: {named}") from failure
            return
        if subject.endswith(FORMAT_SUFFIX):
            self.decisions[file] = current.with_answer(
                subject[: -len(FORMAT_SUFFIX)], value, is_format=True
            )
            return
        self.decisions[file] = current.with_answer(subject, value, is_format=False)

    def plan(self) -> IngestPlan:
        """The current reading of these files, with every answer applied."""
        return self.importer.plan(self.root, self.decisions)


class StagingArea:
    """Every upload currently waiting on an answer.

    Held in memory and on disk together. The process restarting drops the
    staged uploads, which is correct: an unanswered import is a conversation,
    and a conversation does not survive one side of it going away.
    """

    def __init__(self, root: Path, provider: str | None = None) -> None:
        self._root = root / UPLOADS
        self._provider = provider
        self._open: dict[str, Staged] = {}

    @property
    def root(self) -> Path:
        return self._root

    def _importer(self) -> Importer:
        """An importer with a model behind it, or without one if none is set.

        `NullProvider` is filtered out rather than passed through. Handing it
        to the importer would report a provider was consulted and count
        questions asked of something that answers nothing - which would put a
        model in the audit trail of a run that never used one.
        """
        chosen = resolve(self._provider)
        return Importer(None if isinstance(chosen, NullProvider) else chosen)

    def _accept(
        self, files: list[tuple[str, bytes]], *, already: int = 0, bytes_already: int = 0
    ) -> tuple[list[tuple[str, bytes]], list[str]]:
        """Check an upload and return what to stage, plus what was skipped.

        Shared by `open` and `add` so that a second batch of files is held to
        the same limits as the first. Counting only the new batch would let
        somebody past both caps by uploading twice, which is not an attack so
        much as what a person does when their first attempt was incomplete.

        The caps still raise, because they are about the request as a whole.
        A file of the wrong sort does not: it is set aside with its reason, and
        the rest of the folder is staged.
        """
        if not files:
            raise StagingError("no files were uploaded")
        if len(files) + already > MAX_FILES:
            raise StagingError(
                f"{len(files) + already} files is more than this takes at once ({MAX_FILES})"
            )

        total = sum(len(body) for _, body in files) + bytes_already
        if total > MAX_BYTES:
            raise StagingError(
                f"{total / 1_048_576:.1f} MB is over the {MAX_BYTES // 1_048_576} MB limit"
            )

        named, skipped = _sort(files)
        if not named:
            # Every file was of a sort this cannot take. Now it is worth
            # refusing, because there is nothing to stage - and the reasons
            # are the useful part of the message.
            raise StagingError("; ".join(skipped) or "nothing in that upload can be read")
        if len({name for name, _ in named}) != len(named):
            raise StagingError("two of those files have the same name")
        return named, skipped

    def open(self, files: list[tuple[str, bytes]]) -> Staged:
        """Write an upload to disk and read it. Raises on anything refused."""
        named, skipped = self._accept(files)
        self.sweep()
        staged_id = secrets.token_hex(8)
        directory = self._root / staged_id
        directory.mkdir(parents=True, exist_ok=True)
        for name, body in named:
            (directory / name).write_bytes(body)

        staged = Staged(
            id=staged_id,
            root=directory,
            importer=self._importer(),
            opened=time.monotonic(),
            skipped=skipped,
        )
        try:
            plan = staged.plan()
        except UnreadableFileError as failure:
            shutil.rmtree(directory, ignore_errors=True)
            raise StagingError(str(failure)) from failure

        # A file the reader cannot find a header in is reported rather than
        # raised, so a folder of three CSVs and a readme still imports. But an
        # upload where *nothing* read is not a plan with a caveat - there is
        # nothing to stage, and holding the files so the wizard can display an
        # empty mapping helps nobody.
        if not staged.importer.sources:
            shutil.rmtree(directory, ignore_errors=True)
            why = "; ".join(f"{item.path.name}: {item.reason}" for item in plan.unreadable)
            raise StagingError(why or "none of those files is a table this reader can read")

        self._open[staged_id] = staged
        return staged

    def add(self, staged_id: str, files: list[tuple[str, bytes]]) -> Staged:
        """Put more files into an upload that is already open.

        The fix for a quiet and expensive bug. Every upload used to create a
        fresh staging area, so a merchant who picked their settlement report,
        looked at the result, and then picked their bank statement did not end
        up with two files - they ended up with the bank statement and a plan
        that said no settlement report was found. Nothing anywhere said the
        first file had been dropped.

        Answers already given are kept. They are keyed by file name, and the
        files they refer to have not moved, so re-planning after new files
        arrive settles the new ones and leaves the old decisions standing.
        """
        staged = self.get(staged_id)
        existing = {path.name for path in staged.root.iterdir() if path.is_file()}
        named, skipped = self._accept(
            files,
            already=len(existing),
            bytes_already=sum(path.stat().st_size for path in staged.root.iterdir()),
        )

        clashes = sorted(name for name, _ in named if name in existing)
        if clashes:
            raise StagingError(
                f"{', '.join(clashes)} is already in this upload. "
                "Rename it, or start again if you meant to replace it."
                if len(clashes) == 1
                else f"{', '.join(clashes)} are already in this upload."
            )

        for name, body in named:
            (staged.root / name).write_bytes(body)

        # The importer caches what it has read, keyed on the folder it read.
        # A new one is the honest way to make it look again - re-reading three
        # CSVs costs milliseconds, and a stale cache here would show a plan
        # that does not mention the file somebody just added.
        staged.importer = self._importer()
        staged.skipped = [*staged.skipped, *skipped]
        return staged

    def get(self, staged_id: str) -> Staged:
        staged = self._open.get(staged_id)
        if staged is None:
            raise UnknownStagingError(
                "those files are no longer staged - the engine restarted, or they expired. "
                "Upload them again."
            )
        return staged

    def discard(self, staged_id: str) -> None:
        staged = self._open.pop(staged_id, None)
        if staged is not None:
            shutil.rmtree(staged.root, ignore_errors=True)

    def sweep(self) -> None:
        """Drop uploads nobody came back to."""
        cutoff = time.monotonic() - STALE_SECONDS
        for staged_id in [key for key, value in self._open.items() if value.opened < cutoff]:
            self.discard(staged_id)
