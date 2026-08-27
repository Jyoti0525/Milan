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

from pydantic import BaseModel, ConfigDict

from milan.llm.cache import CachedProvider, ResponseCache
from milan.llm.chain import PREFERENCE, Chain
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


def direct(name: str | None = None) -> Provider:
    """The provider with no cache in front of it.

    One caller, and it needs saying why. `milan twice` asks the same question
    twice on purpose; through the cache the second ask would be a disk read
    of the first answer, and the experiment would report perfect stability
    by never running.
    """
    chosen = (name or os.environ.get(PROVIDER_ENV) or "none").strip().lower()
    return _BUILDERS.get(chosen, NullProvider)()


class Status(BaseModel):
    """Whether one provider could answer right now, and why not."""

    model_config = ConfigDict(frozen=True)

    name: str
    model: str
    ready: bool
    reason: str


def status() -> tuple[Status, ...]:
    """Ask every registered provider whether it is usable.

    Exists because `ready()` was written, tested and called by nothing. A
    check nobody can run is a check nobody runs - and this is the one people
    need most: an unset key and an unreachable daemon both look exactly like
    a working setup until the first answer comes back empty.
    """
    found: list[Status] = []
    for name in available():
        provider = _BUILDERS[name]()
        model = getattr(provider, "model", "")
        check = getattr(provider, "ready", None)
        if check is None:
            found.append(
                Status(
                    name=name,
                    model=model,
                    ready=True,
                    reason="the baseline every graded number is measured under",
                )
            )
            continue
        ready = bool(check())
        reason = _why_not(provider, ready)
        if ready:
            ready, reason = _still_served(provider, model)
        found.append(Status(name=name, model=model, ready=ready, reason=reason))
    return tuple(found)


def _still_served(provider: Provider, model: str) -> tuple[bool, str]:
    """Whether the configured model is still in this key's catalogue.

    Written after a key that worked perfectly reported `model_not_found`.
    Both hosted defaults in this project had been retired by their vendors
    between being wired in and being run, and `ready()` said yes to both -
    because it was answering "is a key set" while the question people ask it
    is "will this answer".

    A provider with no catalogue, or one that will not serve the list, is
    left alone. An unreachable list is not evidence that a model is gone.
    """
    catalogue = getattr(provider, "catalogue", None)
    if catalogue is None:
        return True, ""
    served = catalogue()
    if not served or model in served:
        return True, ""
    return False, f"key works, but {model} is not in its catalogue"


def _why_not(provider: Provider, ready: bool) -> str:
    """The next thing to do about it, rather than a status word.

    A daemon that is running without the model is the failure people
    actually hit, and it is worth telling apart from a daemon that is not
    running at all: one needs `ollama pull`, the other needs `ollama serve`.
    """
    if ready:
        return ""
    installed = getattr(provider, "installed_models", None)
    if installed is not None:
        models = installed()
        if not models:
            return "no daemon answering - start it with `ollama serve`"
        return f"daemon up, model missing - `ollama pull {getattr(provider, 'model', '')}`"
    return "no API key in the environment"


def unpinned(provider: Provider) -> Provider:
    """The same provider, with its sampler seed unset where it has one.

    Every run that reports a number pins the seed. This exists for the one
    experiment that must not: asking whether a model answers the same way
    twice is unanswerable if the sampler has been told to repeat itself.

    Gemini has no seed parameter to unset, which is worth knowing rather than
    working around - a provider that cannot be pinned cannot be made
    reproducible at all.
    """
    if hasattr(provider, "seed"):
        provider.seed = None
    return provider


CHAIN = "chain"
"""The name that means "every provider that can answer, best first"."""


def resolve(name: str | None = None, cache_root: Path | None = None) -> Provider:
    """Build the configured provider, wrapped in its cache.

    Three shapes of name, and the last two are the same mechanism:

    * `groq` - one provider.
    * `groq,gemini,ollama` - those providers in that order, falling through
      to the next when one stops answering.
    * `chain` - every provider that is ready right now, in the measured
      preference order.

    An unknown name falls back to `none` rather than raising. A typo in an
    environment variable should degrade the explanations, never stop a
    reconciliation - every number the run reports is computed before a
    provider is consulted.
    """
    chosen = (name or os.environ.get(PROVIDER_ENV) or "none").strip().lower()
    root = cache_root or default_cache_root()

    if chosen == CHAIN:
        return _chain(_ready_in_preference_order(), root)
    if "," in chosen:
        named = tuple(part.strip() for part in chosen.split(",") if part.strip())
        return _chain(named, root)

    build = _BUILDERS.get(chosen, NullProvider)
    provider = build()
    if isinstance(provider, NullProvider):
        # Nothing to cache, and an empty cache directory would imply otherwise.
        return provider
    return CachedProvider(provider, ResponseCache(root))


def _ready_in_preference_order() -> tuple[str, ...]:
    """The preferred providers that could answer right now, best first.

    Filtered by readiness rather than handed the whole preference list. An
    unset key is not a provider that ran out mid-run; it is one that was never
    there, and letting the chain discover that costs two questions and up to
    three minutes of retries to learn something `providers` already knew.
    """
    usable = {found.name for found in status() if found.ready}
    return tuple(name for name in PREFERENCE if name in usable)


def _chain(names: tuple[str, ...], cache_root: Path) -> Provider:
    """Build the named providers into a chain, each behind its own cache.

    The cache goes *inside* each link and never around the chain. A cache in
    front of the chain would key every answer under one model name, so the
    second provider asked would replay the first one's answer - the exact bug
    `CachedProvider._keyed` was written to fix, reintroduced one layer up.
    """
    links: list[Provider] = []
    for name in names:
        build = _BUILDERS.get(name)
        if build is None:
            continue
        provider = build()
        if isinstance(provider, NullProvider):
            # `none` answers nothing by design. A link that exists to be
            # silent would be stood down after two questions and turn the
            # chain into the chain without it, slowly.
            continue
        links.append(CachedProvider(provider, ResponseCache(cache_root)))

    if not links:
        return NullProvider()
    if len(links) == 1:
        # A chain of one is a provider. Wrapping it would put a second name on
        # a column and a fallback story on a run that has nothing to fall to.
        return links[0]
    return Chain(links)
