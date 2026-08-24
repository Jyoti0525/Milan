"""Reading and writing runs.

Datasets are stored as canonical JSON rather than a columnar format. At the
sizes reconciliation actually runs at this is not the bottleneck, and JSON
buys two things that matter more: a byte-for-byte stable encoding that can be
hashed, and a file a human can open when a number looks wrong.

Nothing here is committed to version control. A dataset is a pure function of
its seed and difficulty, so the repository stores the generator instead of
its output.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel

from milan.chaos.config import Difficulty
from milan.domain.dataset import Dataset
from milan.domain.results import ReconReport

DATASET_FILE = "dataset.json"
REPORT_FILE = "report.json"
EVALUATION_FILE = "evaluation.json"


def default_root() -> Path:
    """`data/` beside the repository root, wherever the engine is installed."""
    return Path(__file__).resolve().parents[4] / "data"


def run_directory(root: Path, seed: int, difficulty: Difficulty | str) -> Path:
    name = difficulty.value if isinstance(difficulty, Difficulty) else difficulty
    return root / "runs" / f"{name}-seed{seed}"


def write(model: BaseModel, path: Path) -> Path:
    """Serialise one model to canonical JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    return path


def save_dataset(dataset: Dataset, root: Path) -> Path:
    directory = run_directory(root, dataset.seed, dataset.difficulty)
    return write(dataset, directory / DATASET_FILE)


def load_dataset(root: Path, seed: int, difficulty: Difficulty | str) -> Dataset:
    path = run_directory(root, seed, difficulty) / DATASET_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"no dataset at {path}. Generate one first: "
            f"milan generate --seed {seed} --difficulty "
            f"{difficulty.value if isinstance(difficulty, Difficulty) else difficulty}"
        )
    return Dataset.model_validate_json(path.read_text(encoding="utf-8"))


def save_report(report: ReconReport, root: Path) -> Path:
    directory = run_directory(root, report.seed, report.difficulty)
    return write(report, directory / REPORT_FILE)


def content_hash(model: BaseModel) -> str:
    """A stable digest of a model's canonical encoding.

    Used by `milan reproduce`, which regenerates a dataset and compares
    digests. That is what turns "reproducible" from a claim in a README into
    something the build can fail on.
    """
    payload = model.model_dump_json().encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
