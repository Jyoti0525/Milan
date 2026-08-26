"""Getting a table out of a file somebody's bank produced.

`csv.DictReader` assumes the first line is the header. Real exports routinely
put three lines of account details and a blank line above it, and a reader
that takes the first line ends up with one column named
`Statement for account 50100XXXXXX` and no data at all.

So the header is found rather than assumed: the first line that looks like a
header and is followed by lines with the same number of fields. Everything
above it is kept as `preamble`, because it is usually the account number and
the statement period, and a person checking whether Milan read their file
correctly wants to see that we knew it was there.

That search is the valuable part of this module, and it has nothing to do
with CSV. It works on a grid of strings - so an Excel sheet, whose banner
rows and merged title cell are the same problem in a different container,
goes through the identical code. `workbook` turns a sheet into that grid;
everything from `_find_header` down cannot tell the two apart, which is why
supporting spreadsheets did not mean writing a second reader with its own
subtly different idea of where a statement begins.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from milan.ingest import workbook

ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
"""Tried in order. `utf-8-sig` first because Excel writes a BOM and a BOM read
as text turns the first column name into something no alias will ever match.
`latin-1` last because it never fails, which makes it a fallback rather than
a detection."""

DELIMITERS: str = ",;\t|"

MAX_PREAMBLE_LINES = 25
"""How far down a file the header is allowed to be. Statements with more
banner than this are not statements."""

SHEET = " · "
"""What separates a workbook's file name from its sheet name.

A middle dot rather than a slash or a colon, because this string is shown to
a person, used as a dictionary key, and written into a saved mapping on disk -
and the two obvious separators are both meaningful in a path and in the
`file:field` form the command line answers questions with.

