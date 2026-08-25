"""Who checks the scorer?

Every number in this project's submission comes out of `score()`. The oracle
test proves the matcher is right; nothing proved the thing that grades the
matcher was right, and a scorer that counts a wrong match as correct raises
every published figure at once while every other test stays green.

So the reports here are written by hand, with the answer known in advance, and
the scorer is asked what it makes of them. Several of these cases are the
design stance itself - a forced answer that happens to be right is a false
positive, a merged credit matched to half of itself is not half a success -
and a stance that is not tested is a paragraph in a README.
"""

from __future__ import annotations

from milan.domain.enums import ExceptionCode, MatchStrategy
from milan.domain.money import ZERO, Paise, from_rupees
from milan.domain.results import Proof, ProofLine, ReconException, ReconReport
from milan.domain.truth import AnswerKey, CreditTruth
from milan.evaluation.harness import score

AMOUNT = from_rupees("1000")


def _truth(
    credit_id: str,
    *settlements: str,
    matchable: bool = True,
    provable: bool = True,
    defect: str | None = None,
) -> CreditTruth:
    return CreditTruth(
        credit_id=credit_id,
        settlement_ids=settlements,
        entity_ids=(),
        gross=AMOUNT,
        fee=Paise(0),
        tax=Paise(0),
        tds=Paise(0),
        adjustments=Paise(0),
        rounding_drift=Paise(0),
        matchable=matchable,
        provable=provable,
        defect=defect,
    )


def _proof(credit_id: str, *settlements: str, drift: Paise = ZERO) -> Proof:
    """A proof that balances."""
    return Proof(
        credit_id=credit_id,
        settlement_ids=settlements,
        credit_amount=AMOUNT,
        lines=(ProofLine(label="Settled payments", amount=AMOUNT),),
        strategy=MatchStrategy.EXACT_UTR,
        confidence=1.0,
        drift=drift,
    )


def _broken_proof(credit_id: str, *settlements: str) -> Proof:
    """Claimed, but a rupee short - so not a claim at all."""
    return Proof(
        credit_id=credit_id,
        settlement_ids=settlements,
        credit_amount=AMOUNT,
        lines=(ProofLine(label="Settled payments", amount=Paise(AMOUNT - 100)),),
        strategy=MatchStrategy.AMOUNT_DATE,
        confidence=0.5,
    )


def _report(*proofs: Proof, exceptions: tuple[ReconException, ...] = ()) -> ReconReport:
    return ReconReport(
        seed=42,
        difficulty="realistic",
        records_processed=100,
        proofs=proofs,
        exceptions=exceptions,
        duration_seconds=0.01,
    )


def _answers(*credits: CreditTruth) -> AnswerKey:
    return AnswerKey(seed=42, credits=credits)


class TestTheFourOutcomes:
    def test_the_right_settlement_is_a_true_positive(self) -> None:
        card = score(_report(_proof("c1", "s1")), _answers(_truth("c1", "s1")), "t")

        assert (card.true_positives, card.false_positives) == (1, 0)
        assert card.match_rate == 1.0
        assert card.precision == 1.0

    def test_the_wrong_settlement_is_a_false_positive(self) -> None:
        card = score(_report(_proof("c1", "s2")), _answers(_truth("c1", "s1")), "t")

        assert (card.true_positives, card.false_positives) == (0, 1)
        assert card.match_rate == 0.0
        assert card.precision == 0.0

    def test_a_resolvable_credit_left_alone_is_a_miss(self) -> None:
        card = score(_report(), _answers(_truth("c1", "s1")), "t")

        assert card.false_negatives == 1
        assert card.false_positives == 0
        assert card.match_rate == 0.0

    def test_an_impossible_credit_left_alone_is_a_correct_refusal(self) -> None:
        card = score(_report(), _answers(_truth("c1", "s1", matchable=False)), "t")

        assert card.correct_refusals == 1
        assert card.refusal_rate == 1.0
        assert card.false_negatives == 0
        assert card.matchable == 0

    def test_the_denominators_never_count_the_impossible(self) -> None:
        """Otherwise a correct refusal would lower the match rate, and the
        system would be penalised for the behaviour it exists to have."""
        card = score(
            _report(_proof("c1", "s1")),
            _answers(_truth("c1", "s1"), _truth("c2", "s2", matchable=False)),
            "t",
        )

        assert card.credits_total == 2
        assert (card.matchable, card.impossible) == (1, 1)
        assert card.match_rate == 1.0


