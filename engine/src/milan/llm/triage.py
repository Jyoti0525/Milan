"""Asking a model to name the cause of a shortfall, and not believing it.

The rule that governs this module: **a model may propose, only arithmetic may
conclude.** A model that writes "this looks like a refund" straight into a
summary is fabricating a finding, and refusing to fabricate findings is the
one claim this project actually makes. So nothing here returns prose. It
returns a `Hypothesis` - a typed claim naming a kind and an entity that must
already exist - and the caller hands that to the same arithmetic the
rule-based categoriser uses. A hypothesis that does not foot to the paisa is
discarded, never printed.

That constraint is what makes the model's contribution measurable rather than
asserted. Two numbers fall out of it:

- **agreement**, on shortfalls the rules already named: does the model reach
  the same cause? This says whether it is competent at the task at all.
- **contribution**, on shortfalls the rules could not name: does it propose
  anything that survives verification? This says whether it adds anything.

Both are reported by `milan ablate`. As of this writing the second one has
nothing to work on, because the deterministic checks now name every shortfall
the engine reaches - but "the rules already win" is a claim that has to be
measured against a model actually running, not inferred from its absence.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from milan.domain.enums import EntityType
from milan.domain.money import Paise, format_inr
from milan.domain.records import SettlementRow
from milan.domain.results import UnprovenCredit
from milan.llm.provider import Provider, Request
from milan.recon.batches import BatchGroup

MAX_CANDIDATES = 12
"""How many refund rows are offered to the model.

The nearest few by size, not the whole report. A month of settlement rows
does not fit in a 3B model's usable context, and a list long enough to bury
the right answer measures the context window rather than the model.
"""


class HypothesisKind(StrEnum):
    """The only claims a model is allowed to make.

    A closed vocabulary rather than free text, because every one of these has
    a verifier behind it. A model that could invent a category could produce
    an unfalsifiable one.
    """

    RECOVERY_GAP = "recovery_gap"
    """A refund netted out of some other batch."""

    TAX_VARIANCE = "tax_variance"
    """GST applied at a slab other than the statutory one."""

    FEE_VARIANCE = "fee_variance"
    """A deduction taken at payout that the report does not show."""

    UNKNOWN = "unknown"
    """The model declining. A first-class answer, and the right one more often
    than not - a model that always names something is not more useful than one
    that admits it cannot, it is just harder to catch being wrong."""


class Hypothesis(BaseModel):
    """A checkable claim about why a credit fell short.

    Carries no amount. An amount from a model is an amount nobody computed,
    and every figure this system prints has to trace back to a row.
    """

    model_config = ConfigDict(frozen=True)

    kind: HypothesisKind
    entity_id: str | None = None
    """The refund or adjustment being blamed. Required for a recovery gap and
    meaningless for the others."""

    source: str = "llm"
    """Which provider proposed this, for the categorised-by count. The whole
    "we used AI here and not there" claim is this field, aggregated."""

    invented_id: str | None = None
    """An identifier the model named that is not in the report.

    Recorded rather than merely discarded. Downgrading a hallucinated id to
    `unknown` and returning nothing else made the ablation's "identifiers
    invented" column structurally incapable of being anything but zero - the
    measurement was reporting the guard rather than the model."""


SYSTEM = (
    "You are a settlement reconciliation assistant for an Indian payment gateway. "
    "You classify why a bank credit is smaller than the settlement rows behind it. "
    "You never compute amounts and you never invent identifiers. "
    "You answer with one JSON object and nothing else."
)

_TEMPLATE = """A bank credit was matched to settlement(s) {settlements} but is short by \
{shortfall}.

The settlement rows total:
  gross            {gross}
  fee charged      {fee}
  GST on the fee   {tax}

Refunds and adjustments recorded elsewhere in this report, nearest in size to \
the shortfall:
{candidates}

Which of these explains the shortfall?
  "recovery_gap"  - one of the refunds above was taken out of a different \
batch than the report shows. Give its id.
  "tax_variance"  - GST was applied at a slab other than 18%.
  "fee_variance"  - an extra percentage fee was taken at payout.
  "unknown"       - the evidence does not say. This is a good answer when true.

