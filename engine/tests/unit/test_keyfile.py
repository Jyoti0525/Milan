"""Reading API keys from a file, and refusing to do the dangerous parts."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from milan.llm.keyfile import default_keyfile, load_keyfile


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_name_the_file_defines_reaches_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    loaded = load_keyfile(write(tmp_path, "GROQ_API_KEY=abc123\n"))

    assert loaded == ("GROQ_API_KEY",)
    assert os.environ["GROQ_API_KEY"] == "abc123"


def test_a_key_already_exported_is_never_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file is a convenience. Overriding a deliberate export is a trap.

    CI sets these from a secret manager, and a stale `.env` left in a working
    copy that silently won would send a run at the wrong account with no
    indication anywhere that it had happened.
    """
    monkeypatch.setenv("GROQ_API_KEY", "the-one-that-was-exported")

    loaded = load_keyfile(write(tmp_path, "GROQ_API_KEY=the-one-in-the-file\n"))

    assert loaded == ()
    assert os.environ["GROQ_API_KEY"] == "the-one-that-was-exported"


def test_a_missing_file_is_the_normal_case_and_not_an_error(tmp_path: Path) -> None:
    """Every graded number in this project is measured with no model at all,
    so having no key file is the default configuration rather than a fault."""
    assert load_keyfile(tmp_path / "nothing-here") == ()


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("GEMINI_API_KEY=plain", "plain"),
        ('GEMINI_API_KEY="double quoted"', "double quoted"),
        ("GEMINI_API_KEY='single quoted'", "single quoted"),
        ("export GEMINI_API_KEY=exported", "exported"),
        ("  GEMINI_API_KEY = spaced  ", "spaced"),
    ],
)
def test_the_shapes_people_actually_put_in_these_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, line: str, expected: str
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    load_keyfile(write(tmp_path, line + "\n"))

    assert os.environ["GEMINI_API_KEY"] == expected


def test_comments_and_blanks_and_prose_are_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    text = "# rotate these quarterly\n\nnot a setting at all\nGROQ_API_KEY=kept\n"

    assert load_keyfile(write(tmp_path, text)) == ("GROQ_API_KEY",)


def test_nothing_that_is_not_a_name_becomes_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A line that half-parses must not put a garbage key in the environment.

    `os.environ` is process-global and this runs at import, so a malformed
    file that produced entries would leak them into every later call in the
    process rather than failing where it could be seen.
    """
    loaded = load_keyfile(write(tmp_path, "some prose = with an equals sign\n"))

    assert loaded == ()


def test_no_value_is_ever_returned_to_a_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The names, never the values.

    The one thing this module exists to protect is a string, and a caller that
    can print what it loaded is a caller that eventually does.
    """
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    secret = "sk-do-not-print-me"

    loaded = load_keyfile(write(tmp_path, f"GROQ_API_KEY={secret}\n"))

    assert secret not in "".join(loaded)


def test_the_file_is_looked_for_beside_the_engine_not_in_the_working_directory() -> None:
    """`milan` gets run from wherever the merchant's files are.

    A key that loads from one directory and not another is worse than one that
    never loads: the second failure is obvious, and the first looks exactly
    like the hosted provider being down.
    """
    found = default_keyfile()

    assert found.name == ".env"
    assert found.parent.name == "engine"
