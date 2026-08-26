"""Showing a merchant what we think their files are, before we touch them.

Kept apart from `render` because this is the only output in the project that
is not a result. Everything else prints what a run found; this prints what a
run intends to do, so that somebody can stop it. The whole design of the
import - propose, verify, refuse, ask - is worth nothing if the proposal is
not legible, so this module is part of the safety property rather than
decoration around it.

Certainty is colour-coded and also spelled out in words. Colour carries it at
a glance and the word survives a screenshot, a pipe into a file, and a
terminal somebody has themed.
"""

from __future__ import annotations

from rich.table import Table

from milan.cli.render import console
from milan.domain.results import ReconReport
from milan.ingest.archive import ImportRecord
from milan.ingest.build import Dropped
from milan.ingest.plan import Certainty, FileMapping, IngestPlan, Question

_NUMERIC = {"justify": "right", "no_wrap": True}

_COLOURS: dict[Certainty, str] = {
    Certainty.CONFIRMED: "green",
    Certainty.ANSWERED: "cyan",
    Certainty.UNCONFIRMED: "yellow",
    Certainty.OPEN: "red",
    Certainty.ABSENT: "dim",
}


def files_table(plan: IngestPlan) -> Table:
    """What was found in the folder and what each file was taken to be."""
    table = Table(title=None, box=None, pad_edge=False)
    table.add_column("File")
    table.add_column("Read as")
    table.add_column("Rows", **_NUMERIC)  # type: ignore[arg-type]
    table.add_column("Why")

    for mapping in plan.files:
        table.add_row(
            mapping.name,
            f"[bold]{mapping.kind.value}[/bold]" if mapping.kind else "[dim]not used[/dim]",
            f"{len(mapping.source.rows):,}",
            f"[dim]{mapping.kind_reason}[/dim]",
        )
    for failure in plan.unreadable:
        table.add_row(
            failure.path.name, "[red]unreadable[/red]", "", f"[dim]{failure.reason}[/dim]"
        )
    return table


def mapping_table(mapping: FileMapping) -> Table:
    """One file's columns, and how each was decided."""
    table = Table(
        title=f"[bold]{mapping.name}[/bold]  ->  {mapping.kind.value if mapping.kind else '?'}",
        title_justify="left",
        box=None,
        pad_edge=False,
    )
    table.add_column("Field")
    table.add_column("Column")
    table.add_column("Decided by")
    table.add_column("Because")

    for resolution in mapping.resolutions:
        colour = _COLOURS[resolution.certainty]
        column = resolution.column or ("derived" if resolution.derived else "-")
        if resolution.pattern:
            column = f"{column}  [dim]({resolution.pattern})[/dim]"
        table.add_row(
            f"{resolution.target.name}{'*' if resolution.target.required else ''}",
            column,
            f"[{colour}]{resolution.certainty.value}[/{colour}]",
            f"[dim]{resolution.reason}[/dim]",
        )
    return table


def rejections_table(plan: IngestPlan) -> Table:
    """Proposals the values refused.

    Printed even when empty is not worth it, so the caller checks first - but
    when it has rows it is the most interesting output of the whole import,
    because it is the check earning its place in public.
    """
    table = Table(title=None, box=None, pad_edge=False)
    table.add_column("Field")
    table.add_column("Proposed")
    table.add_column("By")
    table.add_column("Rejected because")

    for rejection in plan.rejections:
        table.add_row(
            f"{rejection.file}:{rejection.target}",
            rejection.column,
            rejection.proposed_by,
            f"[dim]{rejection.reason}[/dim]",
        )
    return table


def show_plan(plan: IngestPlan) -> None:
    """Everything decided about a folder, in the order a person reads it."""
    console.print(files_table(plan))

    for mapping in plan.placed:
        console.print()
        console.print(mapping_table(mapping))

    if plan.rejections:
        console.print()
        console.print("[bold]Proposals the values refused[/bold]")
        console.print(rejections_table(plan))

    limitations = plan.limitations()
    if limitations:
        console.print()
        console.print("[bold]What this import cannot check[/bold]")
        for line in limitations:
            console.print(f"  [yellow]-[/yellow] {line}")


def show_question(question: Question, number: int, total: int) -> None:
    console.print()
    console.print(f"[bold]Question {number} of {total}[/bold]  [dim]({question.key})[/dim]")
    console.print(f"  {question.asks}")
    for index, choice in enumerate(question.choices, start=1):
        console.print(f"    [cyan]{index}[/cyan]  {choice.label}")


def show_blocked(plan: IngestPlan) -> None:
    """What to do about an import that stopped, when nobody is at the keyboard.

    Prints the exact flag for every open question. An import that refuses and
    then leaves the operator to work out the syntax has refused twice.
    """
    console.print()
    console.print("[red]This import stopped, because guessing here would change a balance.[/red]")
    for line in plan.blockers():
        console.print(f"  [red]-[/red] {line}")
    if not plan.questions:
        return
    console.print()
    console.print("Answer them like this, or run without --non-interactive to be asked:")
    for question in plan.questions:
        first = question.choices[0].value if question.choices else "<column>"
        console.print(f'  [dim]--map "{question.key}={first}"[/dim]')


def result_summary(record: ImportRecord, report: ReconReport) -> None:
    """What the import read, before the reconciliation output that follows."""
    table = Table(title=None, box=None, pad_edge=False, show_header=False)
    table.add_column("", style="dim")
    table.add_column("", **_NUMERIC)  # type: ignore[arg-type]

    for kind, count in record.counts.items():
        table.add_row(kind.replace("_", " ").capitalize(), f"{count:,}")
    table.add_row("Records reconciled", f"{report.records_processed:,}")
    if record.withdrawals:
        table.add_row("Statement lines that were debits", f"{record.withdrawals:,}")
    table.add_row("Rows dropped", f"{record.dropped:,}")
    table.add_row("Columns a model contributed", f"{record.columns_proposed:,}")
    table.add_row("Schema proposals refused", f"{len(record.rejections):,}")

    console.print(table)


def dropped_table(dropped: tuple[Dropped, ...], limit: int = 12) -> Table:
    """Rows that would not read, with the line to open in a spreadsheet.

    Capped, because a file whose date format was wrong drops every row and a
    thousand identical lines tell a person nothing the first one did not.
    """
    table = Table(
        title=f"[bold]{len(dropped)} row(s) could not be read[/bold]",
        title_justify="left",
        box=None,
        pad_edge=False,
    )
    table.add_column("File")
    table.add_column("Line", **_NUMERIC)  # type: ignore[arg-type]
    table.add_column("Why")

    for row in dropped[:limit]:
        table.add_row(row.file, f"{row.line:,}", f"[dim]{row.reason}[/dim]")
    if len(dropped) > limit:
        table.add_row("", "", f"[dim]... and {len(dropped) - limit:,} more[/dim]")
    return table
