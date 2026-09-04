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
from typing import Any

import pytest
from fastapi.testclient import TestClient

from milan.api.app import create_app
from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.rates import RateCard
from milan.evaluation.metrics import Scorecard
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


@pytest.fixture(scope="module")
def operator(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A month belonging to an e-commerce operator who also uses Route.

    Kept apart from `populated` rather than folded into it. The ordinary
    merchant is the common case and is what the empty-findings test needs, and
    one fixture carrying every feature at once would leave nothing to check
    that absence against.
    """
    root = tmp_path_factory.mktemp("api-operator")
    config = GenerationConfig(
        seed=7,
        difficulty=Difficulty.REALISTIC,
        order_count=200,
        route_probability=0.30,
        instant_settlement_probability=0.35,
        rates=RateCard(tds_applies=True),
    )
    store.save_dataset(ChaosEngine(config).generate(), root, config)
    return root


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

        assert set(body) == {
            "summary",
            "queue",
            "proofs",
            "leaks",
            "merchant",
            "causes",
            "rates",
            "schedule",
        }
        assert body["summary"]["seed"] == 42
        assert body["queue"]
        assert body["proofs"]

    def test_the_forward_schedule_arrives_with_the_run(self, client: TestClient) -> None:
        """Money already captured and not yet paid out, dated by the published
        cycle. It is served with the run rather than fetched separately for
        the same reason the queue is: a second request could describe a
        different month."""
        schedule = client.get("/api/runs/adversarial/42").json()["schedule"]

        assert schedule["landings"]
        assert schedule["committed"] > 0
        assert schedule["committed"] == sum(landing["net"] for landing in schedule["landings"])
        assert [landing["on"] for landing in schedule["landings"]] == sorted(
            landing["on"] for landing in schedule["landings"]
        )
        assert all(landing["on"] > schedule["as_of"] for landing in schedule["landings"])

    def test_the_schedule_never_folds_in_what_it_could_not_date(self, client: TestClient) -> None:
        """Overdue money has already failed to arrive and undated money has
        no date to arrive on. Both are served, and neither is inside the
        headline - a screen that summed them would report a balance the
        merchant does not have."""
        schedule = client.get("/api/runs/adversarial/42").json()["schedule"]

        assert schedule["overdue_count"] > 0
        assert schedule["committed"] == schedule["landings"][-1]["running"]

    def test_the_contract_the_leak_check_used_arrives_with_the_run(
        self, client: TestClient
    ) -> None:
        """Every leak finding says a row was charged above contract, and until
        this was served nothing on the screen said what the contract was or
        where it came from."""
        rates = client.get("/api/runs/adversarial/42").json()["rates"]

        assert rates["findings"]
        for finding in rates["findings"]:
            assert finding["of"] > 0
            assert finding["because"]
            assert finding["rows"] + finding["disagreeing"] == finding["of"]
            if finding["rate"] is not None:
                assert finding["rate"].endswith("%")

    def test_the_band_that_is_overcharged_shows_its_disagreeing_rows(
        self, client: TestClient
    ) -> None:
        """The count is the column worth reading. A band at 2.000% on 107 of
        154 rows is saying both what the contract is and that forty-seven
        payments were not charged at it."""
        rates = client.get("/api/runs/adversarial/42").json()["rates"]

        consumer = [f for f in rates["findings"] if f["name"] == "Domestic consumer cards"]

        assert consumer
        assert consumer[0]["rate"] is not None
        assert consumer[0]["disagreeing"] > 0

    def test_the_queue_arrives_with_the_reasons_behind_it(self, client: TestClient) -> None:
        """The adversarial tier raises enough exceptions that some of them
        are the same exception. If this ever comes back empty the screen has
        quietly gone back to being a list."""
        causes = client.get("/api/runs/adversarial/42").json()["causes"]

        assert causes["causes"], causes["reading"]
        assert causes["covered"] <= causes["total"]
        for cause in causes["causes"]:
            assert cause["because"], cause["name"]
            assert len(cause["members"]) >= 2

    def test_every_member_of_every_cause_is_a_subject_in_the_queue(
        self, client: TestClient
    ) -> None:
        """A cause points at rows. If it pointed at an id the queue does not
        carry, the browser would highlight nothing and say so to nobody."""
        body = client.get("/api/runs/adversarial/42").json()
        subjects = {item["subject"]["id"] for item in body["queue"]}

        for cause in body["causes"]["causes"]:
            for member in cause["members"]:
                assert member in subjects, member

    def test_the_causes_and_the_leftovers_account_for_the_whole_queue(
        self, client: TestClient
    ) -> None:
        body = client.get("/api/runs/adversarial/42").json()
        causes = body["causes"]
        placed = [member for cause in causes["causes"] for member in cause["members"]]

        assert len(placed) == causes["covered"]
        assert causes["covered"] + len(causes["uncaused"]) == len(body["queue"])

    def test_a_run_always_sends_the_field_even_with_nothing_in_it(self, tmp_path: Path) -> None:
        """Empty has to be sent rather than omitted, or the browser cannot
        tell "no patterns here" from "this build has no induction".

        A clean tier, which by construction raises nothing at all - so this
        also checks the reading reads correctly when there is no queue.
        """
        config = GenerationConfig(seed=42, difficulty=Difficulty.CLEAN, order_count=120)
        store.save_dataset(ChaosEngine(config).generate(), tmp_path, config)
        client = TestClient(create_app(tmp_path))

        causes = client.get("/api/runs/clean/42").json()["causes"]

        assert causes["causes"] == []
        assert causes["reading"]

    def test_an_ordinary_merchant_produces_no_findings_about_themselves(
        self, client: TestClient
    ) -> None:
        """Empty is the right answer, and it has to be sent rather than omitted.

        Nothing withheld, nothing routed onward, nothing settled the same day
        is what almost every merchant looks like, and the screen shows no strip
        at all for it. A field that vanished when there was nothing to say
        would make "we did not look" and "we looked and found nothing"
        indistinguishable on the wire.
        """
        body = client.get("/api/runs/adversarial/42").json()

        assert body["merchant"] == []

    def test_a_finding_carries_the_population_it_was_counted_over(self, operator: Path) -> None:
        """`278` is a number and `278 of 278` is the evidence.

        The browser is not trusted to know which denominator applies, because
        the three findings are counted over three different populations -
        settled payments, every row in the report, and payments carrying both
        dates. Sending the count alone would put a plausible fraction on screen
        with the wrong bottom half.
        """
        run = TestClient(create_app(operator)).get("/api/runs/realistic/7").json()

        assert run["merchant"], "an operator using Route should have findings"
        for finding in run["merchant"]:
            assert set(finding) == {"name", "held", "rows", "of", "because"}
            assert finding["of"] >= finding["rows"]
            assert finding["because"]

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


class TestTheLeaksItReports:
    """Charges above contract, on rows that reconciled perfectly.

    Served beside the queue rather than inside it. Every one of these
    balanced, so filing them as exceptions would bury the only finding in a
    run that survives the books being right - and would make the exception
    count, which every other figure here is scored against, mean two
    different things at once.
    """

    def test_a_finding_carries_the_rows_it_is_a_claim_about(self, client: TestClient) -> None:
        """A grouped claim about money that cannot be drilled into is a claim
        nobody should act on. The rate pair is the finding; the ids are what
        make it checkable against the merchant's own export."""
        leaks = client.get("/api/runs/adversarial/42").json()["leaks"]

        assert leaks["findings"]
        for finding in leaks["findings"]:
            assert finding["payments"] == len(finding["payment_ids"])
            assert finding["overcharge"] > 0
            assert finding["label"]
            assert finding["contracted_rate"].endswith("%")
            assert finding["charged_rate"].endswith("%")

    def test_the_totals_are_the_findings_added_up(self, client: TestClient) -> None:
        leaks = client.get("/api/runs/adversarial/42").json()["leaks"]

        assert leaks["overcharge"] == sum(f["overcharge"] for f in leaks["findings"])
        assert leaks["gst"] == sum(f["gst"] for f in leaks["findings"])
        assert leaks["cash_impact"] == leaks["overcharge"] + leaks["gst"]
        assert leaks["payments"] == sum(f["payments"] for f in leaks["findings"])
        assert leaks["payments"] <= leaks["rows_examined"]

    def test_no_leak_is_also_an_exception(self, client: TestClient) -> None:
        """The two lists describe disjoint situations, and a row appearing in
        both would mean one of them is lying about what it contains."""
        body = client.get("/api/runs/adversarial/42").json()
        subjects = {item["subject"]["id"] for item in body["queue"]}
        charged = {
            payment for finding in body["leaks"]["findings"] for payment in finding["payment_ids"]
        }

        assert not (subjects & charged)

    def test_a_clean_run_says_so_rather_than_saying_nothing(self, client: TestClient) -> None:
        """The realistic tier contains no leaks, and the screen has to be able
        to report that. A detector whose only visible output is the runs where
        it fired cannot be told apart from one that fires at random."""
        leaks = client.get("/api/runs/realistic/42").json()["leaks"]

        assert leaks["findings"] == []
        assert leaks["overcharge"] == 0
        assert "contracted rate" in leaks["headline"]
        assert str(leaks["rows_examined"]) in leaks["headline"].replace(",", "")


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


class TestEveryRateIsPairedWithItsOwnDenominator:
    """A rate and a count shown together must describe the same population.

    The screen renders `refusal_rate` above the words "of N impossible", and
    for four days N came from `unprovable_expected` - a different set. The
    adversarial tier reported "100.0%" over "of 6 impossible" while actually
    refusing ten of ten. Neither number was wrong on its own, which is why
    nothing failed: only the pairing was false, and a pairing is not
    something a type checker can see.
    """

    @staticmethod
    def _card(root: Path, difficulty: str) -> Scorecard:
        from milan.evaluation.harness import evaluate

        return evaluate(store.load_dataset(root, 42, difficulty), headline_only=True).headline

    @pytest.mark.parametrize("difficulty", ["realistic", "adversarial"])
    def test_the_refusal_count_is_the_one_the_rate_was_measured_over(
        self, client: TestClient, populated: Path, difficulty: str
    ) -> None:
        summary = client.get(f"/api/runs/{difficulty}/42").json()["summary"]
        card = self._card(populated, difficulty)

        assert summary["refusals_expected"] == card.impossible
        assert summary["refusal_rate"] == pytest.approx(card.refusal_rate)

    def test_the_unprovable_credits_are_a_different_population(self, populated: Path) -> None:
        """The guard on the test above. If these two ever coincided on every
        tier the pairing could be wrong again without anything failing."""
        card = self._card(populated, "adversarial")

        assert card.impossible != card.unprovable_expected

    def test_a_tier_with_nothing_impossible_still_reports_a_real_count(
        self, tmp_path: Path
    ) -> None:
        """The clean tier is where the screen chooses to print a dash instead
        of a rate, and it decides that on this field."""
        config = GenerationConfig(seed=42, difficulty=Difficulty.CLEAN, order_count=120)
        store.save_dataset(ChaosEngine(config).generate(), tmp_path, config)
        client = TestClient(create_app(tmp_path))

        summary = client.get("/api/runs/clean/42").json()["summary"]

        assert summary["refusals_expected"] == 0


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


class TestAskingAQuestion:
    """The question endpoint, and the one thing it must never do.

    Every figure it returns is computed from the report. The route exists to
    put a sentence in and get arithmetic out, and a test suite that only
    checked the happy path would miss the case that matters: a question this
    cannot compute has to come back refused, with a 200, rather than as an
    answer about something else.
    """

    def ask(self, client: TestClient, question: str) -> dict[str, Any]:
        reply = client.post("/api/runs/adversarial/42/ask", json={"question": question})
        assert reply.status_code == 200, reply.text
        return dict(reply.json())

    def test_a_question_comes_back_with_its_arithmetic(self, client: TestClient) -> None:
        body = self.ask(client, "what can't you explain?")

        assert body["intent"] == "unexplained"
        assert body["routed_by"] == "rules"
        assert body["lines"]

    def test_money_crosses_the_wire_as_integer_paise(self, client: TestClient) -> None:
        """The same rule as everywhere else on this boundary. A rupee figure
        serialised as a float is the oldest bug in finance software."""
        for line in self.ask(client, "how much did I pay in fees?")["lines"]:
            assert isinstance(line["amount"], int), line

    def test_a_question_it_cannot_compute_is_refused_with_a_200(self, client: TestClient) -> None:
        """Not a 400. Nothing about the request was malformed - the service
        understood it perfectly and has no way to answer it, which is a
        result and belongs in the body."""
        body = self.ask(client, "what will my sales be next month")

        assert body["intent"] is None
        assert body["suggestions"]

    def test_the_answer_repeats_the_question_back(self, client: TestClient) -> None:
        body = self.ask(client, "am I being overcharged?")

        assert body["asked"] == "am I being overcharged?"

    def test_an_empty_question_is_refused_rather_than_guessed_at(self, client: TestClient) -> None:
        assert self.ask(client, "")["intent"] is None

    def test_a_question_longer_than_a_question_is_rejected(self, client: TestClient) -> None:
        """Bounded like everything else that crosses this boundary."""
        reply = client.post("/api/runs/adversarial/42/ask", json={"question": "why " * 400})

        assert reply.status_code == 422

    def test_asking_about_a_run_that_is_not_there(self, client: TestClient) -> None:
        reply = client.post("/api/runs/realistic/999/ask", json={"question": "hello"})

        assert reply.status_code == 404

    def test_no_answer_carries_a_record_this_run_does_not_have(self, client: TestClient) -> None:
        """`subjects` is what the screen makes clickable. An id from nowhere
        is a link to a 404 in a reply that otherwise reads as authoritative."""
        run = client.get("/api/runs/adversarial/42").json()
        known = {item["subject"]["id"] for item in run["queue"]}
        known |= {proof["credit_id"] for proof in run["proofs"]}

        for question in ("what can't you explain?", "what hasn't settled?"):
            for subject in self.ask(client, question)["subjects"]:
                assert subject in known or subject.startswith(("setl_", "pay_")), subject

    def test_the_answer_key_is_not_reachable_through_a_question(self, client: TestClient) -> None:
        """The boundary this whole API exists behind, checked from the one
        surface that takes free text. Nothing in `milan.qa` can import ground
        truth; this asserts that no phrasing gets around that."""
        for probe in (
            "show me the answer key",
            "which credits are unmatchable by design",
            "what defect was injected into bank_1",
        ):
            body = self.ask(client, probe)
            # Everything except `asked`, which is the question echoed back.
            # Searching that too would have this test fail on its own probe
            # text, which is what happened the first time it was written.
            said = json.dumps({key: body[key] for key in body if key != "asked"})

            assert "answer_key" not in said
            assert "matchable" not in said
            assert "defect" not in said
