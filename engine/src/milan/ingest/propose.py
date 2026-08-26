"""Asking a model what a stranger's columns mean.

This is the AI in this project that a rule could not replace. Everything else
Milan reports about money is arithmetic, and deliberately so - but no amount
of arithmetic knows that `Particulars` and `Txn Remarks` and `Narration` are
the same field, or that a bank that writes `Deposit Amt` means the credit. A
list of aliases covers the banks somebody has already met. A model covers the
next one.

One question, asked once per file per candidate record type: **which column
is which field?** Each ask carries one record kind's fields and nothing else,
because a three-billion-parameter model handed all four schemas at once maps
them into each other.

There is deliberately no second question asking what kind of file it is. That
version existed and was removed: the answer could only be checked against the
header aliases, which are exactly what had already failed to place the file,
so the check could say no and never yes. Ranking the record kinds by how much
of a file each one's proposed mapping can actually fill answers the same
question with evidence the values can verify.

Every answer is a claim about a name, and every claim is checked twice before
it can affect a rupee: the header has to actually exist in the file, and the
values under it have to parse as the field's kind. What survives both is a
suggestion, not a decision. The resolver still refuses to apply it unless a
person looks, or the header name independently agrees.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field

from milan.ingest.parsing import normalise
from milan.ingest.reading import SourceFile
from milan.ingest.schema import RecordKind, TargetField, fields_of
from milan.llm.provider import Provider, Request

SAMPLE_VALUES = 3
MAX_HEADERS = 40
"""Files wider than this are truncated in the prompt. A settlement export has
about twenty columns; anything past forty is a spreadsheet with a report
pasted into it, and the tail is not where the money lives."""


@dataclass(frozen=True, slots=True)
class Refused:
    """A column a model named that never became a candidate."""

    target: str
    column: str
    reason: str


@dataclass(frozen=True, slots=True)
class Proposal:
    """What a model suggested, before anything checked it."""

    kind: RecordKind | None = None
    columns: dict[str, str] = dataclass_field(default_factory=dict)
    refused: tuple[Refused, ...] = ()
    """Suggestions thrown out before the values were ever consulted: a column
    the file does not have, or one column offered for two different fields.

    Recorded rather than dropped, for the same reason `triage` records an
    invented refund id - a guard whose catches are never counted reports
    itself as never needed.
    """

    source: str = ""

    def merge(self, other: Proposal) -> Proposal:
        """Fold a second ask into the first, and check again for collisions.

        The required fields and the optional ones are asked separately, so a
        column can be claimed once in each half without either half noticing.
        Re-checking after the merge is the only place that catches it.
        """
        columns, clashes = coherent({**self.columns, **other.columns})
        return Proposal(
            kind=self.kind or other.kind,
            columns=columns,
            refused=(*self.refused, *other.refused, *clashes),
            source=self.source or other.source,
        )


def coherent(columns: dict[str, str]) -> tuple[dict[str, str], tuple[Refused, ...]]:
    """Drop every column a mapping claims for more than one field.

    One column cannot be two fields. A model that offers `igst_rate` as the
    credit, the debit and the tax has not produced a mapping with three
    mistakes in it - it has produced something that is not a mapping, and the
    right response is to keep none of the three rather than pick one.

    This is the check that stops a GST invoice register from being read as a
    settlement report. Without it, a single numeric column answering for four
    money fields at once was enough to clear the placement bar.
    """
    claimed: dict[str, list[str]] = {}
    for target, column in columns.items():
        claimed.setdefault(column, []).append(target)

    kept: dict[str, str] = {}
    clashes: list[Refused] = []
    for column, targets in claimed.items():
        if len(targets) == 1:
            kept[targets[0]] = column
            continue
        ordered = sorted(targets)
        named = (
            " and ".join((", ".join(ordered[:-1]), ordered[-1]))
            if len(ordered) > 2
            else (" and ".join(ordered))
        )
        clashes.extend(
            Refused(
                target=target,
                column=column,
                reason=f"offered as both {named}, and one column cannot be two fields",
            )
            for target in ordered
        )
    return kept, tuple(clashes)


MAP_SYSTEM = (
    "You map the columns of an unfamiliar CSV onto a fixed schema used by a "
    "settlement reconciliation engine for an Indian payment gateway. "
    "You reply with a JSON object whose KEYS are field names from the schema "
    "and whose VALUES are column headers copied exactly from the file. "
    "Never the other way round. "
    "You never invent a column name. "
    "You omit any field you are not sure about - omitting a field is safe, and "
    "a wrong column produces a wrong balance. "
    "You answer with one JSON object and nothing else."
)

_MAP = """File name: {name}
This file is {describes}.

Its columns, with example values:
{headers}
{taken}
Map them onto these {half} fields. Use the exact column header text.
{fields}

Omit any field this file does not have. Use each column at most once.
Do not invent column names.

