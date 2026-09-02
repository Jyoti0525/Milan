"""Reading a queue of exceptions as a handful of causes.

No model is involved and none is wanted. Every grouping below is decided by
an arithmetic test with a right answer - two payouts were short by the same
rate or they were not - and a model asked to cluster this would produce
groupings nobody can check, which is the failure mode this whole project is
built to avoid.

The rules run most-specific first and each exception joins at most one cause,
the same discipline the categoriser uses for the same reason: the loosest
rule will answer for anything if it is asked first, and a cluster named by a
loose rule is worse than no cluster at all because it looks like a finding.

Two rules govern all of them:

**Two members or it is not a pattern.** One exception is already stated by
itself; wrapping it in a cause adds a heading and no information, and it
would inflate the coverage figure with clusters of one.

**The test goes in the output.** `Cause.because` carries the invariant and
its numbers, so a reader can disprove the claim rather than take it.

**A shared value is not a shared cause unless sharing it is improbable.**
This rule was written after measuring, not before. Two earlier rules grouped
exceptions that fell on the same date - missing payouts, and captures the
report never mentioned - and both were wrong: with ten items scattered over a
twenty-one day month, two landing on one date is what randomness produces. So
grouping on a date now requires the whole day's population to be affected,
which the exception's own evidence records, and where that cannot be shown
the members are grouped by mechanism instead. A third rule grouped deposits
on the *absence* of evidence and was cut outright; measured against the
answer key it was the only rule whose members came from genuinely different
causes, and a heading over a list of unknowns is the thing this module exists
to replace.

The measurement that produced those three changes is in
`tests/integration/test_causes_are_one_cause.py`, and it runs on every suite.

This is a pure function of the exceptions it is handed. It deliberately does
not live on `ReconReport`: every input is already on the report, so a screen
that induces the causes again cannot disagree with the run that produced
them - which is not true of the merchant profile, and is why that one is
carried and this one is not.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from decimal import Decimal, InvalidOperation

from milan.domain.causes import Cause, Induction
from milan.domain.enums import ExceptionCode
from milan.domain.money import Paise, format_inr
from milan.domain.results import ReconException

PATTERN = 2
"""Members below which a cause is not a cause."""

RATE_TOLERANCE = Decimal("0.0002")
"""Two basis points. Two payouts short by 0.150% and 0.151% of their own
gross are one deduction rate and a rounding difference; 0.15% and 0.40% are
two different problems, and reporting them as one would send somebody to
argue a case the evidence does not support."""

_PERCENT = re.compile(r"^(\d+(?:\.\d+)?)%$")

_REFERENCE = re.compile(r"\b[A-Z0-9]{10,22}\b")
_NOISE = re.compile(r"\b(?:NEFT|RTGS|IMPS|UPI|ACH|NACH|ECS|CR|DR|TRF|FROM|REF|TO|BY)\b")
"""The rails, which are never the payer.

ACH, NACH and ECS joined this list after a measurement, not a review. They
are as much a rail name as NEFT is, and because they were missing they
survived into the stem and became the counterparty - producing the finding
"Repeated deposits from ACH", which names a clearing system as though it
were a business that pays this merchant.
"""

_GATEWAY = frozenset({"RAZORPAY", "RZPY", "SETTLEMENT", "SETTLEMENTS", "PAYOUT", "PAYOUTS"})
"""Words that say a deposit *is* a gateway payout.

