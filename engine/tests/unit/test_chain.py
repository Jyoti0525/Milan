"""Falling through from one provider to the next when a budget runs out."""

from __future__ import annotations

from pathlib import Path

import pytest

from milan.llm.chain import PATIENCE, PREFERENCE, Chain
from milan.llm.provider import Completion, NullProvider, Provider, Request
from milan.llm.registry import resolve


class Says:
    """A provider that answers a fixed number of times and then stops.

    Modelled on a free tier rather than on a switch, because that is the
    failure this exists for: a provider that works perfectly and then, part
    way through a run, stops - without an error, without a different status,
    just silence where an answer was.
    """

    def __init__(self, name: str, answers: int = 1_000, model: str = "") -> None:
        self.name = name
        self.model = model or f"{name}-model"
        self._left = answers
        self.asked = 0

    def complete(self, request: Request) -> Completion:
        del request
        self.asked += 1
        if self._left <= 0:
            return Completion(text="", provider=self.name, model=self.model)
        self._left -= 1
        return Completion(text=f"answer from {self.name}", provider=self.name, model=self.model)


def question() -> Request:
    return Request(prompt="why is this payout short?", max_tokens=64)


def ask(chain: Chain, times: int) -> list[str]:
    return [chain.complete(question()).provider for _ in range(times)]


# ------------------------------------------------------------ the happy path


def test_the_first_provider_answers_and_the_rest_are_never_asked() -> None:
    """Preference means preference. A chain that asked everybody and picked
    would spend the budget it exists to conserve."""
    best, second = Says("groq"), Says("gemini")

    answered = Chain([best, second]).complete(question())

    assert answered.provider == "groq"
    assert second.asked == 0


def test_the_answer_carries_the_model_that_gave_it() -> None:
    """A caller recording who said this has to record a model, not a chain.

    Everything downstream that reports a rate per provider reads this, so a
    completion labelled with the chain would file every model's answers under
    one name and make the comparison meaningless.
    """
    answered = Chain([Says("groq", model="gpt-oss-120b")]).complete(question())

    assert answered.provider == "groq"
    assert answered.model == "gpt-oss-120b"


# ----------------------------------------------------------- running out


def test_the_next_provider_takes_over_when_the_first_stops_answering() -> None:
    """The whole point: a spent budget must not become a column of silences."""
    best, second = Says("groq", answers=3), Says("gemini")

    who = ask(Chain([best, second]), 8)

    assert who[:3] == ["groq"] * 3
    assert who[3:] == ["gemini"] * 5


def test_a_spent_provider_stops_being_asked_at_all() -> None:
    """Not a correctness point - a wall-clock one, and a large one.

    A hosted provider that has run out still costs the full retry ladder on
    every question, up to ninety seconds a time. Asking it once per question
    for the rest of a hundred-and-ten-question run turns two minutes into
    three hours and collects the same nothing.
    """
    best, second = Says("groq", answers=0), Says("gemini")

    ask(Chain([best, second]), 10)

    assert best.asked == PATIENCE, "it should be set aside, not asked ten times"
    assert second.asked == 10


def test_one_silence_does_not_throw_away_the_better_model() -> None:
    """A single unanswered question is as likely to be one oversized prompt as
    an exhausted budget, and standing a model down over it would give up the
    better model for a whole run on the strength of one question."""

    class Hiccups:
        name = "groq"
        model = "gpt-oss-120b"

        def __init__(self) -> None:
            self.asked = 0

        def complete(self, request: Request) -> Completion:
            del request
            self.asked += 1
            text = "" if self.asked == 2 else "an answer"
            return Completion(text=text, provider=self.name, model=self.model)

    flaky = Hiccups()

    who = ask(Chain([flaky, Says("gemini")]), 6)

    assert who.count("groq") == 5
    assert who.count("gemini") == 1


def test_answering_again_clears_the_strikes() -> None:
    """Consecutive silences are the signal. A provider that misses one question
    in every ten has not run out of anything, and counting misses cumulatively
    would stand it down on the twentieth question of two hundred."""

    class EveryOther:
        name = "groq"
        model = "m"

        def __init__(self) -> None:
            self.asked = 0

        def complete(self, request: Request) -> Completion:
            del request
            self.asked += 1
            return Completion(
                text="" if self.asked % 2 == 0 else "yes", provider=self.name, model=self.model
            )

    patchy = EveryOther()
    chain = Chain([patchy, Says("gemini")])

    ask(chain, 20)

    assert patchy.asked > PATIENCE * 2, "it should never have been set aside"


