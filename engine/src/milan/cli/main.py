"""The command line.

One entry point for the whole engine. Every command takes a seed and a
difficulty tier, because every run in this project is reproducible and a
command that quietly used a different dataset than the last one would make
the numbers impossible to compare.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.cli import render
from milan.cli.render import console
from milan.domain.dataset import Dataset
from milan.domain.rates import RateCard
from milan.evaluation.harness import evaluate, to_recon_input
from milan.evaluation.sweep import sweep
from milan.persistence import store
from milan.recon.pipeline import ReconciliationPipeline, RunMetadata

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Settlement reconciliation that proves where every rupee went.",
)

SeedOption = Annotated[int, typer.Option("--seed", help="Anything reproducible starts here.")]
DifficultyOption = Annotated[
    Difficulty, typer.Option("--difficulty", help="Which tier of defects to inject.")
]
SpanOption = Annotated[int, typer.Option("--span", help="Days the activity covers.")]
WithholdingOption = Annotated[
    bool,
    typer.Option(
        "--withholding/--no-withholding",
        help="Section 194-O: withhold 1% of gross, as an e-commerce operator must.",
    ),
]
RootOption = Annotated[
    Path | None, typer.Option("--data-root", help="Where runs are stored.", show_default=False)
]


def _root(root: Path | None) -> Path:
    return root if root is not None else store.default_root()


def _load(root: Path | None, seed: int, difficulty: Difficulty) -> Dataset:
    """Load a stored run, or fail with something a person can act on.

    Both failures here are the user's next command, not a bug: there is no
    run, or the run is older than the generator. A traceback would say
    neither.
    """
    try:
        return store.load_dataset(_root(root), seed, difficulty)
    except (FileNotFoundError, store.StaleDatasetError) as failure:
        console.print(f"[red]{failure}[/red]")
        raise typer.Exit(code=1) from failure


@app.command()
def generate(
    seed: SeedOption = 42,
    difficulty: DifficultyOption = Difficulty.REALISTIC,
    orders: Annotated[int, typer.Option("--orders", help="How many orders to generate.")] = 100,
    span: SpanOption = 21,
    withholding: WithholdingOption = False,
    root: RootOption = None,
) -> None:
    """Generate a merchant's month, with the answer key."""
    config = GenerationConfig(
        seed=seed,
        difficulty=difficulty,
        order_count=orders,
        span_days=span,
        rates=RateCard(tds_applies=withholding),
    )
    dataset = ChaosEngine(config).generate()
    path = store.save_dataset(dataset, _root(root), config)

    console.print(
        f"Generated [bold]{dataset.record_count:,}[/bold] records "
        f"across {len(dataset.bank_credits)} bank credits "
        f"({dataset.answer_key.merged_count} merged, "
        f"{dataset.answer_key.impossible_count} impossible by design)."
    )
    console.print(f"[dim]{path}[/dim]")


@app.command()
def recon(
    seed: SeedOption = 42,
    difficulty: DifficultyOption = Difficulty.REALISTIC,
    root: RootOption = None,
) -> None:
    """Reconcile a generated dataset and report what could not be resolved."""
    data_root = _root(root)
    dataset = _load(root, seed, difficulty)
    report = ReconciliationPipeline().run(
        to_recon_input(dataset), RunMetadata(seed=dataset.seed, difficulty=dataset.difficulty)
    )
    store.save_report(report, data_root)
    render.report_summary(report)


@app.command(name="eval")
def evaluate_command(
    seed: SeedOption = 42,
    difficulty: DifficultyOption = Difficulty.REALISTIC,
    detail: Annotated[bool, typer.Option("--detail", help="Break the headline down.")] = False,
    markdown: Annotated[
        bool,
        typer.Option("--markdown", help="Print the table as markdown, for the README."),
    ] = False,
    root: RootOption = None,
) -> None:
    """Score every configuration against ground truth."""
    data_root = _root(root)
    dataset = _load(root, seed, difficulty)
    evaluation = evaluate(dataset)
    store.write(
        evaluation, store.run_directory(data_root, seed, difficulty) / store.EVALUATION_FILE
    )

    if markdown:
        # print, not console.print - rich would wrap and style a block whose
        # whole purpose is to be pasted somewhere else unchanged.
        print(render.evaluation_markdown(evaluation))
        return

    console.print(render.evaluation_table(evaluation))
    if detail:
        console.print()
        console.print(render.scorecard_detail(evaluation.headline))


