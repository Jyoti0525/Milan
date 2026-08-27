"""What an answer is, and what a refusal is.

One shape for both, because the difference between them is a fact about the
answer rather than a different kind of thing: `intent is None` means nothing
in this system could work out what was being asked, and the honest reply is
to say so and list what it *can* answer.

The rule the whole package exists to keep is the project's own: **a model may
propose, only arithmetic may conclude.** A model here is allowed to decide
which of a fixed list of questions is being asked. It is never allowed to
produce a number, a record id, or a sentence a merchant will read as a
finding. Every figure below is computed from the report, and `sources`
carries the record ids it was computed from, so any line can be checked
against the merchant's own files rather than believed.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from milan.domain.money import ZERO, Paise


class Line(BaseModel):
    """One supporting row of an answer.

    Always carries what it is about and what it is worth. A line with no
    `sources` is an assertion rather than evidence, and this package does not
    produce those - the same rule `ProofLine` keeps, for the same reason.
    """

    model_config = ConfigDict(frozen=True)

    label: str
    amount: Paise = ZERO
    detail: str = ""
    sources: tuple[str, ...] = ()


class Answer(BaseModel):
    """A reply to one question about one reconciled month."""

    model_config = ConfigDict(frozen=True)

    asked: str
    """The question as it was typed. Kept so a transcript reads back."""

    intent: str | None
    """Which of the known questions this was read as, or `None`.

    `None` is a refusal, and it is a first-class outcome rather than an
    error. A settlement question this cannot answer is far better met with
    "I do not answer that, here is what I do answer" than with a plausible
    paragraph about the wrong month - the second is how a finance tool loses
    the right to be trusted with the first.
    """

    headline: str
    """The answer in one sentence, with its number in it."""

    lines: tuple[Line, ...] = ()
    routed_by: str = "rules"
    """`rules`, or the name of the model that read the question.

    Recorded per answer so the share of questions understood with no model at
    all is a measurement rather than a claim. It says nothing about where the
    numbers came from: those are arithmetic in every case, including this one.
    """

    subjects: tuple[str, ...] = ()
    """Record ids the reader can go and look at."""

    suggestions: tuple[str, ...] = ()
    """What this can answer. Populated only on a refusal."""

    @property
    def answered(self) -> bool:
        return self.intent is not None

    @property
    def total(self) -> Paise:
        return Paise(sum(line.amount for line in self.lines))