def test_when_everything_is_spent_the_chain_is_silent_rather_than_wrong() -> None:
    """Silence is a real answer here. Inventing one would put a model's name
    on a claim no model made."""
    chain = Chain([Says("groq", answers=0), Says("gemini", answers=0)])

    assert not chain.complete(question()).answered


# ------------------------------------------------------------- reporting


def test_the_chain_names_its_links_rather_than_calling_itself_chain() -> None:
    """A column headed `chain` in a provider comparison names nothing a reader
    could reproduce, and reproducing it is the only reason the column exists."""
    assert Chain([Says("groq"), Says("gemini")]).name == "groq+gemini"


def test_the_tally_says_how_the_run_divided() -> None:
    """A chained run is a mixture of models, and its headline rate belongs to
    no single one of them. The mixture has to be printable or the headline is
    a number attributed to the wrong model."""
    chain = Chain([Says("groq", answers=3), Says("gemini")])

    ask(chain, 8)

    assert chain.tally() == (("groq", 5, 3, False), ("gemini", 5, 5, True))
    assert chain.mixed


def test_a_run_that_never_fell_through_is_not_reported_as_mixed() -> None:
    chain = Chain([Says("groq"), Says("gemini")])

    ask(chain, 5)

    assert not chain.mixed


def test_a_chain_needs_something_in_it() -> None:
    with pytest.raises(ValueError, match="at least one"):
        Chain([])


# -------------------------------------------------------------- the registry


def test_a_comma_separated_name_builds_a_chain(tmp_path: Path) -> None:
    built = resolve("groq,gemini,ollama", cache_root=tmp_path)

    assert isinstance(built, Chain)
    assert built.name == "groq+gemini+ollama"


def test_a_chain_of_one_is_just_that_provider(tmp_path: Path) -> None:
    """Wrapping it would put a second name on a column and a fallback story on
    a run with nothing to fall back to."""
    built = resolve("groq", cache_root=tmp_path)

    assert not isinstance(built, Chain)


def test_none_is_dropped_from_a_chain_rather_than_occupying_a_link(
    tmp_path: Path,
) -> None:
    """`none` answers nothing by design, so a link holding it would be stood
    down after two questions - turning the chain into the chain without it,
    slowly and for no reason."""
    built = resolve("none,groq,gemini", cache_root=tmp_path)

    assert isinstance(built, Chain)
    assert built.name == "groq+gemini"


def test_a_chain_of_nothing_usable_is_the_null_provider(tmp_path: Path) -> None:
    built = resolve("none,nonsense", cache_root=tmp_path)

    assert isinstance(built, NullProvider)


def test_each_link_carries_its_own_cache(tmp_path: Path) -> None:
    """The cache goes inside each link and never around the chain.

    A cache in front would key every answer under one model name, so the
    second provider asked would replay the first one's answer - the exact bug
    `CachedProvider._keyed` exists to prevent, reintroduced one layer up where
    that fix cannot see it.
    """
    built = resolve("groq,gemini", cache_root=tmp_path)

    assert isinstance(built, Chain)
    models = {getattr(link.provider, "model", "") for link in built.links}

    assert len(models) == len(built.links), "two links must not share one model name"
    assert "" not in models, "a cached link must still say which model it wraps"


def test_the_preference_order_puts_the_measured_best_first() -> None:
    """`milan ablate --all` scores every provider on the same shortfalls, and
    reported 35.2% for gpt-oss-120b, 26.8% for Gemini Flash Lite and 15.5% for
    Qwen 2.5 3B. The order here is that result, and this asserts they have not
    drifted apart silently."""
    assert PREFERENCE == ("groq", "gemini", "ollama")
    assert "none" not in PREFERENCE


def test_every_name_in_the_preference_order_is_a_provider_that_exists(
    tmp_path: Path,
) -> None:
    """A typo here would be invisible: the link is skipped, the chain still
    builds, and the best model silently never gets asked."""
    for name in PREFERENCE:
        built: Provider = resolve(name, cache_root=tmp_path)
        assert not isinstance(built, NullProvider), name
