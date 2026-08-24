"""Terminal output.

Finance output should read like a statement, not like a dashboard: figures
right-aligned, one row per fact, no decoration that is not carrying
information. Colour is used only to separate a resolved credit from one that
needs a person, because that is the only distinction a reader has to make at
a glance.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from milan.domain.money import Paise, format_inr
from milan.domain.results import Proof, ReconReport
from milan.evaluation.harness import Evaluation
from milan.evaluation.metrics import Scorecard

console = Console()

_NUMERIC = {"justify": "right", "no_wrap": True}


def report_summary(report: ReconReport) -> None:
    """What one reconciliation run did."""
    table = Table(title=None, box=None, pad_edge=False, show_header=False)
    table.add_column("", style="dim")
    table.add_column("", **_NUMERIC)  # type: ignore[arg-type]

    resolved = report.credits_resolved
    table.add_row("Records processed", f"{report.records_processed:,}")
    table.add_row("Credits proved", f"{resolved:,}")
    table.add_row("Exceptions raised", f"{len(report.exceptions):,}")
    table.add_row("Elapsed", f"{report.duration_seconds:.3f}s")
    table.add_row("Throughput", f"{report.records_per_second:,.0f} records/s")

    console.print(table)

    if report.exceptions:
        console.print()
        console.print(exception_table(report))


def exception_table(report: ReconReport, limit: int = 12) -> Table:
    """The honest half of the result."""
    table = Table(
        title=f"Exceptions ({len(report.exceptions)})",
        title_justify="left",
        title_style="bold",
        box=None,
        pad_edge=False,
    )
    table.add_column("Code", style="yellow")
    table.add_column("Subject", style="dim")
    table.add_column("Amount", **_NUMERIC)  # type: ignore[arg-type]
    table.add_column("What we found")

    for exception in report.exceptions[:limit]:
        table.add_row(
            exception.code.value,
            _short(exception.subject_id),
            format_inr(exception.amount),
            exception.summary,
        )
    if len(report.exceptions) > limit:
        table.caption = f"... and {len(report.exceptions) - limit} more"
        table.caption_justify = "left"
    return table


def proof_table(proof: Proof) -> Table:
    """One credit, broken down to nothing."""
    table = Table(
        title=f"{_short(proof.credit_id)}  {format_inr(proof.credit_amount)}",
        title_justify="left",
        title_style="bold",
        box=None,
        pad_edge=False,
    )
    table.add_column("Line")
    table.add_column("Amount", **_NUMERIC)  # type: ignore[arg-type]
    table.add_column("Sources", style="dim", **_NUMERIC)  # type: ignore[arg-type]

    for line in proof.lines:
        table.add_row(line.label, format_inr(line.amount), str(len(line.refs)) or "")

    table.add_section()
    table.add_row("Unexplained", format_inr(proof.residual), "")
    table.caption = _proof_caption(proof)
    table.caption_justify = "left"
    return table


def _proof_caption(proof: Proof) -> str:
    """How this credit was resolved, and against what.

    The settlements are named when there is more than one. A merged credit
    that reads like an ordinary one invites the reader to check the total
    against a single settlement, fail, and conclude the proof is wrong.
    """
    if not proof.balances:
        return "does not balance"
    how = f"matched by {proof.strategy.value} at {proof.confidence:.0%} confidence"
    if len(proof.settlement_ids) > 1:
        return f"{how}, covering {len(proof.settlement_ids)} settlements: " + ", ".join(
            _short(settlement_id) for settlement_id in proof.settlement_ids
        )
    return how


def evaluation_table(evaluation: Evaluation) -> Table:
    """Every configuration side by side.

    The baseline row is not filler. A match rate means nothing on its own -
    what it is being compared against is the measurement.
    """
    table = Table(
        title=(f"Evaluation - {evaluation.difficulty} tier, seed {evaluation.seed}"),
        title_justify="left",
        title_style="bold",
        box=None,
        pad_edge=False,
    )
    table.add_column("Configuration")
    table.add_column("Match rate", **_NUMERIC)  # type: ignore[arg-type]
    table.add_column("Precision", **_NUMERIC)  # type: ignore[arg-type]
    table.add_column("Refusals", **_NUMERIC)  # type: ignore[arg-type]
    table.add_column("Merged", **_NUMERIC)  # type: ignore[arg-type]
    table.add_column("False +", **_NUMERIC)  # type: ignore[arg-type]
    table.add_column("Missed", **_NUMERIC)  # type: ignore[arg-type]
    table.add_column("Records/s", **_NUMERIC)  # type: ignore[arg-type]

    for card in evaluation.scorecards:
        table.add_row(
            card.label,
            f"{card.match_rate:.1%}",
            f"{card.precision:.1%}",
            f"{card.correct_refusals}/{card.impossible}",
            f"{card.merged_resolved}/{card.merged_expected}",
            str(card.false_positives),
            str(card.false_negatives),
            f"{card.records_per_second:,.0f}",
        )
    return table


def scorecard_detail(card: Scorecard) -> Table:
    """The breakdown behind a headline number."""
    table = Table(box=None, pad_edge=False, show_header=False)
    table.add_column("", style="dim")
    table.add_column("", **_NUMERIC)  # type: ignore[arg-type]

    table.add_row("Credits", f"{card.credits_total}")
    table.add_row("  resolvable", f"{card.matchable}")
    table.add_row("  impossible by design", f"{card.impossible}")
    table.add_row("Correct matches", f"{card.true_positives}")
    table.add_row("Wrong or forced matches", f"{card.false_positives}")
    table.add_row("Resolvable but missed", f"{card.false_negatives}")
    table.add_row("Correctly refused", f"{card.correct_refusals}")
    table.add_row(
        "Merged credits resolved",
        f"{card.merged_resolved}/{card.merged_expected}",
    )
    table.add_row(
        "Missing payouts flagged",
        f"{card.missing_settlements_detected}/{card.missing_settlements_expected}",
    )
    table.add_row(
        "Unsettled payments flagged",
        f"{card.unreported_payments_detected}/{card.unreported_payments_expected}",
    )

    if card.matches_by_strategy:
        table.add_section()
        for strategy, count in sorted(card.matches_by_strategy.items()):
            table.add_row(f"matched by {strategy}", str(count))

    if card.exceptions_by_code:
        table.add_section()
        for code, count in sorted(card.exceptions_by_code.items()):
            table.add_row(code, str(count))

    if card.unresolved_by_defect:
        table.add_section()
        for defect, count in sorted(card.unresolved_by_defect.items()):
            table.add_row(f"missed, carrying {defect}", str(count))

    return table


def money(paise: Paise) -> str:
    return format_inr(paise)


def _short(identifier: str) -> str:
    """Identifiers are long and the prefix is the part that carries meaning."""
    return identifier if len(identifier) <= 18 else f"{identifier[:15]}..."
