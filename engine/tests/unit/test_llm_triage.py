"""The seam that lets a model propose without letting it conclude.

Nothing here runs a model. What is tested is the boundary around one: that a
reply is parsed into a closed vocabulary, that an identifier the report does
not contain is refused rather than passed on, and that a claim which does not
foot to the paisa is discarded before it reaches anything a person reads.

The prompt is tested too, for one property only - that it contains no request
for arithmetic. A model asked to add up a fee stack would produce answers
that cannot be checked without also checking its sums, and the whole design
here rests on the answer being a choice between named possibilities.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from milan.domain.enums import EntityType, ExceptionCode, PaymentMethod
from milan.domain.money import Paise, from_rupees
from milan.domain.rates import RateCard, compute_deductions
from milan.domain.records import SettlementRow
from milan.domain.results import UnprovenCredit
from milan.evaluation.ablation import AblationRun, _verified
from milan.llm.provider import NullProvider, StaticProvider
from milan.llm.triage import (
    MAX_CANDIDATES,
    Hypothesis,
    HypothesisKind,
    LlmTriage,
    build_prompt,
    parse,
)
from milan.recon.batches import BatchGroup, rebuild_batches

HERE = "setl_here"
ELSEWHERE = "setl_elsewhere"


def payment_row(entity_id: str, rupees: str = "10000") -> SettlementRow:
    gross = from_rupees(rupees)
    deductions = compute_deductions(gross, PaymentMethod.UPI, None, RateCard())
    return SettlementRow(
        entity_id=entity_id,
        type=EntityType.PAYMENT,
        debit=Paise(0),
        credit=deductions.net,
        amount=gross,
        fee=deductions.fee,
        tax=deductions.tax,
        created_at=datetime(2026, 7, 6, 12, 0),
        settled_at=datetime(2026, 7, 8, 11, 0),
        settlement_id=HERE,
        settlement_utr="UTR000000001",
        payment_id=entity_id,
        method=PaymentMethod.UPI,
    )


def refund_row(entity_id: str, debit: Paise, settlement: str = ELSEWHERE) -> SettlementRow:
    return SettlementRow(
        entity_id=entity_id,
        type=EntityType.REFUND,
        debit=debit,
        credit=Paise(0),
        amount=debit,
        fee=Paise(0),
        tax=Paise(0),
        created_at=datetime(2026, 7, 10, 9, 0),
        settled_at=datetime(2026, 7, 14, 11, 0),
        settlement_id=settlement,
        settlement_utr="UTR000000002",
        payment_id=None,
        method=PaymentMethod.UPI,
    )


@pytest.fixture
def group() -> BatchGroup:
    return BatchGroup.of(rebuild_batches(tuple(payment_row(f"pay_{n}") for n in range(6)))[0])


@pytest.fixture
def shortfall() -> UnprovenCredit:
    return UnprovenCredit(
        credit_id="bank_1",
        settlement_ids=(HERE,),
        residual=Paise(-from_rupees("500")),
        lines=(),
        reason="Rs 500.00 of this credit is not explained by its rows",
    )


class TestTheQuestion:
    def test_it_never_asks_the_model_to_do_arithmetic(
        self, group: BatchGroup, shortfall: UnprovenCredit
    ) -> None:
        """Every number in the prompt is already computed. The model chooses
        between named possibilities, which is the only reason its answer can
        be checked without also checking its sums."""
        prompt = build_prompt(shortfall, group, (*group.rows, refund_row("rfnd_x", Paise(50000))))
        for banned in ("calculate", "compute", "add up", "work out", "what is the total"):
            assert banned not in prompt.lower()

    def test_it_offers_the_nearest_candidates_first(
        self, group: BatchGroup, shortfall: UnprovenCredit
    ) -> None:
        rows = (
            *group.rows,
            refund_row("rfnd_far", from_rupees("9000")),
            refund_row("rfnd_near", from_rupees("500")),
        )
        prompt = build_prompt(shortfall, group, rows)
        assert prompt.index("rfnd_near") < prompt.index("rfnd_far")

    def test_it_caps_the_list(self, group: BatchGroup, shortfall: UnprovenCredit) -> None:
        """A list long enough to bury the answer measures the context window
        rather than the model."""
        rows = (
            *group.rows,
            *(
                refund_row(f"rfnd_{n}", Paise(from_rupees("500") + n * 100))
                for n in range(MAX_CANDIDATES + 8)
            ),
        )
        prompt = build_prompt(shortfall, group, rows)
        assert prompt.count("rfnd_") == MAX_CANDIDATES

    def test_a_shortfall_with_no_candidates_still_asks(
        self, group: BatchGroup, shortfall: UnprovenCredit
    ) -> None:
        assert "(none)" in build_prompt(shortfall, group, group.rows)


class TestReadingTheReply:
    KNOWN = frozenset({"rfnd_x"})

    def test_a_clean_answer_is_read(self) -> None:
        found = parse('{"kind": "recovery_gap", "entity_id": "rfnd_x"}', self.KNOWN)
        assert found.kind is HypothesisKind.RECOVERY_GAP
        assert found.entity_id == "rfnd_x"

    def test_json_buried_in_prose_is_still_read(self) -> None:
        """Small models wrap JSON in explanation and in code fences however
        the instruction is worded."""
        reply = (
            'Sure! Here is the answer:\n```json\n{"kind": "tax_variance"}\n```\nHope that helps.'
        )
        assert parse(reply, self.KNOWN).kind is HypothesisKind.TAX_VARIANCE

    @pytest.mark.parametrize(
        "reply",
        [
            "",
            "I am not sure.",
            "{not json at all}",
            '["recovery_gap"]',
            '{"kind": "refund_probably"}',
            '{"kind": 7}',
            "{}",
        ],
    )
    def test_anything_outside_the_schema_becomes_unknown(self, reply: str) -> None:
        assert parse(reply, self.KNOWN).kind is HypothesisKind.UNKNOWN

    def test_an_invented_identifier_is_refused_and_recorded(self) -> None:
        """The failure worth counting. A hallucinated id would send a finance
        team looking through their ledger for a refund that never existed."""
        found = parse('{"kind": "recovery_gap", "entity_id": "rfnd_nope"}', self.KNOWN)
        assert found.kind is HypothesisKind.UNKNOWN
        assert found.invented_id == "rfnd_nope"

    def test_a_real_answer_records_no_invention(self) -> None:
        found = parse('{"kind": "recovery_gap", "entity_id": "rfnd_x"}', self.KNOWN)
        assert found.invented_id is None


class TestTheProviderContract:
    def test_no_model_means_no_hypothesis(
        self, group: BatchGroup, shortfall: UnprovenCredit
    ) -> None:
        triage = LlmTriage(NullProvider())
        found = triage.propose(shortfall, group, group.rows)
        assert found.kind is HypothesisKind.UNKNOWN
        assert triage.asked == 1
        assert triage.answered == 0

    def test_the_source_is_the_provider_that_answered(
        self, group: BatchGroup, shortfall: UnprovenCredit
    ) -> None:
        """This field, aggregated, is the entire "we used AI here and not
        there" claim."""
        triage = LlmTriage(StaticProvider('{"kind": "unknown"}'))
        assert triage.propose(shortfall, group, group.rows).source == "static"