class TestTheStanceTheProjectTakes:
    def test_a_lucky_guess_on_an_impossible_credit_still_counts_against_us(self) -> None:
        """The answer is right and the system could not have known it.

        This is the case the whole design argument rests on: two credits are
        indistinguishable, something answers anyway, and it is correct about
        half the time. Scoring the correct half as a win is how a coin flip
        comes to look like accuracy, so a forced answer is a false positive
        even when it lands.
        """
        card = score(
            _report(_proof("c1", "s1")),
            _answers(_truth("c1", "s1", matchable=False)),
            "t",
        )

        assert card.false_positives == 1
        assert card.true_positives == 0
        assert card.correct_refusals == 0
        assert card.precision == 0.0

    def test_half_a_merged_credit_is_not_half_a_success(self) -> None:
        """One bank line covering two payouts, matched to one of them. The
        merchant is still short a settlement and now has a green tick."""
        card = score(
            _report(_proof("c1", "s1")),
            _answers(_truth("c1", "s1", "s2")),
            "t",
        )

        assert card.false_positives == 1
        assert card.merged_resolved == 0
        assert card.merged_rate == 0.0

    def test_a_merged_credit_matched_to_its_whole_set_counts_once(self) -> None:
        card = score(
            _report(_proof("c1", "s1", "s2")),
            _answers(_truth("c1", "s1", "s2")),
            "t",
        )

        assert (card.true_positives, card.merged_resolved, card.merged_expected) == (1, 1, 1)
        assert card.merged_rate == 1.0

    def test_the_order_of_a_merged_set_is_not_part_of_the_answer(self) -> None:
        card = score(
            _report(_proof("c1", "s2", "s1")),
            _answers(_truth("c1", "s1", "s2")),
            "t",
        )

        assert card.true_positives == 1

    def test_a_proof_that_does_not_balance_is_not_a_claim(self) -> None:
        """It is neither credited nor held against precision - it never
        reached the merchant as an answer."""
        card = score(_report(_broken_proof("c1", "s1")), _answers(_truth("c1", "s1")), "t")

        assert card.proofs_claimed == 1
        assert card.proofs_balanced == 0
        assert (card.true_positives, card.false_positives) == (0, 0)
        assert card.false_negatives == 1


class TestTheThirdOutcome:
    """Identifiable and unprovable: the payout disagrees with the report, so
    the right answer is an exception naming the shortfall, never a match."""

    def _unprovable(self) -> AnswerKey:
        return _answers(_truth("c1", "s1", provable=False, defect="FEE"))

    def test_an_unprovable_credit_is_not_counted_as_a_miss(self) -> None:
        card = score(_report(), self._unprovable(), "t")

        assert card.unprovable_expected == 1
        assert card.matchable == 0
        assert card.false_negatives == 0

    def test_naming_the_shortfall_is_what_scores(self) -> None:
        named = ReconException(
            code=ExceptionCode.FEE_DEDUCTION,
            subject_id="c1",
            amount=from_rupees("12"),
            summary="a fee the report does not show",
        )
        card = score(_report(exceptions=(named,)), self._unprovable(), "t")

        assert card.unprovable_explained == 1
        assert card.explained_rate == 1.0

    def test_saying_only_that_it_differs_does_not(self) -> None:
        """UNEXPLAINED is what a spreadsheet already does."""
        shrug = ReconException(
            code=ExceptionCode.UNEXPLAINED,
            subject_id="c1",
            amount=from_rupees("12"),
            summary="these amounts differ",
        )
        card = score(_report(exceptions=(shrug,)), self._unprovable(), "t")

        assert card.unprovable_explained == 0
        assert card.explained_rate == 0.0
        assert card.unexplained_by_defect == {"FEE": 1}


class TestTheDriftTotal:
    def test_drift_is_summed_signed_and_absolute(self) -> None:
        """Net is the outcome, gross is the exposure. Reporting only the net
        would let drift in both directions read as drift that never happens.
        """
        card = score(
            _report(
                _proof("c1", "s1", drift=Paise(3)),
                _proof("c2", "s2", drift=Paise(-2)),
                _proof("c3", "s3"),
            ),
            _answers(_truth("c1", "s1"), _truth("c2", "s2"), _truth("c3", "s3")),
            "t",
        )

        assert card.proofs_with_drift == 2
        assert card.drift_net == 1
        assert card.drift_gross == 5


class TestWhatTheHeadlineHides:
    def test_a_guesser_ties_on_match_rate_and_loses_on_precision(self) -> None:
        """The measurement that has to hold for any of this to mean anything.

        Two credits are resolvable, two are impossible. The guesser answers
        all four and is right about the impossible ones by luck. Its match
        rate ties; its precision does not, and precision is the column that
        separates them.
        """
        answers = _answers(
            _truth("c1", "s1"),
            _truth("c2", "s2"),
            _truth("c3", "s3", matchable=False),
            _truth("c4", "s4", matchable=False),
        )
        honest = score(_report(_proof("c1", "s1"), _proof("c2", "s2")), answers, "honest")
        guesser = score(
            _report(
                _proof("c1", "s1"),
                _proof("c2", "s2"),
                _proof("c3", "s3"),
                _proof("c4", "s4"),
            ),
            answers,
            "guesser",
        )

        assert honest.match_rate == guesser.match_rate == 1.0
        assert honest.precision == 1.0
        assert guesser.precision == 0.5
        assert (honest.refusal_rate, guesser.refusal_rate) == (1.0, 0.0)
