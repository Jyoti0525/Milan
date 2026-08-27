"""A named reason that several exceptions are the same exception.

A reconciliation tool that hands a finance team thirty exceptions has moved
the work rather than done it. Thirty items is thirty decisions, and most of
them are the same decision made repeatedly: six credits short by the same
undisclosed rate is one question for an account manager, not six.

So the queue's real output is not a list, it is a small number of causes and
whatever genuinely did not fit one.

The rule that governs everything else in this project governs this too. A
cause is not a summary and not a theme - it is a claim with an arithmetic
test attached, and `because` states the test its members passed. Nothing is
grouped because it reads similarly.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from milan.domain.enums import ExceptionCode
from milan.domain.money import ZERO, Paise


class Cause(BaseModel):
    """One reason, and every exception that provably shares it."""

    model_config = ConfigDict(frozen=True)

    name: str
    """What this is, in a finance team's words rather than ours."""

    because: str
    """The test every member passed, with its numbers.

    This is the field that stops a cause being a guess. It has to be
    specific enough that a reader can disprove it - "all six were short by
    0.150% of their own gross" invites checking, "these look like fee
    issues" does not.
    """

    ask: str
    """The single question that would close every member at once.

    The reason to group at all. An exception queue tells somebody what is
    wrong; this tells them what to do about it, once, for the whole cluster.
    Empty when the answer is that nothing needs doing - which is a real and
    valuable outcome, and the one a merchant most wants to hear about nine
    items they were about to spend an afternoon on.
    """

    members: tuple[str, ...]
    """The subject ids, in the order the exceptions were raised."""

    total: Paise = ZERO
    """The money at stake across the cluster, always positive.

    Summed from the exceptions' own amounts, so a structural exception
    carrying no amount contributes nothing rather than being excluded.
    """

    codes: tuple[ExceptionCode, ...] = ()
    """Every exception code in the cluster, deduplicated.

    Usually one. More than one is not a defect: a payout run that never
    arrived produces a missing settlement and can leave unsettled payments
    behind it, and those belong to the same cause.
    """

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def actionable(self) -> bool:
        return bool(self.ask)


class Induction(BaseModel):
    """What the exception queue turned out to be.

    Carries the exceptions that did *not* join a cause as well as the ones
    that did, and reports the coverage as a fraction rather than a
    percentage of a number nobody sees. Forcing every exception into some
    cause would make the coverage figure meaningless and the causes wrong,
    so a queue of thirty that induces three causes over nineteen items is
    reported as exactly that.
    """

    model_config = ConfigDict(frozen=True)

    causes: tuple[Cause, ...]
    """Ranked by money at stake, largest first - which is the order a
    finance team works a queue in."""

    uncaused: tuple[str, ...]
    """Subject ids that stayed themselves. Not a failure: an exception with
    no sibling has no pattern to belong to, and inventing one for it would
    be the exact guess this refuses to make everywhere else."""

    @property
    def covered(self) -> int:
        return sum(cause.size for cause in self.causes)

    @property
    def total(self) -> int:
        return self.covered + len(self.uncaused)

    @property
    def share(self) -> float:
        """The fraction of the queue that turned out to be a pattern."""
        return self.covered / self.total if self.total else 0.0

    @property
    def reading(self) -> str:
        """The one line that goes above the queue."""
        if not self.total:
            return "Nothing to explain."
        if not self.causes:
            return f"{self.total} exceptions, no two of them the same. Every one is its own."
        return (
            f"{self.covered} of {self.total} exceptions are "
            f"{len(self.causes)} cause{'s' if len(self.causes) > 1 else ''}. "
            f"{len(self.uncaused)} stayed individual."
        )
