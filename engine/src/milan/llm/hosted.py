"""The free hosted tiers, behind the same interface as the local one.

Two of them, and they exist for two different reasons. **Groq** is the escape
hatch named in the build order's cut rules: if Ollama will not run on a
reviewer's machine, one environment variable moves the whole system to a
hosted model without a line of code changing. **Gemini** is the second
opinion - the agreement rate between two unrelated models is a far more
honest statement about how much a model contributes here than either model's
own output.

Both are free tiers. A paid key would make every number in this project
unreproducible for anyone who does not have one, which is most of the point
of publishing them.

An absent key is not an error. It means this provider is unavailable, the
same way an unreachable daemon does, and the run continues on the
deterministic summaries.
"""

from __future__ import annotations

import os
import time
from typing import Any

from milan.llm.provider import Completion, Request
from milan.llm.transport import get_json, post_json

GROQ_KEY_ENV = "GROQ_API_KEY"
GROQ_MODEL_ENV = "MILAN_GROQ_MODEL"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
"""Groq's catalogue moved under us. `llama-3.3-70b-versatile` was wired in
here, tested against a recorded body, and had been retired by the time a live
key was available - the API answers `model_not_found` for it now. Every
general-purpose model Groq currently serves is a reasoning model, which is a
fact the answer budget has to account for rather than a detail."""

GEMINI_KEY_ENV = "GEMINI_API_KEY"
GEMINI_MODEL_ENV = "MILAN_GEMINI_MODEL"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_DEFAULT_MODEL = "gemini-3.1-flash-lite"
"""Not the flagship, and the reason is a quota rather than a preference.

`gemini-2.0-flash` was wired in here and returns 404 now, with a message
naming its replacement. That replacement, `gemini-3.6-flash`, allows **twenty
requests a day** on the free tier - one fifth of a single ablation - so a run
against it measures the quota rather than the model. Flash Lite answers the
same hundred and ten questions inside the free allowance, and it answers them
without thinking first, which is why it needs a twentieth of the output
tokens."""

DEFAULT_TIMEOUT = 60.0

RETRIES = 4
"""Attempts to make when a free tier says "not so fast".

Groq's free tier is eight thousand tokens a minute, and one ablation asks a
hundred and ten questions of a model that thinks in paragraphs. Without this
the run answered ten of them and reported a two point seven percent agreement
rate - which is a measurement of the rate limit wearing a model's name."""


def _unanswered(name: str, model: str, elapsed: float = 0.0) -> Completion:
    return Completion(text="", provider=name, model=model, latency_seconds=elapsed)


def _usage(
    answer: dict[str, Any] | None, block: str, prompt_key: str, *output_keys: str
) -> tuple[int, int]:
    """Both token counters out of a usage block, or zeros.

    The two APIs disagree about every name here - `usage.prompt_tokens`
    against `usageMetadata.promptTokenCount` - so the keys are arguments
    rather than a shape. Same defensiveness as the text extractors: a
    rate-limit body is valid JSON with none of these keys, and a cost figure
    is never worth failing a run over.

    More than one output key, because Gemini reports the tokens it spent
    thinking separately from the ones it said out loud - and bills both as
    output. Counting only what it said would understate the cost of a
    thinking model by an order of magnitude, in the direction an error is
    least likely to be questioned in.
    """
    if not isinstance(answer, dict):
        return 0, 0
    usage = answer.get(block)
    if not isinstance(usage, dict):
        return 0, 0

    def counted(key: str) -> int:
        value = usage.get(key)
        return value if isinstance(value, int) and value >= 0 else 0

    return counted(prompt_key), sum(counted(key) for key in output_keys)


