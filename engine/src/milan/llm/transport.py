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
import urllib.error
import urllib.request
from typing import Any

USER_AGENT = "milan/0.1"


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """POST JSON and decode JSON back. `None` for every failure.

    Deliberately silent. A caller that wants to know whether a model answered
    asks the `Completion`, and a caller that wants to know why looks at the
    provider's own diagnostics - a warning logged from here would print once
    per exception on a run with no model configured, which is the common case.
    """
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
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, ValueError):
        # URLError covers a refused connection and an HTTP error status alike;
        # OSError covers the socket dying mid-read; ValueError covers both a
        # URL that cannot be parsed and a body that is not JSON. None of them
        # are worth distinguishing, because the answer to all of them is the
        # same one.
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
