"""Working out which question was asked. Nothing else.

This is the only place a model is allowed anywhere near a settlement
question, and the only thing it is allowed to do is choose one name out of
ten. It never sees an amount, it never produces a sentence a merchant reads,
and it cannot reach the arithmetic - `milan.qa.answering` computes every
figure from the report afterwards, regardless of how the intent was chosen.

Which makes the failure mode a good one. A wrong model call answers a
different question than the one asked, says which question it answered, and
shows the figures for that question - all of them still correct. It cannot
produce a plausible wrong number, because it never produces numbers.

The rules run first and are measured. The share of real phrasings that reach
the right intent with no model at all is the number that says how much of
this is judgement and how much is pattern matching, and it is reported rather
than assumed - see `tests/integration/test_questions_reach_the_right_answer.py`.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from milan.domain.enums import PaymentMethod
from milan.llm.provider import Completion, Provider, Request
from milan.qa.answering import Asked, Books
from milan.qa.intents import BY_NAME, CATALOGUE, Intent

_WORD = re.compile(r"[a-z0-9'-]+")

_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_SLASHED = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_SPOKEN = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    r"[a-z]*\.?(?:\s+(\d{4}))?\b",
    re.IGNORECASE,
)
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")

_ID = re.compile(r"\b((?:bank|setl|pay|rfnd|adj|order)_[a-z0-9]+)\b", re.IGNORECASE)


def _words(text: str) -> frozenset[str]:
    return frozenset(_WORD.findall(text.lower()))


def _when(text: str, books: Books) -> date | None:
    """A date the question names, in any of the shapes people type.

    Read only from the question, and never from a model. A mis-picked intent
    is a visibly wrong answer to a stated question; a hallucinated date is a
    right-looking answer about a day nobody asked about, and nothing on the
    screen would say so.

    A day-first reading is assumed for the slashed form, because this is an
    India-specific tool and `07/08/2026` is the 7th of August here. The
    ambiguity is real and is resolved the way the rest of the project
    resolves it - by the convention of the place - rather than by guessing
    per question.
    """
    found = _ISO.search(text)
    if found is not None:
        return _safe(int(found.group(1)), int(found.group(2)), int(found.group(3)))

    found = _SLASHED.search(text)
    if found is not None:
        return _safe(int(found.group(3)), int(found.group(2)), int(found.group(1)))

    found = _SPOKEN.search(text)
    if found is not None:
        month = _MONTHS.index(found.group(2).lower()[:3]) + 1
        year = int(found.group(3)) if found.group(3) else _year(books)
        return _safe(year, month, int(found.group(1)))
    return None


def _year(books: Books) -> int:
    """The year a bare "14 July" means: the one the statement covers."""
    span = books.period
    return span[0].year if span is not None else datetime.now().year


def _safe(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _subject(text: str, books: Books) -> str | None:
    """A record id the question names, only if this run actually has it.

    Checked against the run rather than accepted on shape. An id that looks
    right and is not in these files would send `proof` looking for something
    that does not exist and answering "no such credit" to a question that
    named a real one from a different month.
    """
    known = {credit.credit_id for credit in books.data.bank_credits}
    known |= {row.settlement_id for row in books.data.settlement_rows if row.settlement_id}
    known |= {payment.payment_id for payment in books.data.payments}
    for candidate in _ID.findall(text):
        if candidate in known:
            return str(candidate)
    return None


_METHODS: dict[str, PaymentMethod] = {
    "upi": PaymentMethod.UPI,
    "card": PaymentMethod.CARD,
    "cards": PaymentMethod.CARD,
    "netbanking": PaymentMethod.NETBANKING,
    "wallet": PaymentMethod.WALLET,
    "wallets": PaymentMethod.WALLET,
    "emi": PaymentMethod.EMI,
    "paylater": PaymentMethod.PAYLATER,
}


def _instrument(words: frozenset[str]) -> PaymentMethod | None:
    """A payment method the question names, if it names exactly one.

    Exactly one, on purpose. "How do cards compare to UPI" names two, and
    answering it about whichever appeared first would be picking a side of a
    comparison the reader asked to see both halves of - so it falls through
    to the breakdown across every method, which is the honest answer to a
    question about two of them.
    """
    found = {_METHODS[word] for word in words if word in _METHODS}
    return found.pop() if len(found) == 1 else None


def read(text: str, books: Books) -> Asked:
    """Pull out of the question everything the rules can be sure of."""
    words = _words(text)
    return Asked(
        text=text.strip(),
        words=words,
        on=_when(text, books),
        subject=_subject(text, books),
        method=_instrument(words),
    )


_DOING = frozenset(
    {
        # Produce a document.
        "draft",
        "write",
        "compose",
        "letter",
        "summarise",
        "summarize",
        # Move it somewhere.
        "email",
        "mail",
        "send",
        "forward",
        "download",
        "export",
        "share",
        # Do it later, or repeatedly.
        "alert",
        "alerts",
        "notify",
        "remind",
        "schedule",
        "subscribe",
        # Say what has not happened yet.
        "forecast",
        "forecasting",
        "predict",
        "projection",
        "project",
    }
)
"""Words that mean the sentence is a request rather than a question.

