"""Three adapters, tested for the one property they all have to have.

Not "does the model give a good answer" - that is measured by the ablation,
against ground truth, and it is not a unit test. What is tested here is that
**none of them can fail a run**. A reconciliation whose numbers are all
computed before a provider is consulted must not fall over because a daemon
is stopped, a key is unset, or a free tier answered 429 with a JSON body that
has none of the keys the happy path indexes into.

Every test in this file passes with no Ollama running and no API key set,
which is the state a reviewer's machine will be in.
"""

from __future__ import annotations

from typing import Any

import pytest

from milan.llm.hosted import GeminiProvider, GroqProvider, _first_choice, _first_part
from milan.llm.ollama import OllamaProvider
from milan.llm.provider import NullProvider, Request
from milan.llm.registry import available, resolve
from milan.llm.transport import get_json, post_json

UNREACHABLE = "http://127.0.0.1:1"
"""Port 1 is privileged and nothing listens on it. A refused connection
arrives fast, which keeps these tests quick without mocking the socket."""


def question() -> Request:
    return Request(prompt="why is this credit short?", max_tokens=32)


class TestTheTransportSwallowsEverything:
    def test_a_refused_connection_is_none(self) -> None:
        assert post_json(f"{UNREACHABLE}/api/generate", {}, timeout=1.0) is None

    def test_a_refused_get_is_none(self) -> None:
        assert get_json(f"{UNREACHABLE}/api/tags", timeout=1.0) is None

    def test_a_malformed_url_is_none_rather_than_a_raise(self) -> None:
        """A misconfigured host is a configuration mistake, and it should
        degrade the explanations rather than end the run."""
        assert post_json("not-a-url", {}, timeout=1.0) is None
        assert get_json("http://", timeout=1.0) is None