class GroqProvider:
    """Groq's OpenAI-compatible chat endpoint."""

    name = "groq"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        seed: int | None = 0,
    ) -> None:
        self.model = model or os.environ.get(GROQ_MODEL_ENV) or GROQ_DEFAULT_MODEL
        self._key = api_key or os.environ.get(GROQ_KEY_ENV) or ""
        self.timeout = timeout
        self.seed = seed
        """Fixed at zero, and honoured on a best-effort basis: Groq documents
        `seed` as a hint rather than a guarantee. `None` omits it."""

    def ready(self) -> bool:
        """Whether a key is configured. Deliberately no network call.

        Whether the *model* still exists is a separate question with a
        separate cost, and it is asked by `catalogue()` from the one command
        that is meant to go and look.
        """
        return bool(self._key)

    def catalogue(self) -> tuple[str, ...]:
        """Every model this key can reach, or nothing if the list is not
        available. Groq serves it on the OpenAI-compatible path."""
        payload = get_json(
            GROQ_MODELS_URL,
            timeout=10.0,
            headers={"Authorization": f"Bearer {self._key}"},
        )
        if not isinstance(payload, dict):
            return ()
        data = payload.get("data")
        if not isinstance(data, list):
            return ()
        return tuple(
            str(entry["id"]) for entry in data if isinstance(entry, dict) and "id" in entry
        )

    def complete(self, request: Request) -> Completion:
        if not self._key:
            return _unanswered(self.name, self.model)

        started = time.perf_counter()
        model = request.model or self.model
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if self.seed is not None:
            body["seed"] = self.seed

        answer = post_json(
            GROQ_URL,
            body,
            timeout=self.timeout,
            headers={"Authorization": f"Bearer {self._key}"},
            retries=RETRIES,
        )
        elapsed = time.perf_counter() - started
        used = _usage(answer, "usage", "prompt_tokens", "completion_tokens")
        return Completion(
            text=_first_choice(answer),
            provider=self.name,
            model=model,
            latency_seconds=elapsed,
            prompt_tokens=used[0],
            completion_tokens=used[1],
        )


def _first_choice(answer: dict[str, Any] | None) -> str:
    """The message text, or "" the moment the shape is not what was expected.

    Written defensively rather than with `answer["choices"][0]["message"]`,
    because a rate-limit body from a free tier is valid JSON with none of
    those keys, and an IndexError here would fail a reconciliation over a
    quota.
    """
    if not isinstance(answer, dict):
        return ""
    choices = answer.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content if isinstance(content, str) else ""


class GeminiProvider:
    """Google's `generateContent`, free tier."""

    name = "gemini"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.model = model or os.environ.get(GEMINI_MODEL_ENV) or GEMINI_DEFAULT_MODEL
        self._key = api_key or os.environ.get(GEMINI_KEY_ENV) or ""
        self.timeout = timeout

    def ready(self) -> bool:
        return bool(self._key)

    def catalogue(self) -> tuple[str, ...]:
        """Google returns ids as `models/gemini-3.6-flash`; the prefix is
        stripped so both providers answer in the same vocabulary."""
        payload = get_json(
            GEMINI_MODELS_URL,
            timeout=10.0,
            headers={"x-goog-api-key": self._key},
        )
        if not isinstance(payload, dict):
            return ()
        models = payload.get("models")
        if not isinstance(models, list):
            return ()
        return tuple(
            str(entry["name"]).removeprefix("models/")
            for entry in models
            if isinstance(entry, dict) and "name" in entry
        )

    def complete(self, request: Request) -> Completion:
        if not self._key:
            return _unanswered(self.name, self.model)

        started = time.perf_counter()
        model = request.model or self.model
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": request.prompt}]}],
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
            },
        }
        if request.system:
            payload["systemInstruction"] = {"parts": [{"text": request.system}]}

        answer = post_json(
            GEMINI_URL.format(model=model),
            payload,
            timeout=self.timeout,
            # In the header rather than the query string: a key on a URL ends
            # up in proxy logs and in shell history, and this one belongs to
            # whoever runs the project.
            headers={"x-goog-api-key": self._key},
            retries=RETRIES,
        )
        elapsed = time.perf_counter() - started
        used = _usage(
            answer,
            "usageMetadata",
            "promptTokenCount",
            "candidatesTokenCount",
            "thoughtsTokenCount",
        )
        return Completion(
            text=_first_part(answer),
            provider=self.name,
            model=model,
            latency_seconds=elapsed,
            prompt_tokens=used[0],
            completion_tokens=used[1],
        )


def _first_part(answer: dict[str, Any] | None) -> str:
    """The first text part of the first candidate, or "".

    Same defensiveness as `_first_choice`, and for one more reason: a response
    blocked by a safety filter comes back with `candidates` present and
    `content` absent, which indexing would turn into a KeyError.
    """
    if not isinstance(answer, dict):
        return ""
    candidates = answer.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    first = candidates[0]
    if not isinstance(first, dict):
        return ""
    content = first.get("content")
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        return ""
    text = parts[0].get("text") if isinstance(parts[0], dict) else None
    return text if isinstance(text, str) else ""
