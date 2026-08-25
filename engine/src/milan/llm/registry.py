"""Choosing a provider without the rest of the system knowing which.

One function, one environment variable, and a default that needs nothing
installed. Everything above this line asks for a provider and gets one; it
never learns whether a model answered, only whether the completion did.

The provider list is deliberately all free options. A paid key would make the
project unreproducible for anyone without one, which defeats the point of
publishing the numbers.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from milan.llm.cache import CachedProvider, ResponseCache
from milan.llm.hosted import GeminiProvider, GroqProvider
from milan.llm.ollama import OllamaProvider
from milan.llm.provider import NullProvider, Provider

PROVIDER_ENV = "MILAN_LLM_PROVIDER"
CACHE_ENV = "MILAN_LLM_CACHE"

_BUILDERS: dict[str, Callable[[], Provider]] = {
    "none": NullProvider,
    "ollama": OllamaProvider,
    "groq": GroqProvider,
    "gemini": GeminiProvider,
}
"""Every provider this project will talk to, and all of them free.

`none` stays the default and stays first. It is not the fallback for when the
others are missing - it is the configuration every graded number in this
project is measured under, and the others are the experiment.
"""


def default_cache_root() -> Path:
    configured = os.environ.get(CACHE_ENV)
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[4] / "data" / "llm-cache"


def available() -> tuple[str, ...]:
    return tuple(sorted(_BUILDERS))


def resolve(name: str | None = None, cache_root: Path | None = None) -> Provider:
    """Build the configured provider, wrapped in its cache.

    An unknown name falls back to `none` rather than raising. A typo in an
    environment variable should degrade the explanations, never stop a
    reconciliation - every number the run reports is computed before a
    provider is consulted.
    """
    chosen = (name or os.environ.get(PROVIDER_ENV) or "none").strip().lower()
    build = _BUILDERS.get(chosen, NullProvider)
    provider = build()
    if isinstance(provider, NullProvider):
        # Nothing to cache, and an empty cache directory would imply otherwise.
        return provider
    return CachedProvider(provider, ResponseCache(cache_root or default_cache_root()))
