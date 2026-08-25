"""The ablation, end to end, with a provider that is not a model.

The unit tests hold the pieces - the prompt, the parser, the verifier, the
counters. None of them ran the thing that wires those together, and the
coverage report said so: `ablate.py` at 39%, the CLI command and the table
renderer at zero. That is precisely the failure the build order's definition
of done is written against - *it has a test, it runs from the seeded command*
- and a measurement nobody runs in CI is a measurement that quietly stops
working.

`StaticProvider` rather than Ollama, on purpose. These have to pass on a
machine with no daemon and no key, and what is under test is the wiring, not
whether a 3B model happened to be right today.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from milan.chaos.config import Difficulty
from milan.cli.main import app
from milan.cli.render import ablation_table
from milan.evaluation.ablate import ablate
from milan.llm.provider import NullProvider, StaticProvider

runner = CliRunner()


def flat(output: str) -> str:
    """Console output with its wrapping removed.

    Rich wraps to the console width, so whether a phrase survives on one line
    depends on the width the suite happens to run at. A sibling test in
    `test_cli.py` passed at `pytest-99` and failed at `pytest-101` because a
    tmp_path grew by two characters and moved the wrap point.
    """
    return " ".join(output.split())


SEEDS = (1, 2)
"""Two adversarial seeds is about a dozen shortfalls - enough for every
counter to move, few enough to keep this test in the default run."""


class TestTheDriver:
    def test_it_finds_shortfalls_to_ask_about(self) -> None:
        """The bug this file exists because of.

        The first working version of `ablate` reported 0/0 on every count,
        because it read shortfalls from the path that proves *accepted*
        matches. Nearly every shortfall in this system is found on the other
        path - proving vetoes matching inside the cascade, so a credit that
        will not reconstruct has its claim withdrawn before it is ever
        reported as matched - and an ablation with nothing to ask about looks
        exactly like a model that had nothing to add.
        """
        result = ablate(NullProvider(), Difficulty.ADVERSARIAL, SEEDS, orders=600)
        assert result.asked > 0, "no shortfalls were put to the provider"

    def test_a_silent_provider_answers_nothing_and_breaks_nothing(self) -> None:
        result = ablate(NullProvider(), Difficulty.ADVERSARIAL, SEEDS, orders=600)
        assert result.answered == 0
        assert result.agreement_hits == 0
        assert result.contributions == 0

    def test_every_shortfall_it_asks_about_was_already_named(self) -> None:
        """The claim behind the published `contribution: 0/0`.

        Not an assumption - if the rules ever stop naming a shortfall the
        engine reaches, this fails and the contribution figure becomes a real
        fraction that has to be measured rather than a division by zero.
        """
        result = ablate(NullProvider(), Difficulty.ADVERSARIAL, SEEDS, orders=600)
        assert result.open_cases == 0
        assert result.agreement_cases == result.asked

    def test_a_confidently_wrong_provider_contributes_nothing(self) -> None:
        """A model naming a refund that does not exist gets nothing printed,
        and gets counted for having tried."""
        liar = StaticProvider('{"kind": "recovery_gap", "entity_id": "rfnd_ghost"}')
        result = ablate(liar, Difficulty.ADVERSARIAL, SEEDS, orders=600)

        assert result.answered == result.asked
        assert result.agreement_hits == 0
        assert result.contributions == 0
        assert result.invented_ids == result.asked

    def test_a_provider_that_declines_invents_nothing(self) -> None:
        result = ablate(
            StaticProvider('{"kind": "unknown"}'), Difficulty.ADVERSARIAL, SEEDS, orders=600
        )
        assert result.invented_ids == 0
        assert result.rejected == 0
        assert result.kinds == {"unknown": result.asked}

    def test_the_same_seeds_give_the_same_answer(self) -> None:
        """The ablation is a published figure, so it is held to the same
        reproducibility the rest of the project claims."""
        provider = StaticProvider('{"kind": "unknown"}')
        first = ablate(provider, Difficulty.ADVERSARIAL, SEEDS, orders=600)
        second = ablate(provider, Difficulty.ADVERSARIAL, SEEDS, orders=600)
        assert first.agreement_cases == second.agreement_cases
        assert first.kinds == second.kinds

    def test_a_clean_tier_has_nothing_to_ask(self) -> None:
        """No shortfalls at all on the clean tier, and that is not an error."""
        result = ablate(NullProvider(), Difficulty.CLEAN, (1,), orders=200)
        assert result.asked == 0
        assert result.agreement_rate == 0.0
        assert result.contribution_rate == 0.0


class TestTheCommand:
    def test_it_runs_with_no_model_present(self) -> None:
        """`--provider none` is the configuration a reviewer's machine is in,
        and it has to produce a table rather than a stack trace."""
        result = runner.invoke(
            app, ["ablate", "--provider", "none", "--seeds", "1", "--orders", "400"]
        )
        assert result.exit_code == 0, result.output
        assert "agreement with the rules" in flat(result.output)

    def test_it_says_so_when_the_model_answered_nothing(self) -> None:
        """Otherwise a stopped daemon and a useless model produce the same
        table, and the reader cannot tell which they are looking at."""
        result = runner.invoke(
            app, ["ablate", "--provider", "none", "--seeds", "1", "--orders", "400"]
        )
        assert "answered none of" in flat(result.output)

    def test_an_unknown_provider_is_refused_with_the_list(self) -> None:
        result = runner.invoke(app, ["ablate", "--provider", "gpt-9", "--seeds", "1"])
        assert result.exit_code == 2
        assert "ollama" in flat(result.output)

    @pytest.mark.parametrize("difficulty", ["clean", "realistic", "messy", "adversarial"])
    def test_it_runs_on_every_tier(self, difficulty: str) -> None:
        result = runner.invoke(
            app,
            [
                "ablate",
                "--provider",
                "none",
                "--seeds",
                "1",
                "--orders",
                "200",
                "--difficulty",
                difficulty,
            ],
        )
        assert result.exit_code == 0, result.output


class TestTheTable:
    def test_it_renders_the_two_rates_separately(self) -> None:
        """A reader who conflates agreement and contribution concludes either
        that a competent model is useless or that a useless one is competent,
        so they never share a row."""
        result = ablate(
            StaticProvider('{"kind": "unknown"}'), Difficulty.ADVERSARIAL, (1,), orders=600
        )
        rendered = ablation_table(result)
        text = "\n".join(
            "".join(str(cell) for cell in column._cells) for column in rendered.columns
        )
        assert "agreement with the rules" in text
        assert "contribution beyond them" in text
        assert "identifiers invented" in text

    def test_it_survives_an_empty_run(self) -> None:
        result = ablate(NullProvider(), Difficulty.CLEAN, (1,), orders=200)
        assert ablation_table(result) is not None