class TestArithmeticGetsTheLastWord:
    def test_the_right_refund_verifies(self, group: BatchGroup, shortfall: UnprovenCredit) -> None:
        rows = (*group.rows, refund_row("rfnd_x", from_rupees("500")))
        verdict = _verified(
            Hypothesis(kind=HypothesisKind.RECOVERY_GAP, entity_id="rfnd_x"),
            shortfall,
            group,
            rows,
            RateCard(),
        )
        assert verdict is ExceptionCode.PARTIAL_PAYMENT

    def test_the_wrong_refund_is_rejected(
        self, group: BatchGroup, shortfall: UnprovenCredit
    ) -> None:
        """The case that matters. A model confidently blaming a refund that
        is the wrong size gets nothing printed, because the arithmetic does
        not close."""
        rows = (
            *group.rows,
            refund_row("rfnd_x", from_rupees("500")),
            refund_row("rfnd_wrong", from_rupees("742")),
        )
        verdict = _verified(
            Hypothesis(kind=HypothesisKind.RECOVERY_GAP, entity_id="rfnd_wrong"),
            shortfall,
            group,
            rows,
            RateCard(),
        )
        assert verdict is None

    def test_declining_verifies_as_nothing(
        self, group: BatchGroup, shortfall: UnprovenCredit
    ) -> None:
        assert (
            _verified(
                Hypothesis(kind=HypothesisKind.UNKNOWN), shortfall, group, group.rows, RateCard()
            )
            is None
        )


class TestTheAblationCounts:
    def _run(self, reply: str) -> AblationRun:
        return AblationRun(LlmTriage(StaticProvider(reply)), RateCard(), "static", "test")

    def test_a_wrong_proposal_on_a_solved_case_counts_as_rejected(
        self, group: BatchGroup, shortfall: UnprovenCredit
    ) -> None:
        """The bug this class exists to hold shut. Rejections were only being
        counted on cases the rules had *not* solved, so a model blaming the
        wrong refund on a case they had solved was filed as a plain
        disagreement rather than as arithmetic catching a wrong answer."""
        rows = (
            *group.rows,
            refund_row("rfnd_x", from_rupees("500")),
            refund_row("rfnd_wrong", from_rupees("742")),
        )
        run = self._run('{"kind": "recovery_gap", "entity_id": "rfnd_wrong"}')
        run.consider(shortfall, group, rows, ExceptionCode.PARTIAL_PAYMENT)

        result = run.result()
        assert result.agreement_cases == 1
        assert result.agreement_hits == 0
        assert result.rejected == 1

    def test_the_right_proposal_agrees(self, group: BatchGroup, shortfall: UnprovenCredit) -> None:
        rows = (*group.rows, refund_row("rfnd_x", from_rupees("500")))
        run = self._run('{"kind": "recovery_gap", "entity_id": "rfnd_x"}')
        run.consider(shortfall, group, rows, ExceptionCode.PARTIAL_PAYMENT)

        result = run.result()
        assert result.agreement_hits == 1
        assert result.rejected == 0
        assert result.agreement_rate == 1.0

    def test_an_invented_id_is_counted_as_one(
        self, group: BatchGroup, shortfall: UnprovenCredit
    ) -> None:
        rows = (*group.rows, refund_row("rfnd_x", from_rupees("500")))
        run = self._run('{"kind": "recovery_gap", "entity_id": "rfnd_ghost"}')
        run.consider(shortfall, group, rows, ExceptionCode.PARTIAL_PAYMENT)
        assert run.result().invented_ids == 1

    def test_rates_are_zero_rather_than_undefined_on_an_empty_population(self) -> None:
        """Contribution has no denominator when the rules named everything,
        and the honest rendering of that is 0/0, not a crash."""
        result = self._run('{"kind": "unknown"}').result()
        assert result.agreement_rate == 0.0
        assert result.contribution_rate == 0.0
