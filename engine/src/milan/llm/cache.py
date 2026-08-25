"""A content-addressed cache in front of any provider.

Two reasons, and the second matters more than the first.

**Cost.** Every free tier has a rate limit, and re-running an evaluation
should not spend it re-asking questions that were already answered.

**Reproducibility.** A cached run is a deterministic run. Once an answer is on
disk, the same seed produces the same output for anyone who has the cache -
including a reviewer who has no API key and no local model at all. That turns
"here are our numbers" into "here are our numbers, and here is the run".

The key is the hash of the whole request, so changing the prompt, the model or
the temperature is a different question and gets a different answer rather
than quietly reusing the old one.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from milan.llm.provider import Completion, Provider, Request


class ResponseCache:
    """Answers on disk, addressed by the hash of the question."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self.hits = 0
        self.misses = 0

    def path_for(self, request: Request) -> Path:
        """Shard by the first two hex characters.

        A single directory with tens of thousands of files is slow to list on
        Windows and unpleasant to inspect by hand. Both matter: this cache is
        meant to be committed and read.
        """
        digest = request.fingerprint()
        return self._root / digest[:2] / f"{digest}.json"

    def get(self, request: Request) -> Completion | None:
        path = self.path_for(request)
        if not path.is_file():
            self.misses += 1
            return None
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A half-written or hand-edited entry is a miss, not a crash. The
            # cache is an optimisation; it must never be able to fail a run.
            self.misses += 1
            return None
        self.hits += 1
        return Completion.model_validate(stored).model_copy(update={"cached": True})

    def put(self, request: Request, completion: Completion) -> None:
        """Store an answer. Unanswered completions are not stored.

        Caching a failure would make an outage permanent: every later run
        would read back the empty answer and never retry.
        """
        if not completion.answered:
            return
        path = self.path_for(request)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = completion.model_copy(update={"cached": False})
        temporary = path.with_suffix(".tmp")
        temporary.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)


class CachedProvider:
    """Any provider, with the cache in front of it."""

    def __init__(self, inner: Provider, cache: ResponseCache) -> None:
        self._inner = inner
        self._cache = cache
        self.name = inner.name

    def complete(self, request: Request) -> Completion:
        cached = self._cache.get(request)
        if cached is not None:
            return cached

        started = time.perf_counter()
        completion = self._inner.complete(request)
        timed = completion.model_copy(update={"latency_seconds": time.perf_counter() - started})
        self._cache.put(request, timed)
        return timed
