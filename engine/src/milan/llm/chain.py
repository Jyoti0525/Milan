"""Several providers in preference order, and the first one that answers.

The problem this solves is a free tier, which is not a switch but a budget.
Groq's is eight thousand tokens a minute; Gemini's is a request count per day.
A run long enough to be worth measuring outlives both, and what happens at
that moment decides whether the run is a result or a measurement of a quota:
without this, every question after the budget runs out is scored as a model
that declined to answer.

So the order is a preference and the fallback is the point. Ask the best
model. When it stops answering, ask the next one. Keep going down the list
until somebody does, and the local model is last because it is the one that
cannot run out.

**Order is measured, not assumed.** `milan ablate --all` scores every provider
on the same shortfalls, and the default order below is what it reported:
gpt-oss-120b agrees with the arithmetic on 35.2% of them, Gemini Flash Lite on
26.8%, Qwen 2.5 3B on 15.5%. Re-run it before changing the order, and change
the order when it says to.

Two things this deliberately does **not** do.

It does not ask a provider that has stopped answering. A budget that is spent
stays spent for the rest of the run, and Groq's transport waits up to ninety
seconds across four retries before giving up - so retrying an exhausted
provider on all hundred and ten questions turns a two-minute run into a
three-hour one and gets the same nothing at the end of it.

It does not hide which model answered. A chained run is a mixture, and
reporting a mixture under one name is the kind of number this project exists
not to print. Every completion carries the name of the provider that produced
it, and `tally` says how the run divided.
"""

from __future__ import annotations

from collections.abc import Iterable

from milan.llm.provider import Completion, Provider, Request

__all__ = ["PREFERENCE", "Chain", "Link"]

PREFERENCE: tuple[str, ...] = ("groq", "gemini", "ollama")
"""Best first, by measured agreement on shortfall triage. See the module note.

`none` is absent on purpose. It answers nothing by design, so a chain ending
in it would spend a link discovering that - and a chain that *starts* with it
would stand it down after two questions and silently become the chain without
it, which is a confusing way to write the same thing.
"""

PATIENCE = 2
"""Consecutive silences before a provider is set aside for the rest of the run.

Not one. A single unanswered question is as likely to be one oversized prompt
as an exhausted budget, and standing a model down over it would throw away the
better model for the whole run on the strength of one question.

Not five either. Every strike against an exhausted hosted provider costs the
full retry ladder - up to ninety seconds a time - so patience is paid for in
minutes, and two is enough to tell a blip from a wall.
"""


class Link:
    """One provider in the chain, and how it has been doing.

    A small mutable object rather than a tuple, because the whole mechanism is
    that this remembers. A chain that recomputed availability per question
    would ask an exhausted provider every time.
    """

    __slots__ = ("answered", "asked", "provider", "strikes")

    def __init__(self, provider: Provider) -> None:
        self.provider = provider
        self.asked = 0
        self.answered = 0
        self.strikes = 0

    @property
    def name(self) -> str:
        return self.provider.name

    @property
    def standing(self) -> bool:
        """Whether this link is still worth asking."""
        return self.strikes < PATIENCE

    def ask(self, request: Request) -> Completion:
        self.asked += 1
        completion = self.provider.complete(request)
        if completion.answered:
            self.answered += 1
            # Reset rather than decrement. Consecutive silences are the signal
            # - a provider that answers nine questions and misses one has not
            # run out of anything, and carrying that miss forward would stand
            # it down on the tenth miss of a thousand questions.
            self.strikes = 0
        else:
            self.strikes += 1
        return completion


class Chain:
    """Ask each provider in turn, and return the first real answer."""

    def __init__(self, providers: Iterable[Provider]) -> None:
        self.links = tuple(Link(provider) for provider in providers)
        if not self.links:
            raise ValueError("a chain needs at least one provider")
        self.name = "+".join(link.name for link in self.links)
        """Every link, in order, so a table column says what it is.

        Not "chain". A column headed `chain` in a comparison of providers
        names nothing a reader could reproduce, and reproducing it is the only
        reason the column is there.
        """

    @property
    def model(self) -> str:
        """The first link's model, for anything that wants to name one.

        Honest only because of where the cache sits. Each link is wrapped in
        its own cache *before* it reaches the chain, so an answer is stored
        under the model that gave it; if the chain were wrapped instead, this
        one name would key every provider's answers into one entry and the
        second model asked would silently replay the first one's. That bug has
        been made once here already, across two sizes of the same model, and
        it looked like a finding rather than a fault.
        """
        first = getattr(self.links[0].provider, "model", "")
        return first if isinstance(first, str) else ""

    def complete(self, request: Request) -> Completion:
        """The first answer from a provider still standing, or silence.

        The returned completion is the answering provider's own, name and
        model included, so a caller recording "who said this" records the
        model rather than the chain.
        """
        last: Completion | None = None
        for link in self.links:
            if not link.standing:
                continue
            completion = link.ask(request)
            if completion.answered:
                return completion
            last = completion

        # Everything is spent or unreachable. Returning the last unanswered
        # completion rather than inventing one keeps the provider name of
        # whoever was asked last, which is what a reader needs in order to go
        # and look at a quota.
        return last if last is not None else Completion(text="", provider=self.name)

    def tally(self) -> tuple[tuple[str, int, int, bool], ...]:
        """Per link: its name, questions put to it, answers, still standing.

        The composition of the run. A chained ablation is a mixture of models
        and its headline rate belongs to no single one of them, so the mixture
        has to be printable or the headline is misleading.
        """
        return tuple((link.name, link.asked, link.answered, link.standing) for link in self.links)

    @property
    def mixed(self) -> bool:
        """Whether more than one provider actually answered anything."""
        return sum(1 for link in self.links if link.answered) > 1