A guard on the premise rather than on the output. `_one_counterparty_keeps_
paying` exists to say "this recurring money is not a gateway payout at all",
and a narration reading RAZORPAY SETTLEMENT has already answered that
question the other way. Firing anyway produced the exact sentence "confirm
whether RZPY is money from outside Razorpay", which is a cause asking
somebody to check something its own evidence states.
"""


# ------------------------------------------------------------------ helpers


def _rate(text: str | None) -> Decimal | None:
    """Read `0.150%` back as a number, or refuse.

    The categoriser writes rates for people and this reads them back, which
    is a seam that can silently rot: reword the format and every fee cluster
    quietly stops forming, with no error and a coverage figure that just
    drifts down. A test pins the two together for exactly that reason.
    """
    found = _PERCENT.match((text or "").strip())
    if found is None:
        return None
    try:
        return Decimal(found.group(1)) / 100
    except InvalidOperation:  # pragma: no cover - the regex already bounds it
        return None


def _stem(narration: str) -> str:
    """What a narration says once the reference and the rails are removed.

    Two deposits from the same counterparty share everything except the
    transaction reference. Stripping the reference, the network name and
    the connecting words leaves the payer, which is the thing that actually
    recurs - and a recurring payer is the difference between "six deposits
    we cannot explain" and "your logistics partner pays you every Tuesday".
    """
    text = _REFERENCE.sub(" ", narration.upper())
    text = _NOISE.sub(" ", text)
    words = [word for word in re.findall(r"[A-Z]{3,}", text)]
    return " ".join(words[:4])


def _settlements(item: ReconException) -> tuple[str, ...]:
    """The settlement ids an exception names in its own evidence.

    Every shortfall the categoriser produces records which settlements it
    was reconstructed against. Read back here rather than re-derived, so
    that the ids compared are the ids the run actually used.
    """
    written = item.evidence.get("settlements", "")
    return tuple(part.strip() for part in written.split(",") if part.strip())


def _total(group: Iterable[ReconException]) -> Paise:
    return Paise(sum(abs(item.amount) for item in group))


def _codes(group: Iterable[ReconException]) -> tuple[ExceptionCode, ...]:
    return tuple(dict.fromkeys(item.code for item in group))


def _members(group: Iterable[ReconException]) -> tuple[str, ...]:
    return tuple(item.subject_id for item in group)


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


# -------------------------------------------------------------------- rules
#
# Each takes the exceptions still unclaimed and yields causes. Order is
# load-bearing: the earlier a rule sits, the more specific its test.


def _the_same_money_counted_twice(queue: list[ReconException]) -> Iterator[Cause]:
    """A payout reported missing that a deposit in this queue already names.

    The sharpest test in the module, and the only one that needs no
    tolerance at all: the shortfall exception carries the settlement id in
    its own evidence, and the missing-payout exception *is* that id. There
    is no judgement involved in noticing they are the same event.

    They are both raised on purpose. The cascade withdrew the credit's claim
    because the arithmetic would not close, so the engine has not concluded
    that this deposit paid that payout - and a settlement nothing has
    concluded a credit for is unmatched, which is what the second exception
    says. Both sentences are individually true.

    Together they are misleading, and the queue's own total is the proof:
    the money appears once as a payout that never arrived and again as a
    deposit that arrived short, so a merchant reading the headline sees
    roughly twice the exposure they have. Measured over thirty-six months,
    fifty of every eighty payouts reported missing were this - the credit
    was in the same queue, matched to the right settlement, and merely
    unprovable.

    Reported here rather than fixed in the pipeline on purpose. Suppressing
    the second exception would mean the engine asserting a match its own
    prover declined to assert, which is the trade this project does not
    make. Naming the duplication costs nothing and asserts nothing.
    """
    named: dict[str, ReconException] = {}
    for item in queue:
        for settlement_id in _settlements(item):
            named.setdefault(settlement_id, item)

    group = [
        item
        for item in queue
        if item.code is ExceptionCode.MISSING_SETTLEMENT and item.subject_id in named
    ]
    if len(group) < PATTERN:
        return
    yield Cause(
        name="Payouts reported missing that a deposit here already accounts for",
        because=(
            f"{_plural(len(group), 'payout')} totalling {format_inr(_total(group))} are "
            "reported as never having reached the bank. For each one, this same queue "
            "holds a deposit that was matched to it and then came up short - so the "
            "money is here twice, once from each side."
        ),
        ask=(
            f"Work the {len(group)} shortfalls, not these. Closing each shortfall "
            "closes the payout with it, and the exposure is half what the queue total "
            "suggests."
        ),
        members=_members(group),
        total=_total(group),
        codes=_codes(group),
    )


def _one_undisclosed_rate(queue: list[ReconException]) -> Iterator[Cause]:
    """Payouts short by the same percentage of their own gross.

    The strongest signal in the whole queue and the one worth the most
    money. Each of these individually reads as a variance on one batch; the
    fact that the same rate came off several unrelated batches is what turns
    it from an anomaly into a deduction the merchant is not being told about.
    """
    buckets: dict[int, list[ReconException]] = defaultdict(list)
    for item in queue:
        if item.code is not ExceptionCode.FEE_DEDUCTION:
            continue
        rate = _rate(item.evidence.get("implied_rate"))
        if rate is None:
            continue
        buckets[int(rate / RATE_TOLERANCE)].append(item)

    for group in buckets.values():
        if len(group) < PATTERN:
            continue
        rates = [_rate(item.evidence.get("implied_rate")) for item in group]
        seen = [rate for rate in rates if rate is not None]
        low, high = min(seen), max(seen)
        span = f"{low:.3%}" if low == high else f"{low:.3%} to {high:.3%}"
        yield Cause(
            name="A deduction that is not in the settlement report",
            because=(
                f"{_plural(len(group), 'payout')} arrived short against a report that "
                f"foots, and each shortfall is the same share of its own batch - "
                f"{span}. Unrelated batches do not lose the same percentage by accident."
            ),
            ask=(
                f"Ask Razorpay what the extra {span} taken at payout is. One answer "
                f"closes all {len(group)}."
            ),
            members=_members(group),
            total=_total(group),
            codes=_codes(group),
        )


def _one_tax_rate(queue: list[ReconException]) -> Iterator[Cause]:
    """GST off at the same non-statutory slab across several payouts."""
    buckets: dict[str, list[ReconException]] = defaultdict(list)
    for item in queue:
        if item.code is ExceptionCode.TAX_DEDUCTION and item.evidence.get("rate_applied"):
            buckets[item.evidence["rate_applied"]].append(item)

    for slab, group in buckets.items():
        if len(group) < PATTERN:
            continue
        yield Cause(
            name=f"GST deducted at {slab}, not the rate the report shows",
            because=(
                f"{_plural(len(group), 'payout')} came up short by exactly what "
                f"{slab} GST on their own fee would cost. One rate, applied "
                "consistently, is a setting rather than an error."
            ),
            ask=(
                f"Confirm which GST rate applies to your merchant category. If it is "
                f"{slab}, the settlement report is showing the wrong one."
            ),
            members=_members(group),
            total=_total(group),
            codes=_codes(group),
        )


def _refunds_recovered_elsewhere(queue: list[ReconException]) -> Iterator[Cause]:
    """Shortfalls that are refunds netted into a later payout.

    The cause whose value is that it needs no action. These are the single
    most common thing a finance team chases and the single most common thing
    that turns out to be nothing - the money is accounted for, it just left
    from a batch with no relationship to the sale. Saying so once, over the
    whole cluster, is worth more than nine correct individual explanations
    nobody has time to read.
    """
    group = [
        item
        for item in queue
        if item.code is ExceptionCode.PARTIAL_PAYMENT and item.evidence.get("recovered_by")
    ]
    if len(group) < PATTERN:
        return
    landed = {item.evidence["recovered_by"] for item in group}
    yield Cause(
        name="Refunds netted out of a later payout",
        because=(
            f"Each of {_plural(len(group), 'payout')} is short by the size of a "
            f"refund or chargeback that this report shows being recovered from "
            f"{len(landed)} other batch{'es' if len(landed) != 1 else ''}. Every rupee is "
            "accounted for; it left from somewhere else."
        ),
        ask="",
        members=_members(group),
        total=_total(group),
        codes=_codes(group),
    )


def _a_payout_run_never_arrived(queue: list[ReconException]) -> Iterator[Cause]:
    """A whole day's payouts, none of which landed.

    The first version of this grouped any two missing payouts that shared a
    date, and that was wrong for a reason worth recording: with ten missing
    payouts spread over a twenty-one day month, two of them landing on the
    same date is what randomness looks like, not a run that failed. It named
    a cause the evidence did not support, which is the one thing this module
    exists not to do.

    So the test is now the whole run: every payout the gateway says it sent
    that day is missing, and the count of what it sent comes from the
    exception's own evidence rather than from an assumption. Two out of five
    is two payouts to chase. Five out of five is a run that never left.
    """
    buckets: dict[str, list[ReconException]] = defaultdict(list)
    for item in queue:
        if item.code is ExceptionCode.MISSING_SETTLEMENT and item.evidence.get("settled_on"):
            buckets[item.evidence["settled_on"]].append(item)

    for day, group in buckets.items():
        if len(group) < PATTERN:
            continue
        sent = {item.evidence.get("batches_that_day") for item in group}
        if len(sent) != 1 or sent == {None}:
            continue
        expected = next(iter(sent))
        if expected is None or not expected.isdigit() or int(expected) != len(group):
            continue
        yield Cause(
            name=f"The whole payout run of {day} is missing",
            because=(
                f"The gateway says it sent {_plural(len(group), 'payout')} on {day}, "
                f"totalling {format_inr(_total(group))}. Not one of them is on the "
                "statement - it is the entire day, not a payout that went astray."
            ),
            ask=(
                f"Ask Razorpay whether the {day} settlement run executed, and the bank "
                "for any credit received against it since."
            ),
            members=_members(group),
            total=_total(group),
            codes=_codes(group),
        )


def _payouts_that_never_arrived(queue: list[ReconException]) -> Iterator[Cause]:
    """The missing payouts left over, as one cause rather than as a date.

    They share a mechanism - the gateway says it paid and the bank has no
    record - and that is the whole of what they share. Splitting them by
    date would invent structure; leaving them individual would hand back a
    list. One cause, one call, and the dates named inside it.
    """
    group = [item for item in queue if item.code is ExceptionCode.MISSING_SETTLEMENT]
    if len(group) < PATTERN:
        return
    days = sorted({item.evidence.get("settled_on", "") for item in group} - {""})
    span = days[0] if len(days) == 1 else f"{days[0]} to {days[-1]}"
    yield Cause(
        name="Payouts the gateway reported that never reached the bank",
        because=(
            f"{_plural(len(group), 'settlement')} totalling {format_inr(_total(group))}, "
            f"dated {span}, are reported as paid. No credit on the statement matches "
            "any of them, and they do not account for any full day's run."
        ),
        ask=(
            f"Ask Razorpay for the UTR of each of these {len(group)} payouts, then ask "
            "the bank to trace them."
        ),
        members=_members(group),
        total=_total(group),
        codes=_codes(group),
    )


def _captures_never_reported(queue: list[ReconException]) -> Iterator[Cause]:
    """Money captured that the settlement report never claims to have paid.

    Grouped by the mechanism and by nothing else. An earlier version split
    these by capture date and it was the same mistake as the payout run: two
    of eight unreported payments falling on one day out of twenty-one is
    chance, and naming it a cause put a date in front of somebody that meant
    nothing.

    The method mix is reported inside the cause instead, as a description
    rather than as the reason. If every one of them is UPI that is worth a
    reader's attention, and it is still not a claim this can prove.
    """
    group = [item for item in queue if item.code is ExceptionCode.UNSETTLED_PAYMENT]
    if len(group) < PATTERN:
        return
    methods = Counter(item.evidence.get("method", "") for item in group)
    methods.pop("", None)
    if len(methods) == 1:
        how = f", all taken by {next(iter(methods))}"
    elif methods:
        top, count = methods.most_common(1)[0]
        how = f" - {count} of them by {top}" if count > len(group) / 2 else ""
    else:
        how = ""
    horizon = {item.evidence.get("report_complete_to", "") for item in group} - {""}
    complete_to = f" The report is complete to {sorted(horizon)[0]}." if len(horizon) == 1 else ""
    yield Cause(
        name="Captured payments the settlement report never mentions",
        because=(
            f"{_plural(len(group), 'payment')} totalling {format_inr(_total(group))} "
            f"were captured and cleared their settlement window{how}, and appear "
            f"nowhere in the report.{complete_to} Nothing is unmatched - the gateway "
            "never claimed to have paid them, so no amount of matching bank credits "
            "would find them."
        ),
        ask=(
            f"Ask Razorpay for the settlement status of these {len(group)} payment ids. "
            "This is the money most likely to stay missing."
        ),
        members=_members(group),
        total=_total(group),
        codes=_codes(group),
    )


def _one_settlement_several_credits(queue: list[ReconException]) -> Iterator[Cause]:
    """Deposits competing for the same payout.

    Filed as one question rather than as one exception per deposit, because
    it is one question: only one of them is the payout, and the person who
    can say which will say it once.
    """
    buckets: dict[str, list[ReconException]] = defaultdict(list)
    for item in queue:
        if item.evidence.get("reason") == "contested settlement":
            buckets[item.evidence.get("settlement", "")].append(item)

    for settlement, group in buckets.items():
        if len(group) < PATTERN or not settlement:
            continue
        yield Cause(
            name=f"Several deposits all fit settlement {settlement}",
            because=(
                f"{_plural(len(group), 'credit')} match {settlement} on every piece "
                "of evidence these files carry. Only one of them can be it, and "
                "nothing here says which."
            ),
            ask=(
                f"Ask Razorpay for the UTR of {settlement}. One reference separates "
                f"all {len(group)}."
            ),
            members=_members(group),
            total=_total(group),
            codes=_codes(group),
        )


def _one_counterparty_keeps_paying(queue: list[ReconException]) -> Iterator[Cause]:
    """Deposits with no settlement behind them that keep coming from one place.

    The reason this is worth a rule of its own: an unexplained deposit reads
    as a reconciliation failure, and a *recurring* unexplained deposit from
    a named payer usually is not one. It is money arriving from outside the
    gateway - a marketplace, a partner, a loan - into a queue that only
    knows about gateway payouts. Naming the payer turns a defect into a
    fact about the business.
    """
    buckets: dict[str, list[ReconException]] = defaultdict(list)
    for item in queue:
        if item.evidence.get("reason") != "no candidate":
            continue
        stem = _stem(item.evidence.get("narration", ""))
        # A stem naming the gateway fails this rule's premise before it is
        # tested. These deposits say on their face that they are settlement
        # payouts, so whatever is wrong with them, "money from outside
        # Razorpay" is not it - and grouping them by payer would be grouping
        # every unexplained payout in the month under one invented heading.
        if stem and not (_GATEWAY & set(stem.split())):
            buckets[stem].append(item)

    for stem, group in buckets.items():
        if len(group) < PATTERN:
            continue
        yield Cause(
            name=f"Repeated deposits from {stem}",
            because=(
                f"{_plural(len(group), 'credit')} totalling "
                f"{format_inr(_total(group))} carry the same narration and no "
                "settlement behind any of them. A payer that recurs is usually not "
                "a gateway payout at all."
            ),
            ask=(
                f"Confirm whether {stem} is money from outside Razorpay. If it is, "
                f"these {len(group)} belong in another ledger, not this queue."
            ),
            members=_members(group),
            total=_total(group),
            codes=_codes(group),
        )


RULES: tuple[Callable[[list[ReconException]], Iterator[Cause]], ...] = (
    _the_same_money_counted_twice,
    _one_undisclosed_rate,
    _one_tax_rate,
    _a_payout_run_never_arrived,
    _one_settlement_several_credits,
    _one_counterparty_keeps_paying,
    _refunds_recovered_elsewhere,
    _payouts_that_never_arrived,
    _captures_never_reported,
)
"""Most specific first, and the order is the design.

