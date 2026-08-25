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
from milan.evaluation.ablation import Ablation
from milan.evaluation.harness import Evaluation
from milan.evaluation.metrics import Scorecard
from milan.evaluation.sweep import Sweep

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

    table.add_row("Records processed", f"{card.records_processed:,}")
    table.add_row("Elapsed", f"{card.duration_seconds:.3f}s")
    table.add_section()
    table.add_row("Credits", f"{card.credits_total}")
    table.add_row("  resolvable", f"{card.matchable}")
    table.add_row("  impossible by design", f"{card.impossible}")
    table.add_row("Correct matches", f"{card.true_positives}")
    table.add_row("Wrong or forced matches", f"{card.false_positives}")
    table.add_row("Resolvable but missed", f"{card.false_negatives}")
    table.add_row("Correctly refused", f"{card.correct_refusals}")
    # Beside the match rate rather than instead of it. They answer different
    # questions - "did we reconcile it" and "did we work out what it was" -
    # and the gap between them is exactly the population that used to fail
    # matching with nowhere for that failure to be reported.
    table.add_row(
        "Settlement attributed",
        f"{card.attributed}/{card.matchable + card.unprovable_expected} "
        f"({card.attribution_rate:.1%})",
    )
    table.add_row(
        "Shortfalls named, not claimed",
        f"{card.unprovable_explained}/{card.unprovable_expected} ({card.explained_rate:.0%})",
    )
    table.add_row("  of those that could not be resolved", f"{card.refusal_rate:.1%}")
    table.add_section()
    table.add_row("Proofs claimed", f"{card.proofs_claimed}")
    table.add_row("  that balanced to the paisa", f"{card.proofs_balanced}")
    table.add_row("  that needed the rounding allowance", f"{card.proofs_with_drift}")
    # Gross before net, because the net is the smaller number and reading it
    # first is what turns "it cancels out" into "it does not happen".
    table.add_row("Rounding drift, gross", format_inr(card.drift_gross))
    table.add_row("  net across the run", format_inr(card.drift_net))
    table.add_row(
        "Merged credits resolved",
        f"{card.merged_resolved}/{card.merged_expected} ({card.merged_rate:.0%})",
    )
    table.add_row(
        "Missing payouts flagged",
        f"{card.missing_settlements_detected}/{card.missing_settlements_expected}"
        f" ({card.missing_detection_rate:.0%})",
    )
    table.add_row(
        "Unsettled payments flagged",
        f"{card.unreported_payments_detected}/{card.unreported_payments_expected}"
        f" ({card.unreported_detection_rate:.0%})",
    )
    table.add_section()
    table.add_row("Exceptions raised", f"{card.exceptions_total}")
    table.add_row("  per credit", f"{card.exception_rate:.2f}")
    table.add_row("  sorted without a model", f"{card.rules_share:.1%}")
    for source, count in sorted(card.categorised_by.items()):
        table.add_row(f"  sorted by {source}", str(count))

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

    if card.unexplained_by_defect:
        table.add_section()
        for defect, count in sorted(card.unexplained_by_defect.items()):
            table.add_row(f"shortfall unnamed, carrying {defect}", str(count))

    return table


def money(paise: Paise) -> str:
    return format_inr(paise)


def _short(identifier: str) -> str:
    """Identifiers are long and the prefix is the part that carries meaning."""
    return identifier if len(identifier) <= 18 else f"{identifier[:15]}..."


MARKDOWN_OPEN = "<!-- generated: eval -->"
MARKDOWN_CLOSE = "<!-- /generated -->"
SWEEP_OPEN = "<!-- generated: sweep -->"


def evaluation_markdown(evaluation: Evaluation) -> str:
    """The same table, as markdown, for pasting into the README.

    This exists because the README's numbers were retyped once and went
    stale: the match rates were current and the refusal column had been
    carried over from an earlier run, which is not a kind of error a reader
    can catch. A table that is printed by the command it describes cannot
    disagree with it, and the fences let a test assert that the README
    contains exactly what a fresh run produces.
    """
    header = (
        "| Configuration | Match rate | Precision | Correct refusals | Shortfalls named |",
        "|---|---|---|---|---|",
    )
    rows = tuple(
        f"| {card.label} | {card.match_rate:.1%} | {card.precision:.1%} "
        f"| {card.correct_refusals}/{card.impossible} "
        f"| {card.unprovable_explained}/{card.unprovable_expected} |"
        for card in evaluation.scorecards
    )
    return "\n".join((MARKDOWN_OPEN, *header, *rows, MARKDOWN_CLOSE))