class TestOllamaWithoutADaemon:
    @pytest.fixture
    def provider(self) -> OllamaProvider:
        return OllamaProvider(host=UNREACHABLE, timeout=1.0)

    def test_it_reports_no_models(self, provider: OllamaProvider) -> None:
        assert provider.installed_models() == ()

    def test_it_is_not_ready(self, provider: OllamaProvider) -> None:
        assert not provider.ready()

    def test_completing_returns_unanswered_rather_than_raising(
        self, provider: OllamaProvider
    ) -> None:
        completion = provider.complete(question())
        assert not completion.answered
        assert completion.provider == "ollama"

    def test_a_running_daemon_missing_this_model_is_not_ready(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure people actually hit. A daemon answering `/api/tags`
        looks like a working setup right up until the first empty answer."""
        provider = OllamaProvider(model="qwen2.5:3b")
        monkeypatch.setattr(
            "milan.llm.ollama.get_json",
            lambda *_args, **_kwargs: {"models": [{"name": "llama3:8b"}]},
        )
        assert provider.installed_models() == ("llama3:8b",)
        assert not provider.ready()

    def test_a_response_without_the_expected_key_is_unanswered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "milan.llm.ollama.post_json", lambda *_args, **_kwargs: {"error": "model not found"}
        )
        assert not OllamaProvider().complete(question()).answered


class TestTheHostedTiersWithoutAKey:
    @pytest.mark.parametrize("build", [GroqProvider, GeminiProvider])
    def test_an_absent_key_means_unavailable_not_broken(
        self, build: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        provider = build()
        assert not provider.ready()
        assert not provider.complete(question()).answered

    @pytest.mark.parametrize("build", [GroqProvider, GeminiProvider])
    def test_a_key_makes_it_ready_without_calling_anything(self, build: Any) -> None:
        assert build(api_key="test-key").ready()

    def test_groq_with_a_key_but_no_network_is_unanswered(self) -> None:
        provider = GroqProvider(api_key="test-key", timeout=1.0)
        assert not provider.complete(question()).answered


class TestARateLimitBodyIsNotACrash:
    """A free tier's 429 is valid JSON with none of the keys the happy path
    reads. Indexing into it would fail a reconciliation over a quota."""

    @pytest.mark.parametrize(
        "body",
        [
            None,
            {},
            {"error": {"message": "rate limit reached"}},
            {"choices": []},
            {"choices": [{}]},
            {"choices": [{"message": {}}]},
            {"choices": "not a list"},
        ],
    )
    def test_groq_shapes(self, body: Any) -> None:
        assert _first_choice(body) == ""

    @pytest.mark.parametrize(
        "body",
        [
            None,
            {},
            {"candidates": []},
            {"candidates": [{"finishReason": "SAFETY"}]},
            {"candidates": [{"content": {}}]},
            {"candidates": [{"content": {"parts": []}}]},
            {"candidates": [{"content": {"parts": [{}]}}]},
        ],
    )
    def test_gemini_shapes(self, body: Any) -> None:
        assert _first_part(body) == ""

    def test_the_happy_shapes_still_read(self) -> None:
        assert _first_choice({"choices": [{"message": {"content": "hello"}}]}) == "hello"
        assert _first_part({"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}) == "hi"


class TestTheRegistry:
    def test_every_provider_is_registered(self) -> None:
        assert available() == ("gemini", "groq", "none", "ollama")

    @pytest.mark.parametrize("name", ["ollama", "groq", "gemini"])
    def test_a_real_provider_is_wrapped_in_the_cache(self, name: str, tmp_path: Any) -> None:
        """Not for speed. A cached answer is what makes a run with a model
        reproducible for somebody who has neither the model nor a key."""
        provider = resolve(name, cache_root=tmp_path)
        assert provider.name == name
        assert type(provider).__name__ == "CachedProvider"

    def test_none_is_not_wrapped(self, tmp_path: Any) -> None:
        """An empty cache directory would imply questions were being asked."""
        assert isinstance(resolve("none", cache_root=tmp_path), NullProvider)

    def test_the_environment_selects_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MILAN_LLM_PROVIDER", "ollama")
        assert resolve().name == "ollama"

    def test_a_typo_still_degrades_to_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MILAN_LLM_PROVIDER", "olama")
        assert isinstance(resolve(), NullProvider)


class TestTheHappyPathsNobodyRunsInCi:
    """The bodies a working key would produce.

    Uncovered until the coverage report was read: every test above exercises
    a provider failing, which is the right emphasis but leaves the code that
    runs when things work never executed. A response shape that changed under
    us would have been found by a user, not by this suite.
    """

    def test_ollama_reads_a_generation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "milan.llm.ollama.post_json",
            lambda *_a, **_k: {"response": '{"kind": "unknown"}', "done": True},
        )
        completion = OllamaProvider().complete(question())
        assert completion.answered
        assert completion.text == '{"kind": "unknown"}'
        assert completion.model == "qwen2.5:3b"

    def test_groq_reads_a_chat_completion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def fake(url: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            captured["url"] = url
            captured["payload"] = payload
            captured["headers"] = kwargs.get("headers", {})
            return {"choices": [{"message": {"content": "answered"}}]}

        monkeypatch.setattr("milan.llm.hosted.post_json", fake)
        completion = GroqProvider(api_key="test-key").complete(question())

        assert completion.text == "answered"
        assert captured["headers"]["Authorization"] == "Bearer test-key"
        assert captured["payload"]["temperature"] == 0.0

    def test_gemini_reads_a_generate_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def fake(url: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            captured["url"] = url
            captured["payload"] = payload
            captured["headers"] = kwargs.get("headers", {})
            return {"candidates": [{"content": {"parts": [{"text": "answered"}]}}]}

        monkeypatch.setattr("milan.llm.hosted.post_json", fake)
        completion = GeminiProvider(api_key="test-key").complete(
            Request(prompt="why?", system="be brief", max_tokens=32)
        )

        assert completion.text == "answered"
        assert captured["headers"]["x-goog-api-key"] == "test-key"
        assert "systemInstruction" in captured["payload"]

    def test_the_gemini_key_never_goes_in_the_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A key on a query string ends up in proxy logs and shell history,
        and this one belongs to whoever runs the project."""
        captured: dict[str, Any] = {}

        def fake(url: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            captured["url"] = url
            return {}

        monkeypatch.setattr("milan.llm.hosted.post_json", fake)
        GeminiProvider(api_key="secret-key").complete(question())
        assert "secret-key" not in captured["url"]

    def test_a_request_model_overrides_the_configured_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("milan.llm.ollama.post_json", lambda *_a, **_k: {"response": "ok"})
        completion = OllamaProvider().complete(
            Request(prompt="why?", model="llama3:8b", max_tokens=16)
        )
        assert completion.model == "llama3:8b"
