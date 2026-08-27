"""How often the import gets a column right, measured against a known answer.

The claim this exists to keep honest: *a model may propose, only arithmetic
may conclude*. That is a claim about safety, and it is cheap to satisfy by
asking a person about everything — which is what a first cut of this resolver
did, and what made a gateway export come out as fifteen questions.

So there are two figures here and they pull against each other:

**Wrong** is the one that must be zero. A column settled without a question,
where the answer key says a different column. Nothing downstream can catch it:
read `Amount Taken Out` as the credit and every total still balances, upside
down. Any change that trades questions for convenience is only allowed if this
stays at nothing.

**Asked** is the one worth reducing. Every question is a person reading a
dialog about a file they already understand.

`Settled by name` is counted separately and is never credited to a model. Those
columns are decided by `schema.py`'s aliases before a provider is consulted,
and scoring them as model successes would report the header dictionary as
artificial intelligence.

Run it with `milan measure`. With no provider it reports what names and values
alone achieve, which is the configuration every graded number in this project
is measured under.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

from milan.domain.dataset import Dataset
from milan.ingest.plan import Certainty, FileMapping
from milan.ingest.resolver import Importer
from milan.ingest.schema import RecordKind
from milan.llm.provider import Provider
from milan.samples import build, dialects
from milan.samples.truth import CORPUS, Truth

__all__ = ["Accuracy", "Outcome", "measure", "write_corpus"]


@dataclass(frozen=True, slots=True)
class Outcome:
    """What became of one field of one file."""

    file: str
    field: str
    expected: str
    got: str | None
    certainty: str
    asked: bool
    proposed_by: str
    blank: bool = False
    """The file names this column and puts nothing in it.

    A bank statement with a `Cheque Number` header and no cheque numbers in
    it does not hold a UTR, and an import concluding the file has none is
    right. Counting that as a column we failed to find would report a
    correct answer as a failure, and would put pressure on exactly the wrong
    thing - the way to make the figure go up would be to map a field to a
    column of nothing.
    """

    suggested: str = ""
    """What the question offered as its lead answer, where it asked one.

    The figure that decides whether a question is worth its interruption. A
    dialog whose suggestion is right every time is a dialog that could have
    been a decision with an undo; one whose suggestion is right most of the
    time is doing exactly what it should.
    """

    @property
    def right(self) -> bool:
        return self.got == self.expected

    @property
    def by_name(self) -> bool:
        """Settled by the header dictionary, before any model was consulted."""
        return self.certainty == Certainty.CONFIRMED.value and not self.proposed_by


@dataclass
class Accuracy:
    """The tally, and the rows behind it.

    The rows are kept because a bare percentage is not reviewable. A run that
    reports 96% and cannot say which column it lost is not a measurement
    anybody should act on.
    """

    outcomes: list[Outcome] = field(default_factory=list)
    kinds: list[tuple[str, str | None, str | None]] = field(default_factory=list)
    provider: str = "none"

    def _where(self, predicate: object) -> list[Outcome]:
        assert callable(predicate)
        return [outcome for outcome in self.outcomes if predicate(outcome)]

    @property
    def settled_by_name(self) -> list[Outcome]:
        return self._where(lambda o: o.by_name and not o.asked)

    @property
    def settled_right(self) -> list[Outcome]:
        """Settled without a question, and correct."""
        return self._where(lambda o: not o.asked and o.got is not None and o.right)

    @property
    def wrong(self) -> list[Outcome]:
        """Settled without a question, and *not* correct. Must be empty."""
        return self._where(lambda o: not o.asked and o.got is not None and not o.right)

    @property
    def asked(self) -> list[Outcome]:
        return self._where(lambda o: o.asked)

    @property
    def missed(self) -> list[Outcome]:
        """The file has the column *with values in it*; the import found none."""
        return self._where(lambda o: not o.asked and o.got is None and not o.blank)

    @property
    def blank(self) -> list[Outcome]:
        """The column is in the header row and empty on every row below it.

        Reported rather than folded into either side. It is not a miss, and
        calling it a success would be just as wrong - the honest statement is
        that the file offered a name and no data, and there was nothing to
        find.
        """
        return self._where(lambda o: o.blank)

    @property
    def proposed(self) -> list[Outcome]:
        """Settled on a model's proposal rather than on a header name."""
        return self._where(lambda o: not o.asked and o.proposed_by and o.got is not None)

    @property
    def proposals_right(self) -> list[Outcome]:
        return [outcome for outcome in self.proposed if outcome.right]

    @property
    def suggested(self) -> list[Outcome]:
        """Questions that led with a suggestion rather than a bare list."""
        return self._where(lambda o: o.asked and o.suggested)

    @property
    def suggested_right(self) -> list[Outcome]:
        return [outcome for outcome in self.suggested if outcome.suggested == outcome.expected]

    @property
    def kinds_right(self) -> int:
        return sum(1 for _, expected, got in self.kinds if expected == got)

    def rate(self, part: Sequence[Outcome], whole: Sequence[Outcome]) -> str:
        """A rate that carries the population it was measured over.

        A bare percentage over an unstated denominator is the failure this
        codebase has already made once and written a decision about; the
        denominator travels with the figure everywhere it is printed.
        """
        if not whole:
            return "no cases"
        return f"{len(part) / len(whole):.1%} of {len(whole)}"


