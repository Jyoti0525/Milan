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

    @pytest.mark.parametrize("refused", ["", "   ", ".hidden.csv", "run.sh", "logo.png"])
    def test_a_name_that_is_not_usable_is_refused_rather_than_corrected(self, refused: str) -> None:
        """Silently renaming a merchant's file is how the wrong file gets
        reconciled. Refusing the *name* is not refusing the upload - see
        `TestOneBadFileDoesNotRefuseTheFolderItArrivedIn`."""
        with pytest.raises(StagingError):
            safe_name(refused)

    @pytest.mark.parametrize("taken", ["report.xlsx", "BOOK.XLSM", "statement.tsv"])
    def test_a_spreadsheet_is_taken(self, taken: str) -> None:
        """The formats a merchant actually has. A gateway dashboard's export
        button gives a workbook, and refusing it at the door was the reason
        the browser could not accept the most likely file in the folder."""
        assert safe_name(taken) == taken

    @pytest.mark.parametrize("taken", ["statement.pdf", "old.xls", "dump.json", "books.zip"])
    def test_a_file_we_have_advice_about_comes_in_rather_than_bouncing(self, taken: str) -> None:
        """These four are what somebody wrongly believes their books are, and
        each has a sentence attached telling them what to do instead. That
        sentence lives in the reader, which is where the folder path gets it
        too - so they are staged and diagnosed rather than turned away at the
        door on a filename.

        Turning them away here is what made one PDF in a folder reject the
        whole upload."""
        assert safe_name(taken) == taken

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


class TestFilesCanJoinAnUploadInsteadOfReplacingIt:
    """The bug this closes was quiet and expensive.

    Every upload used to create a fresh staging area. A merchant who picked
    their settlement report, looked at what came back, and then picked their
    bank statement did not end up with two files - they ended up with the
    statement alone and a plan saying no settlement report was found. The
    first file was gone and nothing anywhere said so.
    """

    def test_a_second_file_joins_the_first(self, client: TestClient, dataset: Dataset) -> None:
        first = upload(client, settlement__csv=settlement_csv(dataset))
        response = client.post(
            f"/api/uploads/{first['id']}/files",
            files=[("files", ("bank.csv", bank_csv(dataset), "text/csv"))],
        )
        assert response.status_code == 200, response.text
        plan = response.json()
        assert {file["file"] for file in plan["files"]} == {"settlement.csv", "bank.csv"}

    def test_the_upload_keeps_its_identity(self, client: TestClient, dataset: Dataset) -> None:
        """A new id would orphan the staging directory the first file is in."""
        first = upload(client, settlement__csv=settlement_csv(dataset))
        response = client.post(
            f"/api/uploads/{first['id']}/files",
            files=[("files", ("bank.csv", bank_csv(dataset), "text/csv"))],
        )
        assert response.json()["id"] == first["id"]

    def test_adding_the_bank_statement_makes_the_plan_ready(
        self, client: TestClient, dataset: Dataset
    ) -> None:
        """A settlement report on its own cannot be reconciled against
        anything, and the blocker says so. Adding the statement clears it."""
        first = upload(client, settlement__csv=settlement_csv(dataset))
        assert first["ready"] is False
        assert any("bank statement" in line for line in first["blockers"])

        response = client.post(
            f"/api/uploads/{first['id']}/files",
            files=[("files", ("bank.csv", bank_csv(dataset), "text/csv"))],
        )
        assert response.json()["ready"] is True

    def test_an_answer_already_given_survives_the_addition(
        self, client: TestClient, dataset: Dataset
    ) -> None:
        """Answers are keyed by file name and the files have not moved. Losing
        them would mean every added file cost the merchant their earlier
        decisions, which is its own reason not to add one."""
        first = upload(
            client,
            settlement__csv=settlement_csv(dataset),
            bank__csv=bank_csv(dataset, two_dates=True),
        )
        asked = next(q for q in first["questions"] if q["subject"] == "value_date")
        answered = client.post(
            f"/api/uploads/{first['id']}/answers",
            json={"answers": {asked["key"]: "Value Date"}},
        )
        assert answered.status_code == 200, answered.text

        added = client.post(
            f"/api/uploads/{first['id']}/files",
            files=[
                ("files", ("payments.csv", b"payment_id,order_id\npay_1,order_1\n", "text/csv"))
            ],
        )
        assert added.status_code == 200, added.text
        bank = next(f for f in added.json()["files"] if f["file"] == "bank.csv")
        chosen = next(r for r in bank["resolutions"] if r["field"] == "value_date")
        assert chosen["column"] == "Value Date"
        assert chosen["certainty"] == "answered"

    def test_a_duplicate_name_is_refused_rather_than_overwriting(
        self, client: TestClient, dataset: Dataset
    ) -> None:
        """Silently replacing a merchant's file is how the wrong month gets
        reconciled."""
        first = upload(client, settlement__csv=settlement_csv(dataset))
        response = client.post(
            f"/api/uploads/{first['id']}/files",
            files=[("files", ("settlement.csv", settlement_csv(dataset), "text/csv"))],
        )
        assert response.status_code == 422
        assert "already in this upload" in response.json()["detail"]

    def test_the_file_cap_counts_what_is_already_there(
        self, client: TestClient, dataset: Dataset
    ) -> None:
        """Counting only the new batch would let two uploads past a cap that
        one cannot pass."""
        first = upload(client, settlement__csv=settlement_csv(dataset))
        response = client.post(
            f"/api/uploads/{first['id']}/files",
            files=[
                ("files", (f"extra{n}.csv", b"a,b\n1,2\n", "text/csv")) for n in range(MAX_FILES)
            ],
        )
        assert response.status_code == 422
        assert "more than this takes" in response.json()["detail"]

    def test_adding_to_an_upload_that_expired_says_so(self, client: TestClient) -> None:
        response = client.post(
            "/api/uploads/deadbeefdeadbeef/files",
            files=[("files", ("bank.csv", b"a,b\n1,2\n", "text/csv"))],
        )
        assert response.status_code == 404


