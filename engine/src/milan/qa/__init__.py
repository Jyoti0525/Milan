"""Answering a merchant's question about their own settlement month.

The example the Razorpay Track 04 brief names by name, built to this
project's rule rather than around it: **a model may propose, only arithmetic
may conclude.**

What that means concretely is that a model is given one job here - deciding
which of ten known questions was asked - and is given it only when the rules
cannot. Every figure in every answer is computed from the report by
`milan.qa.answering`, whichever way the question was routed, so the system
answers exactly as correctly with no model at all. It just understands fewer
phrasings, and how many fewer is measured rather than asserted.

A question that reaches nothing is refused, out loud, with a list of what
does work. That is not a fallback: a settlement assistant that produces a
confident paragraph about the wrong month is worse than useless, because the
merchant has no way to tell that reply from a right one.
"""

from __future__ import annotations

from milan.llm.provider import Provider
from milan.qa.answering import ANSWERS, Books
from milan.qa.intents import examples
from milan.qa.question import Answer, Line
from milan.qa.routing import asks_for_an_action, by_model, by_rules, read

__all__ = ["Answer", "Books", "Line", "ask"]


def ask(question: str, books: Books, provider: Provider | None = None) -> Answer:
    """Answer one question about one reconciled month.

    `provider` is optional and the answer is not worse without it - only the
    range of phrasings that reach an answer is narrower. That is the same
    arrangement as everywhere else in this system: the model widens the door,
    it does not decide what is behind it.
    """
    asked = read(question, books)
    if not asked.text:
        return _refuse(question, "Ask me something about this month's settlements.")

    # Before the rules and before any model, because both of them route on
    # nouns and an action request is full of the right ones. "Set up an alert
    # when a payout is short" is a `shortfall` sentence by every trigger in
    # the catalogue, and answering it hands somebody a correct account of
    # this month while leaving them believing a notification exists.
    if asks_for_an_action(asked):
        return _refuse(
            asked.text,
            (
                "I can work figures out from these files, but I cannot send, draft, set "
                "up or predict anything - so I would rather say so than answer the "
                "nearest question I recognise. I will not forecast money nobody has "
                "paid yet, though I will tell you when money already captured is due "
                "to land. What I can answer:"
            ),
        )

    intent = by_rules(asked)
    routed_by = "rules"

    if intent is None and provider is not None:
        intent, routed_by = by_model(asked, provider)

    if intent is None:
        return _refuse(
            asked.text,
            (
                "I could not tell which question that is, and I would rather say so "
                "than answer a different one. Here is what I can work out from these "
                "files:"
            ),
        )

    answer = ANSWERS[intent.name](books, asked)
    return answer.model_copy(update={"routed_by": routed_by})


def _refuse(question: str, why: str) -> Answer:
    return Answer(
        asked=question.strip(),
        intent=None,
        headline=why,
        routed_by="nobody",
        suggestions=examples(),
    )
