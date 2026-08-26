"""Addressing an answer to a file, when the file's name cannot be typed.

A sheet inside a workbook is identified as
`Settlement Report Aug 2026.xlsx · Payouts`. That name is right — everything
downstream is keyed on it, and two sheets answering to one key would be two
halves of a month overwriting each other — and it is also unusable on a
command line, because it contains a middle dot that nobody types and most
Windows terminals render as a question mark.

The import was printing exactly that string as the suggested `--map` line. So
the suggestion was useless precisely where it was most needed: on the file
format a merchant is most likely to hand over.

An abbreviation fixes the typing. Ambiguity is refused rather than resolved,
for the same reason it is refused everywhere else here: guessing which of two
files somebody meant is how the wrong column gets mapped in silence.
"""

from __future__ import annotations

import pytest

from milan.cli.main import _apply_answers, _resolve_file

KNOWN = (
    "Settlement Report Aug 2026.xlsx · Payouts",
    "Settlement Report Aug 2026.xlsx · Transactions",
    "Acct Statement_XX1234.csv",
    "axis_918020012345678_aug.csv",
)


class TestAFileCanBeNamedByAnyUniquePartOfItsName:
    def test_the_full_name_still_works(self) -> None:
        assert _resolve_file(KNOWN[0], KNOWN) == KNOWN[0]

    def test_a_sheet_name_alone_is_enough(self) -> None:
        """The whole point: `--map Payouts:credit=...` instead of a line with
        a middle dot in it."""
        assert _resolve_file("Payouts", KNOWN) == KNOWN[0]
        assert _resolve_file("Transactions", KNOWN) == KNOWN[1]

    def test_case_does_not_matter(self) -> None:
        assert _resolve_file("payouts", KNOWN) == KNOWN[0]

    def test_a_partial_file_name_is_enough(self) -> None:
        assert _resolve_file("Acct", KNOWN) == KNOWN[2]

    def test_surrounding_space_is_forgiven(self) -> None:
        assert _resolve_file("  Payouts ", KNOWN) == KNOWN[0]


class TestAnAmbiguousNameIsRefusedRatherThanResolved:
    def test_a_prefix_matching_two_sheets_is_refused(self) -> None:
        """`Settlement Report` names both sheets of the workbook. Picking the
        first would map a settlement column onto the payments sheet."""
        with pytest.raises(ValueError, match="more than one file"):
            _resolve_file("Settlement Report", KNOWN)

    def test_the_refusal_lists_what_it_could_have_meant(self) -> None:
        with pytest.raises(ValueError) as failure:
            _resolve_file("Settlement Report", KNOWN)
        assert "Payouts" in str(failure.value)
        assert "Transactions" in str(failure.value)

    def test_a_name_that_matches_nothing_says_what_was_read(self) -> None:
        """An import that refuses and then leaves the operator guessing at the
        syntax has refused twice."""
        with pytest.raises(ValueError) as failure:
            _resolve_file("bank.csv", KNOWN)
        assert "no file here is called" in str(failure.value)
        assert "Acct Statement_XX1234.csv" in str(failure.value)


class TestTheAnswersReachTheRightFile:
    def test_an_abbreviated_answer_lands_on_the_full_name(self) -> None:
        found = _apply_answers({}, ["Payouts:credit=Amount Paid In"], KNOWN)
        assert set(found) == {KNOWN[0]}
        assert found[KNOWN[0]].columns == {"credit": "Amount Paid In"}

    def test_two_answers_to_the_same_sheet_accumulate(self) -> None:
        found = _apply_answers(
            {},
            ["Payouts:credit=Amount Paid In", "Payouts:debit=Amount Taken Out"],
            KNOWN,
        )
        assert found[KNOWN[0]].columns == {
            "credit": "Amount Paid In",
            "debit": "Amount Taken Out",
        }

    def test_answers_to_two_sheets_stay_apart(self) -> None:
        """Both sheets live in one file. An abbreviation that collapsed them
        would put the settlement mapping on the payments table."""
        found = _apply_answers(
            {},
            ["Payouts:credit=Amount Paid In", "Transactions:payment_id=Payment Ref"],
            KNOWN,
        )
        assert set(found) == {KNOWN[0], KNOWN[1]}

    def test_a_malformed_flag_is_refused(self) -> None:
        with pytest.raises(ValueError, match="file:field=value"):
            _apply_answers({}, ["Payouts:credit"], KNOWN)

    def test_without_a_file_list_the_name_is_taken_literally(self) -> None:
        """`_apply_answers` is called before the files are read in one path,
        and an abbreviation cannot be resolved against nothing."""
        found = _apply_answers({}, ["bank.csv:amount=Deposit"], ())
        assert set(found) == {"bank.csv"}
