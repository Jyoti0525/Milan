"""The command line.

One entry point for the whole engine. Every command takes a seed and a
difficulty tier, because every run in this project is reproducible and a
command that quietly used a different dataset than the last one would make
the numbers impossible to compare.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.cli import ingest_render, render
from milan.cli.render import console
from milan.domain.dataset import Dataset
from milan.domain.enums import EntityType
from milan.domain.rates import RateCard
from milan.evaluation.ablate import ablate
from milan.evaluation.control import compare
from milan.evaluation.curve import curve
from milan.evaluation.harness import evaluate, to_recon_input
from milan.evaluation.sweep import sweep
from milan.evaluation.twice import run_twice
from milan.ingest import archive, build
from milan.ingest.build import Imported
from milan.ingest.plan import IngestPlan, Question, to_saved
from milan.ingest.reading import UnreadableFileError
from milan.ingest.resolver import Decisions, Importer, decisions_from
from milan.ingest.schema import RecordKind
from milan.leaks.clusters import summarise
from milan.leaks.detector import detect
from milan.llm.provider import NullProvider
from milan.llm.registry import available, direct, resolve, status, unpinned
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
RouteOption = Annotated[
    float,
    typer.Option(
        "--route",
        min=0.0,
        max=1.0,
        help="Share of payments split to a linked account through Route.",
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
    route: RouteOption = 0.0,
    root: RootOption = None,
) -> None:
    """Generate a merchant's month, with the answer key."""
    config = GenerationConfig(
        seed=seed,
        difficulty=difficulty,
        order_count=orders,
        span_days=span,
        route_probability=route,
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


IMPORTED_TIER = "imported"
"""The tier name an imported run carries.

Not one of the generated difficulties, and deliberately not pretending to be.
A generated run's tier says which defects were injected on purpose; an
imported run has whatever defects the merchant's month actually had, and
there is no answer key to score it against.
"""

FORMAT_SUFFIX = ".format"

MAX_QUESTIONS = 200
"""A ceiling on the interactive loop.

Every answer is meant to close the question it answers, and each round
re-plans from scratch rather than patching the previous plan - which is the
right design and also the one where a resolver bug turns into a prompt that
never stops. This is the guard against that, not a limit anybody should hit.
"""


@app.command(name="import")
def import_command(
    source: Annotated[
        Path, typer.Option("--from", help="A folder of the merchant's own CSV files.")
    ],
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            help="Which model to ask about column names no alias covers. "
            "Defaults to whatever MILAN_LLM_PROVIDER says, and to none.",
        ),
    ] = None,
    answers: Annotated[
        list[str] | None,
        typer.Option(
            "--map",
            help='Answer one question without being asked: --map "bank.csv:amount=Deposit Amt".',
        ),
    ] = None,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive/--non-interactive",
            help="Ask about anything the columns and the values could not settle.",
        ),
    ] = True,
    yes: Annotated[
        bool, typer.Option("--yes", help="Skip the final confirmation of the mapping.")
    ] = False,
    reuse: Annotated[
        bool,
        typer.Option(
            "--reuse/--fresh",
            help="Start from the mapping a previous import of this folder settled on.",
        ),
    ] = True,
    root: RootOption = None,
) -> None:
    """Reconcile a folder of the merchant's own files, whatever shape they are in.

    Reads every CSV in the folder, works out what each column means, and stops
    to ask about anything it cannot settle from the header names and the
    values. Nothing is guessed: a column that two fields could be, or that
    only a model's suggestion supports, is either answered by a person or left
    out.
    """
    data_root = _root(root)
    slug = archive.slug_for(source)

    chosen = resolve(provider)
    model = None if isinstance(chosen, NullProvider) else chosen
    importer = Importer(model)

    decisions: dict[str, Decisions] = {}
    if reuse:
        saved = archive.load_mapping(data_root, slug)
        if saved is not None:
            decisions = decisions_from(saved)
            console.print(
                f"[dim]reusing the mapping settled on last time "
                f"({archive.directory(data_root, slug) / archive.MAPPING_FILE})[/dim]"
            )
    try:
        decisions = _apply_answers(decisions, answers or [])
        plan = importer.plan(source, decisions)
    except (UnreadableFileError, ValueError) as failure:
        console.print(f"[red]{failure}[/red]")
        raise typer.Exit(code=1) from failure

    plan = _answer_interactively(importer, source, plan, decisions, interactive)
    ingest_render.show_plan(plan)

    if not plan.ready:
        ingest_render.show_blocked(plan)
        raise typer.Exit(code=2)

    if (
        not yes
        and _at_a_keyboard()
        and interactive
        and not typer.confirm("\nRun the reconciliation on this mapping?", default=True)
    ):
        console.print("[dim]nothing was run and nothing was written.[/dim]")
        raise typer.Exit(code=1)

    imported = build.build(plan)
    report = ReconciliationPipeline().run(
        imported.data, RunMetadata(seed=0, difficulty=IMPORTED_TIER)
    )
    record = _import_record(slug, source, plan, imported)
    written = archive.save(
        data_root,
        slug,
        record=record,
        mapping=to_saved(plan),
        data=imported.data,
        report=report,
    )

    console.print()
    ingest_render.result_summary(record, report)
    if imported.dropped:
        console.print()
        console.print(ingest_render.dropped_table(imported.dropped))
    console.print()
    render.report_summary(report)
    console.print(f"\n[dim]{written}[/dim]")


