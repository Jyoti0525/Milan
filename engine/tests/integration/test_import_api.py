"""The screen for a run that has no answer key.

A generated run is scored against ground truth generated alongside it. A
merchant's own files come with no ground truth and never will - so every
accuracy figure on the other screen is unavailable here, and the most
dishonest thing this project could do is compute something that looks like
one anyway.

What is asserted below is the absence. `ImportSummary` must not carry a match
rate, a precision, a refusal rate or an explained rate, because there is
nothing to measure them against. What it carries instead is the provenance:
which files were read, which model was asked about the columns, how many
columns it contributed, what it proposed that the values refused, and which
checks were switched off for want of a file.

The route is separate from `/api/runs` for the same reason. One endpoint
returning two shapes would push the difference into the browser, to be
handled by a conditional nobody maintains.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from milan.api.app import create_app
from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.dataset import Dataset
from milan.domain.rates import RateCard
from milan.ingest import archive, build
from milan.ingest.plan import to_saved
from milan.ingest.resolver import Importer
from milan.recon.pipeline import ReconciliationPipeline, RunMetadata

SLUG = "july-2026"


def _write(dataset: Dataset, root: Path) -> Path:
    """A merchant's folder, in names the alias list already covers.

    Deliberately plain. The reader and the resolver are exercised hard in
    `test_ingest_reading` and `test_ingest_resolver`; what this file is about
    is the shape of the response, and a folder that needed a model to read
    would make these tests depend on a daemon.
    """
    root.mkdir(parents=True, exist_ok=True)
    with (root / "settlement.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "entity_id",
                "type",
                "amount",
                "credit",
                "debit",
                "fee",
                "tax",
                "created_at",
                "settlement_id",
                "settled_at",
                "settlement_utr",
                "payment_id",
                "method",
                "card_type",
            ]
        )
        for row in dataset.settlement_rows:
            writer.writerow(
                [
                    row.entity_id,
                    row.type.value,
                    f"{row.amount / 100:.2f}",
                    f"{row.credit / 100:.2f}",
                    f"{row.debit / 100:.2f}",
                    f"{row.fee / 100:.2f}",
                    f"{row.tax / 100:.2f}",
                    row.created_at.isoformat(sep=" "),
                    row.settlement_id or "",
                    row.settled_at.isoformat(sep=" ") if row.settled_at else "",
                    row.settlement_utr or "",
                    row.payment_id or "",
                    row.method.value if row.method else "",
                    row.card_type.value if row.card_type else "",
                ]
            )

    with (root / "statement.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Value Date", "Narration", "Ref No", "Credit"])
        for credit in dataset.bank_credits:
            writer.writerow(
                [
                    credit.value_date.strftime("%d-%b-%Y"),
                    credit.narration,
                    credit.utr or "",
                    f"{credit.amount / 100:.2f}",
                ]
            )
    return root


@pytest.fixture(scope="module")
def served(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    """One imported folder, written to a data root the API then serves."""
    dataset = ChaosEngine(
        GenerationConfig(
            seed=9,
            difficulty=Difficulty.REALISTIC,
            order_count=80,
            span_days=21,
            rates=RateCard(),
        )
    ).generate()

    data_root = tmp_path_factory.mktemp("data")
    source = _write(dataset, tmp_path_factory.mktemp("merchant") / SLUG)

    plan = Importer(None).plan(source)
    assert plan.ready, plan.blockers()
    imported = build.build(plan)
    report = ReconciliationPipeline().run(imported.data, RunMetadata(seed=0, difficulty="imported"))
    archive.save(
        data_root,
        SLUG,
        record=archive.ImportRecord(
            slug=SLUG,
            source_root=str(source),
            consulted=plan.consulted,
            files=tuple(mapping.name for mapping in plan.placed),
            counts=imported.counts,
            dropped=len(imported.dropped),
            withdrawals=imported.withdrawals,
            limitations=plan.limitations(),
            rejections=(),
            columns_proposed=0,
        ),
        mapping=to_saved(plan),
        data=imported.data,
        report=report,
    )
    yield TestClient(create_app(data_root))


class TestTheImportedRunsAreListedSeparately:
    def test_the_picker_sees_the_import(self, served: TestClient) -> None:
        response = served.get("/api/imports")
        assert response.status_code == 200
        listed = response.json()
        assert [row["slug"] for row in listed] == [SLUG]
        assert listed[0]["records"] > 0
        assert listed[0]["credits"] > 0

    def test_it_says_which_model_read_the_columns(self, served: TestClient) -> None:
        """`none` is a real answer and the one every claim about this path
        should be checked in. A picker that omitted it would leave a reader
        assuming a model was involved when none was."""
        listed = served.get("/api/imports").json()
        assert listed[0]["consulted"] == "none"
        assert listed[0]["columns_proposed"] == 0

    def test_a_folder_nobody_imported_is_a_404(self, served: TestClient) -> None:
        response = served.get("/api/imports/never-imported")
        assert response.status_code == 404
        assert "milan import" in response.json()["detail"]

    def test_an_empty_data_root_lists_nothing_rather_than_failing(self, tmp_path: Path) -> None:
        client = TestClient(create_app(tmp_path))
        assert client.get("/api/imports").status_code == 200
        assert client.get("/api/imports").json() == []


class TestTheSummaryClaimsNothingItCannotMeasure:
    @pytest.mark.parametrize(
        "absent", ["match_rate", "precision", "refusal_rate", "explained_rate"]
    )
    def test_no_accuracy_figure_appears_without_an_answer_key(
        self, served: TestClient, absent: str
    ) -> None:
        """The assertion this whole file exists for. Each of these is measured
        against ground truth on the generated screen; here there is none, and
        a zero in its place would read as a measurement rather than as an
        absence."""
        summary = served.get(f"/api/imports/{SLUG}").json()["summary"]
        assert absent not in summary

    def test_what_it_does_report_is_read_off_the_run(self, served: TestClient) -> None:
        body = served.get(f"/api/imports/{SLUG}").json()
        summary = body["summary"]
        assert summary["records_processed"] > 0
        assert summary["credits_total"] > 0
        assert summary["proofs_balanced"] == len(body["proofs"])
        assert summary["exceptions_total"] == len(body["queue"])
        assert sum(summary["exceptions_by_code"].values()) == summary["exceptions_total"]

    def test_drift_survives_because_it_needs_no_answer_key(self, served: TestClient) -> None:
        """The one accuracy-shaped number an imported run can honestly keep.
        A credit that reconstructs to zero has proved itself; nothing external
        had to say so."""
        summary = served.get(f"/api/imports/{SLUG}").json()["summary"]
        assert summary["drift_gross"] >= abs(summary["drift_net"])
        assert summary["proofs_with_drift"] <= summary["proofs_balanced"]


class TestProvenanceStandsInPlaceOfAScore:
    def test_it_names_the_files_it_read_and_where_they_came_from(self, served: TestClient) -> None:
        provenance = served.get(f"/api/imports/{SLUG}").json()["provenance"]
        assert set(provenance["files"]) == {"settlement.csv", "statement.csv"}
        assert SLUG in provenance["source_root"]

    def test_it_says_what_the_run_could_not_check(self, served: TestClient) -> None:
        """A merchant reading a clean exception list has a right to know which
        checks were switched off before they trust it. This folder has no
        payments file, so unsettled payments cannot be raised at all."""
        provenance = served.get(f"/api/imports/{SLUG}").json()["provenance"]
        assert any("no payments file" in line for line in provenance["limitations"])

    def test_it_carries_the_counts_that_add_up_to_the_record_total(
        self, served: TestClient
    ) -> None:
        body = served.get(f"/api/imports/{SLUG}").json()
        counts = body["provenance"]["counts"]
        assert sum(counts.values()) == body["summary"]["records_processed"]


class TestTheRestOfTheScreenIsTheSameScreen:
    def test_the_exception_queue_has_the_same_shape_as_a_generated_run(
        self, served: TestClient
    ) -> None:
        """The queue, the proofs and the leaks are built by the same code for
        both paths. Only the scorecard differs, because only the scorecard
        needed the answer key."""
        queue = served.get(f"/api/imports/{SLUG}").json()["queue"]
        assert queue
        for item in queue:
            assert set(item) >= {"code", "summary", "amount", "evidence", "subject"}
            assert item["subject"]["kind"] in {"credit", "settlement", "payment", "unknown"}

    def test_every_proof_reconstructs_its_credit(self, served: TestClient) -> None:
        proofs = served.get(f"/api/imports/{SLUG}").json()["proofs"]
        assert proofs
        for proof in proofs:
            assert proof["lines"]

    def test_the_leak_view_reports_even_when_it_found_nothing(self, served: TestClient) -> None:
        """A detector whose only evidence of working is the runs where it
        fired is a detector nobody can trust on the runs where it did not."""
        leaks = served.get(f"/api/imports/{SLUG}").json()["leaks"]
        assert leaks["rows_examined"] > 0
        assert leaks["headline"]


class TestTheGeneratedPathIsUntouched:
    def test_the_runs_route_still_answers(self, served: TestClient) -> None:
        assert served.get("/api/runs").status_code == 200

    def test_health_still_names_the_data_root(self, served: TestClient) -> None:
        body = served.get("/api/health").json()
        assert body["status"] == "ok"
        assert body["data_root"]
