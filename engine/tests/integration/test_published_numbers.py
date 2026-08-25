"""The README's table has to be the table the command prints.

Every other test in this suite checks that the engine is right. This one
checks that what we *say about it* is right, which is a separate failure with
its own history: the README's match rates were current while its refusal
column had been carried over from an earlier run, and nothing on screen or in
CI could tell.

A wrong number in a README is not a documentation problem in a project whose
entire claim is measurement. It is the claim being wrong.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.cli.render import MARKDOWN_CLOSE, MARKDOWN_OPEN, evaluation_markdown
from milan.evaluation.harness import evaluate

README = Path(__file__).resolve().parents[3] / "README.md"

# The exact run the README says it is quoting. If this and the README's
# reproduce command ever disagree, one of them is lying to a reader.
PUBLISHED = GenerationConfig(
    seed=42, difficulty=Difficulty.ADVERSARIAL, order_count=600, span_days=21
)


def _published_block() -> str:
    body = README.read_text(encoding="utf-8")
    found = re.search(
        f"{re.escape(MARKDOWN_OPEN)}.*?{re.escape(MARKDOWN_CLOSE)}", body, flags=re.DOTALL
    )
    assert found is not None, f"no generated eval block in {README}"
    return found.group(0).strip()


class TestTheReadmeIsCurrent:
    def test_the_table_matches_a_fresh_run(self) -> None:
        """Regenerate, rescore, and compare against what is published."""
        dataset = ChaosEngine(PUBLISHED).generate()
        produced = evaluation_markdown(evaluate(dataset)).strip()
        assert produced == _published_block(), (
            "README.md is out of date. Refresh it with:\n"
            "  uv run milan generate --seed 42 --difficulty adversarial --orders 600\n"
            "  uv run milan eval --seed 42 --difficulty adversarial --markdown"
        )

    def test_the_readme_tells_the_reader_how_to_reproduce_it(self) -> None:
        """A published number with no command beside it is an assertion."""
        body = README.read_text(encoding="utf-8")
        assert f"--orders {PUBLISHED.order_count}" in body
        assert f"--difficulty {PUBLISHED.difficulty.value}" in body
        assert f"--seed {PUBLISHED.seed}" in body

    @pytest.mark.parametrize("stale", ["| 8/8 |", "23.8% | 100.0% | 8/8"])
    def test_the_superseded_figures_are_gone(self, stale: str) -> None:
        """Guards the specific wrong numbers this test was written for."""
        assert stale not in README.read_text(encoding="utf-8")
