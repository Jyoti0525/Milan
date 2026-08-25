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

    def test_sweep_runs_and_reports_a_denominator(self) -> None:
        """The sweep generates its own datasets and stores nothing, so it
        takes no data root. What it must show is the `of` column: a pooled
        rate without the count behind it is the single-seed problem again in
        a longer sentence."""
        result = runner.invoke(app, ["sweep", "--seeds", "3", "--orders", "150"])

        assert result.exit_code == 0, result.output
        assert "shortfalls named" in result.output
        assert "Worst seed" in result.output

    def test_sweep_markdown_is_plain_and_fenced(self) -> None:
        """It exists to be pasted into the README unchanged, so it must not
        arrive wrapped or styled."""
        result = runner.invoke(app, ["sweep", "--seeds", "2", "--orders", "150", "--markdown"])

        assert result.exit_code == 0, result.output
        assert result.output.strip().startswith("<!-- generated: sweep -->")
        assert result.output.strip().endswith("<!-- /generated -->")
        assert "|---|" in result.output

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
        config = GenerationConfig(seed=42, difficulty=difficulty, order_count=200)
        dataset = ChaosEngine(config).generate()
        store.save_dataset(dataset, tmp_path, config)
        reloaded = store.load_dataset(tmp_path, 42, difficulty)

        assert store.content_hash(dataset) == store.content_hash(reloaded)
        assert reloaded.record_count == dataset.record_count
        assert reloaded.answer_key == dataset.answer_key


class TestAStoredRunHasToStillBeCurrent:
    """A dataset is only trustworthy because it is a pure function of its
    config. Once the generator moves, the file still loads and still looks
    well formed, and every number scored against it is about a merchant this
    code no longer produces."""

    def test_a_run_whose_config_no_longer_produces_it_is_refused(self, tmp_path: Path) -> None:
        config = GenerationConfig(seed=42, difficulty=Difficulty.MESSY, order_count=120)
        store.save_dataset(ChaosEngine(config).generate(), tmp_path, config)

        # Stand in for a generator change by moving the config out from under
        # the data. The engine cannot rebuild this dataset from that config,
        # which is exactly the state a real change leaves behind.
        store.write(
            config.model_copy(update={"order_count": 121}),
            store.run_directory(tmp_path, 42, Difficulty.MESSY) / store.CONFIG_FILE,
        )

        with pytest.raises(store.StaleDatasetError, match="different version"):
            store.load_dataset(tmp_path, 42, Difficulty.MESSY)

    def test_a_run_with_no_config_beside_it_is_refused(self, tmp_path: Path) -> None:
        config = GenerationConfig(seed=42, difficulty=Difficulty.CLEAN, order_count=80)
        store.save_dataset(ChaosEngine(config).generate(), tmp_path, config)
        (store.run_directory(tmp_path, 42, Difficulty.CLEAN) / store.CONFIG_FILE).unlink()

        with pytest.raises(store.StaleDatasetError, match="no config beside it"):
            store.load_dataset(tmp_path, 42, Difficulty.CLEAN)

    def test_verify_can_be_switched_off_for_inspecting_a_file(self, tmp_path: Path) -> None:
        """The library keeps an escape hatch; the CLI deliberately does not."""
        config = GenerationConfig(seed=42, difficulty=Difficulty.CLEAN, order_count=80)
        store.save_dataset(ChaosEngine(config).generate(), tmp_path, config)
        (store.run_directory(tmp_path, 42, Difficulty.CLEAN) / store.CONFIG_FILE).unlink()

        assert store.load_dataset(tmp_path, 42, Difficulty.CLEAN, verify=False).seed == 42

    def test_the_command_line_says_what_to_do_rather_than_traceback(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            app, ["eval", "--difficulty", "messy", "--data-root", str(tmp_path)]
        )
        assert result.exit_code == 1
        # Whitespace collapsed before matching, because rich wraps to the
        # console width and the message contains a tmp_path - so whether
        # "milan generate" survived on one line depended on how many times
        # pytest had been run on this machine. It passed at pytest-99 and
        # failed at pytest-101. A test whose result depends on a directory
        # counter is not testing the thing it names.
        assert "milan generate" in " ".join(result.output.split())
