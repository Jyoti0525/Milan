"""Deciding what each column is, and refusing to when nothing can.

The rule this module enforces, stated once so the branches below can be read
against it:

    **Ambiguity never resolves itself.** A field that two columns could be, or
    that only a model's guess supports, either stops the import or is dropped.
    It is never quietly assigned.

Which of those two depends entirely on whether the field is required. A
required field that cannot be settled blocks, because a settlement report
without a fee column is not a settlement report. An optional one is dropped
and its cost reported, because losing the card-type column costs a leak
attribution and losing the wrong guess costs a wrong balance.

Three things get a say, in this order:

  1. **The values.** A column whose contents do not parse as the field's kind
     is not a candidate, whoever nominated it. This is the only one of the
     three with a veto.
  2. **The header name.** An alias this schema already knows is confirmation,
     and it is the reason a normally-named export imports with no questions
     at all.
  3. **A model.** Consulted for the names nobody has met before. Its answer is
     a candidate like any other, and on a required field it is never enough
     on its own.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path

from milan.ingest.parsing import ISO, normalise, parse_temporal
from milan.ingest.plan import (
    ABSENT,
    DERIVE,
    Certainty,
    Choice,
    FieldResolution,
    FileMapping,
    IngestPlan,
    Question,
    QuestionKind,
    Rejection,
    SavedMapping,
    Unreadable,
)
from milan.ingest.profile import ColumnProfile, profile_column
from milan.ingest.propose import Proposal, SchemaProposer
from milan.ingest.reading import SourceFile, UnreadableFileError, discover, read_all
from milan.ingest.schema import RecordKind, TargetField, ValueKind, fields_of, required_of
from milan.llm.provider import Provider

CONFIDENT_KIND = 0.75
"""How many of a record kind's required fields must be recognisable by name
before the file is placed without asking. Three quarters, because a real
export is missing a column or two and a rule that demanded all of them would
send every file to the model."""

ACCEPTABLE_KIND = 0.5
"""The bar for placing a file on its header names when nothing beats it.

Half the required fields recognised, with the rest becoming questions. That
is enough for a file the names half-recognise, because the half they missed
is asked about rather than assumed.
"""


def _feasible(profiles: dict[str, ColumnProfile], kind: RecordKind) -> str:
    """Whether this file could be this record kind at all. Empty means yes.

    The question is not whether anything *did* map to each required field, but
    whether anything *could* - is there a column here, under any name, whose
    values read as that field's kind. It is a fact about the file, settled
    before any name or any model is consulted.

    This is the gate that keeps a register of GST invoices out. A model will
    map an id, an amount and a reference onto `payments` from almost any
    table, and three of the four required fields is enough to look convincing.
    What it cannot do is produce a captured-at date from a file that has no
    date column in it, and that absence is checkable without asking anybody.

    Returns the reason it is impossible rather than a bare `False`, because
    "nothing in this file reads as a date" is the single most useful sentence
    an import can say about a file it declined to use.
    """
    for target in required_of(kind):
        if not any(profile.fits(target.kind) for profile in profiles.values()):
            return f"no column in it reads as {target.kind.value}, which {kind.value} needs"
    return ""


DERIVABLE = frozenset({"debit", "credit"})
"""Fields that can be worked out from the others rather than mapped.

