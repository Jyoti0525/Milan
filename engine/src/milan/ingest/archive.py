"""Keeping an import, so the second one asks nothing.

A generated run is reproducible because it is a pure function of its seed. An
imported one cannot be: the merchant's files are the input, and they live
outside this repository. What can be made reproducible is everything that
happened *to* those files - which column was read as the fee, which date
format was chosen, what a model proposed and what a person answered - and
that is what is written here.

The effect is the one that matters for a demonstration: point Milan at a
folder once and answer its questions; point it at the same folder again and
it runs straight through, with no prompt and no model. The judgment happened
once and was recorded, rather than being repeated and possibly answered
differently.

The merchant's own directory is never written to. Their folder is evidence,
and evidence a tool has left files in is worth less.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from milan.domain.results import ReconReport
from milan.ingest.plan import SavedMapping
from milan.persistence.store import write
from milan.recon.inputs import ReconInput

IMPORTS = "imports"
MAPPING_FILE = "mapping.json"
INPUT_FILE = "input.json"
REPORT_FILE = "report.json"
RECORD_FILE = "import.json"


class ImportRecord(BaseModel):
    """What one import did, in the terms a person would ask about it."""

    model_config = ConfigDict(frozen=True)

    slug: str
    source_root: str
    consulted: str
    """Which provider was asked to propose column mappings. `none` means the
    import ran on column names and value shapes alone."""

    files: tuple[str, ...]
    counts: dict[str, int]
    dropped: int
    withdrawals: int
    limitations: tuple[str, ...]
    rejections: tuple[str, ...]
    """Column proposals the values refused, one line each. Empty on an import
    that consulted no model, and on one where the model proposed nothing
    wrong."""

    columns_proposed: int
    columns_checked: int = 0
    """Columns settled by the file's own arithmetic rather than by a name, an
    answer or a suggestion.

    Defaulted, because imports archived before the identity checks existed
    have no such count and inventing one for them would be worse than
    reporting none. A run predating the field reads as zero and says so.
    """
    """How many columns a model contributed that the header names did not
    already cover. The entire "AI did something here" claim about ingest,
    stated as a count."""


def slug_for(source: Path) -> str:
    """A directory name for this import, derived from the folder's own name.

    Two different folders with the same name would collide. That is accepted
    rather than solved with a hash: a name a person recognises is worth more
    than a name that is guaranteed unique, and `milan import` prints the
    source path it recorded either way.
    """
    name = re.sub(r"[^a-z0-9]+", "-", source.name.lower()).strip("-")
    return name or "import"


def directory(data_root: Path, slug: str) -> Path:
    return data_root / IMPORTS / slug


def save(
    data_root: Path,
    slug: str,
    *,
    record: ImportRecord,
    mapping: SavedMapping,
    data: ReconInput,
    report: ReconReport,
) -> Path:
    """Write the import beside the generated runs, and return its directory."""
    target = directory(data_root, slug)
    write(record, target / RECORD_FILE)
    write(mapping, target / MAPPING_FILE)
    write(data, target / INPUT_FILE)
    write(report, target / REPORT_FILE)
    return target


def load_mapping(data_root: Path, slug: str) -> SavedMapping | None:
    path = directory(data_root, slug) / MAPPING_FILE
    if not path.exists():
        return None
    return SavedMapping.model_validate_json(path.read_text(encoding="utf-8"))


def load_record(data_root: Path, slug: str) -> ImportRecord | None:
    path = directory(data_root, slug) / RECORD_FILE
    if not path.exists():
        return None
    return ImportRecord.model_validate_json(path.read_text(encoding="utf-8"))


def load_input(data_root: Path, slug: str) -> ReconInput | None:
    path = directory(data_root, slug) / INPUT_FILE
    if not path.exists():
        return None
    return ReconInput.model_validate_json(path.read_text(encoding="utf-8"))


def load_report(data_root: Path, slug: str) -> ReconReport | None:
    path = directory(data_root, slug) / REPORT_FILE
    if not path.exists():
        return None
    return ReconReport.model_validate_json(path.read_text(encoding="utf-8"))


def imports(data_root: Path) -> tuple[str, ...]:
    """Every import stored under this data root, in name order."""
    root = data_root / IMPORTS
    if not root.is_dir():
        return ()
    return tuple(sorted(path.name for path in root.iterdir() if (path / RECORD_FILE).exists()))
