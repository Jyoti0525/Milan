"""The arithmetic behind every answer.

Nothing in this module consults a model, and nothing in it is reachable by
one. A model's only job upstream is to decide which of these functions runs;
each of them then computes its own figures from the report and the merchant's
own rows, and attaches the record ids it used.

That separation is the whole design. It means the worst a wrong model call
can do is answer a different question than the one asked - visibly, because
the answer says which question it read - rather than answer the right
question with a number nobody can trace.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from milan.domain.enums import EntityType, ExceptionCode, PaymentMethod
from milan.domain.money import ZERO, Paise, format_inr
from milan.domain.results import ReconReport
from milan.forecast import schedule_from
from milan.leaks.clusters import summarise
from milan.qa.question import Answer, Line
from milan.recon.causes import induce
from milan.recon.inputs import ReconInput

SHORTFALL_CODES = (
    ExceptionCode.FEE_DEDUCTION,
    ExceptionCode.TAX_DEDUCTION,
    ExceptionCode.PARTIAL_PAYMENT,
)
"""The three ways a payout arrives smaller than the report describes.

`MISSING_SETTLEMENT` is deliberately not one of them: a payout that did not
arrive is not a payout that arrived short, and folding them together would
answer "why was my payout small" with money that never moved.
"""

MOST_LINES = 12
"""How many supporting rows an answer carries before it says how many more.

A question answered with sixty lines has been answered with a file. The
figure in the headline is over everything; the lines are the largest of
them, and the count of what is not shown is stated rather than dropped.
"""


class Books(BaseModel):
    """One reconciled month: the merchant's files, and what was made of them."""

    model_config = ConfigDict(frozen=True)

    data: ReconInput
    report: ReconReport

    @property
    def period(self) -> tuple[date, date] | None:
        """The days the bank statement covers, or nothing if it is empty."""
        days = [credit.value_date for credit in self.data.bank_credits]
        return (min(days), max(days)) if days else None