A settlement report that carries one signed amount instead of a debit and a
credit column is common, and rejecting it would be refusing a shape the
engine can handle perfectly well. Which of the two it is follows from the row
type, so this is arithmetic rather than a guess - but it is still offered as
an answer rather than assumed, because a report that *does* have both columns
and disagrees with its own signs is a thing worth finding out about.
"""


@dataclass(frozen=True, slots=True)
class Decisions:
    """Answers already given about one file, and where each came from."""

    kind: RecordKind | None = None
    ignored: bool = False
    """Whether the merchant has said this file is not to be used.

    Distinct from `kind is None`, which means nothing has been decided yet.
    This is a decision, and it has to outrank the placement rules - otherwise
    saying "that is not an order book" changes nothing, because the column
    names that placed the file are still there and still say the same thing.

    The case that made this necessary: a purchase ledger, four columns wide,
    which a model placed as an orders export because a PO number, a value and
    a raised-on date are exactly what an order book needs. Nothing about the
    file rules it out. Only the person who owns it knows.
    """

    columns: dict[str, str] = dataclass_field(default_factory=dict)
    patterns: dict[str, str] = dataclass_field(default_factory=dict)
    prior: dict[str, tuple[str, str]] = dataclass_field(default_factory=dict)
    """Field to the certainty and provider a previous import recorded for it.

    Only ever populated when replaying a saved mapping. Without it a replay
    reports every column as `answered` by a person - which is a different
    account of the same import, and the wrong one. The saved mapping is the
    record of *how each column was decided*, and re-reading it must not
    overwrite that with how it was re-read.

    The published count of columns a model contributed is computed from this
    field, so flattening it would report zero AI involvement on every import
    after the first.
    """

    def with_answer(self, subject: str, value: str, *, is_format: bool) -> Decisions:
        """A fresh answer from a person. It replaces whatever was recorded.

        Answering a field with a column that is already answering another one
        clears the other. One column cannot be two fields, and a person saying
        `paid_in` is the credit has just said it is not the debit - so the
        debit goes back to being a question rather than the two of them
        quietly sharing a column.

        This is the same rule `coherent` applies to a model's proposals, and
        it was missing here for a while. The guard only policed the model,
        which left the one path where somebody could break the invariant
        deliberately: accept a suggestion that put `paid_in` on the debit,
        then answer `paid_in` for the credit. Both stuck, every settlement row
        came out with its debit equal to its credit, and nothing said a word.
        """
        if is_format:
            return Decisions(
                self.kind,
                self.ignored,
                dict(self.columns),
                {**self.patterns, subject: value},
                dict(self.prior),
            )

        taken = value not in {ABSENT, DERIVE}
        columns = {
            field: chosen
            for field, chosen in self.columns.items()
            if field != subject and not (taken and chosen == value)
        }
        displaced = {field for field in self.columns if field not in columns and field != subject}
        remaining = {
            field: entry
            for field, entry in self.prior.items()
            if field != subject and field not in displaced
        }
        return Decisions(
            self.kind, self.ignored, {**columns, subject: value}, dict(self.patterns), remaining
        )

    def with_kind(self, kind: RecordKind) -> Decisions:
        return Decisions(kind, False, dict(self.columns), dict(self.patterns), dict(self.prior))

    def ignoring(self) -> Decisions:
        """This file is not to be read, whatever its columns suggest."""
        return Decisions(None, True, dict(self.columns), dict(self.patterns), dict(self.prior))


# ------------------------------------------------------------ record kinds


def _evidence(
    profiles: dict[str, ColumnProfile],
    kind: RecordKind,
    proposed: dict[str, str] | None = None,
) -> tuple[float, float]:
    """How well this record kind explains this file, and how much of it.

    Two numbers, and the second is the one that does the work. A settlement
    report and a payments file both carry an id, an amount and a date, so a
    settlement export satisfies every required field of `payments` and would
    be placed as one on required fields alone. What separates them is that
    `settlement_rows` also accounts for the fee, the tax, the payout id and
    fifteen other columns, and `payments` accounts for none of them - so the
    kind that explains the most of what is actually in the file wins, with the
    required fields as a gate rather than as the ranking.

    `proposed` folds a model's suggested mapping in beside the header aliases.
    Every column it names is still checked against the values before it counts
    for anything, which is what stops this from being a model marking its own
    work.
    """
    suggested = proposed or {}
    used: set[str] = set()
    required_hits = 0

    for target in fields_of(kind):
        names = [
            name
            for name, profile in profiles.items()
            if normalise(name) in target.aliases and profile.fits(target.kind)
        ]
        offered = suggested.get(target.name)
        if offered is not None and offered in profiles and profiles[offered].fits(target.kind):
            names.append(offered)
        if not names:
            continue
        used.update(names)
        if target.required:
            required_hits += 1

    return required_hits / (len(required_of(kind)) or 1), len(used) / (len(profiles) or 1)


Mapper = Callable[[RecordKind], dict[str, str]]


def _rank(
    profiles: dict[str, ColumnProfile], proposed: Mapper | None = None
) -> list[tuple[RecordKind, tuple[float, float]]]:
    """Every record kind this file could possibly be, best explanation first.

    Impossible kinds are dropped rather than scored low. A record type that
    cannot be filled from this file is not a weak candidate, it is not a
    candidate, and leaving it in the ranking to be beaten on points is how a
    file ends up placed as the least bad of four wrong answers.
    """
    scored = [
        (kind, _evidence(profiles, kind, proposed(kind) if proposed is not None else None))
        for kind in RecordKind
        if not _feasible(profiles, kind)
    ]
    scored.sort(key=lambda entry: (entry[1][1], entry[1][0]), reverse=True)
    return scored


DECISIVE = 1.5
"""How far ahead of the next best a record kind has to be to be placed on a
score under the confident bar.

