"""The commands, and the files they hand each other.

Neither of these was tested until a `--withholding` flag went in that typer
never registered. The mistake survived because the command was run with its
output redirected, so a usage error looked exactly like success. A smoke test
that asserts an exit code would have caught it in seconds.

The round-trip matters for a different reason. `milan recon` reconciles what
`milan generate` wrote, so a field lost in serialisation would mean every
number downstream was measured against data that was never generated - and
nothing anywhere would fail.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.cli.main import app
from milan.persistence import store

runner = CliRunner()
ALL_TIERS = pytest.mark.parametrize("difficulty", list(Difficulty))


def generate(root: Path, *extra: str) -> None:
    result = runner.invoke(
        app,
        ["generate", "--seed", "42", "--orders", "120", "--data-root", str(root), *extra],
    )
    assert result.exit_code == 0, result.output


class TestEveryCommandRuns:
    def test_generate_then_recon_then_eval(self, tmp_path: Path) -> None:
        generate(tmp_path)
        for command in ("recon", "eval"):
            result = runner.invoke(app, [command, "--seed", "42", "--data-root", str(tmp_path)])
            assert result.exit_code == 0, result.output

    def test_eval_detail_renders(self, tmp_path: Path) -> None:
        """The detail table reads fields the summary does not.

        A metric added to the scorecard and rendered nowhere is invisible;
        one rendered wrongly raises only on this path.
        """
        generate(tmp_path)
        result = runner.invoke(
            app, ["eval", "--seed", "42", "--data-root", str(tmp_path), "--detail"]
        )
        assert result.exit_code == 0, result.output
        assert "sorted without a model" in result.output

    def test_withholding_is_accepted_and_changes_the_data(self, tmp_path: Path) -> None:
        """The flag that shipped broken.

        Asserting it is accepted is not enough - a flag typer registers and
        the command ignores fails the same way, silently.
        """
        plain, withheld = tmp_path / "plain", tmp_path / "withheld"
        generate(plain)
        generate(withheld, "--withholding")

        before = store.load_dataset(plain, 42, Difficulty.REALISTIC)
        after = store.load_dataset(withheld, 42, Difficulty.REALISTIC)
        assert sum(t.tds for t in before.answer_key.credits) == 0
        assert sum(t.tds for t in after.answer_key.credits) > 0

    def test_prove_explains_a_credit(self, tmp_path: Path) -> None:
        generate(tmp_path)
        dataset = store.load_dataset(tmp_path, 42, Difficulty.REALISTIC)
        target = next(
            truth.credit_id
            for truth in dataset.answer_key.credits
            if truth.matchable and truth.provable and truth.settlement_ids
        )
        result = runner.invoke(
            app, ["prove", target[:14], "--seed", "42", "--data-root", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output
        assert "Unexplained" in result.output

    def test_prove_says_why_when_there_is_nothing_to_show(self, tmp_path: Path) -> None:
        """Failing with a bare non-zero exit would be worse than useless."""
        generate(tmp_path)
        result = runner.invoke(
            app, ["prove", "bank_nosuchcredit", "--seed", "42", "--data-root", str(tmp_path)]
        )
        assert result.exit_code == 1
        assert "No credit" in result.output

    def test_reproduce_confirms_determinism(self) -> None:
        result = runner.invoke(app, ["reproduce", "--seed", "42", "--orders", "120"])
        assert result.exit_code == 0, result.output
        assert "Identical" in result.output


class TestThePipesBetweenCommands:
    @ALL_TIERS
    def test_a_saved_dataset_reloads_byte_for_byte(
        self, tmp_path: Path, difficulty: Difficulty
    ) -> None:
        dataset = ChaosEngine(
            GenerationConfig(seed=42, difficulty=difficulty, order_count=200)
        ).generate()
        store.save_dataset(dataset, tmp_path)
        reloaded = store.load_dataset(tmp_path, 42, difficulty)

        assert store.content_hash(dataset) == store.content_hash(reloaded)
        assert reloaded.record_count == dataset.record_count
        assert reloaded.answer_key == dataset.answer_key