Reply with one JSON object and nothing else. Each key is a field name from
the list above; each value is a column header from the file:
{{"columns": {example}}}"""


def _headers_block(source: SourceFile) -> str:
    lines: list[str] = []
    for header in source.headers[:MAX_HEADERS]:
        values = [value for value in source.column(header) if value][:SAMPLE_VALUES]
        shown = ", ".join(values) if values else "(always empty)"
        lines.append(f"  {header}  ->  {shown}")
    return "\n".join(lines)


def map_prompt(
    source: SourceFile,
    kind: RecordKind,
    *,
    required_only: bool,
    already: dict[str, str] | None = None,
) -> str:
    """The question, narrowed to one half of the schema.

    Asked in two halves because a settlement report has twenty-two fields, and
    a three-billion-parameter model handed all of them at once returns a
    mapping that is mostly plausible-looking noise. The required half is nine
    fields, which is a question a small model can answer - and it is the half
    that decides whether the file can be used at all.
    """
    wanted = [target for target in fields_of(kind) if target.required is required_only]
    settled = already or {}
    taken = (
        "\nAlready decided. Do not offer these columns again:\n"
        + "\n".join(f"  {field} = {column}" for field, column in sorted(settled.items()))
        if settled
        else ""
    )
    return _MAP.format(
        name=source.name,
        describes=kind.describes,
        half="required" if required_only else "optional",
        headers=_headers_block(source),
        fields="\n".join(f"  {target.name}  - {target.describes}" for target in wanted),
        taken=taken,
        example=_example(wanted),
    )


def _example(wanted: list[TargetField]) -> str:
    """The reply template, written with this file's real field names in it.

    A placeholder like `{"<field>": "<column header>"}` is not enough. Handed
    that, a small model reliably returns the file's own headers as both the
    keys and the values - a mapping of every column onto itself, which parses
    as JSON, contains no invented names, and means nothing. Naming two real
    fields in the example fixes the direction, and it was the single change
    that took the local model from mapping nothing to mapping everything.
    """
    named = [target.name for target in wanted[:2]] or ["field"]
    body = ", ".join(f'"{name}": "<a column header>"' for name in named)
    return "{" + body + ", ...}"


_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _payload(text: str) -> dict[str, object] | None:
    """The first JSON object in a reply, or nothing.

    Greedy on purpose, unlike the one in `llm.triage`: this reply contains a
    nested object, and a non-greedy match would stop at the inner closing
    brace and return half the mapping.
    """
    found = _OBJECT.search(text or "")
    if found is None:
        return None
    try:
        parsed = json.loads(found.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_mapping(
    text: str, source: SourceFile, kind: RecordKind, wanted: frozenset[str] | None = None
) -> Proposal:
    """Read a proposed mapping, keeping only names that exist in both schemas.

    A header is matched exactly first and then by its normalised form, because
    models reliably reply with `Value Date` when the file says `Value  Date`
    and rejecting that would be pedantry. Anything that still does not resolve
    to a real column is recorded as invented, never applied.
    """
    payload = _payload(text)
    if payload is None:
        return Proposal(kind=kind)

    proposed = payload.get("columns")
    if not isinstance(proposed, dict):
        return Proposal(kind=kind)

    by_name = {header: header for header in source.headers}
    by_normal = {normalise(header): header for header in source.headers}
    known = wanted if wanted is not None else frozenset(t.name for t in fields_of(kind))
    """Only the half that was asked about.

    Without this, a reply to the required half is checked against every field
    of the record, so a suggestion for an optional field is read out of a
    prompt that never mentioned it - and a bad one is then recorded twice,
    once by each half. The count of refused proposals is a published number;
    counting the same refusal twice would overstate the guard."""

    columns: dict[str, str] = {}
    refused: list[Refused] = []
    for raw_field, raw_column in proposed.items():
        target = str(raw_field).strip()
        if target not in known or not isinstance(raw_column, str) or not raw_column.strip():
            continue
        named = raw_column.strip()
        resolved = by_name.get(named) or by_normal.get(normalise(named))
        if resolved is None:
            refused.append(
                Refused(
                    target=target,
                    column=named,
                    reason="no column by that name is in this file",
                )
            )
            continue
        columns[target] = resolved

    kept, clashes = coherent(columns)
    return Proposal(kind=kind, columns=kept, refused=(*refused, *clashes))


class SchemaProposer:
    """One provider, asked about schema and never about money."""

    def __init__(self, provider: Provider, max_tokens: int = 768) -> None:
        self._provider = provider
        self._max_tokens = max_tokens

        self.asked = 0
        self.answered = 0
        self.replayed = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.seconds = 0.0

    @property
    def name(self) -> str:
        return self._provider.name

    def _ask(self, prompt: str, system: str, max_tokens: int) -> str:
        self.asked += 1
        completion = self._provider.complete(
            Request(prompt=prompt, system=system, max_tokens=max_tokens, temperature=0.0)
        )
        self.prompt_tokens += completion.prompt_tokens
        self.completion_tokens += completion.completion_tokens
        self.seconds += completion.latency_seconds
        if completion.cached:
            self.replayed += 1
        if not completion.answered:
            return ""
        self.answered += 1
        return completion.text

    def map_columns(
        self,
        source: SourceFile,
        kind: RecordKind,
        *,
        required_only: bool = False,
        already: dict[str, str] | None = None,
    ) -> Proposal:
        prompt = map_prompt(source, kind, required_only=required_only, already=already)
        text = self._ask(prompt, MAP_SYSTEM, self._max_tokens)
        if not text:
            return Proposal(kind=kind, source=self.name)
        wanted = frozenset(
            target.name for target in fields_of(kind) if target.required is required_only
        )
        return replace(parse_mapping(text, source, kind, wanted), source=self.name)