@app.command()
def prove(
    credit: Annotated[str, typer.Argument(help="Bank credit id, or a unique prefix of one.")],
    seed: SeedOption = 42,
    difficulty: DifficultyOption = Difficulty.REALISTIC,
    root: RootOption = None,
) -> None:
    """Show one bank credit broken down to nothing."""
    dataset = _load(root, seed, difficulty)
    report = ReconciliationPipeline().run(
        to_recon_input(dataset), RunMetadata(seed=dataset.seed, difficulty=dataset.difficulty)
    )

    matches = [proof for proof in report.proofs if proof.credit_id.startswith(credit)]
    if not matches:
        _report_no_proof(report, credit)
        raise typer.Exit(code=1)
    if len(matches) > 1:
        console.print(
            f"[yellow]{credit} matches {len(matches)} credits. Be more specific.[/yellow]"
        )
        raise typer.Exit(code=1)

    console.print(render.proof_table(matches[0]))


def _report_no_proof(report: object, credit: str) -> None:
    """Say why there is nothing to show, rather than just failing."""
    exceptions = [
        exception
        for exception in getattr(report, "exceptions", ())
        if exception.subject_id.startswith(credit)
    ]
    if exceptions:
        console.print(f"[yellow]{exceptions[0].code.value}[/yellow] {exceptions[0].summary}")
        for key, value in exceptions[0].evidence.items():
            console.print(f"  [dim]{key}[/dim] {value}")
    else:
        console.print(f"[red]No credit starting {credit} in this run.[/red]")


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host", help="Interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Port to bind.")] = 8000,
    root: RootOption = None,
) -> None:
    """Serve the reconciliation API for the exception queue.

    Binds to loopback unless told otherwise. This serves a merchant's
    settlement data and has no authentication, so the default has to be the
    one that is safe when nobody thought about it.
    """
    import uvicorn

    from milan.api.app import create_app

    console.print(f"[dim]serving {_root(root)} on http://{host}:{port}[/dim]")
    uvicorn.run(create_app(_root(root)), host=host, port=port, log_level="warning")


@app.command(name="sweep")
def sweep_command(
    seeds: Annotated[int, typer.Option("--seeds", help="How many seeds to score.")] = 20,
    difficulty: DifficultyOption = Difficulty.ADVERSARIAL,
    orders: Annotated[int, typer.Option("--orders", help="Orders per seed.")] = 600,
    withholding: WithholdingOption = False,
    markdown: Annotated[
        bool, typer.Option("--markdown", help="Print the table as markdown, for the README.")
    ] = False,
) -> None:
    """Score many seeds and pool the counts.

    One seed is not a measurement for the smaller figures. Match rate and
    precision do not move between seeds; "shortfalls named" has a denominator
    of about six per run and swung from 17% to 83% across twenty of them.
    Nothing is stored - every dataset here is generated, scored and dropped,
    so this never competes with the single-seed run a reader reproduces.
    """
    result = sweep(difficulty, tuple(range(1, seeds + 1)), orders, withholding)
    if markdown:
        print(render.sweep_markdown(result))
        return
    console.print(render.sweep_table(result))


@app.command()
def reproduce(
    seed: SeedOption = 42,
    difficulty: DifficultyOption = Difficulty.REALISTIC,
    orders: Annotated[int, typer.Option("--orders")] = 100,
    span: SpanOption = 21,
    withholding: WithholdingOption = False,
) -> None:
    """Generate the same dataset twice and compare digests.

    Reproducibility is asserted everywhere in this project. This is the
    command that makes it falsifiable.
    """
    config = GenerationConfig(seed=seed, difficulty=difficulty, order_count=orders, span_days=span)
    first = store.content_hash(ChaosEngine(config).generate())
    second = store.content_hash(ChaosEngine(config).generate())

    console.print(f"run 1  [dim]{first}[/dim]")
    console.print(f"run 2  [dim]{second}[/dim]")
    if first != second:
        console.print("[red]Digests differ. The generator is not deterministic.[/red]")
        raise typer.Exit(code=1)
    console.print("[green]Identical.[/green]")


if __name__ == "__main__":
    app()
