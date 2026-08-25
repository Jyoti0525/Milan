"""The seam where a model may sit, tested with no model present.

Built before it is needed so the day it is needed is a wiring day. What is
worth testing now is not that a model answers well - none is connected - but
the three properties the rest of the system relies on:

1. The default configuration answers nothing, and nothing breaks.
2. A cached answer is byte-identical to the first one, which is what makes a
   run with a model still reproducible.
3. A failure is never cached, because caching an outage makes it permanent.
"""

from __future__ import annotations

from pathlib import Path

from milan.llm.cache import CachedProvider, ResponseCache
from milan.llm.provider import Completion, NullProvider, Request, StaticProvider
from milan.llm.registry import available, resolve


def question(prompt: str = "why is this credit short?") -> Request:
    return Request(prompt=prompt, model="test-model")


class TestTheDefaultIsNoModel:
    def test_the_null_provider_answers_nothing(self) -> None:
        completion = NullProvider().complete(question())
        assert not completion.answered
        assert completion.provider == "none"

    def test_an_unset_environment_resolves_to_it(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.delenv("MILAN_LLM_PROVIDER", raising=False)
        assert isinstance(resolve(), NullProvider)

    def test_an_unknown_provider_degrades_instead_of_raising(self) -> None:
        """A typo in an environment variable must not stop a reconciliation.

        Every figure the run reports is computed before a provider is
        consulted, so the correct response to a misconfigured model is worse
        explanations, not a failed run.
        """
        assert isinstance(resolve("gpt-nonexistent"), NullProvider)

    def test_none_is_registered_and_listed(self) -> None:
        assert "none" in available()


class TestTheCache:
    def test_the_second_answer_comes_from_disk(self, tmp_path: Path) -> None:
        inner = StaticProvider("the fee was charged at the corporate rate")
        provider = CachedProvider(inner, ResponseCache(tmp_path))

        first = provider.complete(question())
        second = provider.complete(question())

        assert inner.calls == 1, "the provider was asked twice for the same question"
        assert not first.cached
        assert second.cached
        assert second.text == first.text

    def test_a_different_question_is_a_different_answer(self, tmp_path: Path) -> None:
        inner = StaticProvider("an answer")
        provider = CachedProvider(inner, ResponseCache(tmp_path))

        provider.complete(question("why is this short?"))
        provider.complete(question("why is this over?"))
        assert inner.calls == 2

    def test_changing_the_temperature_is_a_different_question(self, tmp_path: Path) -> None:
        """Anything that can change the answer has to change the key, or two
        different questions collide and return each other's answers."""
        inner = StaticProvider("an answer")
        provider = CachedProvider(inner, ResponseCache(tmp_path))

        provider.complete(Request(prompt="p", temperature=0.0))
        provider.complete(Request(prompt="p", temperature=0.7))
        assert inner.calls == 2

    def test_two_models_answering_one_question_do_not_share_an_entry(self, tmp_path: Path) -> None:
        """The bug this was written for, and where it would have surfaced.

        A caller does not name a model; it asks a provider, and the provider
        uses the one it was built with. So `Request.model` was empty on every
        real request and the model was absent from the cache key - two
        different models answering the same question shared one entry, and
        the second replayed the first one's answer.

        Invisible everywhere except the one experiment this cache exists to
        make reproducible: a benchmark across model sizes would have printed
        two identical columns and read as a finding.
        """

        class Sized:
            """A provider that names its model, as the real ones do."""

            name = "sized"

            def __init__(self, model: str, answer: str) -> None:
                self.model = model
                self._answer = answer
                self.calls = 0

            def complete(self, request: Request) -> Completion:
                del request
                self.calls += 1
                return Completion(text=self._answer, provider=self.name, model=self.model)

        cache = ResponseCache(tmp_path)
        small = Sized("qwen2.5:1.5b", "refund rfnd_a")
        large = Sized("qwen2.5:3b", "refund rfnd_b")

        # No model on the request, which is the shape every real caller
        # sends: the triage asks a provider a question and leaves the choice
        # of model to whatever it was configured with.
        asked = Request(prompt="why is this credit short?")
        first = CachedProvider(small, cache).complete(asked)
        second = CachedProvider(large, cache).complete(asked)

        assert small.calls == 1 and large.calls == 1
        assert not second.cached
        assert second.text != first.text

    def test_an_unanswered_completion_is_never_stored(self, tmp_path: Path) -> None:
        """Caching a failure would make an outage permanent."""
        cache = ResponseCache(tmp_path)
        request = question()
        cache.put(request, Completion(text="", provider="none"))
        assert cache.get(request) is None

    def test_a_corrupt_entry_is_a_miss_not_a_crash(self, tmp_path: Path) -> None:
        """The cache is an optimisation and must never be able to fail a run."""
        cache = ResponseCache(tmp_path)
        request = question()
        path = cache.path_for(request)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ this is not json", encoding="utf-8")

        assert cache.get(request) is None

    def test_the_key_is_the_content_not_the_order_of_fields(self, tmp_path: Path) -> None:
        del tmp_path
        left = Request(prompt="p", system="s", model="m", max_tokens=10)
        right = Request(max_tokens=10, model="m", system="s", prompt="p")
        assert left.fingerprint() == right.fingerprint()
