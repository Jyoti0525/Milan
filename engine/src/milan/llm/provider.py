"""The contract any language model has to fit behind.

Deliberately narrow. A provider takes text and returns text, and it is not
allowed to do anything else - no tool calls, no arithmetic, no access to the
ledger. Everything Milan reports about money is computed deterministically
before a provider is ever consulted, so the worst a bad model can do here is
produce a poor explanation of a number that is already correct.

The default provider returns nothing at all. That is not a stub waiting to be
replaced: `NullProvider` is the configuration every graded number is measured
under, and the system has to be complete without a model for the measurement
to mean anything.
"""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class Request(BaseModel):
    """One question for a model.

    Frozen and fully specified, because it doubles as the cache key. A field
    that affects the answer and is not on this model would make two different
    questions collide in the cache and return each other's answers.
    """

    model_config = ConfigDict(frozen=True)

    prompt: str
    system: str = ""
    model: str = ""
    max_tokens: int = Field(default=512, gt=0)

    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    """Zero by default, and it should stay there.

    A reconciliation tool that answers differently on a second run is not
    reproducible, and reproducibility is the claim this project is built on.
    Sampling is a knob for prose, and none of this output is prose.
    """

    def fingerprint(self) -> str:
        """A stable content address for this exact question.

        Sorted keys and a canonical separator, so the same request always
        hashes the same way regardless of field order or Python version.
        """
        payload = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Completion(BaseModel):
    """What came back, and where from."""

    model_config = ConfigDict(frozen=True)

    text: str
    provider: str
    model: str = ""
    cached: bool = False
    latency_seconds: float = 0.0

    prompt_tokens: int = 0
    completion_tokens: int = 0
    """What the model actually consumed, read from the provider's own
    counters rather than estimated from the text.

    Carried because a cost figure has to be measured like everything else
    here. Estimating tokens from characters would put a number in a table
    that nobody could check against a bill, which is the same failure as
    every other unmeasured claim in this project. Zero means the provider
    did not report them - not that nothing was spent.
    """

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def answered(self) -> bool:
        """Whether a model actually said something.

        Callers must check this rather than assuming text. A provider that is
        unavailable, rate-limited or switched off returns an unanswered
        completion instead of raising, so an absent model degrades the output
        rather than ending the run.
        """
        return bool(self.text.strip())


class Provider(Protocol):
    """Anything that can turn a request into a completion."""

    name: str

    def complete(self, request: Request) -> Completion:
        """Answer, or return an unanswered completion. Never raise."""
        ...


class NullProvider:
    """Answers nothing, always.

    The configuration every graded number in this project is measured under.
    Running the whole pipeline against this provider is what proves the claim
    that no reported figure depends on a model, so it is a first-class
    implementation rather than a placeholder.
    """

    name = "none"

    def complete(self, request: Request) -> Completion:
        del request
        return Completion(text="", provider=self.name)


class StaticProvider:
    """Returns a fixed answer. For tests, and for demonstrating the seam.

    Useful precisely because it is deterministic: a test that exercises the
    path through the cache and the categoriser should not also be testing
    whether a model happened to say something sensible today.
    """

    name = "static"

    def __init__(self, answer: str) -> None:
        self._answer = answer
        self.calls = 0

    def complete(self, request: Request) -> Completion:
        del request
        self.calls += 1
        return Completion(text=self._answer, provider=self.name)