def sweep_table(result: Sweep) -> Table:
    """Pooled figures, with the range each was pooled from beside it.

    The range column is not decoration. A rate pooled from twenty seeds and a
    rate that happened to be that value on one seed look identical in a
    report; the swing is what tells them apart.
    """
    table = Table(
        title=(
            f"{len(result.seeds)} seeds - {result.difficulty} tier, {result.orders} orders each"
        ),
        title_justify="left",
        title_style="bold",
        box=None,
        pad_edge=False,
    )
    table.add_column("Measure")
    table.add_column("Pooled", **_NUMERIC)  # type: ignore[arg-type]
    table.add_column("Of", **_NUMERIC)  # type: ignore[arg-type]
    table.add_column("Worst seed", **_NUMERIC)  # type: ignore[arg-type]
    table.add_column("Median", **_NUMERIC)  # type: ignore[arg-type]
    table.add_column("Best seed", **_NUMERIC)  # type: ignore[arg-type]

    for spread in result.spreads:
        swung = spread.swing >= 0.2
        table.add_row(
            spread.name,
            f"{spread.pooled:.1%}",
            f"{spread.numerator}/{spread.denominator}",
            f"[yellow]{spread.lowest:.1%}[/yellow]" if swung else f"{spread.lowest:.1%}",
            f"{spread.middle:.1%}",
            f"[yellow]{spread.highest:.1%}[/yellow]" if swung else f"{spread.highest:.1%}",
        )

    table.add_section()
    table.add_row("rounding drift, gross", format_inr(result.drift_gross))
    table.add_row("  net", format_inr(result.drift_net))
    table.add_row("  proofs carrying it", str(result.proofs_with_drift))
    return table


def sweep_markdown(result: Sweep) -> str:
    """The pooled table as markdown, on the same terms as `evaluation_markdown`."""
    header = (
        "| Measure | Pooled | Of | Worst seed | Median | Best seed |",
        "|---|---|---|---|---|---|",
    )
    rows = tuple(
        f"| {spread.name} | {spread.pooled:.1%} "
        f"| {spread.numerator}/{spread.denominator} "
        f"| {spread.lowest:.1%} | {spread.middle:.1%} | {spread.highest:.1%} |"
        for spread in result.spreads
    )
    return "\n".join((SWEEP_OPEN, *header, *rows, MARKDOWN_CLOSE))


def ablation_table(result: Ablation) -> Table:
    """What the model was worth, next to what it cost.

    Laid out so the two questions stay apart. Agreement says whether the model
    can do the job at all; contribution says whether it added anything to a
    job the rules had already finished. A reader who conflates them will
    conclude either that a competent model is useless or that a useless model
    is competent.
    """
    table = Table(
        title=f"{result.provider}{f' - {result.model}' if result.model else ''}",
        title_justify="left",
        title_style="bold",
        box=None,
        pad_edge=False,
    )
    table.add_column("Measure")
    table.add_column("Value", justify="right")
    table.add_column("Of", justify="right")

    answered = f"{result.answered}/{result.asked}"
    table.add_row("questions answered", answered, "")
    table.add_section()
    table.add_row(
        "agreement with the rules",
        f"{result.agreement_rate:.1%}",
        f"{result.agreement_hits}/{result.agreement_cases}",
    )
    table.add_row(
        "contribution beyond them",
        f"{result.contribution_rate:.1%}",
        f"{result.contributions}/{result.open_cases}",
    )
    table.add_section()
    table.add_row("proposals rejected by arithmetic", str(result.rejected), "")
    table.add_row("identifiers invented", str(result.invented_ids), "")
    if result.kinds:
        table.add_section()
        for kind, count in sorted(result.kinds.items(), key=lambda pair: -pair[1]):
            table.add_row(f"  proposed {kind}", str(count), "")
    return table