class Asked(BaseModel):
    """One question, with whatever the rules could pull out of it.

    `on` and `subject` are extracted by rules and never by a model. A model
    that mis-picks an intent produces a visibly wrong answer to a stated
    question; a model that invents a date produces a right-looking answer
    about a day the merchant did not ask about, and nothing on the screen
    would say so.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    words: frozenset[str]
    on: date | None = None
    subject: str | None = None
    method: PaymentMethod | None = None
    """A payment method the question names, if it names one.

    Extracted by rules like the date and the id, and for the same reason. A
    model that mis-picks an intent is visibly wrong; a model that decides a
    question about UPI was about cards produces a correct-looking total for
    the wrong instrument."""


def _clip(lines: list[Line], noun: str) -> tuple[Line, ...]:
    if len(lines) <= MOST_LINES:
        return tuple(lines)
    hidden = len(lines) - MOST_LINES
    return (
        *lines[:MOST_LINES],
        Line(label=f"... and {hidden} more {noun}", detail="not shown, but counted above"),
    )


def _period(books: Books) -> str:
    span = books.period
    if span is None:
        return "this run"
    start, end = span
    return f"{start} to {end}" if start != end else f"{start}"


def _nothing(asked: Asked, intent: str, headline: str) -> Answer:
    """An answer of zero is still an answer, and has to read like one.

    "No overcharges found" is a finding. Falling through to a refusal because
    a list came back empty would tell a merchant this cannot answer the
    question, when in fact it answered it and the answer was good news.
    """
    return Answer(asked=asked.text, intent=intent, headline=headline)


# --------------------------------------------------------------------- money


def charges(books: Books, asked: Asked) -> Answer:
    """The fee, the GST on it, and any statutory withholding."""
    rows = books.data.settlement_rows
    payments = [row for row in rows if row.type is EntityType.PAYMENT]
    fee = Paise(sum(row.fee for row in rows))
    tax = Paise(sum(row.tax for row in rows))
    gross = Paise(sum(row.amount for row in payments))

    lines = [
        Line(
            label="Platform fee",
            amount=fee,
            detail=(
                f"{fee / gross:.3%} of {format_inr(gross)} settled"
                if gross
                else "no settled payments"
            ),
        ),
        Line(label="GST on the fee", amount=tax, detail="recoverable as input tax credit"),
    ]

    withholding = books.report.profile.withholding
    withheld = ZERO
    if withholding.held:
        # Read off the rows rather than recomputed from a rate, so this figure
        # cannot disagree with the profile that reported the withholding.
        withheld = Paise(sum(row.amount - row.fee - row.tax - row.signed_net for row in payments))
        lines.append(
            Line(
                label="Withheld under Section 194-O",
                amount=withheld,
                detail=f"{withholding.share} settled payments, creditable against tax due",
            )
        )

    total = Paise(fee + tax + withheld)
    return Answer(
        asked=asked.text,
        intent="charges",
        headline=(
            f"{format_inr(total)} came off {format_inr(gross)} of settled payments "
            f"over {_period(books)} - {format_inr(fee)} in fees, {format_inr(tax)} GST"
            + (f", {format_inr(withheld)} withheld." if withheld else ".")
        ),
        lines=tuple(lines),
    )


def refunds(books: Books, asked: Asked) -> Answer:
    """What went back out, and what sending it back cost."""
    rows = [
        row
        for row in books.data.settlement_rows
        if row.type in (EntityType.REFUND, EntityType.ADJUSTMENT)
    ]
    if not rows:
        return _nothing(asked, "refunds", "No refunds or chargebacks in this period.")

    returned = Paise(sum(row.amount for row in rows))
    cost = Paise(sum(row.fee + row.tax for row in rows))
    disputes = [row for row in rows if row.type is EntityType.ADJUSTMENT]

    lines = [
        Line(
            label=f"Refunds ({len(rows) - len(disputes)})",
            amount=Paise(sum(row.amount for row in rows if row.type is EntityType.REFUND)),
            detail="netted out of whichever payout was running when they cleared",
            sources=tuple(row.entity_id for row in rows if row.type is EntityType.REFUND)[:20],
        ),
    ]
    if disputes:
        lines.append(
            Line(
                label=f"Chargebacks and adjustments ({len(disputes)})",
                amount=Paise(sum(row.amount for row in disputes)),
                sources=tuple(row.entity_id for row in disputes)[:20],
            )
        )
    if cost:
        lines.append(
            Line(
                label="What returning it cost",
                amount=cost,
                detail="instant refund charges and the GST on them",
            )
        )

    return Answer(
        asked=asked.text,
        intent="refunds",
        headline=(
            f"{format_inr(returned)} went back to customers across {len(rows)} refunds "
            f"and adjustments over {_period(books)}"
            + (f", costing {format_inr(cost)} to return." if cost else ".")
        ),
        lines=tuple(lines),
    )


def received(books: Books, asked: Asked) -> Answer:
    """What actually landed in the bank, by day."""
    credits = books.data.bank_credits
    if asked.on is not None:
        credits = tuple(credit for credit in credits if credit.value_date == asked.on)
        if not credits:
            return _nothing(asked, "received", f"Nothing arrived in the bank on {asked.on}.")

    total = Paise(sum(credit.amount for credit in credits))
    by_day: dict[date, list[str]] = defaultdict(list)
    money: dict[date, int] = defaultdict(int)
    for credit in credits:
        by_day[credit.value_date].append(credit.credit_id)
        money[credit.value_date] += credit.amount

    lines = [
        Line(
            label=str(day),
            amount=Paise(money[day]),
            detail=f"{len(by_day[day])} credit{'s' if len(by_day[day]) > 1 else ''}",
            sources=tuple(by_day[day]),
        )
        for day in sorted(by_day, reverse=True)
    ]
    when = f"on {asked.on}" if asked.on is not None else f"over {_period(books)}"
    # Counted over the credits actually being reported on, not the run. A
    # question about one day answered with the month's proof count is a
    # number that is true of something the reader did not ask about.
    shown = {credit.credit_id for credit in credits}
    proved = sum(1 for one in books.report.proofs if one.credit_id in shown and one.balances)
    return Answer(
        asked=asked.text,
        intent="received",
        headline=(
            f"{format_inr(total)} arrived across {len(credits)} bank credits {when}. "
            f"{proved} of them {'is' if proved == 1 else 'are'} proved to the paisa."
        ),
        lines=_clip(lines, "days"),
        subjects=tuple(credit.credit_id for credit in credits[:MOST_LINES]),
    )


def landing(books: Books, asked: Asked) -> Answer:
    """When money already captured is due to reach the bank.

    The only answer in this module about a day that has not happened, and the
    only one that could be mistaken for a forecast. It is not one: every date
    is Razorpay's published cycle applied to a capture timestamp the merchant
    already has, and every amount is their own fee stack applied to money
    they have already taken. Nothing is extrapolated, and a question about
    sales nobody has made still reaches no intent at all.

    The two figures kept out of the headline total are named in it instead.
    Overdue money has already failed to arrive and undated money has no date
    to arrive on, so adding either to "what is coming" would answer a cash
    question with a number the merchant cannot spend.
    """
    schedule = schedule_from(books.data, books.report.profile.rates())

    if asked.on is not None:
        through = schedule.through(asked.on)
        return _nothing(
            asked,
            "landing",
            (
                f"{format_inr(through)} is due to have reached the bank by {asked.on}, "
                f"from payments already captured."
            ),
        )

    if not schedule.landings:
        return _nothing(
            asked,
            "landing",
            (
                "Nothing captured is still waiting for a payout - every payment in these "
                f"files was settled on or before {schedule.as_of}."
            ),
        )

    lines = [
        Line(
            label=str(one.on),
            amount=one.net,
            detail=(
                f"{one.count} payment{'s' if one.count > 1 else ''}, "
                f"{format_inr(schedule.through(one.on))} by then"
            ),
            sources=tuple(item.payment_id for item in one.commitments[:MOST_LINES]),
        )
        for one in schedule.landings
    ]

    horizon = schedule.horizon
    headline = (
        f"{format_inr(schedule.committed)} is due to reach the bank between "
        f"{schedule.landings[0].on} and {horizon}, from {schedule.payments} payments "
        f"captured on or before {schedule.as_of}. "
        "Dated by the published settlement cycle, not predicted."
    )
    if schedule.overdue:
        headline += (
            f" Separately, {format_inr(schedule.overdue_net)} across "
            f"{len(schedule.overdue)} payments was due before {schedule.as_of} "
            "and has no payout behind it."
        )
    if schedule.undated:
        headline += (
            f" A further {format_inr(schedule.undated_net)} across "
            f"{len(schedule.undated)} rows has no date these files support."
        )

    return Answer(
        asked=asked.text,
        intent="landing",
        headline=headline,
        lines=_clip(lines, "days"),
        subjects=tuple(item.payment_id for item in schedule.landings[0].commitments[:MOST_LINES]),
    )


def overcharge(books: Books, asked: Asked) -> Answer:
    """Fees above the contracted rate, on payouts that reconciled perfectly.

    The finding that survives everything balancing, which is why it is worth
    its own question: nothing is unmatched, the bank agrees with the report,
    and the merchant is still losing money on every transaction of that kind.
    """
    report = summarise(books.report.leaks, len(books.data.settlement_rows))
    if report.clean:
        return _nothing(
            asked,
            "overcharge",
            (
                f"No rows charged above contract. Every one of "
                f"{len(books.data.settlement_rows):,} settlement rows was billed at "
                "the rate this merchant is contracted to."
            ),
        )

    lines = [
        Line(
            label=f"{group.method} charged at {group.charged_rate:.2%}",
            amount=group.overcharge,
            detail=(
                f"{group.payments} payments, contracted at "
                f"{group.contracted_rate:.2%} - {format_inr(group.cash_impact)} left "
                f"the account including GST, first seen {group.first_seen}"
            ),
            sources=group.payment_ids[:20],
        )
        for group in report.clusters
    ]
    return Answer(
        asked=asked.text,
        intent="overcharge",
        # The leak report writes its own headline, and it is reused rather
        # than reworded. Two sentences describing the same overcharge is two
        # places for the figure to drift.
        headline=(
            f"{report.headline()} Every one of these payouts reconciled perfectly - "
            "nothing was unmatched, and the loss is only visible against the contract."
        ),
        lines=_clip(lines, "rate mismatches"),
    )


# ---------------------------------------------------------------- the queue


def shortfall(books: Books, asked: Asked) -> Answer:
    """Payouts that arrived smaller than the report says they should have."""
    found = [item for item in books.report.exceptions if item.code in SHORTFALL_CODES]
    if asked.subject is not None:
        found = [item for item in found if item.subject_id == asked.subject]
    if not found:
        return _nothing(
            asked,
            "shortfall",
            (
                "No payout arrived short of what the settlement report describes. "
                "Every credit that was matched also reconstructed to the paisa."
            ),
        )

    total = Paise(sum(item.amount for item in found))
    lines = [
        Line(
            label=item.summary,
            amount=item.amount,
            detail=item.evidence.get("settlements", ""),
            sources=(item.subject_id,),
        )
        for item in sorted(found, key=lambda item: -item.amount)
    ]
    causes = induce(found)
    tail = ""
    if causes.causes:
        tail = f" {causes.causes[0].size} of them share one cause: {causes.causes[0].name.lower()}."

    return Answer(
        asked=asked.text,
        intent="shortfall",
        headline=(
            f"{len(found)} payouts arrived short by {format_inr(total)} in total over "
            f"{_period(books)}, and each shortfall is named rather than written off.{tail}"
        ),
        lines=_clip(lines, "shortfalls"),
        subjects=tuple(item.subject_id for item in found[:MOST_LINES]),
    )


def unsettled(books: Books, asked: Asked) -> Answer:
    """Captured money the settlement report never claims to have paid."""
    found = [
        item for item in books.report.exceptions if item.code is ExceptionCode.UNSETTLED_PAYMENT
    ]
    if not found:
        return _nothing(
            asked,
            "unsettled",
            (
                "Every payment captured before the report's own horizon appears in it. "
                "Nothing was captured and then left out."
            ),
        )

    total = Paise(sum(item.amount for item in found))
    horizon = {item.evidence.get("report_complete_to", "") for item in found} - {""}
    lines = [
        Line(
            label=item.subject_id,
            amount=item.amount,
            detail=(
                f"captured {item.evidence.get('captured_on', '?')} by "
                f"{item.evidence.get('method', '?')}"
            ),
            sources=(item.subject_id,),
        )
        for item in sorted(found, key=lambda item: -item.amount)
    ]
    return Answer(
        asked=asked.text,
        intent="unsettled",
        headline=(
            f"{format_inr(total)} across {len(found)} payments was captured and never "
            "appears in the settlement report at all"
            + (f", which is complete to {sorted(horizon)[0]}. " if len(horizon) == 1 else ". ")
            + "Nothing is unmatched - the gateway never claimed to have paid these, so "
            "no amount of matching bank credits would find them."
        ),
        lines=_clip(lines, "payments"),
        subjects=tuple(item.subject_id for item in found[:MOST_LINES]),
    )


def unexplained(books: Books, asked: Asked) -> Answer:
    """The queue, as the few reasons behind it."""
    exceptions = books.report.exceptions
    if not exceptions:
        return _nothing(
            asked,
            "unexplained",
            (
                f"Nothing is unresolved. All {books.report.credits_resolved} bank "
                "credits reconstruct to the paisa."
            ),
        )

    found = induce(exceptions)
    total = Paise(sum(abs(item.amount) for item in exceptions))
    lines = [
        Line(
            label=cause.name,
            amount=cause.total,
            detail=cause.because + (f" To do: {cause.ask}" if cause.ask else " Nothing to chase."),
            sources=cause.members[:20],
        )
        for cause in found.causes
    ]
    if found.uncaused:
        lines.append(
            Line(
                label=f"{len(found.uncaused)} that are each their own",
                detail="no sibling in this queue, so no pattern to belong to",
                sources=found.uncaused[:20],
            )
        )
    return Answer(
        asked=asked.text,
        intent="unexplained",
        headline=(
            f"{len(exceptions)} things could not be resolved, worth "
            f"{format_inr(total)} between them. {found.reading}"
        ),
        lines=_clip(lines, "causes"),
    )


def biggest(books: Books, asked: Asked) -> Answer:
    """The one thing to do about this month, if only one thing gets done.

    Ranked by money, and causes beat individual exceptions at equal value:
    six items with one answer between them is a better use of an afternoon
    than one item worth slightly more.
    """
    found = induce(books.report.exceptions)
    if found.causes:
        first = found.causes[0]
        return Answer(
            asked=asked.text,
            intent="biggest",
            headline=(
                f"{first.name} - {format_inr(first.total)} across {first.size} items. "
                + (first.ask or "Nothing needs chasing on these; they are accounted for.")
            ),
            lines=(
                Line(label="Why this is one thing", detail=first.because, amount=first.total),
                *(
                    Line(
                        label=cause.name,
                        amount=cause.total,
                        detail=f"{cause.size} items",
                        sources=cause.members[:20],
                    )
                    for cause in found.causes[1:]
                ),
            ),
            subjects=first.members[:MOST_LINES],
        )

    if books.report.exceptions:
        worst = max(books.report.exceptions, key=lambda item: abs(item.amount))
        return Answer(
            asked=asked.text,
            intent="biggest",
            headline=(
                f"{worst.summary} Nothing else in this queue shares a cause with it, "
                "so there is no cluster to close - only this one."
            ),
            lines=(Line(label=worst.code.value, amount=worst.amount, sources=(worst.subject_id,)),),
            subjects=(worst.subject_id,),
        )

    return _nothing(
        asked, "biggest", "Nothing is wrong with this month. Every credit reconstructs."
    )


# ------------------------------------------------------- slicing the month


def by_method(books: Books, asked: Asked) -> Answer:
    """What each instrument brought in, and what it cost to accept.

    The question a merchant asks when deciding what to promote. UPI is nearly
    free and cards are not, so "which of these is worth having" is a fee
    question rather than a volume question - and the answer is both columns
    side by side rather than either one alone.
    """
    rows = [
        row
        for row in books.data.settlement_rows
        if row.type is EntityType.PAYMENT and row.method is not None
    ]
    if not rows:
        return _nothing(asked, "by_method", "No settled payments carry a method in this report.")

    wanted = asked.method
    if wanted is not None:
        rows = [row for row in rows if row.method is wanted]
        if not rows:
            return _nothing(
                asked, "by_method", f"Nothing settled by {wanted.value} in this period."
            )

    gross: dict[str, int] = defaultdict(int)
    cost: dict[str, int] = defaultdict(int)
    count: Counter[str] = Counter()
    for row in rows:
        name = row.method.value if row.method is not None else "unknown"
        gross[name] += row.amount
        cost[name] += row.fee + row.tax
        count[name] += 1

    def describe(name: str) -> str:
        if not gross[name]:
            return f"{count[name]} payments"
        share = Decimal(cost[name]) / Decimal(gross[name])
        return (
            f"{count[name]} payments, {format_inr(Paise(cost[name]))} in fees and GST "
            f"- {share:.3%} of what it brought in"
        )

    lines = [
        Line(label=name, amount=Paise(gross[name]), detail=describe(name))
        for name in sorted(gross, key=lambda name: -gross[name])
    ]

    total = Paise(sum(gross.values()))
    charged = Paise(sum(cost.values()))
    if wanted is not None:
        headline = (
            f"{wanted.value} brought in {format_inr(total)} across {len(rows)} settled "
            f"payments over {_period(books)}, and cost {format_inr(charged)} in fees "
            "and GST to accept."
        )
    else:
        headline = (
            f"{format_inr(total)} settled across {len(gross)} payment methods over "
            f"{_period(books)}, costing {format_inr(charged)} in fees and GST. "
            f"{lines[0].label} is the largest."
        )
    return Answer(asked=asked.text, intent="by_method", headline=headline, lines=tuple(lines))


def on_a_day(books: Books, asked: Asked) -> Answer:
    """Everything this run knows about one date.

    Deliberately broad rather than precise, and it is the fallback for any
    question that names a day and nothing else this can place. Somebody who
    typed a date wants that date; answering with the whole month would be
    answering something they did not ask.
    """
    if asked.on is None:
        span = books.period
        where = f" The statement runs {_period(books)}." if span is not None else ""
        return _nothing(
            asked, "on_a_day", f"Name a date and I will say what happened on it.{where}"
        )

    day = asked.on
    credits = [credit for credit in books.data.bank_credits if credit.value_date == day]
    settled = {
        row.settlement_id
        for row in books.data.settlement_rows
        if row.settled_at is not None and row.settled_at.date() == day and row.settlement_id
    }
    captured = [payment for payment in books.data.payments if payment.captured_at.date() == day]
    # Matched on the evidence rather than on a date field, because different
    # exception kinds record their date under different keys - `settled_on`,
    # `captured_on`, `raised_on` - and a reader asking about a day means all
    # of them.
    raised = [
        item
        for item in books.report.exceptions
        if day.isoformat() in " ".join(item.evidence.values())
    ]

    if not (credits or settled or captured or raised):
        return _nothing(asked, "on_a_day", f"Nothing in these files happened on {day}.")

    arrived = Paise(sum(credit.amount for credit in credits))
    taken = Paise(sum(payment.amount for payment in captured))
    lines = []
    if credits:
        lines.append(
            Line(
                label=f"Arrived in the bank ({len(credits)})",
                amount=arrived,
                sources=tuple(credit.credit_id for credit in credits),
            )
        )
    if settled:
        lines.append(
            Line(
                label=f"Payout runs dated this day ({len(settled)})",
                detail="what the gateway says it sent",
                sources=tuple(sorted(settled)),
            )
        )
    if captured:
        lines.append(
            Line(
                label=f"Captured from customers ({len(captured)})",
                amount=taken,
                detail="settles two working days later unless taken instantly",
            )
        )
    if raised:
        lines.append(
            Line(
                label=f"Unresolved cases naming this day ({len(raised)})",
                amount=Paise(sum(abs(item.amount) for item in raised)),
                sources=tuple(item.subject_id for item in raised)[:20],
            )
        )

    return Answer(
        asked=asked.text,
        intent="on_a_day",
        headline=(
            f"On {day}: {format_inr(arrived)} arrived across {len(credits)} bank "
            f"credits, {format_inr(taken)} was captured from customers, and "
            f"{len(raised)} unresolved cases name that date."
        ),
        lines=tuple(lines),
        subjects=tuple(credit.credit_id for credit in credits[:MOST_LINES]),
    )


def largest(books: Books, asked: Asked) -> Answer:
    """The biggest payouts.

    Not the same question as `biggest`, which is the largest *problem*. A
    merchant asking which payouts were biggest is doing cash planning; one
    asking what is biggest wrong is working a queue.
    """
    credits = sorted(books.data.bank_credits, key=lambda credit: -credit.amount)
    if not credits:
        return _nothing(asked, "largest", "No bank credits in this period.")

    proved = {one.credit_id for one in books.report.proofs if one.balances}
    shown = credits[:MOST_LINES]
    lines = [
        Line(
            label=credit.credit_id,
            amount=credit.amount,
            detail=(
                f"{credit.value_date} - "
                + ("proved to the paisa" if credit.credit_id in proved else "not proved")
            ),
            sources=(credit.credit_id,),
        )
        for credit in shown
    ]
    top = Paise(sum(credit.amount for credit in shown))
    everything = Paise(sum(credit.amount for credit in credits))
    return Answer(
        asked=asked.text,
        intent="largest",
        headline=(
            f"The largest single credit was {format_inr(credits[0].amount)} on "
            f"{credits[0].value_date}. The top {len(shown)} together are "
            f"{format_inr(top)} of {format_inr(everything)} received."
        ),
        lines=tuple(lines),
        subjects=tuple(credit.credit_id for credit in shown),
    )


def timing(books: Books, asked: Asked) -> Answer:
    """How long money actually took to arrive, measured rather than quoted.

    The published answer is T+2 working days. What a merchant wants to know
    is whether that is what *they* get, and the only way to say so is to
    measure the gap on their own rows.
    """
    lags = [
        (row.settled_at.date() - row.created_at.date()).days
        for row in books.data.settlement_rows
        if row.settled_at is not None and row.type is EntityType.PAYMENT
    ]
    if not lags:
        return _nothing(asked, "timing", "Nothing in this report has settled yet.")

    spread = Counter(lags)
    lines = [
        Line(
            label=("same day" if days == 0 else f"{days} calendar day{'s' if days > 1 else ''}"),
            detail=f"{count} payments, {count / len(lags):.0%} of settled volume",
        )
        for days, count in sorted(spread.items())
    ]
    typical = spread.most_common(1)[0][0]
    same_day = spread[0]
    instant = (
        f" {same_day} settled the same day, which is instant settlement rather than "
        "the ordinary cycle."
        if same_day
        else ""
    )
    return Answer(
        asked=asked.text,
        intent="timing",
        headline=(
            f"Payments in this report take {min(lags)} to {max(lags)} calendar days to "
            f"settle, most commonly {typical}.{instant}"
        ),
        lines=_clip(lines, "settlement lags"),
    )


# -------------------------------------------------------------- the merchant


def merchant(books: Books, asked: Asked) -> Answer:
    """What the rows say about who this merchant is."""
    profile = books.report.profile
    shown = (*profile.named, *profile.questions)
    if not shown:
        return _nothing(
            asked,
            "merchant",
            (
                "Nothing unusual. No withholding on the payments, no Route transfers, "
                "no same-day payouts - an ordinary merchant selling their own goods. "
                "Read from the settlement rows, not configured."
            ),
        )

    lines = [
        Line(
            label=finding.name + ("?" if finding.held is None else ""),
            detail=f"{finding.share} - {finding.because}",
        )
        for finding in shown
    ]
    settled = [finding.name for finding in profile.named]
    open_ = [finding.name for finding in profile.questions]
    headline = (
        f"Read from their own settlement rows: {', '.join(settled)}."
        if settled
        else "Nothing was settled by the rows."
    )
    if open_:
        headline += (
            f" The rows disagree about {', '.join(open_)}, so that one is put to a "
            "person rather than decided."
        )
    return Answer(asked=asked.text, intent="merchant", headline=headline, lines=tuple(lines))


def proof(books: Books, asked: Asked) -> Answer:
    """One credit or settlement, broken down to nothing."""
    wanted = asked.subject or ""
    for one in books.report.proofs:
        if one.credit_id == wanted or wanted in one.settlement_ids:
            return Answer(
                asked=asked.text,
                intent="proof",
                headline=(
                    f"{format_inr(one.credit_amount)} arrived and every paisa of it is "
                    f"accounted for, across {len(one.lines)} lines. Matched by "
                    f"{one.strategy.value.replace('_', ' ')} at {one.confidence:.0%}."
                ),
                lines=tuple(
                    Line(label=line.label, amount=line.amount, sources=line.refs)
                    for line in one.lines
                ),
                subjects=(one.credit_id, *one.settlement_ids),
            )

    for item in books.report.exceptions:
        if item.subject_id == wanted:
            return Answer(
                asked=asked.text,
                intent="proof",
                headline=item.summary,
                lines=tuple(Line(label=key, detail=value) for key, value in item.evidence.items()),
                subjects=(item.subject_id,),
            )

    return _nothing(
        asked,
        "proof",
        f"{wanted} is not a credit or settlement this run knows about.",
    )


ANSWERS = {
    "by_method": by_method,
    "on_a_day": on_a_day,
    "largest": largest,
    "timing": timing,
    "landing": landing,
    "charges": charges,
    "refunds": refunds,
    "received": received,
    "overcharge": overcharge,
    "shortfall": shortfall,
    "unsettled": unsettled,
    "unexplained": unexplained,
    "biggest": biggest,
    "merchant": merchant,
    "proof": proof,
}
"""Every intent in the catalogue has exactly one of these. A test asserts it,
because an intent a model can pick and nothing can answer is a crash waiting
for the phrasing that reaches it."""
