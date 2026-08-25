"""The claim that no reported figure depends on a model, made falsifiable.

This project says, in the README and in the submission, that every graded
number is computed deterministically and that a language model cannot move
one. That is the sort of claim which is true when written and quietly stops
being true nine commits later, when somebody wires a provider into the
categoriser because it was convenient.

So it is asserted structurally rather than behaviourally. A test that ran the
pipeline twice and compared numbers would only prove the model was not
consulted *on that data*; this proves it cannot be consulted at all, because
the reconciliation packages do not import the one that talks to models.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "src" / "milan"

SEALED = ("recon", "domain", "chaos")
"""The packages that produce every graded figure.

`domain` holds the money rules, `chaos` generates the data and the answer key,
and `recon` does the matching and the proving. Between them they decide every
number in the sweep. None of them may reach the `llm` package.
"""


def modules_in(package: str) -> list[Path]:
    return sorted((SOURCE / package).rglob("*.py"))


def imported_names(path: Path) -> set[str]:
    """Every module this file imports, by dotted name."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


@pytest.mark.parametrize("package", SEALED)
def test_the_scored_packages_cannot_reach_a_model(package: str) -> None:
    files = modules_in(package)
    assert files, f"no modules found in {package}, so this test proves nothing"

    for path in files:
        offending = {name for name in imported_names(path) if name.startswith("milan.llm")}
        assert not offending, (
            f"{path.relative_to(SOURCE)} imports {sorted(offending)}.\n"
            "Every figure this project publishes is computed in these packages, and "
            "the claim that no model can move one rests on them not being able to "
            "ask. If a model genuinely belongs in this path, the claim in the README "
            "has to change first."
        )


def test_the_evaluation_harness_is_also_sealed() -> None:
    """Scoring must not consult a model either.

    The ablation lives in the same package and does talk to one, which is the
    point of it - so this checks the modules that produce the scorecard rather
    than the whole directory.
    """
    for name in ("harness.py", "metrics.py", "sweep.py"):
        path = SOURCE / "evaluation" / name
        offending = {n for n in imported_names(path) if n.startswith("milan.llm")}
        assert not offending, f"evaluation/{name} imports {sorted(offending)}"


def test_the_ablation_does_reach_one() -> None:
    """The negative space of the tests above.

    If nothing imported `milan.llm`, every assertion here would pass on a
    project with no model support at all, and would keep passing after the
    seam was deleted.
    """
    reached = imported_names(SOURCE / "evaluation" / "ablation.py") | imported_names(
        SOURCE / "evaluation" / "ablate.py"
    )
    assert any(name.startswith("milan.llm") for name in reached)
