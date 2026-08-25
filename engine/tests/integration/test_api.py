"""The HTTP surface, and the two things it must never do.

Most of this is ordinary: the endpoints answer, the shapes are right, the
status codes distinguish "no such run" from "that run is stale". Two cases are
not ordinary and are the reason this file is worth its length.

**The API must not serve the answer key.** `milan.recon` is forbidden from
importing ground truth, and a JSON route that hands it to a browser would walk
straight around that boundary. The whole claim of this project is that the
match rate is a measurement rather than a demo, and a queue that can see the
answers is a demo.

**Money must cross the wire as integer paise.** Not a formatted string, and
above all not a float. `0.1 + 0.2` is the oldest bug in finance software and
serialising to JSON is exactly where it gets reintroduced.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from milan.api.app import create_app
from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.persistence import store


@pytest.fixture(scope="module")
def populated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("api-root")
    for difficulty in (Difficulty.REALISTIC, Difficulty.ADVERSARIAL):
        config = GenerationConfig(seed=42, difficulty=difficulty, order_count=200)
        store.save_dataset(ChaosEngine(config).generate(), root, config)
    return root


@pytest.fixture(scope="module")
def client(populated: Path) -> TestClient:
    return TestClient(create_app(populated))


class TestTheRunsItCanSee:
    def test_health_reports_where_it_is_reading_from(self, client: TestClient) -> None:
        body = client.get("/api/health").json()

        assert body["status"] == "ok"
        assert body["data_root"]

    def test_it_lists_what_is_on_disk(self, client: TestClient) -> None:
        runs = client.get("/api/runs").json()

        assert {run["difficulty"] for run in runs} == {"realistic", "adversarial"}
        assert all(run["orders"] == 200 for run in runs)
        assert all(run["credits"] > 0 for run in runs)

    def test_one_stale_run_does_not_take_down_the_picker(self, tmp_path: Path) -> None:
        """Found by running it: a run left over from before a generator
        change made `/api/runs` return a 500, so the picker could not show
        the very run the person needed to be told to regenerate.

        Listing is metadata. Opening is the thing that has to be trustworthy.
        """
        fresh = GenerationConfig(seed=1, difficulty=Difficulty.CLEAN, order_count=80)
        store.save_dataset(ChaosEngine(fresh).generate(), tmp_path, fresh)
        stale = GenerationConfig(seed=2, difficulty=Difficulty.MESSY, order_count=80)
        store.save_dataset(ChaosEngine(stale).generate(), tmp_path, stale)
        store.write(
            stale.model_copy(update={"order_count": 81}),
            store.run_directory(tmp_path, 2, Difficulty.MESSY) / store.CONFIG_FILE,
        )

        response = TestClient(create_app(tmp_path)).get("/api/runs")

        assert response.status_code == 200
        listed = {(run["difficulty"], run["stale"]) for run in response.json()}
        assert listed == {("clean", False), ("messy", True)}

    def test_an_empty_root_lists_nothing_rather_than_failing(self, tmp_path: Path) -> None:
        """Nothing generated yet is a normal state for a fresh checkout, and
        the UI has to be able to say so rather than show an error."""
        empty = TestClient(create_app(tmp_path))

        assert empty.get("/api/runs").status_code == 200
        assert empty.get("/api/runs").json() == []


class TestOneRun:
    def test_it_returns_the_queue_the_proofs_and_the_summary_together(
        self, client: TestClient
    ) -> None:
        """One response, because they are one consistent picture of one run."""
        body = client.get("/api/runs/adversarial/42").json()

        assert set(body) == {"summary", "queue", "proofs"}
        assert body["summary"]["seed"] == 42
        assert body["queue"]
        assert body["proofs"]

    def test_every_proof_rebuilds_exactly_what_the_bank_paid(self, client: TestClient) -> None:
        """The running total is computed server-side precisely so this can be
        asserted. A proof whose lines do not add up to the credit is not a
        proof, and it must never reach a screen that says it is."""
        body = client.get("/api/runs/adversarial/42").json()

        for proof in body["proofs"]:
            assert proof["running"][-1] == proof["credit_amount"]
            assert proof["residual"] == 0
            assert sum(line["amount"] for line in proof["lines"]) == proof["credit_amount"]
            assert len(proof["running"]) == len(proof["lines"])

    def test_every_queue_item_names_what_it_is_about(self, client: TestClient) -> None:
        """An id and an amount is a spreadsheet row. The subject is what makes
        it a case somebody can pick up."""
        body = client.get("/api/runs/adversarial/42").json()

        for item in body["queue"]:
            assert item["subject"]["id"]
            assert item["subject"]["kind"] in {"credit", "settlement", "payment", "unknown"}
            assert item["summary"]

    def test_the_three_kinds_of_subject_are_distinguished(self, client: TestClient) -> None:
        """A credit that arrived unexplained, a payout that never arrived and
        a payment never reported are three different people's problem. The
        adversarial tier generates all three."""
        body = client.get("/api/runs/adversarial/42").json()
        kinds = {item["subject"]["kind"] for item in body["queue"]}

        assert {"credit", "settlement", "payment"} <= kinds
        assert "unknown" not in kinds

    def test_a_missing_run_is_a_404(self, client: TestClient) -> None:
        response = client.get("/api/runs/messy/999")

        assert response.status_code == 404
        assert "milan generate" in response.json()["detail"]

    def test_a_stale_run_is_a_409_not_a_500(self, tmp_path: Path) -> None:
        """Nothing has gone wrong with the server. The data on disk came from
        a different generator, and the message says which command fixes it."""
        config = GenerationConfig(seed=1, difficulty=Difficulty.CLEAN, order_count=80)
        store.save_dataset(ChaosEngine(config).generate(), tmp_path, config)
        (store.run_directory(tmp_path, 1, Difficulty.CLEAN) / store.CONFIG_FILE).unlink()

        response = TestClient(create_app(tmp_path)).get("/api/runs/clean/1")

        assert response.status_code == 409
        assert "no config beside it" in response.json()["detail"]


class TestTheBoundaryTheEngineEnforces:
    def test_the_answer_key_never_leaves_the_engine(self, client: TestClient) -> None:
        """The matcher may not import ground truth. A JSON route that serves
        it would walk around that boundary rather than break it, which is
        worse - nothing would fail."""
        body = client.get("/api/runs/adversarial/42").text.lower()

        for leak in ("answer_key", "matchable", "provable", "settlement_set", "leaktruth"):
            assert leak not in body

    def test_scores_are_present_but_the_answers_are_not(self, client: TestClient) -> None:
        """The distinction that makes the previous test meaningful: the
        summary reports a match rate, which is computed against ground truth
        inside the evaluation package and never exposed record by record."""
        summary = client.get("/api/runs/adversarial/42").json()["summary"]

        assert 0.0 <= summary["match_rate"] <= 1.0
        assert summary["precision"] == 1.0


class TestMoneyCrossesTheWireAsPaise:
    def test_no_amount_is_ever_a_float(self, client: TestClient) -> None:
        """The oldest bug in finance software, reintroduced at the last
        possible moment. Every amount in the payload is checked, at any
        depth, rather than the few a hand-written assertion would reach."""
        payload = json.loads(client.get("/api/runs/adversarial/42").text)
        offenders: list[str] = []

        def walk(node: object, path: str) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, f"{path}[{index}]")
            elif isinstance(node, float) and _is_money(path):
                offenders.append(path)

        walk(payload, "")
        assert not offenders, f"money serialised as float at: {offenders}"

    def test_amounts_are_not_pre_formatted_strings(self, client: TestClient) -> None:
        """Formatting is a display concern. Sending "Rs 1,234.50" would make
        the number unusable for anything except printing it back out."""
        body = client.get("/api/runs/adversarial/42").json()

        assert isinstance(body["proofs"][0]["credit_amount"], int)
        assert isinstance(body["summary"]["drift_gross"], int)
        assert isinstance(body["queue"][0]["amount"], int)


def _is_money(path: str) -> bool:
    leaf = path.rsplit(".", 1)[-1].split("[")[0]
    return leaf in {
        "amount",
        "credit_amount",
        "drift",
        "drift_gross",
        "drift_net",
        "running",
        "residual",
    }