def _sheet_of(mapping: FileMapping) -> str:
    return mapping.source.sheet


def write_corpus(data: Dataset, root: Path) -> dict[tuple[str, str], Path]:
    """Every file in the answer key, written out. Returns writer -> path."""
    root.mkdir(parents=True, exist_ok=True)
    written: dict[tuple[str, str], Path] = {}

    flat: dict[str, tuple[object, str]] = {
        "razorpay_settlement": (dialects.razorpay_settlement, "settlement_report.csv"),
        "unfamiliar_settlement": (dialects.unfamiliar_settlement, "gateway_payouts.csv"),
        "hdfc_statement": (dialects.hdfc_statement, "hdfc_statement.csv"),
        "icici_statement": (dialects.icici_statement, "icici_statement.csv"),
        "kotak_statement": (dialects.kotak_statement, "kotak_statement.csv"),
        "axis_statement": (dialects.axis_statement, "axis_statement.csv"),
        "capture_log": (dialects.capture_log, "payments.csv"),
        "order_book": (dialects.order_book, "orders.csv"),
        "gst_register": (dialects.gst_register, "gstr1.csv"),
        "vendor_ledger": (dialects.vendor_ledger, "purchase_ledger.csv"),
    }
    for writer, (function, name) in flat.items():
        path = root / name
        assert callable(function)
        function(data, path)
        written[(writer, "")] = path

    book = root / "gateway_export.xlsx"
    dialects.gateway_workbook(data, book)
    written[("gateway_workbook", "Payouts")] = book
    written[("gateway_workbook", "Transactions")] = book
    return written


def _has_values(mapping: FileMapping, column: str) -> bool:
    """Whether the column the answer key names actually holds anything."""
    if column not in mapping.source.headers:
        return False
    return any(value.strip() for value in mapping.source.column(column))


def _outcomes(mapping: FileMapping, truth: Truth) -> Iterator[Outcome]:
    asked = {question.subject: question.suggested for question in mapping.questions}
    columns = mapping.columns
    by = {resolution.target.name: resolution for resolution in mapping.resolutions}

    for name, expected in truth.columns.items():
        resolution = by.get(name)
        yield Outcome(
            file=mapping.name,
            field=name,
            expected=expected,
            got=columns.get(name),
            certainty=resolution.certainty.value if resolution else "missing",
            asked=name in asked,
            proposed_by=resolution.proposed_by if resolution else "",
            blank=not _has_values(mapping, expected),
            suggested=asked.get(name, ""),
        )


def measure(provider: Provider | None = None, *, seed: int = 42, orders: int = 400) -> Accuracy:
    """Read the whole corpus and score every column against the answer key."""
    data = build.month(seed=seed, orders=orders)
    tally = Accuracy()

    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_corpus(data, root)

        resolver = Importer(provider)
        tally.provider = resolver.consulted
        plan = resolver.plan(root)

        placed: dict[tuple[str, str], FileMapping] = {}
        for mapping in plan.files:
            placed[(mapping.source.path.name, _sheet_of(mapping))] = mapping

        names = {
            "settlement_report.csv": "razorpay_settlement",
            "gateway_payouts.csv": "unfamiliar_settlement",
            "hdfc_statement.csv": "hdfc_statement",
            "icici_statement.csv": "icici_statement",
            "kotak_statement.csv": "kotak_statement",
            "axis_statement.csv": "axis_statement",
            "payments.csv": "capture_log",
            "orders.csv": "order_book",
            "gstr1.csv": "gst_register",
            "purchase_ledger.csv": "vendor_ledger",
            "gateway_export.xlsx": "gateway_workbook",
        }

        for (filename, sheet), mapping in sorted(placed.items()):
            writer = names.get(filename)
            if writer is None:
                continue
            truth = next(
                (item for item in CORPUS if item.writer == writer and item.sheet == sheet),
                None,
            )
            if truth is None:
                continue

            got_kind: str | None = mapping.kind.value if mapping.kind else None
            want_kind: str | None = truth.kind.value if truth.kind else None
            tally.kinds.append((mapping.name, want_kind, got_kind))

            if truth.kind is None or mapping.kind is not RecordKind(truth.kind):
                continue
            tally.outcomes.extend(_outcomes(mapping, truth))

    return tally
