"""Handing a merchant's files to the engine over HTTP.

The command line has a folder to point at. A browser has a person with three
CSVs, so the upload has to become that folder - and the whole refuse-and-ask
contract has to survive the move. That is what this file checks: uploading
changes nothing, an unanswered plan will not commit, and answering one
question can open another.

The security assertions matter more than usual here, because this is the only
POST the engine has. It binds to loopback and has no authentication, so the
filename check, the count cap and the size cap are the boundary rather than a
belt beside a brace. A filename is data from a browser; treating it as a path
is how an upload writes outside its own directory.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from milan.api.app import create_app
from milan.api.staging import MAX_FILES, StagingError, safe_name
from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.dataset import Dataset
from milan.domain.rates import RateCard


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    return ChaosEngine(
        GenerationConfig(
            seed=9,
            difficulty=Difficulty.REALISTIC,
            order_count=60,
            span_days=21,
            rates=RateCard(),
        )
    ).generate()


def settlement_csv(dataset: Dataset) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
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
            ]
        )
    return buffer.getvalue().encode("utf-8")


def bank_csv(dataset: Dataset, *, two_dates: bool = False) -> bytes:
    """A statement, optionally with both a transaction date and a value date.

    The two-date version is the one that asks a question, and it is a real
    statement shape rather than a contrivance - those are different days, and
    which one reconciliation should use is a finance decision.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    header = (
        ["Txn Date", "Value Date", "Narration", "Credit"]
        if two_dates
        else [
            "Value Date",
            "Narration",
            "Credit",
        ]
    )
    writer.writerow(header)
    for credit in dataset.bank_credits:
        stamped = credit.value_date.strftime("%d-%b-%Y")
        row = [stamped, stamped] if two_dates else [stamped]
        writer.writerow([*row, credit.narration, f"{credit.amount / 100:.2f}"])
    return buffer.getvalue().encode("utf-8")


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    yield TestClient(create_app(tmp_path))