class TestOneBadFileDoesNotRefuseTheFolderItArrivedIn:
    """The bug a merchant hits on their first real attempt.

    They select their whole folder - statement, settlement report, and the PDF
    they downloaded before realising we wanted a table. Every file was refused
    because of the PDF: six files in, one error out, nothing staged, and no
    way to tell which file caused it without trying them one at a time.

    A folder legitimately holds things we cannot read. Reading what we can and
    saying what we could not is the only behaviour that survives contact with
    somebody's actual downloads directory.
    """

    def test_a_pdf_in_the_folder_does_not_stop_the_rest(
        self, client: TestClient, dataset: Dataset
    ) -> None:
        response = client.post(
            "/api/uploads",
            files=[
                ("files", ("settlement.csv", settlement_csv(dataset), "text/csv")),
                ("files", ("bank.csv", bank_csv(dataset), "text/csv")),
                ("files", ("statement.pdf", b"%PDF-1.7\ntrailer\n", "application/pdf")),
            ],
        )
        assert response.status_code == 200, response.text
        plan = response.json()
        assert {file["file"] for file in plan["files"]} == {"settlement.csv", "bank.csv"}
        assert plan["ready"] is True

    def test_the_pdf_is_reported_with_advice_rather_than_dropped(
        self, client: TestClient, dataset: Dataset
    ) -> None:
        """Silence is the worse failure. A merchant who handed over their bank
        statement as a PDF and sees a run covering a month with no bank side
        needs to be told which file we could not use."""
        response = client.post(
            "/api/uploads",
            files=[
                ("files", ("settlement.csv", settlement_csv(dataset), "text/csv")),
                ("files", ("bank.csv", bank_csv(dataset), "text/csv")),
                ("files", ("statement.pdf", b"%PDF-1.7\ntrailer\n", "application/pdf")),
            ],
        )
        unreadable = " ".join(response.json()["unreadable"])
        assert "statement.pdf" in unreadable
        assert "no columns to read" in unreadable

    def test_a_file_of_a_sort_we_cannot_advise_on_is_set_aside_quietly(
        self, client: TestClient, dataset: Dataset
    ) -> None:
        """A logo in the folder is not an error and not advice-worthy. It is
        named in the not-read list and costs nothing else."""
        response = client.post(
            "/api/uploads",
            files=[
                ("files", ("settlement.csv", settlement_csv(dataset), "text/csv")),
                ("files", ("bank.csv", bank_csv(dataset), "text/csv")),
                ("files", ("logo.png", b"\x89PNG\r\n\x1a\n", "image/png")),
            ],
        )
        assert response.status_code == 200, response.text
        plan = response.json()
        assert plan["ready"] is True
        assert any("logo.png" in line for line in plan["unreadable"])

    def test_an_upload_of_nothing_usable_is_still_refused(self, client: TestClient) -> None:
        """Reading none of it is different from reading most of it. There is
        nothing to stage, and holding an empty plan helps nobody."""
        response = client.post(
            "/api/uploads",
            files=[("files", ("statement.pdf", b"%PDF-1.7\ntrailer\n", "application/pdf"))],
        )
        assert response.status_code == 422
        assert "no columns to read" in response.json()["detail"]

    def test_a_skipped_file_survives_a_later_answer(
        self, client: TestClient, dataset: Dataset
    ) -> None:
        """The plan is rebuilt from scratch on every answer. A skipped file
        recorded only at upload time would vanish from the list the moment
        somebody answered their first question."""
        response = client.post(
            "/api/uploads",
            files=[
                ("files", ("settlement.csv", settlement_csv(dataset), "text/csv")),
                ("files", ("bank.csv", bank_csv(dataset, two_dates=True), "text/csv")),
                ("files", ("statement.pdf", b"%PDF-1.7\ntrailer\n", "application/pdf")),
            ],
        )
        plan = response.json()
        asked = next(q for q in plan["questions"] if q["subject"] == "value_date")
        answered = client.post(
            f"/api/uploads/{plan['id']}/answers",
            json={"answers": {asked["key"]: "Value Date"}},
        )
        assert any("statement.pdf" in line for line in answered.json()["unreadable"])


