"""Reading API keys from a file the repository is told to ignore.

An API key has to reach the process somehow, and every route people actually
use is worse than this one. Exporting it in a shell leaves it in the history
file. Putting it on the command line leaves it in the process table, visible
to every other user on the machine. Pasting it into a chat window or an issue
leaves it somewhere that is backed up, indexed, and outside your control - a
key that has been pasted anywhere is burned whether or not anyone noticed, and
the only fix is rotation.

So: `engine/.env`, which `.gitignore` has excluded since before this file
existed. One `NAME=value` per line.

Two rules, and both of them are the point:

**A key already in the environment always wins.** A file cannot silently
replace a key that CI, a secret manager, or the person at the keyboard has
already set. Reading a file is a convenience; overriding a deliberate export
would make it a trap.

**It is loaded at an entry point, not on demand.** `cli/main.py` and
`api/app.py` call it at import; the registry does not. That is deliberate -
`load_keyfile` mutates `os.environ`, and a call buried inside `resolve()`
would quietly undo a test's `monkeypatch.delenv` in the middle of the test
that set it. The cost is a real trap, hit while writing this: a one-off script
that imports `milan.llm.registry` directly gets no key and sees both hosted
providers answer nothing in zero seconds, which looks exactly like two dead
keys. Such a script should call this first.

**Nothing here ever prints a value.** Not on success, not in an error, not
truncated to the first six characters. The one thing this module exists to
protect is a string, and a log line is one of the places it must not go.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["KEYFILE", "default_keyfile", "load_keyfile"]

KEYFILE = ".env"


def default_keyfile() -> Path:
    """`engine/.env`, found from this file rather than the working directory.

    Deliberately not `Path.cwd() / ".env"`. `milan` is installed as a command
    and gets run from wherever the merchant's files happen to be, and a key
    that loads from one directory and not another is worse than one that never
    loads at all - the second failure is obvious and the first looks like the
    hosted provider being down.
    """
    return Path(__file__).resolve().parents[3] / KEYFILE


def load_keyfile(path: Path | None = None) -> tuple[str, ...]:
    """Put any names the file defines into the environment. Returns the names.

    The names, never the values. A caller that wants to tell someone which
    keys were found can say so without holding one.

    A missing file is not an error and does not warn. The default
    configuration of this project has no hosted provider in it, and every
    graded number is measured with no model at all - so having no key file is
    the normal case, not a broken one.
    """
    source = path if path is not None else default_keyfile()
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ()

    loaded: list[str] = []
    for line in text.splitlines():
        name, value = _entry(line)
        if not name or name in os.environ:
            continue
        os.environ[name] = value
        loaded.append(name)
    return tuple(loaded)


def _entry(line: str) -> tuple[str, str]:
    """One `NAME=value` line, or a pair of empty strings if it is not one.

    Handles the three things people actually put in these files: a leading
    `export`, surrounding quotes, and comments. Anything more elaborate is a
    shell script, and a shell script is not what this reads.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return "", ""

    name, _, value = stripped.partition("=")
    name = name.removeprefix("export ").strip()
    if not name.replace("_", "").isalnum():
        return "", ""

    value = value.strip()
    if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return name, value