def upload(client: TestClient, **files: bytes) -> dict[str, Any]:
    response = client.post(
        "/api/uploads",
        files=[
            ("files", (name.replace("__", "."), body, "text/csv")) for name, body in files.items()
        ],
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


class TestUploadingIsNotImporting:
    def test_files_that_read_cleanly_come_back_ready(
        self, client: TestClient, dataset: Dataset
    ) -> None:
        plan = upload(client, settlement__csv=settlement_csv(dataset), bank__csv=bank_csv(dataset))
        assert plan["ready"] is True
        assert plan["questions"] == []
        assert {file["file"] for file in plan["files"]} == {"settlement.csv", "bank.csv"}

    def test_nothing_is_archived_until_it_is_committed(
        self, client: TestClient, dataset: Dataset
    ) -> None:
        """Files landing on disk changes nothing. Until somebody agrees to the
        mapping there is no run, and the imports list says so."""
        upload(client, settlement__csv=settlement_csv(dataset), bank__csv=bank_csv(dataset))
        assert client.get("/api/imports").json() == []

    def test_a_file_it_cannot_read_is_refused_with_a_reason(self, client: TestClient) -> None:
        response = client.post(
            "/api/uploads",
            files=[("files", ("notes.csv", b"just a sentence, nothing tabular\n", "text/csv"))],
        )
        assert response.status_code == 422
        assert "header" in response.json()["detail"]


class TestTheQuestionsSurviveTheMoveToHttp:
    def test_a_statement_with_two_date_columns_asks_rather_than_picks(
        self, client: TestClient, dataset: Dataset
    ) -> None:
        plan = upload(
            client,
            settlement__csv=settlement_csv(dataset),
            bank__csv=bank_csv(dataset, two_dates=True),
        )
        assert plan["ready"] is False
        asked = [q for q in plan["questions"] if q["subject"] == "value_date"]
        assert len(asked) == 1
        assert {choice["value"] for choice in asked[0]["choices"]} >= {"Txn Date", "Value Date"}

    def test_answering_it_makes_the_plan_ready(self, client: TestClient, dataset: Dataset) -> None:
        plan = upload(
            client,
            settlement__csv=settlement_csv(dataset),
            bank__csv=bank_csv(dataset, two_dates=True),
        )
        answered = client.post(
            f"/api/uploads/{plan['id']}/answers",
            json={"answers": {"bank.csv:value_date": "Value Date"}},
        )
        assert answered.status_code == 200
        assert answered.json()["ready"] is True
        assert answered.json()["questions"] == []

    def test_an_unanswered_plan_will_not_commit(self, client: TestClient, dataset: Dataset) -> None:
        """The wizard should not offer the button. A client is not a place to
        enforce anything."""
        plan = upload(
            client,
            settlement__csv=settlement_csv(dataset),
            bank__csv=bank_csv(dataset, two_dates=True),
        )
        response = client.post(f"/api/uploads/{plan['id']}/commit", json={"name": "july"})
        assert response.status_code == 409

    def test_an_answer_naming_a_file_nobody_uploaded_is_refused(
        self, client: TestClient, dataset: Dataset
    ) -> None:
        """A browser and a server disagreeing about what is on screen. The
        next thing that happens is somebody approving a mapping they cannot
        see, so it is an error rather than a no-op."""
        plan = upload(client, settlement__csv=settlement_csv(dataset), bank__csv=bank_csv(dataset))
        response = client.post(
            f"/api/uploads/{plan['id']}/answers",
            json={"answers": {"nothing.csv:value_date": "Value Date"}},
        )
        assert response.status_code == 422
        assert "not one of the files you uploaded" in response.json()["detail"]


class TestCommittingKeepsTheRunAndDropsTheFiles:
    def test_the_committed_import_appears_in_the_list(
        self, client: TestClient, dataset: Dataset
    ) -> None:
        plan = upload(client, settlement__csv=settlement_csv(dataset), bank__csv=bank_csv(dataset))
        slug = client.post(f"/api/uploads/{plan['id']}/commit", json={"name": "July 2026"}).json()[
            "slug"
        ]

        listed = client.get("/api/imports").json()
        assert [row["slug"] for row in listed] == [slug]
        assert client.get(f"/api/imports/{slug}").status_code == 200

    def test_the_uploaded_files_are_not_kept_afterwards(
        self, client: TestClient, dataset: Dataset, tmp_path: Path
    ) -> None:
        """The mapping records how they were read and the normalised records
        are what every later screen reads. A second copy of the merchant's
        settlement data in a directory nobody manages buys nothing."""
        plan = upload(client, settlement__csv=settlement_csv(dataset), bank__csv=bank_csv(dataset))
        client.post(f"/api/uploads/{plan['id']}/commit", json={"name": "July"})
        assert not (tmp_path / "uploads" / str(plan["id"])).exists()

    def test_the_committed_run_reconciles_the_uploaded_records(
        self, client: TestClient, dataset: Dataset
    ) -> None:
        plan = upload(client, settlement__csv=settlement_csv(dataset), bank__csv=bank_csv(dataset))
        slug = client.post(f"/api/uploads/{plan['id']}/commit", json={"name": "July"}).json()[
            "slug"
        ]
        view = client.get(f"/api/imports/{slug}").json()
        assert view["summary"]["credits_total"] == len(dataset.bank_credits)
        assert view["proofs"]

    def test_a_staged_upload_can_be_thrown_away(
        self, client: TestClient, dataset: Dataset, tmp_path: Path
    ) -> None:
        plan = upload(client, settlement__csv=settlement_csv(dataset), bank__csv=bank_csv(dataset))
        assert client.delete(f"/api/uploads/{plan['id']}").status_code == 200
        assert not (tmp_path / "uploads" / str(plan["id"])).exists()
        assert client.get(f"/api/uploads/{plan['id']}").status_code == 404

    def test_asking_for_an_upload_that_expired_says_what_to_do(self, client: TestClient) -> None:
        response = client.get("/api/uploads/deadbeefdeadbeef")
        assert response.status_code == 404
        assert "Upload them again" in response.json()["detail"]


class TestAFilenameIsDataAndNotAPath:
    @pytest.mark.parametrize(
        "hostile",
        [
            "../../escape.csv",
            "..\\..\\escape.csv",
            "/etc/passwd.csv",
            "C:\\Windows\\System32\\evil.csv",
            "sub/dir/statement.csv",
        ],
    )
    def test_a_path_is_reduced_to_its_last_component(self, hostile: str) -> None:
        """The only POST this engine has, on a server with no authentication.
        A filename that reaches the filesystem intact is a filename that can
        write outside its own directory."""
        assert "/" not in safe_name(hostile)
        assert "\\" not in safe_name(hostile)
        assert not safe_name(hostile).startswith("..")

    @pytest.mark.parametrize("refused", ["", "   ", ".hidden.csv", "run.sh", "statement.pdf"])
    def test_a_name_that_is_not_usable_is_refused_rather_than_corrected(self, refused: str) -> None:
        """Silently renaming a merchant's file is how the wrong file gets
        reconciled."""
        with pytest.raises(StagingError):
            safe_name(refused)

    @pytest.mark.parametrize("taken", ["report.xlsx", "BOOK.XLSM", "statement.tsv"])
    def test_a_spreadsheet_is_taken(self, taken: str) -> None:
        """The formats a merchant actually has. A gateway dashboard's export
        button gives a workbook, and refusing it at the door was the reason
        the browser could not accept the most likely file in the folder."""
        assert safe_name(taken) == taken

    @pytest.mark.parametrize(
        ("refused", "phrase"),
        [
            ("statement.pdf", "no columns to read"),
            ("statement.xls", "before 2007"),
            ("export.json", "not a table yet"),
            ("books.zip", "unzip it"),
        ],
    )
    def test_a_refusal_says_what_to_do_about_it(self, refused: str, phrase: str) -> None:
        """A PDF bank statement is the single most likely thing to arrive here
        and be unreadable, and "unsupported format" leaves that person stuck
        beside a download page that also offers CSV."""
        with pytest.raises(StagingError, match=phrase):
            safe_name(refused)

    def test_an_upload_of_too_many_files_is_refused(self, client: TestClient) -> None:
        response = client.post(
            "/api/uploads",
            files=[
                ("files", (f"file{n}.csv", b"a,b\n1,2\n", "text/csv")) for n in range(MAX_FILES + 1)
            ],
        )
        assert response.status_code == 422
        assert "more than this takes" in response.json()["detail"]

    def test_two_files_with_the_same_name_are_refused(self, client: TestClient) -> None:
        """One would silently overwrite the other, and the import would
        reconcile half of what was handed over."""
        response = client.post(
            "/api/uploads",
            files=[
                ("files", ("statement.csv", b"a,b\n1,2\n", "text/csv")),
                ("files", ("sub/statement.csv", b"a,b\n3,4\n", "text/csv")),
            ],
        )
        assert response.status_code == 422
        assert "same name" in response.json()["detail"]

    def test_an_empty_upload_is_refused(self, client: TestClient) -> None:
        assert client.post("/api/uploads", files=[]).status_code in {400, 422}


class TestTheUploadPathIsNotAWayIntoStoredRuns:
    def test_only_the_upload_routes_accept_a_post(self, client: TestClient) -> None:
        """The origin list is the control doing the work here, but it is worth
        knowing that widening the methods did not open a write path onto the
        generated runs. There is no route that writes to `data/runs`."""
        assert client.post("/api/runs", json={}).status_code == 405
        assert client.post("/api/runs/adversarial/42", json={}).status_code == 405
        assert client.delete("/api/imports/anything").status_code == 405
