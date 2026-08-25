"""A model running on this machine.

The default local option, and the reason the project can claim a zero-rupee
cost with a straight face: Qwen 2.5 3B at four-bit quantisation is about two
gigabytes, which fits on the 4 GB RTX 3050 this was built on, and it runs
without an account, a key or a network.

Nothing here is allowed to fail a run. If the daemon is not running, if the
model was never pulled, if generation takes longer than the timeout - the
answer is an unanswered completion, and the exception it would have explained
keeps the deterministic summary the categoriser already gave it.
"""

from __future__ import annotations

import os
import time

from milan.llm.provider import Completion, Request
from milan.llm.transport import get_json, post_json

HOST_ENV = "MILAN_OLLAMA_HOST"
MODEL_ENV = "MILAN_OLLAMA_MODEL"

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:3b"

DEFAULT_TIMEOUT = 120.0
"""Generous, and it has to be.

A 3B model on a laptop GPU answers a short prompt in a few seconds once it is
resident, and takes the best part of a minute the first time while the weights
are loaded from disk. A timeout tight enough to feel responsive would turn the
first question of every session into a failure.
"""


class OllamaProvider:
    """Ollama's `/api/generate`, with every failure mode flattened."""

    name = "ollama"

    def __init__(
        self,
        model: str | None = None,
        host: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        seed: int | None = 0,
    ) -> None:
        self.model = model or os.environ.get(MODEL_ENV) or DEFAULT_MODEL
        self.host = (host or os.environ.get(HOST_ENV) or DEFAULT_HOST).rstrip("/")
        self.timeout = timeout
        self.seed = seed
        """The sampler's seed, fixed at zero for every run that reports a
        number. `None` lets the daemon pick one, which is what an ordinary
        integration does by default - and the only setting under which the
        question "does a model answer the same way twice" can be asked
        honestly."""

    def installed_models(self) -> tuple[str, ...]:
        """What this daemon can serve, or nothing if it is not answering."""
        payload = get_json(f"{self.host}/api/tags", timeout=5.0)
        if not isinstance(payload, dict):
            return ()
        models = payload.get("models")
        if not isinstance(models, list):
            return ()
        return tuple(
            str(entry["name"]) for entry in models if isinstance(entry, dict) and "name" in entry
        )

    def ready(self) -> bool:
        """Whether this exact model is here, not merely whether Ollama is.

        A running daemon with the model absent is the failure people actually
        hit, and it looks identical to a working setup until the first
        question comes back empty.
        """
        installed = self.installed_models()
        return any(name == self.model or name.startswith(f"{self.model}:") for name in installed)

    def complete(self, request: Request) -> Completion:
        started = time.perf_counter()
        model = request.model or self.model
        options: dict[str, object] = {
            "temperature": request.temperature,
            "num_predict": request.max_tokens,
        }
        if self.seed is not None:
            # Ollama seeds per request. Fixed, because a reconciliation tool
            # that answers differently on a second run is not reproducible,
            # and temperature zero alone does not guarantee it across every
            # sampler. Omitted entirely when unpinned, so the daemon picks.
            options["seed"] = self.seed
        payload = {
            "model": model,
            "prompt": request.prompt,
            "system": request.system,
            "stream": False,
            "options": options,
        }
        answer = post_json(f"{self.host}/api/generate", payload, timeout=self.timeout)
        elapsed = time.perf_counter() - started
        if answer is None:
            return Completion(text="", provider=self.name, model=model, latency_seconds=elapsed)

        text = answer.get("response")
        return Completion(
            text=text if isinstance(text, str) else "",
            provider=self.name,
            model=model,
            latency_seconds=elapsed,
            prompt_tokens=_count(answer, "prompt_eval_count"),
            completion_tokens=_count(answer, "eval_count"),
        )


def _count(answer: dict[str, object], key: str) -> int:
    """One of Ollama's token counters, or zero.

    Absent on some builds and on a response cut short, and a missing counter
    is a reason to report zero rather than to fail a run over bookkeeping.
    """
    value = answer.get(key)
    return value if isinstance(value, int) and value >= 0 else 0
