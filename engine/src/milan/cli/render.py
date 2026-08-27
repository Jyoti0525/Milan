"""Terminal output.

Finance output should read like a statement, not like a dashboard: figures
right-aligned, one row per fact, no decoration that is not carrying
information. Colour is used only to separate a resolved credit from one that
needs a person, because that is the only distinction a reader has to make at
a glance.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from rich.console import Console
from rich.table import Table

from milan.domain.merchant import MerchantProfile
from milan.domain.money import Paise, format_inr
from milan.domain.results import Proof, ReconReport
from milan.evaluation.ablation import Ablation
from milan.evaluation.control import Comparison
from milan.evaluation.curve import Curve
from milan.evaluation.harness import Evaluation
from milan.evaluation.metrics import Scorecard
from milan.evaluation.sweep import Spread, Sweep
from milan.evaluation.twice import Twice
from milan.leaks.clusters import LeakReport
from milan.llm.pricing import RATES
from milan.llm.registry import Status
from milan.samples.measure import Accuracy

console = Console()

_NUMERIC = {"justify": "right", "no_wrap": True}


def merchant_table(profile: MerchantProfile) -> Table | None:
    """Who the files say this merchant is, or nothing if they say nothing.

    Only the facts that turned out to be true, plus anything the rows could
    not settle. A list of three lines saying `no` is not a finding, and a
    screen that prints one trains the reader to stop looking at it.
    """
    shown = [*profile.named, *profile.questions]
    if not shown:
        return None

    table = Table(
        title="Who this merchant is, read from their own rows",
        title_justify="left",
        title_style="bold",
        box=None,
        pad_edge=False,
    )
    table.add_column("Finding")
    table.add_column("Rows", **_NUMERIC)  # type: ignore[arg-type]
    table.add_column("Because")

    for finding in shown:
        name = (
            f"[yellow]{finding.name}?[/yellow]"
            if finding.held is None
            else f"[green]{finding.name}[/green]"
        )
        table.add_row(name, finding.share, finding.because)
    return table


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

    merchant = merchant_table(report.profile)
    if merchant is not None:
        console.print()
        console.print(merchant)

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
    # The one finding here that survives everything reconciling, so it sits
    # with the scored figures rather than in a footnote. Precision first,
    # because a leak claimed that is not there costs a merchant a phone call
    # with their account manager and some of their credibility.
    table.add_row(
        "Charges above contract found",
        f"{card.leaks_found}/{card.leaks_expected} ({card.leak_recall:.0%})",
    )
    table.add_row(
        "  claimed that were not there",
        f"{card.leaks_false} ({card.leak_precision:.0%} precise)",
    )
    table.add_row("  overcharged", format_inr(card.leak_overcharge))
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
CURVE_OPEN = "<!-- generated: curve -->"


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


def _cell(spread: Spread) -> str:
    """One tier's reading of one measure, with what it was measured over.

    A dash when the denominator is zero, never `0.0%`. The clean tier
    generates nothing impossible, nothing merged and nothing mispriced, so
    three of these measures have nothing to score there - and a percentage
    printed over an empty denominator claims the system failed at work it was
    never given.
    """
    if spread.denominator == 0:
        return "[dim]-[/dim]"
    return f"{spread.pooled:.1%} [dim]{spread.numerator}/{spread.denominator}[/dim]"


def curve_table(result: Curve) -> Table:
    """Every measure across every tier, side by side.

    The rates are the smaller half of this table. The counts beside them are
    what show the work increasing: clean has no impossible credits to refuse
    and no leaks to catch, adversarial has both, and a reader comparing two
    100% figures needs to see that they are not measurements of the same
    thing.
    """
    table = Table(
        title=(f"{len(result.seeds)} seeds per tier, {result.orders} orders each"),
        title_justify="left",
        title_style="bold",
        box=None,
        pad_edge=False,
    )
    # Not wrapped: "merged credits resolved" broken across two lines puts the
    # second half of a measure name under the first tier's figure, which reads
    # as a row of its own.
    table.add_column("Measure", no_wrap=True)
    for tier in result.tiers:
        table.add_column(tier, justify="right")

    for measure in result.measures():
        table.add_row(measure, *(_cell(spread) for spread in result.row(measure)))

    table.add_section()
    table.add_row(
        "rounding drift, gross",
        *(format_inr(run.drift_gross) for run in result.sweeps),
    )
    return table


def curve_markdown(result: Curve) -> str:
    """The curve as markdown, on the same terms as the other two."""
    header = (
        "| Measure | " + " | ".join(result.tiers) + " |",
        "|---" * (len(result.tiers) + 1) + "|",
    )
    rows = tuple(
        "| "
        + measure
        + " | "
        + " | ".join(
            "-"
            if spread.denominator == 0
            else f"{spread.pooled:.1%} <sub>{spread.numerator}/{spread.denominator}</sub>"
            for spread in result.row(measure)
        )
        + " |"
        for measure in result.measures()
    )
    return "\n".join((CURVE_OPEN, *header, *rows, MARKDOWN_CLOSE))


def chain_table(tally: Sequence[tuple[str, int, int, bool]]) -> Table:
    """How a chained run divided between its providers.

    Printed underneath a chained ablation because the headline rate above it
    belongs to no single model. A run where the best model answered forty
    questions and the second answered seventy is a measurement of neither one
    on its own, and the only honest way to publish it is beside the split.

    `ran out, handed on` is the column worth reading. A provider that stopped
    answering part way through has met a free tier rather than failed, and the
    run carried on down the list - which is the feature working, and also the
    reason the rate above is a blend.
    """
    table = Table(
        title="Which provider answered",
        title_justify="left",
        title_style="bold",
        box=None,
        pad_edge=False,
    )
    table.add_column("Provider")
    table.add_column("Asked", **_NUMERIC)  # type: ignore[arg-type]
    table.add_column("Answered", **_NUMERIC)  # type: ignore[arg-type]
    table.add_column("")

    for name, asked, answered, standing in tally:
        note = "" if standing else "[yellow]ran out, handed on[/yellow]"
        table.add_row(name, str(asked), str(answered), note)
    return table


def ablation_parity(results: Sequence[Ablation]) -> Table:
    """The same shortfalls, the same verifier, one column per provider.

    `milan measure --all` answers whether a model helps decide what a column
    is, and the answer there is that the file's own arithmetic decides it, so
    every provider reaches the same mapping. This answers the other question,
    and it is the one where a model can still earn its place: given a payout
    that arrived short and a report the rules could not explain, does this
    model name the reason - and does the name survive the arithmetic.

    Read the rows in this order.

    **Identifiers invented** is the one that must be zero. A proposal naming a
    refund that is not in the report sends a finance team through their ledger
    looking for something that never existed, and it is the only failure here
    that costs a person time rather than a token.

    **Agreement** is scored on shortfalls the rules already named, so it is a
    competence check and nothing more. It cannot move a graded number, because
    the rules had already answered.

    **Contribution** is the only figure that could justify a model being in
    the pipeline at all: shortfalls the rules could *not* name, where the
    model proposed something that then passed the same arithmetic the rules
    use. A zero here with a healthy agreement rate is a model that is
    competent and unnecessary, which is a real and reportable result.

    **Rejected by arithmetic** is not a failure column. It is the veto
    working: every one of these was discarded before anything reached a
    screen, and a provider with a high count is being caught rather than
    trusted.

    **Answered** guards all of it. A free tier that ran out of budget looks
    exactly like a model that declined, and both are scored as disagreements -
    so a rate underneath an incomplete `answered` is a floor, not an estimate.
    """
    table = Table(
        title="The same shortfalls, scored per provider",
        title_justify="left",
        title_style="bold",
        box=None,
        pad_edge=False,
    )
    table.add_column("Measure")
    for result in results:
        table.add_column(result.provider, justify="right")

    def row(label: str, cell: Callable[[Ablation], str]) -> None:
        table.add_row(label, *(cell(result) for result in results))

    table.add_row(
        "identifiers invented",
        *(
            f"[bold red]{result.invented_ids}[/bold red]"
            if result.invented_ids
            else "[bold green]0[/bold green]"
            for result in results
        ),
    )
    table.add_section()
    row("model", lambda result: result.model or "-")
    row("questions answered", lambda result: f"{result.answered}/{result.asked}")
    row(
        "agreement with the rules",
        lambda result: (
            f"{result.agreement_rate:.1%} of {result.agreement_cases}"
            if result.agreement_cases
            else "-"
        ),
    )
    row(
        "contribution beyond them",
        lambda result: (
            f"{result.contribution_rate:.1%} of {result.open_cases}"
            if result.open_cases
            else "0 of 0"
        ),
    )
    row("rejected by arithmetic", lambda result: str(result.rejected))
    table.add_section()
    row("tokens", lambda result: f"{result.tokens:,}")
    row("replayed from cache", lambda result: f"{result.replayed}/{result.asked}")
    row("model time, as measured", lambda result: f"{result.seconds:,.1f}s")
    return table


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

    table.add_section()
    table.add_row("tokens in", f"{result.prompt_tokens:,}", "")
    table.add_row("  out", f"{result.completion_tokens:,}", "")
    table.add_row("answers replayed from cache", f"{result.replayed}/{result.asked}", "")
    # What the answers cost when they were produced, not what this run took.
    # A replay is three seconds; saying so here would understate the work and
    # make the cache look like a speedup rather than a record.
    table.add_row("model time, as measured", f"{result.seconds:.1f}s", "")
    # Zero, and it stays zero: a local model and free tiers. The projections
    # below are what this volume would cost somebody who was billed for it,
    # and each one carries the rate it was quoted at.
    table.add_row("spent", "Rs 0.00", "")
    for rate in RATES:
        table.add_row(
            f"  at {rate.label}",
            f"${rate.project(result.prompt_tokens, result.completion_tokens)}",
            f"[dim]{rate.source}, {rate.checked_on}[/dim]",
        )
    return table


def twice_table(result: Twice) -> Table:
    """The same questions, asked twice, side by side.

    The rows are the evidence and the caption is the claim. A reader who only
    reads the caption should still see the two columns disagreeing.
    """
    table = Table(
        title=(
            f"{result.provider}{f' - {result.model}' if result.model else ''}"
            f" at temperature {result.temperature:g}, {result.difficulty} tier, "
            f"{len(result.seeds)} seed{'s' if len(result.seeds) > 1 else ''}"
        ),
        title_justify="left",
        title_style="bold",
        box=None,
        pad_edge=False,
    )
    table.add_column("Credit", style="dim")
    table.add_column("First answer")
    table.add_column("Second answer")

    for question in result.questions:
        moved = question.changed
        table.add_row(
            _short(question.credit_id),
            str(question.first),
            f"[yellow]{question.second}[/yellow]" if moved else str(question.second),
        )

    table.add_section()
    table.add_row("changed", f"{result.changed}/{result.asked}", "")
    table.add_row("named a different record", str(result.different_records), "")
    return table


def provider_table(found: tuple[Status, ...]) -> Table:
    """Which providers can answer, and the command that fixes the rest."""
    table = Table(box=None, pad_edge=False)
    table.add_column("Provider")
    table.add_column("Model", style="dim")
    table.add_column("Ready", justify="right")
    table.add_column("")

    for entry in found:
        table.add_row(
            entry.name,
            entry.model or "-",
            "[green]yes[/green]" if entry.ready else "[yellow]no[/yellow]",
            f"[dim]{entry.reason}[/dim]",
        )
    return table


def leak_report(report: LeakReport) -> Table:
    """The findings, worst first, with the rows behind each one.

    The headline is a sentence rather than a figure because the figure alone
    invites the wrong reaction. "Rs 136.83" on a month of settlements reads as
    a rounding error and gets ignored; the same number said as a rate applied
    to the wrong card type, every day for a month, is a contract problem worth
    a phone call.
    """
    table = Table(
        title=report.headline(),
        title_justify="left",
        title_style="bold",
        box=None,
        pad_edge=False,
    )
    table.add_column("Finding")
    table.add_column("Payments", justify="right")
    table.add_column("Overcharged", justify="right")

    if report.clean:
        return table

    for group in report.clusters:
        what = (group.card_type or group.method).replace("_", " ")
        table.add_row(
            f"{what} charged {group.charged_rate:.2%}, contracted {group.contracted_rate:.2%}",
            str(group.payments),
            format_inr(group.overcharge),
        )
        table.add_row(
            f"  on {format_inr(group.gross_affected)} settled, "
            f"{group.first_seen} to {group.last_seen}",
            "",
            "",
        )
        if group.networks:
            table.add_row(f"  networks: {', '.join(group.networks)}", "", "")
        # Five is enough to check the claim against an export without turning
        # the finding back into the list it was written to replace.
        shown = ", ".join(group.payment_ids[:5])
        more = len(group.payment_ids) - 5
        table.add_row(f"  {shown}{f' +{more} more' if more > 0 else ''}", "", "")
        table.add_section()

    table.add_row("GST charged on those fees", "", format_inr(report.gst))
    table.add_row("  recoverable as input tax credit", "", "")
    return table


CONTROL_OPEN = "<!-- generated: control -->"


def control_table(result: Comparison) -> Table:
    """Both control policies, on accuracy and on cost.

    The accuracy rows are the boring half and that is the finding. What the
    reader is meant to look at is the two rows under the rule: the same
    answers, reached by asking the rungs twice as many times.
    """
    table = Table(
        title=(f"{result.difficulty}, {len(result.seeds)} seeds, {result.orders} orders each"),
        title_justify="left",
        title_style="bold",
        box=None,
        pad_edge=False,
    )
    table.add_column("Measure", no_wrap=True)
    for arm in result.arms:
        table.add_column(arm.label, justify="right")

    for measure in result.measures:
        table.add_row(measure, *(_cell(arm.named(measure)) for arm in result.arms))

    table.add_section()
    table.add_row("rung attempts", *(f"{arm.attempts:,}" for arm in result.arms))
    table.add_row("  per credit", *(f"{arm.attempts_per_credit:.2f}" for arm in result.arms))
    table.add_row("matching time", *(f"{arm.seconds:.2f}s" for arm in result.arms))
    return table


def control_markdown(result: Comparison) -> str:
    """The comparison as markdown, on the same terms as the other tables."""
    header = (
        "| Measure | " + " | ".join(arm.label for arm in result.arms) + " |",
        "|---" * (len(result.arms) + 1) + "|",
    )
    rows = [
        "| "
        + measure
        + " | "
        + " | ".join(
            "-"
            if arm.named(measure).denominator == 0
            else (
                f"{arm.named(measure).pooled:.1%} "
                f"({arm.named(measure).numerator}/{arm.named(measure).denominator})"
            )
            for arm in result.arms
        )
        + " |"
        for measure in result.measures
    ]
    rows.append(
        "| **rung attempts** | " + " | ".join(f"**{arm.attempts:,}**" for arm in result.arms) + " |"
    )
    rows.append(
        "| **matching time** | "
        + " | ".join(f"**{arm.seconds:.2f}s**" for arm in result.arms)
        + " |"
    )
    return "\n".join((CONTROL_OPEN, *header, *rows, MARKDOWN_CLOSE))


def parity_report(scores: Sequence[Accuracy]) -> Table:
    """The same corpus, the same answer key, one column per provider.

    The question this exists to answer is whether the local model and a hosted
    one are at the same level, and the honest answer turned out to be that the
    question has stopped mattering for this part of the system: the file's own
    arithmetic settles the mapping, so every provider reaches the same
    mapping, and a provider that reached a different one would be reaching a
    worse one.

    Which is exactly why it is worth printing. A claim that swapping the model
    changes nothing is a claim, and this is the instrument that would catch it
    becoming false - a column here that does not match its neighbours is
    either a model earning its place or a check that has stopped working.

    `settled wrongly` is the row to read first and it is the row that must be
    zero in every column. A provider that settles more columns by settling one
    of them wrongly has not done better.
    """
    table = Table(box=None, pad_edge=False, title="The same twelve files, scored per provider")
    table.add_column("Measure")
    for scored in scores:
        table.add_column(scored.provider, justify="right")

    def row(label: str, cell: Callable[[Accuracy], str], note: str = "") -> None:
        table.add_row(label, *(cell(scored) for scored in scores))
        del note

    wrongs = [len(scored.wrong) for scored in scores]
    table.add_row(
        "settled wrongly",
        *(
            f"[bold red]{count}[/bold red]" if count else "[bold green]0[/bold green]"
            for count in wrongs
        ),
    )
    table.add_section()
    row("files placed", lambda s: f"{s.kinds_right}/{len(s.kinds)}")
    row("columns settled", lambda s: s.rate(s.settled_right, s.outcomes))
    row("columns asked about", lambda s: str(len(s.asked)))
    row("columns not found", lambda s: str(len(s.missed)))
    row(
        "suggestions correct",
        lambda s: f"{len(s.suggested_right)}/{len(s.suggested)}" if s.suggested else "-",
    )
    return table


def accuracy_report(scored: Accuracy) -> Table:
    """The import marked against an answer key, with the failures named.

    `wrong` is printed first and in red whatever its value, because a report
    whose worst figure is only visible when it is bad trains people not to
    look for it. Zero is the result; zero shown plainly is the point.

    Every rate carries the population it was measured over. A bare percentage
    over an unstated denominator is a mistake this project has already made
    once, and the fix travels with the figure rather than living in a docstring.
    """
    table = Table(
        box=None, pad_edge=False, title=f"Scored against the answer key ({scored.provider})"
    )
    table.add_column("")
    table.add_column("", justify="right")
    table.add_column("", style="dim")

    wrong = len(scored.wrong)
    table.add_row(
        "settled wrongly",
        f"[bold red]{wrong}[/bold red]" if wrong else "[bold green]0[/bold green]",
        "settled without asking, and not what the file holds",
    )
    table.add_section()
    table.add_row(
        "files placed",
        f"{scored.kinds_right}/{len(scored.kinds)}",
        "including the ones that should be left alone",
    )
    table.add_row(
        "columns settled",
        str(len(scored.settled_right)),
        scored.rate(scored.settled_right, scored.outcomes),
    )
    table.add_row("columns asked about", str(len(scored.asked)), "put to a person")
    table.add_row(
        "columns not found",
        str(len(scored.missed)),
        "the file has them; the import concluded it had none",
    )
    if scored.blank:
        table.add_row(
            "columns with no data",
            str(len(scored.blank)),
            "the file names the column and leaves every row of it empty",
        )

    if scored.suggested:
        table.add_section()
        table.add_row(
            "suggestions offered",
            str(len(scored.suggested)),
            "a question led with a proposed answer",
        )
        table.add_row(
            "suggestions correct",
            f"{len(scored.suggested_right)}/{len(scored.suggested)}",
            scored.rate(scored.suggested_right, scored.suggested),
        )

    for outcome in scored.wrong:
        table.add_section()
        table.add_row(
            f"[red]{outcome.file}[/red]",
            outcome.field,
            f"read as {outcome.got!r}, the file holds it in {outcome.expected!r}",
        )

    for name, expected, got in scored.kinds:
        if expected == got:
            continue
        table.add_section()
        table.add_row(
            f"[yellow]{name}[/yellow]",
            "placed",
            f"as {got or 'nothing'}, not {expected or 'nothing'}",
        )

    return table
