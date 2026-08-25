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
from milan.domain.enums import EntityType
from milan.domain.rates import RateCard
from milan.evaluation.ablate import ablate
from milan.evaluation.curve import curve
from milan.evaluation.harness import evaluate, to_recon_input
from milan.evaluation.sweep import sweep
from milan.evaluation.twice import run_twice
from milan.leaks.clusters import summarise
from milan.leaks.detector import detect
from milan.llm.registry import available, direct, resolve, unpinned
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


@app.command(name="curve")
def curve_command(
    seeds: Annotated[int, typer.Option("--seeds", help="How many seeds per tier.")] = 20,
    orders: Annotated[int, typer.Option("--orders", help="Orders per seed.")] = 600,
    withholding: WithholdingOption = False,
    markdown: Annotated[
        bool, typer.Option("--markdown", help="Print the table as markdown, for the README.")
    ] = False,
) -> None:
    """Score every tier over the same seeds, and put them side by side.

    Every headline figure this project publishes comes from the adversarial
    tier. That is the right choice for a single number and it says nothing
    about the shape of the curve, which is the question a reader actually has:
    does this hold up as the data gets worse, or was the hard tier never hard?

    The answer is in the denominators. The clean tier generates no impossible
    credits, no merged payouts and no mispriced rows, so three of these
    measures have nothing to score there at all; the adversarial tier
    generates all of them. Two rates of 100% are not the same measurement, and
    the counts beside them are what shows it.
    """
    result = curve(tuple(range(1, seeds + 1)), orders, withholding)
    if markdown:
        print(render.curve_markdown(result))
        return
    console.print(render.curve_table(result))


@app.command()
def leaks(
    seed: SeedOption = 42,
    difficulty: DifficultyOption = Difficulty.ADVERSARIAL,
    data_root: RootOption = None,
) -> None:
    """Find money that is wrong while the books balance.

    Every other command in this tool asks whether a payout arrived. This one
    asks whether it should have been that size, and it is the only question
    here that still has an answer when the reconciliation is perfectly clean:
    a card contracted at 2% charged at 2.15% leaves a settlement report that
    foots, a batch that balances, and a bank credit that proves to the paisa.

    Nothing is unmatched, so no matcher can see it. It is found by reading a
    row against the contract instead of against another row.
    """
    dataset = _load(data_root, seed, difficulty)
    payments = [row for row in dataset.settlement_rows if row.type is EntityType.PAYMENT]
    report = summarise(detect(tuple(dataset.settlement_rows), RateCard()), len(payments))
    console.print(render.leak_report(report))


@app.command(name="ablate")
def ablate_command(
    provider: Annotated[
        str,
        typer.Option("--provider", help="Which model to put the questions to."),
    ] = "ollama",
    seeds: Annotated[int, typer.Option("--seeds", help="How many seeds to run.")] = 5,
    difficulty: DifficultyOption = Difficulty.ADVERSARIAL,
    orders: Annotated[int, typer.Option("--orders", help="Orders per seed.")] = 600,
    model: Annotated[
        str,
        typer.Option("--model", help="Override the provider's model, to compare two."),
    ] = "",
) -> None:
    """Measure what a model adds to the shortfall explanations.

    Two numbers, and they answer different questions. **Agreement** is scored
    on shortfalls the rules already named, so it says whether the model is
    competent at this task at all. **Contribution** is scored on the ones they
    could not name, and it is the only figure that could justify a model being
    in the pipeline.

    Nothing here can move a graded number. The reconciliation runs first and
    runs unchanged; the model is asked afterwards about the same shortfalls,
    and every answer it gives is put through the same arithmetic the rules
    use before it counts for anything.
    """
    if provider not in available():
        console.print(
            f"[red]No provider called {provider!r}.[/] Registered: {', '.join(available())}."
        )
        raise typer.Exit(code=2)

    built = resolve(provider)
    if model:
        # Named on the command line rather than through the environment, so
        # two models can be compared in two lines of shell history that say
        # which was which. The cache keys on the model, so the second run
        # does not replay the first one's answers.
        _name_model(built, model)
    chosen = model or getattr(built, "model", "")
    result = ablate(built, difficulty, tuple(range(1, seeds + 1)), orders, chosen)

    if result.asked and not result.answered:
        console.print(
            f"[yellow]{provider} answered none of {result.asked} questions.[/] "
            "The reconciliation is unaffected - every figure it reports is "
            "computed before a provider is consulted - but this ablation has "
            "measured an absent model rather than a poor one."
        )
    console.print(render.ablation_table(result))


@app.command(name="twice")
def twice_command(
    seeds: Annotated[int, typer.Option("--seeds", help="How many seeds to draw from.")] = 5,
    difficulty: DifficultyOption = Difficulty.ADVERSARIAL,
    orders: Annotated[int, typer.Option("--orders", help="Orders in the run.")] = 600,
    provider: Annotated[str, typer.Option("--provider", help="Which model to ask.")] = "ollama",
    temperature: Annotated[
        float, typer.Option("--temperature", help="Sampling. Zero is greedy decoding.")
    ] = 0.7,
    questions: Annotated[
        int, typer.Option("--questions", help="How many shortfalls to ask about. 0 for all.")
    ] = 12,
    pin: Annotated[
        bool,
        typer.Option(
            "--pin/--no-pin",
            help="Keep the sampler seed fixed, as every scored run does.",
        ),
    ] = True,
) -> None:
    """Ask a model the same questions twice, and see whether it agrees with itself.

    The other half of the reproducibility argument. `milan reproduce` shows
    that the same input produces the same books; this shows what happens when
    the answers come from a model instead, which is the design this project
    deliberately did not adopt.

    Run without the cache in front of it, on purpose. Everywhere else a cached
    answer is what makes a run with a model reproducible; here, replaying the
    first answer would prove the point by refusing to run the experiment.
    """
    if provider not in available():
        console.print(
            f"[red]No provider called {provider!r}.[/] Registered: {', '.join(available())}."
        )
        raise typer.Exit(code=2)

    built = direct(provider)
    if not pin:
        built = unpinned(built)
    result = run_twice(
        built,
        seeds=tuple(range(1, seeds + 1)),
        difficulty=difficulty,
        orders=orders,
        temperature=temperature,
        limit=questions,
        model=getattr(built, "model", ""),
    )
    if result.asked == 0:
        console.print("[yellow]No shortfalls in this run to ask about.[/yellow]")
        return

    console.print(render.twice_table(result))
    console.print()
    pinning = "with the sampler seed pinned" if pin else "with the seed left to the daemon"
    if result.stable:
        console.print(
            f"[green]Identical.[/green] At temperature {temperature:g} {pinning}, "
            "this model repeated itself on every question."
        )
    else:
        console.print(
            f"[yellow]{result.changed} of {result.asked} answers moved[/yellow] between "
            f"two passes over the same questions {pinning}, with no input changing. "
            f"{result.different_records} named a different record the second time.\n"
            "Milan's own output does not move: [dim]uv run milan reproduce[/dim]."
        )


def _name_model(provider: object, model: str) -> None:
    """Point a provider at a different model, through its cache if it has one."""
    target = getattr(provider, "inner", provider)
    if hasattr(target, "model"):
        target.model = model


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