def _at_a_keyboard() -> bool:
    """Whether anybody is there to answer. A pipe is not a person."""
    return sys.stdin.isatty()


def _apply_answers(decisions: dict[str, Decisions], answers: list[str]) -> dict[str, Decisions]:
    """Read `--map file.csv:field=Column` into decisions.

    `record` is accepted in place of a field name, to place a file the column
    names could not. That is the escape hatch for a folder we read as
    unusable: the merchant knows which file is their settlement report, and
    they should be able to say so without renaming anything.
    """
    found = dict(decisions)
    for raw in answers:
        key, separator, value = raw.partition("=")
        if not separator:
            raise ValueError(f'--map needs "file:field=value", got {raw!r}')
        file, colon, subject = key.partition(":")
        if not colon:
            raise ValueError(f'--map needs "file:field=value", got {raw!r}')
        found[file] = _record_answer(found.get(file, Decisions()), subject.strip(), value.strip())
    return found


def _record_answer(current: Decisions, subject: str, value: str) -> Decisions:
    if subject == "record":
        try:
            return current.with_kind(RecordKind(value))
        except ValueError as failure:
            named = ", ".join(kind.value for kind in RecordKind)
            raise ValueError(f"{value!r} is not a record type. Try one of: {named}") from failure
    if subject.endswith(FORMAT_SUFFIX):
        return current.with_answer(subject[: -len(FORMAT_SUFFIX)], value, is_format=True)
    return current.with_answer(subject, value, is_format=False)


def _answer_interactively(
    importer: Importer,
    source: Path,
    plan: IngestPlan,
    decisions: dict[str, Decisions],
    interactive: bool,
) -> IngestPlan:
    """Ask about each open question in turn, re-planning after every answer."""
    if not interactive or not _at_a_keyboard():
        return plan

    asked = 0
    while plan.questions and asked < MAX_QUESTIONS:
        question = plan.questions[0]
        ingest_render.show_question(question, asked + 1, len(plan.questions))
        chosen = _read_choice(question)
        decisions[question.file] = _record_answer(
            decisions.get(question.file, Decisions()), question.subject, chosen
        )
        plan = importer.plan(source, decisions)
        asked += 1
    return plan


def _read_choice(question: Question) -> str:
    """Take an answer by number, and keep asking until it is one of the offered ones."""
    while True:
        raw = typer.prompt("  Which one", default="1")
        try:
            index = int(raw)
        except ValueError:
            console.print("  [red]Answer with the number beside the option.[/red]")
            continue
        if 1 <= index <= len(question.choices):
            return question.choices[index - 1].value
        console.print(f"  [red]Pick a number between 1 and {len(question.choices)}.[/red]")