Named rather than spelled inline, because the command line has to split a
name back apart on it to offer an abbreviation somebody can type.
"""

SAMPLE_ROWS = 8
"""How many rows below a candidate header have to agree on field count."""


class UnreadableFileError(RuntimeError):
    """The file is not a table this reader can find a header in."""


@dataclass(frozen=True, slots=True)
class SourceFile:
    """One CSV, read and nothing more. No meaning has been assigned yet."""

    path: Path
    encoding: str
    delimiter: str
    headers: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    line_numbers: tuple[int, ...]
    """The 1-based file line each row came from, parallel to `rows`.

    Carried rather than derived, because blank lines inside a statement are
    skipped on the way in. Without this, a dropped row would be reported at a
    line number that drifts further from the truth with every blank line above
    it, which is worse than reporting no line number at all."""

    preamble: tuple[str, ...]
    header_line: int
    """1-based line number the header was found on. Printed so a person can
    check we started where they would have."""

    sheet: str = ""
    """Which sheet of a workbook this came from. Empty for a CSV.

    One file can now produce several of these, and everything downstream -
    the profiles, the answers a merchant gives, the saved mapping that makes
    a re-import reproducible - is keyed on `name`. So the sheet title has to
    be part of the name rather than a label beside it, or a workbook with a
    settlements sheet and a payments sheet would have both halves answering
    to the same key and the second would overwrite the first.
    """

    @property
    def name(self) -> str:
        """How this table is addressed: the file name, plus the sheet if any.

        The separator is a middle dot rather than a slash or a colon, because
        this string is shown to a person, used as a dictionary key, and
        written into a saved mapping on disk - and the two obvious separators
        are both meaningful in a path and in the `file:field` form the command
        line answers questions with.
        """
        return f"{self.path.name}{SHEET}{self.sheet}" if self.sheet else self.path.name

    def column(self, header: str) -> tuple[str, ...]:
        """Every value in one column, in file order, blanks included."""
        return tuple(row.get(header, "") for row in self.rows)


def _decode(path: Path) -> tuple[str, str]:
    for encoding in ENCODINGS:
        try:
            return path.read_text(encoding=encoding), encoding
        except UnicodeDecodeError:
            continue
    raise UnreadableFileError(f"{path.name} is not text in any encoding this reader knows")


def _delimiter(sample: str) -> str:
    """Sniff, then check the sniff.

    `csv.Sniffer` is confident about single-column files in a way that is
    never useful, so its answer is only taken when it produces more than one
    column. Otherwise the delimiter that yields the most columns wins, and a
    comma breaks the tie because it is the one everything defaults to.
    """
    try:
        found = csv.Sniffer().sniff(sample, delimiters=DELIMITERS).delimiter
    except csv.Error:
        found = ""
    if found and len(next(csv.reader([sample.splitlines()[0]], delimiter=found), [])) > 1:
        return found

    first = sample.splitlines()[0] if sample.splitlines() else ""
    best = max(DELIMITERS, key=lambda char: (first.count(char), char == ","))
    return best if first.count(best) else ","


def _looks_like_header(cells: list[str]) -> bool:
    """A header row is words, and enough of them.

    Two cells minimum, at least half of them non-empty, and at least half of
    those made of something other than digits and separators. A row of dates
    and amounts is data no matter where it sits in the file.
    """
    filled = [cell.strip() for cell in cells if cell.strip()]
    if len(cells) < 2 or len(filled) * 2 < len(cells):
        return False
    wordy = [cell for cell in filled if any(char.isalpha() for char in cell)]
    return len(wordy) * 2 >= len(filled)


def _find_header(rows: list[list[str]]) -> int:
    """The index of the header row, or raise.

    The test is not "does this look like a header" alone - a banner line can
    pass that. It is "does this look like a header *and* do the rows under it
    have the same shape", which a banner line never does.
    """
    limit = min(MAX_PREAMBLE_LINES, len(rows))
    for index in range(limit):
        cells = rows[index]
        if not _looks_like_header(cells):
            continue
        below = [row for row in rows[index + 1 : index + 1 + SAMPLE_ROWS] if any(row)]
        if not below:
            continue
        agreeing = sum(1 for row in below if len(row) == len(cells))
        if agreeing * 2 >= len(below):
            return index
    raise UnreadableFileError(
        "no header row found in the first "
        f"{limit} lines - the columns under every candidate had a different shape"
    )


def _name_columns(cells: list[str]) -> tuple[str, ...]:
    """Header names, blanks filled in and duplicates made distinct.

    Exports with a trailing delimiter produce an unnamed final column, and
    exports with two `Amount` columns are not rare. Both would collapse
    silently in a dict, so both get a name here instead.
    """
    named: list[str] = []
    for position, cell in enumerate(cells, start=1):
        name = cell.strip() or f"column_{position}"
        if name in named:
            name = f"{name} ({position})"
        named.append(name)
    return tuple(named)


def _assemble(
    path: Path,
    records: list[tuple[int, list[str]]],
    *,
    encoding: str,
    delimiter: str,
    sheet: str = "",
) -> SourceFile:
    """A numbered grid of strings, with the header found and the rows keyed.

    Shared by both readers on purpose. Finding the header, naming the blank
    and duplicate columns, and keeping the line each row came from are the
    three things this package needs from a table, and none of them depends on
    whether the table arrived as text or as a sheet.
    """
    rows = [cells for _, cells in records]

    header_index = _find_header(rows)
    headers = _name_columns(rows[header_index])
    records = _without_footer(records, header_index, len(headers))

    body: list[dict[str, str]] = []
    numbers: list[int] = []
    for line, cells in records[header_index + 1 :]:
        if not any(cell.strip() for cell in cells):
            continue
        padded = [*cells, *([""] * (len(headers) - len(cells)))]
        body.append({name: (padded[index] or "").strip() for index, name in enumerate(headers)})
        numbers.append(line)

    return SourceFile(
        path=path,
        encoding=encoding,
        delimiter=delimiter,
        headers=headers,
        rows=tuple(body),
        line_numbers=tuple(numbers),
        preamble=tuple(delimiter.join(row).strip() for row in rows[:header_index] if any(row)),
        header_line=records[header_index][0],
        sheet=sheet,
    )


MIN_COLUMNS_FOR_FOOTER = 3
"""Below this width, a one-cell row is not distinguishable from a record."""


def _without_footer(
    records: list[tuple[int, list[str]]], header_index: int, width: int
) -> list[tuple[int, list[str]]]:
    """Drop the closing line a statement signs off with.

    `*** End of Statement ***` sits under the last transaction of an HDFC
    export, in the first column, with every other column empty. It is not a
    transaction, and reading it as one puts a row on the screen that has a
    narration and no date, no reference and no amount.

    Nothing downstream breaks on it - a credit line with no amount is not a
    credit line, so the money stays right either way. What it costs is the
    count: a statement of thirty-eight credits reports thirty-nine rows read,
    and a merchant checking our number against their own is the person that
    matters most here.

    Only trailing rows, and only rows with a single populated cell in a table
    at least three columns wide. An interior sparse row is somebody's data; a
    two-column file has no room for the distinction. `Total` lines are left to
    the parser, because they carry an amount and refusing to read a number
    that is genuinely there is not this function's call to make.
    """
    if width < MIN_COLUMNS_FOR_FOOTER:
        return records
    end = len(records)
    while end > header_index + 1:
        filled = [cell for cell in records[end - 1][1] if cell.strip()]
        if len(filled) != 1:
            break
        end -= 1
    return records[:end]


def read_text(path: Path) -> SourceFile:
    """Read one delimited text file into rows keyed by column name."""
    text, encoding = _decode(path)
    if not text.strip():
        raise UnreadableFileError(f"{path.name} is empty")

    delimiter = _delimiter(text[:4096])
    # Parsed from a stream rather than from `splitlines`, so that a quoted
    # narration containing a line break stays one record. Splitting first and
    # parsing after turns that row into two malformed ones, and the second is
    # a row of fragments that will be reported as unreadable at a line number
    # nobody can make sense of.
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    records = [(reader.line_num, cells) for cells in reader]
    return _assemble(path, records, encoding=encoding, delimiter=delimiter)


def read_workbook(path: Path) -> tuple[SourceFile, ...]:
    """Every sheet of a workbook that has a table in it.

    A sheet nobody can find a header in is skipped rather than fatal. Real
    workbooks carry a cover sheet with a logo and a date, a notes sheet, and
    sometimes a pivot cache - none of which is a table, and any of which would
    otherwise take the whole file down with it. The refusal is only raised
    when *no* sheet yields a table, which is the case where the merchant
    genuinely handed over something we cannot read.
    """
    found: list[SourceFile] = []
    failures: list[str] = []
    for title, grid in workbook.sheets(path):
        records = [(number, cells) for number, cells in enumerate(grid, start=1)]
        try:
            found.append(_assemble(path, records, encoding="xlsx", delimiter=",", sheet=title))
        except UnreadableFileError as failure:
            failures.append(f"{title}: {failure}")
    if not found:
        raise UnreadableFileError(
            f"{path.name} has no sheet that looks like a table ({'; '.join(failures)})"
        )
    return tuple(found)


def read_all(path: Path) -> tuple[SourceFile, ...]:
    """Every table in one file: one for a CSV, one per sheet for a workbook.

    The plural is the whole reason this exists. A gateway that exports a
    workbook puts settlements and payments on separate sheets of one file, and
    an import that returned a single table per path would read one of them and
    report success.
    """
    reason = workbook.diagnose(path)
    if reason:
        raise UnreadableFileError(f"{path.name}: {reason}")
    if path.suffix.lower() in workbook.WORKBOOK_SUFFIXES:
        try:
            return read_workbook(path)
        except workbook.FormatError as failure:
            raise UnreadableFileError(str(failure)) from failure
    return (read_text(path),)


def read(path: Path) -> SourceFile:
    """The first table in a file.

    Kept for callers that know they are looking at a single-table file. An
    import uses `read_all`; a test that wrote one CSV and wants it back uses
    this.
    """
    return read_all(path)[0]


def discover(root: Path) -> tuple[Path, ...]:
    """Every table-shaped file in a directory, in a stable order.

    Not recursive. A merchant hands over a folder, not a tree, and walking
    into subdirectories is how an import ends up reading last year's archive
    alongside this month's statement.
    """
    if not root.is_dir():
        raise UnreadableFileError(f"{root} is not a directory")
    found: Iterable[Path] = (
        path
        for path in root.iterdir()
        # Files Excel has open leave a `~$name.xlsx` lock file beside the real
        # one. It is a workbook by extension and garbage by content, and
        # importing a merchant's folder while they have the statement open is
        # not an unusual thing to do.
        if path.is_file()
        and path.suffix.lower() in workbook.DISCOVERABLE
        and not path.name.startswith("~$")
    )
    return tuple(sorted(found, key=lambda path: path.name))