Reply with exactly this JSON and nothing else:
{{"kind": "<one of the four>", "entity_id": "<refund id, or null>"}}"""


def _candidate_rows(
    shortfall: Paise, group: BatchGroup, all_rows: tuple[SettlementRow, ...]
) -> tuple[SettlementRow, ...]:
    """Refunds from other batches, nearest in size to the shortfall first."""
    elsewhere = [
        row
        for row in all_rows
        if row.type in (EntityType.REFUND, EntityType.ADJUSTMENT)
        and row.debit
        and row.settlement_id not in group.settlement_set
    ]
    elsewhere.sort(key=lambda row: abs(row.debit - shortfall))
    return tuple(elsewhere[:MAX_CANDIDATES])


def build_prompt(
    unproven: UnprovenCredit, group: BatchGroup, all_rows: tuple[SettlementRow, ...]
) -> str:
    """The question, with every number already computed.

    The model is shown arithmetic rather than asked for it. It picks between
    named possibilities; it does not add anything up, which is the only way
    its answer can be checked without also checking its sums.
    """
    shortfall = Paise(abs(unproven.residual))
    candidates = _candidate_rows(shortfall, group, all_rows)
    listed = (
        "\n".join(
            f"  {row.entity_id}  {format_inr(row.debit)}  ({row.type.value})" for row in candidates
        )
        or "  (none)"
    )
    return _TEMPLATE.format(
        settlements=", ".join(unproven.settlement_ids) or "(none)",
        shortfall=format_inr(shortfall),
        gross=format_inr(group.gross),
        fee=format_inr(group.fee),
        tax=format_inr(group.tax),
        candidates=listed,
    )


_OBJECT = re.compile(r"\{.*?\}", re.DOTALL)


def parse(text: str, known_ids: frozenset[str]) -> Hypothesis:
    """Read the model's reply, and refuse anything that is not in the schema.

    Small models wrap JSON in prose and in code fences no matter how the
    instruction is worded, so the first object in the text is taken rather
    than the whole string parsed. Everything after that is rejection: an
    unrecognised kind, or an id that is not in the report, becomes `UNKNOWN`.

    An invented identifier is the specific failure this guards. A model that
    hallucinates `rfnd_abc123` would otherwise send somebody looking through
    their ledger for a refund that has never existed.
    """
    found = _OBJECT.search(text or "")
    if found is None:
        return Hypothesis(kind=HypothesisKind.UNKNOWN)
    try:
        payload = json.loads(found.group(0))
    except json.JSONDecodeError:
        return Hypothesis(kind=HypothesisKind.UNKNOWN)
    if not isinstance(payload, dict):
        return Hypothesis(kind=HypothesisKind.UNKNOWN)

    raw = str(payload.get("kind", "")).strip().lower()
    try:
        kind = HypothesisKind(raw)
    except ValueError:
        return Hypothesis(kind=HypothesisKind.UNKNOWN)

    entity = payload.get("entity_id")
    entity_id = str(entity).strip() if isinstance(entity, str) and entity.strip() else None
    if kind is HypothesisKind.RECOVERY_GAP and entity_id not in known_ids:
        # Naming a refund that is not in the report is worse than naming
        # nothing, so the claim is downgraded - but what it named is kept, or
        # the one failure mode most worth counting would never be counted.
        return Hypothesis(kind=HypothesisKind.UNKNOWN, invented_id=entity_id)
    return Hypothesis(kind=kind, entity_id=entity_id)


class LlmTriage:
    """One question per unexplained shortfall, and a typed answer back."""

    def __init__(self, provider: Provider, max_tokens: int = 96, temperature: float = 0.0) -> None:
        self._provider = provider
        self._max_tokens = max_tokens
        self._temperature = temperature
        """Zero everywhere the numbers come from, and settable for one
        experiment: asking the same question twice with sampling on, to show
        what a model-driven matcher would do to a set of books."""

        self.asked = 0
        self.answered = 0

        # What it cost to ask, in the only units a bill is written in.
        # Accumulated here rather than in the ablation because this is the
        # only place that touches a provider, and a token counted anywhere
        # else would be a token counted twice.
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.replayed = 0
        """Answers that came from the cache. The difference between a run
        that spent a GPU and a run that spent nothing."""

        self.seconds = 0.0

    def propose(
        self, unproven: UnprovenCredit, group: BatchGroup, all_rows: tuple[SettlementRow, ...]
    ) -> Hypothesis:
        shortfall = Paise(abs(unproven.residual))
        candidates = _candidate_rows(shortfall, group, all_rows)
        known = frozenset(row.entity_id for row in candidates)

        self.asked += 1
        completion = self._provider.complete(
            Request(
                prompt=build_prompt(unproven, group, all_rows),
                system=SYSTEM,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
            )
        )
        self.prompt_tokens += completion.prompt_tokens
        self.completion_tokens += completion.completion_tokens
        self.seconds += completion.latency_seconds
        if completion.cached:
            self.replayed += 1

        if not completion.answered:
            return Hypothesis(kind=HypothesisKind.UNKNOWN, source=self._provider.name)
        self.answered += 1
        return parse(completion.text, known).model_copy(update={"source": self._provider.name})