def _import_record(
    slug: str, source: Path, plan: IngestPlan, imported: Imported
) -> archive.ImportRecord:
    proposed = sum(
        1 for mapping in plan.placed for resolution in mapping.resolutions if resolution.proposed_by
    )
    return archive.ImportRecord(
        slug=slug,
        source_root=str(source.resolve()),
        consulted=plan.consulted,
        files=tuple(mapping.name for mapping in plan.placed),
        counts=imported.counts,
        dropped=len(imported.dropped),
        withdrawals=imported.withdrawals,
        limitations=plan.limitations(),
        rejections=tuple(
            f"{rejection.file}:{rejection.target} <- {rejection.column} ({rejection.reason})"
            for rejection in plan.rejections
        ),
        columns_proposed=proposed,
    )


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


@app.command(name="control")
def control_command(
    difficulty: DifficultyOption = Difficulty.ADVERSARIAL,
    seeds: Annotated[int, typer.Option("--seeds", help="How many seeds to run.")] = 20,
    orders: Annotated[int, typer.Option("--orders", help="Orders per seed.")] = 600,
    markdown: Annotated[
        bool, typer.Option("--markdown", help="Print the table as markdown, for the README.")
    ] = False,
) -> None:
    """Settle whether this is a cascade or an agent, with a number.

    The build order says that until an adaptive matcher has been measured
    against the fixed one, this project calls itself a cascade and never an
    agent. This is that measurement: the same rungs, the same verifier, the
    same scorer, and the only difference is who decides what to try next.

    Read the cost rows first. The accuracy rows are where the two policies
    agree, and agreeing is the whole result - a policy that reaches identical
    answers by asking the rungs twice as many times has not earned the more
    impressive noun.
    """
    result = compare(difficulty, tuple(range(1, seeds + 1)), orders)
    if markdown:
        print(render.control_markdown(result))
        return
    console.print(render.control_table(result))
    if not result.accuracy_matches:
        console.print(
            "\n[yellow]The two policies do not agree.[/yellow] Every measure above is "
            "pooled over the same seeds, so a difference here is the control policy "
            "and nothing else."
        )


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


@app.command(name="providers")
def providers_command() -> None:
    """Say which models could answer right now, and what to do about the rest.

    An unset key and a stopped daemon both look exactly like a working setup
    until the first question comes back empty, and the reconciliation will not
    tell you - by design, since every figure it reports is computed before a
    provider is consulted. This is where that silence gets a voice.
    """
    console.print(render.provider_table(status()))


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
    max_tokens: Annotated[
        int,
        typer.Option(
            "--max-tokens",
            help="Answer budget. Reasoning models need a few hundred to finish thinking.",
        ),
    ] = 96,
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
    result = ablate(
        built, difficulty, tuple(range(1, seeds + 1)), orders, chosen, max_tokens=max_tokens
    )

    if result.asked and not result.answered:
        console.print(
            f"[yellow]{provider} answered none of {result.asked} questions.[/] "
            "The reconciliation is unaffected - every figure it reports is "
            "computed before a provider is consulted - but this ablation has "
            "measured an absent model rather than a poor one."
        )
    elif result.answered < result.asked:
        # A partial answer is the dangerous case, because it still prints a
        # rate. Groq's free tier is eight thousand tokens a minute, and the
        # first run of this against it answered ten of a hundred and ten and
        # reported 2.7% agreement - a measurement of the rate limit wearing
        # the model's name.
        missing = result.asked - result.answered
        console.print(
            f"[yellow]{missing} of {result.asked} questions went unanswered.[/] "
            "They are scored as disagreements, so the rate below is a floor "
            "rather than an estimate. A free tier that ran out of budget "
            "looks exactly like a model that declined."
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