The most valuable rule in this module, and it was added because of one
sentence: "set up an alert when a payout is short". Every trigger in the
catalogue reads that as `shortfall` - the word is right there - and the
reply was a correct, confident account of this month's shortfalls to
somebody who had asked for a notification and now believes they have one.

That is the failure this package exists to avoid, arriving through a door
nothing was watching. Domain nouns are exactly what an action request
contains, so matching on nouns can never tell the two apart; the verb can.
Anything here is refused before a trigger or a model sees it, because a
model handed "draft a dispute letter" will pick `refunds` for the same
reason the rules did, and be just as wrong.

Deliberately verbs of *doing*, never of *asking*. "Show", "give", "break
down" and "list" are how people ask for figures they are owed, and pulling
any of them in here would refuse the questions this is for.
"""


def asks_for_an_action(asked: Asked) -> bool:
    """Whether the sentence asks this to *do* something rather than say one.

    This package computes figures from rows that already exist. It cannot
    send, schedule, draft or predict, and the honest reply to all four is to
    say so rather than to answer the nearest question it recognises.
    """
    return bool(_DOING & asked.words)


def by_rules(asked: Asked) -> Intent | None:
    """The first intent every one of whose trigger groups is satisfied.

    An id in the question outranks every word in it. "Why is bank_x short" is
    about that credit, and answering it with a month-wide shortfall total
    would be answering a question the person did not ask while appearing to
    have understood them.
    """
    if asked.subject is not None and not _asks_about_the_month(asked):
        return BY_NAME["proof"]

    for intent in CATALOGUE:
        for trigger in intent.triggers:
            if all(group & asked.words for group in trigger):
                return intent

    # A date nothing else claimed is a question about that date. Last, so it
    # never takes a question another intent understood - "how much did I
    # receive on 14 July" is a `received` question that happens to name a
    # day - and present at all because somebody who typed a date wants that
    # date rather than a refusal.
    if asked.on is not None:
        return BY_NAME["on_a_day"]
    return None


_MONTH_WIDE = frozenset({"total", "all", "every", "overall", "month", "everything"})


def _asks_about_the_month(asked: Asked) -> bool:
    """An id plus a word like "total" is still a question about the month.

    Narrow on purpose. The default when an id is present is that the id is
    the subject, and this only overrides that when the question says so.
    """
    return bool(_MONTH_WIDE & asked.words)


PROMPT = """You route questions about a settlement reconciliation to one of a fixed list.

Reply with one name from the list and nothing else. If none of them is what the
person is asking, reply with: none

{catalogue}

Question: {question}
Name:"""


def by_model(asked: Asked, provider: Provider) -> tuple[Intent | None, str]:
    """Ask a model which of the known questions this is. Nothing more.

    The reply is checked against the catalogue rather than trusted. A model
    that answers with a name nobody defined, an explanation, or an intent
    invented on the spot is treated exactly like a model that said `none` -
    the question goes unrouted and the merchant is told so.

    `none` is offered explicitly and it matters that it is. A model given ten
    options and no way out will pick the nearest one, and the nearest one to
    "what is the weather" is an answer about settlements that reads as though
    the question was understood.
    """
    catalogue = "\n".join(f"- {intent.name}: {intent.asks}" for intent in CATALOGUE)
    reply = provider.complete(
        Request(
            prompt=PROMPT.format(catalogue=catalogue, question=asked.text),
            max_tokens=16,
            temperature=0.0,
        )
    )
    return _understood(reply), reply.provider or getattr(provider, "name", "model")


def _understood(reply: Completion) -> Intent | None:
    said = (reply.text or "").strip().lower().splitlines()
    if not said:
        return None
    # First line, first word: a model that adds a sentence of reasoning has
    # still answered, and refusing its answer over the formatting would be
    # discarding a correct routing on a technicality.
    first = _WORD.findall(said[0])
    return BY_NAME.get(first[0]) if first else None