`_the_same_money_counted_twice` leads because it is the only rule here that
needs no tolerance: it matches an id against the same id. It also has to run
before `_payouts_that_never_arrived`, which would otherwise file a duplicated
payout under a heading saying the money never arrived - when the deposit is
three rows further down the same queue.

The next four test a shared *value* - a rate, a slab, a settlement id, a
payer - which is a claim that can be checked and can be wrong. The last
three group on a shared *mechanism*, which is weaker but always true of its
members, so they run last and take what is left.

`_a_payout_run_never_arrived` must precede `_payouts_that_never_arrived` or
the general rule would swallow the specific one and a whole failed run would
be reported as some missing payouts.
"""


def induce(exceptions: Iterable[ReconException]) -> Induction:
    """Read a queue of exceptions as causes, plus whatever did not fit."""
    queue = list(exceptions)
    claimed: set[int] = set()
    found: list[Cause] = []

    for rule in RULES:
        remaining = [item for index, item in enumerate(queue) if index not in claimed]
        for cause in rule(remaining):
            # A rule may only claim what was still free when it ran; two
            # rules that both match an exception must not both count it, or
            # the coverage figure exceeds the queue.
            taken = set(cause.members)
            found.append(cause)
            claimed.update(
                index
                for index, item in enumerate(queue)
                if item.subject_id in taken and index not in claimed
            )

    return Induction(
        causes=tuple(sorted(found, key=lambda cause: (-cause.total, -cause.size, cause.name))),
        uncaused=tuple(item.subject_id for index, item in enumerate(queue) if index not in claimed),
    )
