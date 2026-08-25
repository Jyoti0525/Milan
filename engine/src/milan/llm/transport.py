"""One HTTP POST, and every way it can fail turned into `None`.

`urllib` rather than `httpx` or `requests`. Every call in this package is a
single JSON POST to one endpoint, and adding an HTTP client to the runtime
dependencies of a reconciliation engine to make three of those is a heavier
dependency than the thing it does. `httpx` is already here as a dev
dependency for the API tests, and it stays there.

The contract is the whole point of the module: **this never raises.** A
provider that throws when the daemon is not running, or when a free tier
returns 429, would let a missing model fail a reconciliation - and every
figure this engine reports is computed before a provider is ever consulted.
An unreachable model is allowed to cost an explanation. It is not allowed to
cost a run.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

USER_AGENT = "milan/0.1"

RETRYABLE = frozenset({429, 500, 502, 503, 504})
"""Statuses worth asking again about.

429 is the one that matters. A free tier is a rate limit, and an evaluation
that quietly loses a hundred of its hundred and ten questions to one has
measured the limit rather than the model - which is a far worse outcome than
a slow run, because it looks like a result.
"""

MAX_WAIT = 90.0
"""The longest a single retry will sleep, however long the server asks for.

A provider that says "come back in an hour" is telling you to run this later,
not to block a reconciliation for an hour.
"""


def _wait_for(failure: urllib.error.HTTPError, attempt: int) -> float:
    """How long to wait: what the server asked for, or a doubling fallback."""
    asked = failure.headers.get("Retry-After") if failure.headers else None
    if isinstance(asked, str) and asked:
        try:
            return min(float(asked), MAX_WAIT)
        except ValueError:
            # A date rather than a count of seconds. Parsing HTTP dates to
            # save one backoff is not worth the surface.
            pass
    return min(5.0 * 2.0**attempt, MAX_WAIT)


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
    retries: int = 0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | None:
    """POST JSON and decode JSON back. `None` for every failure.

    Deliberately silent. A caller that wants to know whether a model answered
    asks the `Completion`, and a caller that wants to know why looks at the
    provider's own diagnostics - a warning logged from here would print once
    per exception on a run with no model configured, which is the common case.

    Retries are off by default and used only by the hosted providers, where a
    free tier's token-per-minute budget is exhausted long before an evaluation
    is. A local daemon that refuses a connection will refuse the next one too,
    and sleeping over it would turn "no model configured" into a slow run.
    """
    for attempt in range(retries + 1):
        answer = _attempt(url, payload, timeout, headers, attempt, retries, sleep)
        if answer is _RETRY:
            continue
        return answer if isinstance(answer, dict) else None
    return None


_RETRY = object()
"""Distinct from `None`, which means "give up". Needed because a failed
attempt that is worth repeating and one that is not both have no answer."""


def _attempt(
    url: str,
    payload: dict[str, Any],
    timeout: float,
    headers: dict[str, str] | None,
    attempt: int,
    retries: int,
    sleep: Callable[[float], None],
) -> Any:
    try:
        # Building the request is inside the try, not before it. A URL with no
        # scheme raises ValueError in the constructor rather than at send, so
        # a misconfigured MILAN_OLLAMA_HOST took down the run it was supposed
        # to degrade - the one failure mode this module exists to prevent,
        # reachable from a typo in an environment variable.
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                **(headers or {}),
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as failure:
        # Caught before URLError, which it subclasses, because this is the one
        # failure with a status worth reading: a rate limit is temporary and
        # everything else here is not.
        if failure.code not in RETRYABLE or attempt >= retries:
            return None
        sleep(_wait_for(failure, attempt))
        return _RETRY
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, ValueError):
        # URLError covers a refused connection; OSError covers the socket
        # dying mid-read; ValueError covers both a URL that cannot be parsed
        # and a body that is not JSON. None of them are worth distinguishing,
        # because the answer to all of them is the same one.
        return None
    return decoded if isinstance(decoded, dict) else None


def get_json(url: str, *, timeout: float, headers: dict[str, str] | None = None) -> Any | None:
    """GET JSON. `None` for every failure. Used only for health checks."""
    try:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"User-Agent": USER_AGENT, **(headers or {})},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, ValueError):
        return None
