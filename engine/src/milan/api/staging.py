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

ALLOWED = workbook.READABLE
"""Taken from the reader rather than restated here.

These two lists were separate for a day and that was long enough for them to
disagree: the reader learned to open workbooks and the upload endpoint went on
refusing them at the door, so the browser could not send the format the
merchant was most likely to have.
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
        # somebody holding a PDF bank statement no better off, and a PDF bank
        # statement is the single most common thing to arrive here.
        raise StagingError(f"{name}: {_why_not(suffix)}")
    return name


_ADVICE: dict[str, str] = {
    ".pdf": (
        "a PDF has no columns to read, only ink in the shape of columns. "
        "Every major Indian bank offers the same statement as CSV or Excel "
        "next to the PDF - download that one."
    ),
    ".xls": (
        "this is the Excel format from before 2007. Open it and use Save As "
        "to write it as .xlsx or .csv, and it will read."
    ),
    ".json": (
        "a JSON dump is not a table yet. Export the same data from your dashboard as CSV or Excel."
    ),
    ".zip": "unzip it and hand over the files inside.",
}


def _why_not(suffix: str) -> str:
    """What to do about a file this reader does not take.

    Advice where advice exists, and the plain list where it does not. The
    refusal is not in question either way - the difference is whether the
    person reading it knows what to do next.
    """
    known = _ADVICE.get(suffix)
    allowed = ", ".join(sorted(ALLOWED))
    if known:
        return f"{known} (this reader takes {allowed})"
    return f"not a file this reader takes. It takes {allowed}"


@dataclass
class Staged:
    """One upload, its importer, and every answer given about it so far."""

    id: str
    root: Path
    importer: Importer
    opened: float
    decisions: dict[str, Decisions] = field(default_factory=dict)

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
                # "Do not use this file" is answered by having no answer. The
                # file goes back to being one nothing could place, which is
                # exactly the state the question was offered from.
                self.decisions.pop(file, None)
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

    def open(self, files: list[tuple[str, bytes]]) -> Staged:
        """Write an upload to disk and read it. Raises on anything refused."""
        if not files:
            raise StagingError("no files were uploaded")
        if len(files) > MAX_FILES:
            raise StagingError(f"{len(files)} files is more than this takes at once ({MAX_FILES})")

        total = sum(len(body) for _, body in files)
        if total > MAX_BYTES:
            raise StagingError(
                f"{total / 1_048_576:.1f} MB is over the {MAX_BYTES // 1_048_576} MB limit"
            )

        named = [(safe_name(name), body) for name, body in files]
        if len({name for name, _ in named}) != len(named):
            raise StagingError("two of those files have the same name")

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