class TestSayingAFileIsNotWhatWeThink:
    """The escape hatch in the other direction, over HTTP.

    A purchase ledger placed as an orders export is the case: a PO number, a
    value and a raised-on date are exactly what an order book needs, nothing
    in the file rules it out, and only the person who owns it knows. Before
    this, the wizard offered no way to say so - a file the rules had placed
    stayed placed.
    """

    LEDGER = b"PO Number,Vendor,Raised On,Value\nPO-0001,Acme,04-Jul-2026,1200.00\n"

    def test_a_placed_file_can_be_left_out(self, client: TestClient, dataset: Dataset) -> None:
        plan = upload(
            client,
            settlement__csv=settlement_csv(dataset),
            bank__csv=bank_csv(dataset),
            ledger__csv=self.LEDGER,
        )
        answered = client.post(
            f"/api/uploads/{plan['id']}/answers",
            json={"answers": {"ledger.csv:record": "-"}},
        )
        assert answered.status_code == 200, answered.text
        ledger = next(f for f in answered.json()["files"] if f["file"] == "ledger.csv")
        assert ledger["kind"] is None

    def test_the_decision_survives_the_next_replan(
        self, client: TestClient, dataset: Dataset
    ) -> None:
        """The plan is rebuilt from scratch after every answer, on the same
        column names that placed the file the first time. Recording this as
        the absence of a decision meant the rules ran again and put the file
        straight back - the merchant says "not that" and watches nothing
        happen."""
        plan = upload(
            client,
            settlement__csv=settlement_csv(dataset),
            bank__csv=bank_csv(dataset, two_dates=True),
            ledger__csv=self.LEDGER,
        )
        client.post(
            f"/api/uploads/{plan['id']}/answers",
            json={"answers": {"ledger.csv:record": "-"}},
        )
        asked = next(q for q in plan["questions"] if q["subject"] == "value_date")
        after = client.post(
            f"/api/uploads/{plan['id']}/answers",
            json={"answers": {asked["key"]: "Value Date"}},
        )
        ledger = next(f for f in after.json()["files"] if f["file"] == "ledger.csv")
        assert ledger["kind"] is None

    def test_it_says_you_left_it_out_rather_than_that_we_did_not_recognise_it(
        self, client: TestClient, dataset: Dataset
    ) -> None:
        """Telling somebody we did not recognise a file they have just told us
        to leave out reads as a system that forgot."""
        plan = upload(
            client,
            settlement__csv=settlement_csv(dataset),
            bank__csv=bank_csv(dataset),
            ledger__csv=self.LEDGER,
        )
        answered = client.post(
            f"/api/uploads/{plan['id']}/answers",
            json={"answers": {"ledger.csv:record": "-"}},
        ).json()
        offer = next(q for q in answered["questions"] if q["file"] == "ledger.csv")
        assert "You left" in offer["asks"]
        assert offer["blocking"] is False

    def test_it_can_be_taken_back(self, client: TestClient, dataset: Dataset) -> None:
        """Somebody who leaves out the wrong file has to be able to undo it."""
        plan = upload(
            client,
            settlement__csv=settlement_csv(dataset),
            bank__csv=bank_csv(dataset),
            ledger__csv=self.LEDGER,
        )
        client.post(
            f"/api/uploads/{plan['id']}/answers",
            json={"answers": {"ledger.csv:record": "-"}},
        )
        back = client.post(
            f"/api/uploads/{plan['id']}/answers",
            json={"answers": {"ledger.csv:record": "orders"}},
        ).json()
        ledger = next(f for f in back["files"] if f["file"] == "ledger.csv")
        assert ledger["kind"] == "orders"