A bank statement whose amount column is called `Deposit Amount(INR)` scores
two thirds rather than three quarters - and the next best record type scores
a third. Being twice as good an explanation as anything else is evidence,
even when it is not a perfect one, and a rule that ignored it would send a
file to a model that the names had already answered.
"""


def _identify(
    source: SourceFile,
    profiles: dict[str, ColumnProfile],
    proposer: SchemaProposer | None,
    propose: Mapper | None = None,
) -> tuple[RecordKind | None, str, bool]:
    """Place a file: by its names where they suffice, by a model where they do not.

    A cascade, like the matcher, and for the same reason - each rung is
    cheaper and more checkable than the one below it, and a model sits near
    the bottom rather than at the top.

    The last rung is the one worth reading twice. Asking a model "what is this
    file" and then checking its answer against the header aliases is circular:
    the aliases are exactly what just failed, so they can only ever say no.
    Asking it to map the columns instead gives a claim that the *values* can
    check - a file is a settlement report if the columns a model matched to
    fee, tax and payout id actually hold money and ids. That check is
    independent of the one that failed, which is the whole reason to run it.
    """
    ranked = _rank(profiles)
    if not ranked:
        return (
            None,
            "; ".join(sorted({_feasible(profiles, kind) for kind in RecordKind} - {""})),
            False,
        )

    best, (required, coverage) = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else (0.0, 0.0)
    ahead = (coverage, required) > (runner_up[1], runner_up[0])

    if required >= CONFIDENT_KIND and ahead:
        return (
            best,
            f"{int(required * 100)}% of the required column names recognised, "
            f"and {int(coverage * 100)}% of the file's columns accounted for",
            False,
        )

    if required >= ACCEPTABLE_KIND and ahead and required >= runner_up[0] * DECISIVE:
        return (
            best,
            f"the clearest fit by some way: {int(required * 100)}% of what "
            f"{best.value} needs is here, against {int(runner_up[0] * 100)}% "
            f"for the next best",
            False,
        )

    if proposer is None or propose is None:
        return _unplaced(best, required, "the column names match no record type well enough")

    mapped = _rank(profiles, propose)
    chosen, (filled, explained) = mapped[0]
    if filled >= ACCEPTABLE_KIND:
        return (
            chosen,
            f"{proposer.name} matched columns to {int(filled * 100)}% of what "
            f"{chosen.value} requires and the values agree, accounting for "
            f"{int(explained * 100)}% of the file",
            False,
        )

    return _unplaced(
        best,
        required,
        f"{proposer.name} could fill only {int(filled * 100)}% of what the "
        f"closest record type requires from this file",
    )


def _unplaced(best: RecordKind, required: float, why: str) -> tuple[RecordKind | None, str, bool]:
    """The last rung: take the best-scoring kind if it is good enough, else stop.

    Falling back to the header names rather than giving up matters. A model
    being wrong about a file is not a reason to discard what the column names
    already said about it.

    The third value marks the placement as weak, and it is what stops this
    rung from being worse than giving up. A file placed here is placed on half
    its required names and nothing else - see `_map` for what that costs it.
    """
    if required >= ACCEPTABLE_KIND:
        return best, f"{why}; placed as {best.value} on its column names alone", True
    return None, why, False


def _placeable(
    source: SourceFile, profiles: dict[str, ColumnProfile], *, ignored: bool = False
) -> tuple[Question, ...]:
    """Offer to be told what an unplaced file is, when it could be anything.

    The escape hatch, made visible. A merchant knows which of their exports is
    the settlement report even when its columns are named nothing we have met,
    and until this existed the only way to say so was a command-line flag -
    which left the browser showing "not used" beside a file and no way at all
    to disagree.

    Only kinds the file could actually supply are offered, so a register of
    GST invoices - which has no date column and therefore cannot be any of the
    four - is not asked about at all. Being left alone is the right outcome
    for that file, and a question about it would be noise.
    """
    possible = tuple(kind for kind, _ in _rank(profiles))
    if not possible:
        return ()
    return (
        Question(
            kind=QuestionKind.RECORD_KIND,
            file=source.name,
            subject="record",
            asks=(
                # Two different situations, and telling somebody we did not
                # recognise a file they have just told us to leave out reads
                # as a system that forgot.
                f"You left {source.name} out. Say what it is if you want it read."
                if ignored
                else (
                    f"{source.name} was not recognised. If you know what it is, "
                    f"say so - otherwise it is left alone."
                )
            ),
            choices=(
                *(
                    Choice(value=kind.value, label=f"{kind.value} - {kind.describes}")
                    for kind in possible
                ),
                Choice(value=ABSENT, label="do not use this file"),
            ),
            blocking=False,
        ),
    )


# ------------------------------------------------------------------ fields


def _choices(names: tuple[str, ...], target: TargetField) -> tuple[Choice, ...]:
    options = [Choice(value=name, label=name) for name in names]
    if target.name in DERIVABLE:
        options.append(
            Choice(value=DERIVE, label="derive it from the row type and the signed amount")
        )
    options.append(
        Choice(
            value=ABSENT,
            label="not in this file" + (f" ({target.costs})" if target.costs else ""),
        )
    )
    return tuple(options)


def _ask(
    target: TargetField,
    names: tuple[str, ...],
    asks: str,
    file: str,
    suggested: str = "",
) -> Question:
    return Question(
        kind=QuestionKind.COLUMN,
        file=file,
        subject=target.name,
        asks=asks,
        choices=_choices(names, target),
        suggested=suggested,
    )


def _forced(
    target: TargetField,
    chosen: str,
    profiles: dict[str, ColumnProfile],
    file: str,
    prior: tuple[str, str] | None = None,
) -> tuple[FieldResolution, Question | None]:
    """Apply a decision already made, keeping the account of who made it.

    `prior` carries the certainty and provider a saved mapping recorded. A
    replay that discarded it would relabel a model's suggestion as a person's
    answer - the one relabelling on this screen that could actually mislead
    somebody, since `answered` is the label that means a human looked.
    """
    recorded, by = prior if prior is not None else ("", "")

    def certainty(default: Certainty) -> tuple[Certainty, str]:
        if not recorded:
            return default, "answered"
        try:
            kept = Certainty(recorded)
        except ValueError:
            return default, "answered"
        return kept, f"carried forward from the saved mapping ({kept.value})"

    if chosen == ABSENT:
        return (
            FieldResolution(target=target, certainty=Certainty.ABSENT, reason="answered: absent"),
            None,
        )
    if chosen == DERIVE:
        kept, why = certainty(Certainty.ANSWERED)
        return (
            FieldResolution(
                target=target,
                certainty=kept,
                derived=True,
                proposed_by=by,
                reason=f"{why}: derive from the row type and the signed amount",
            ),
            None,
        )
    if chosen not in profiles:
        return (
            FieldResolution(
                target=target,
                certainty=Certainty.OPEN,
                candidates=tuple(profiles),
                reason=f"answered {chosen!r}, which is not a column in this file",
            ),
            _ask(target, tuple(profiles), f"{chosen!r} is not a column in {file}.", file),
        )
    kept, why = certainty(Certainty.ANSWERED)
    return (
        FieldResolution(
            target=target,
            certainty=kept,
            column=chosen,
            proposed_by=by,
            reason=why,
        ),
        None,
    )


def _resolve_field(
    target: TargetField,
    profiles: dict[str, ColumnProfile],
    proposed: str | None,
    proposer_name: str,
    file: str,
) -> tuple[FieldResolution, Question | None, Rejection | None]:
    candidates = tuple(name for name, profile in profiles.items() if profile.fits(target.kind))
    rejection: Rejection | None = None

    if proposed is not None and proposed not in candidates:
        rejection = Rejection(
            file=file,
            target=target.name,
            column=proposed,
            reason=(
                profiles[proposed].why_not(target.kind)
                if proposed in profiles
                else f"{proposed} is not a column in this file"
            ),
            proposed_by=proposer_name,
        )
        proposed = None

    named = tuple(name for name in candidates if normalise(name) in target.aliases)

    def settled(column: str, certainty: Certainty, reason: str) -> FieldResolution:
        return FieldResolution(
            target=target,
            certainty=certainty,
            column=column,
            candidates=candidates,
            reason=reason,
            proposed_by=proposer_name if column == proposed else "",
        )

    if len(named) == 1:
        column = named[0]
        if proposed is None or proposed == column:
            agreed = settled(column, Certainty.CONFIRMED, "the header name and the values agree")
            return agreed, None, rejection
        return (
            FieldResolution(
                target=target,
                certainty=Certainty.OPEN,
                candidates=candidates,
                reason=f"the header says {column}, {proposer_name} says {proposed}",
            ),
            _ask(
                target,
                (column, proposed),
                f"{file}: the column named {column!r} looks right, but "
                f"{proposer_name} thinks {proposed!r} is the one. They cannot "
                f"both be, and picking wrong changes the totals.",
                file,
                suggested=column,
            ),
            rejection,
        )

    if len(named) > 1:
        if not target.required and proposed in named:
            assert proposed is not None
            return (
                settled(
                    proposed,
                    Certainty.UNCONFIRMED,
                    f"{len(named)} columns could be this; {proposer_name} chose this one",
                ),
                None,
                rejection,
            )
        if not target.required:
            return (
                FieldResolution(
                    target=target,
                    certainty=Certainty.ABSENT,
                    candidates=candidates,
                    reason=f"{', '.join(named)} could all be this, and nothing chose between them",
                ),
                None,
                rejection,
            )
        return (
            FieldResolution(
                target=target,
                certainty=Certainty.OPEN,
                candidates=candidates,
                reason=f"{len(named)} columns are named like this field",
            ),
            _ask(
                target,
                named,
                f"{file}: {len(named)} columns could be it - "
                f"{', '.join(repr(name) for name in named)}. Their names are "
                f"equally good and their contents do not settle it.",
                file,
            ),
            rejection,
        )

    if proposed is not None:
        if len(candidates) == 1 and not target.required:
            # Corroboration, but only where being wrong is survivable. If a
            # model names the one column in the file whose values could be
            # this field, either it is that column or the field is absent -
            # and for an optional field, absent is a fine answer either way.
            # For a required one it is not: a statement whose true amount
            # column is missing altogether still has exactly one money column
            # in it, and that column is the balance.
            return (
                settled(
                    proposed,
                    Certainty.UNCONFIRMED,
                    f"{proposer_name} proposed it, and it is the only column in the file "
                    f"whose values read as {target.kind.value}",
                ),
                None,
                rejection,
            )
        if not target.required:
            return (
                settled(
                    proposed,
                    Certainty.UNCONFIRMED,
                    f"{proposer_name} proposed it and the values allow it; "
                    f"no header name confirms it",
                ),
                None,
                rejection,
            )
        return (
            FieldResolution(
                target=target,
                certainty=Certainty.OPEN,
                candidates=candidates,
                reason=f"{proposer_name} proposed {proposed}; nothing else confirms it",
            ),
            _ask(
                target,
                (proposed, *(name for name in candidates if name != proposed)),
                f"{file}: no column here is named anything we recognise for "
                f"this. {proposer_name} suggests {proposed!r}, and nothing in "
                f"that column contradicts it.",
                file,
                suggested=proposed,
            ),
            rejection,
        )

    if target.required:
        return (
            FieldResolution(
                target=target,
                certainty=Certainty.OPEN,
                candidates=candidates,
                reason="no header is named like this field and nothing proposed one",
            ),
            _ask(
                target,
                candidates,
                f"{file}: no column here is named anything we recognise for "
                f"this. It holds {target.describes}.",
                file,
            ),
            rejection,
        )

    return (
        FieldResolution(target=target, certainty=Certainty.ABSENT, reason="no column for it"),
        None,
        rejection,
    )


# ------------------------------------------------------------- date formats


def _label(pattern: str, example: str) -> str:
    read = parse_temporal(example, pattern)
    shown = read.date().isoformat() if read else "unreadable"
    name = "ISO 8601" if pattern == ISO else pattern
    return f"{name}  -  reads {example!r} as {shown}"


def _date_question(
    target: TargetField, profile: ColumnProfile, file: str, patterns: tuple[str, ...]
) -> Question:
    example = profile.conflict or (profile.samples[0] if profile.samples else "")
    return Question(
        kind=QuestionKind.DATE_FORMAT,
        file=file,
        subject=f"{target.name}.format",
        asks=(
            f"{file}: dates in {profile.name!r} are ambiguous. "
            f"{example!r} is a different day depending on which way round it "
            f"is read, and every payout would move with it."
        ),
        choices=tuple(
            Choice(value=pattern, label=_label(pattern, example)) for pattern in patterns
        ),
    )


def _settle_format(
    resolution: FieldResolution,
    profiles: dict[str, ColumnProfile],
    chosen: str | None,
    file: str,
) -> tuple[FieldResolution, Question | None]:
    """Pin a date format, or ask which of the readings the file meant."""
    target = resolution.target
    if target.kind is not ValueKind.TEMPORAL or resolution.column is None:
        return resolution, None
    profile = profiles[resolution.column]

    if chosen is not None and chosen in profile.temporal:
        return replace_pattern(resolution, chosen), None
    if not profile.ambiguous_dates:
        return replace_pattern(resolution, profile.temporal[0]), None
    return (
        FieldResolution(
            target=target,
            certainty=Certainty.OPEN,
            column=resolution.column,
            candidates=resolution.candidates,
            reason=f"{profile.conflict!r} reads as a different day under each surviving format",
            proposed_by=resolution.proposed_by,
        ),
        _date_question(target, profile, file, profile.temporal),
    )


def replace_pattern(resolution: FieldResolution, pattern: str) -> FieldResolution:
    return FieldResolution(
        target=resolution.target,
        certainty=resolution.certainty,
        column=resolution.column,
        pattern=pattern,
        candidates=resolution.candidates,
        reason=resolution.reason,
        proposed_by=resolution.proposed_by,
        derived=resolution.derived,
    )


# ----------------------------------------------------------------- the plan


class Importer:
    """Reads a folder once, and re-plans it as often as answers arrive.

    The sources and the model's proposals are cached on the instance because
    an interactive import calls `plan` after every answer, and neither
    re-reading a hundred thousand rows nor re-asking a model a question it has
    already answered would change anything.
    """

    def __init__(self, provider: Provider | None = None) -> None:
        self.proposer = SchemaProposer(provider) if provider is not None else None
        self._sources: tuple[SourceFile, ...] = ()
        self._unreadable: tuple[Unreadable, ...] = ()
        self._profiles: dict[str, dict[str, ColumnProfile]] = {}
        self._proposals: dict[str, Proposal] = {}
        self._loaded: Path | None = None

    @property
    def consulted(self) -> str:
        return self.proposer.name if self.proposer is not None else "none"

    @property
    def sources(self) -> tuple[SourceFile, ...]:
        """The files this importer has read. Empty until `load`."""
        return self._sources

    def load(self, root: Path) -> None:
        if self._loaded == root:
            return
        sources: list[SourceFile] = []
        unreadable: list[Unreadable] = []
        for path in discover(root):
            try:
                # Plural: one workbook is one path and several tables, and
                # importing only its first sheet would be the rare kind of bug
                # that leaves every downstream figure internally consistent
                # and describing less money than the merchant actually took.
                sources.extend(read_all(path))
            except UnreadableFileError as failure:
                unreadable.append(Unreadable(path=path, reason=str(failure)))
        self._sources = tuple(sources)
        self._unreadable = tuple(unreadable)
        self._profiles = {
            source.name: {
                header: profile_column(header, source.column(header)) for header in source.headers
            }
            for source in sources
        }
        self._proposals = {}
        self._loaded = root

    def plan(self, root: Path, decisions: dict[str, Decisions] | None = None) -> IngestPlan:
        self.load(root)
        given = decisions or {}
        mappings = tuple(
            self._map(source, given.get(source.name, Decisions())) for source in self._sources
        )
        return IngestPlan(
            root=root,
            files=mappings,
            unreadable=self._unreadable,
            consulted=self.consulted,
        )

    # ------------------------------------------------------------ internals

    def _required_proposal(self, source: SourceFile, kind: RecordKind) -> Proposal:
        """A mapping for this kind's required fields only.

        The question asked while deciding what a file is. Narrow on purpose:
        the required fields are both the smaller prompt and the half that
        settles placement, so paying for the optional two thirds of a schema
        on three record kinds that will be discarded is waste.
        """
        return self._cached(f"{source.name}:{kind.value}:required", source, kind, True)

    def _proposal(self, source: SourceFile, kind: RecordKind) -> Proposal:
        """The full mapping, asked in two halves and merged.

        The optional half is only ever asked for the kind a file was actually
        placed as, and it is told what the required half already claimed so
        that it does not offer the same column twice.
        """
        required = self._required_proposal(source, kind)
        if self.proposer is None:
            return required
        optional = self._cached(
            f"{source.name}:{kind.value}:optional", source, kind, False, required.columns
        )
        return required.merge(optional)

    def _cached(
        self,
        key: str,
        source: SourceFile,
        kind: RecordKind,
        required_only: bool,
        already: dict[str, str] | None = None,
    ) -> Proposal:
        if key not in self._proposals:
            self._proposals[key] = (
                self.proposer.map_columns(
                    source, kind, required_only=required_only, already=already
                )
                if self.proposer is not None
                else Proposal(kind=kind)
            )
        return self._proposals[key]

    def _map(self, source: SourceFile, decisions: Decisions) -> FileMapping:
        profiles = self._profiles[source.name]

        kind: RecordKind | None
        weak = False
        if decisions.ignored:
            # Said outright, so nothing here re-argues it. The column names
            # that placed this file have not changed and would place it again.
            return FileMapping(
                source=source,
                kind=None,
                kind_reason="you said this file is not one of yours to read",
                questions=_placeable(source, profiles, ignored=True),
            )
        if decisions.kind is not None:
            # A person saying what a file is settles it. Their answer is never
            # weak evidence, whatever the column names scored.
            kind, reason = decisions.kind, "chosen"
        else:
            kind, reason, weak = _identify(
                source,
                profiles,
                self.proposer,
                lambda candidate: self._required_proposal(source, candidate).columns,
            )
        if kind is None:
            return FileMapping(
                source=source,
                kind=None,
                kind_reason=reason,
                questions=_placeable(source, profiles),
            )

        proposal = self._proposal(source, kind)
        rejections: list[Rejection] = [
            Rejection(
                file=source.name,
                target=refused.target,
                column=refused.column,
                reason=refused.reason,
                proposed_by=proposal.source or self.consulted,
            )
            for refused in proposal.refused
        ]

        resolutions: list[FieldResolution] = []
        questions: list[Question] = []
        for target in fields_of(kind):
            forced = decisions.columns.get(target.name)
            if forced is not None:
                resolution, question = _forced(
                    target, forced, profiles, source.name, decisions.prior.get(target.name)
                )
                rejection = None
            else:
                resolution, question, rejection = _resolve_field(
                    target,
                    profiles,
                    proposal.columns.get(target.name),
                    proposal.source or self.consulted,
                    source.name,
                )
            if rejection is not None:
                rejections.append(rejection)
            if question is None and resolution.column is not None:
                resolution, question = _settle_format(
                    resolution, profiles, decisions.patterns.get(target.name), source.name
                )
            resolutions.append(resolution)
            if question is not None:
                questions.append(question)

        if weak and any(question.blocking for question in questions):
            # A file placed on half its names, which then cannot answer
            # something required, was not placed - it was guessed at, and the
            # question that follows is a question about our own guess rather
            # than about the merchant's data.
            #
            # The case that produced this rule: a hand-kept refund log, four
            # columns wide, scored two thirds against `orders` because it has
            # an amount and a date. It was placed, found no order id, and
            # stopped the entire import until somebody answered a question
            # about a file that was never an order book. Being left alone with
            # the reason printed is the right outcome, and `_placeable` still
            # offers to be told otherwise.
            unanswered = ", ".join(sorted({q.subject for q in questions if q.blocking}))
            return FileMapping(
                source=source,
                kind=None,
                kind_reason=(
                    f"the closest fit was {kind.value}, but nothing in this "
                    f"file answers {unanswered} - so it is left alone"
                ),
                questions=_placeable(source, profiles),
            )

        return FileMapping(
            source=source,
            kind=kind,
            kind_reason=reason,
            resolutions=tuple(resolutions),
            questions=tuple(questions),
            rejections=tuple(rejections),
        )


def decisions_from(saved: SavedMapping) -> dict[str, Decisions]:
    """Rebuild the answers a previous import arrived at.

    What makes a repeat import reproducible. A folder with a saved mapping
    beside it imports with no questions and no model, which is the difference
    between a demo that works and a demo that needs a daemon.
    """
    found: dict[str, Decisions] = {}
    for entry in saved.files:
        try:
            kind = RecordKind(entry.kind)
        except ValueError:
            continue
        columns = {
            column.field: (DERIVE if column.derived else column.column)
            for column in entry.columns
            if column.derived or column.column is not None
        }
        found[entry.file] = Decisions(
            kind=kind,
            columns={field: value for field, value in columns.items() if value is not None},
            patterns={column.field: column.pattern for column in entry.columns if column.pattern},
            prior={
                column.field: (column.certainty, column.proposed_by) for column in entry.columns
            },
        )
    return found
