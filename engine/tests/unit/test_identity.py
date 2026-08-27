"""The arithmetic that decides a proposal, and what it refuses to decide.

Every test here is about the same trade. Accepting a model's suggestion
without asking is only permissible where the file itself can be made to
confirm it, so the cases that matter are not the ones where the check passes
- they are the ones where a wrong mapping is put in front of it and it has to
say no.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from milan.domain.dataset import Dataset
from milan.ingest import identity
from milan.ingest.reading import SourceFile, read
from milan.ingest.schema import RecordKind
from milan.samples import build, dialects
from milan.samples.truth import ICICI, UNFAMILIAR


@pytest.fixture(scope="module")
def data() -> Dataset:
    return build.month(seed=42, orders=200)


@pytest.fixture(scope="module")
def settlement(data: Dataset, tmp_path_factory: pytest.TempPathFactory) -> SourceFile:
    path = tmp_path_factory.mktemp("identity") / "payouts.csv"
    dialects.unfamiliar_settlement(data, path)
    return read(path)


@pytest.fixture(scope="module")
def icici(data: Dataset, tmp_path_factory: pytest.TempPathFactory) -> SourceFile:
    path = tmp_path_factory.mktemp("identity") / "icici.csv"
    dialects.icici_statement(data, path)
    return read(path)


# ------------------------------------------------------ the settlement equation


def test_the_true_mapping_satisfies_the_equation(settlement: SourceFile) -> None:
    verdict = identity.check(settlement, RecordKind.SETTLEMENT_ROWS, dict(UNFAMILIAR.columns))
    assert verdict.holds
    assert verdict.failed == 0
    assert verdict.checked >= identity.MINIMUM_ROWS
    assert "arithmetic holds" in verdict.account


def test_credit_and_debit_the_wrong_way_round_is_caught(settlement: SourceFile) -> None:
    """The failure the whole check exists for.

    Swapping these two produces a file that still totals correctly and reports
    every payout as money leaving the account. No downstream arithmetic
    notices, because the arithmetic is symmetric - which is exactly why it has
    to be caught here.
    """
    columns = dict(UNFAMILIAR.columns)
    columns["credit"], columns["debit"] = columns["debit"], columns["credit"]

    verdict = identity.check(settlement, RecordKind.SETTLEMENT_ROWS, columns)

    assert not verdict.holds
    assert verdict.failed > 0
    assert "does not hold" in verdict.reason


def test_the_gross_amount_pointed_at_the_fee_is_caught(settlement: SourceFile) -> None:
    columns = dict(UNFAMILIAR.columns)
    columns["amount"] = columns["fee"]

    assert not identity.check(settlement, RecordKind.SETTLEMENT_ROWS, columns).holds


def test_two_fields_sharing_one_column_is_never_proof(settlement: SourceFile) -> None:
    columns = dict(UNFAMILIAR.columns)
    columns["tax"] = columns["fee"]

    assert not identity.check(settlement, RecordKind.SETTLEMENT_ROWS, columns).holds


def test_a_missing_money_column_cannot_be_endorsed(settlement: SourceFile) -> None:
    columns = dict(UNFAMILIAR.columns)
    del columns["tax"]

    verdict = identity.check(settlement, RecordKind.SETTLEMENT_ROWS, columns)

    assert not verdict.holds
    assert "no column for tax" in verdict.reason


def test_no_identity_is_claimed_for_other_kinds(settlement: SourceFile) -> None:
    """Silence is not proof.

    An orders export has no equation over its columns. The check has to say
    so, rather than returning a verdict that reads as approval.
    """
    verdict = identity.check(settlement, RecordKind.ORDERS, dict(UNFAMILIAR.columns))

    assert not verdict.holds
    assert "no arithmetic identity" in verdict.reason


def test_too_few_rows_is_not_a_proof(tmp_path: Path, data: Dataset) -> None:
    path = tmp_path / "short.csv"
    dialects.unfamiliar_settlement(data, path)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:4]), encoding="utf-8")

    verdict = identity.check(read(path), RecordKind.SETTLEMENT_ROWS, dict(UNFAMILIAR.columns))

    assert not verdict.holds
    assert "too few" in verdict.reason


# ----------------------------------------------------- eliminating on a statement


def test_the_deposit_column_survives_elimination(icici: SourceFile) -> None:
    verdict = identity.bank_amount(
        icici,
        ICICI.columns["amount"],
        ("S No.", "Withdrawal Amount (INR )", "Deposit Amount (INR )", "Balance (INR )", "-"),
    )

    assert verdict.holds
    assert "running balance" in verdict.account
    assert "zero on every row" in verdict.account


def test_the_balance_is_never_taken_for_the_amount(icici: SourceFile) -> None:
    """The reason a proposal for this field used to be refused outright.

    A statement whose deposit column is absent still has a money column, and
    it is the running balance. Reading it as money that arrived would invent a
    month of income out of a column that is only ever a subtotal.
    """
    verdict = identity.bank_amount(
        icici,
        "Balance (INR )",
        ("Withdrawal Amount (INR )", "Deposit Amount (INR )", "Balance (INR )"),
    )

    assert not verdict.holds
    assert "running balance" in verdict.reason


def test_a_row_number_is_not_an_amount(icici: SourceFile) -> None:
    verdict = identity.bank_amount(
        icici, "S No.", ("S No.", "Deposit Amount (INR )", "Balance (INR )")
    )

    assert not verdict.holds


def test_nothing_is_proved_while_two_candidates_remain(tmp_path: Path) -> None:
    """Elimination that does not finish must not be rounded up to a proof.

    A statement carrying real movement on both sides - money in and money out
    on different rows - loses the balance to the continuity check and keeps
    two candidates. Either could be the credit column. The honest outcome
    there is the question, not the likelier of the two.

    Written by hand rather than generated, because the sample statements hold
    credits only: their debit column is all zeros and is eliminated, which is
    correct and is the other case.
    """
    balance = 1_000_00
    lines = ["Date,Particulars,Debit,Credit,Balance"]
    for index in range(40):
        paid_in = 0 if index % 3 == 0 else 500_00 + index
        paid_out = 250_00 + index if index % 3 == 0 else 0
        balance += paid_in - paid_out
        lines.append(
            f"0{1 + index % 9}/08/2026,NEFT {index},"
            f"{paid_out / 100:.2f},{paid_in / 100:.2f},{balance / 100:.2f}"
        )
    path = tmp_path / "both-sides.csv"
    path.write_text(chr(10).join(lines), encoding="utf-8")

    verdict = identity.bank_amount(read(path), "Credit", ("Debit", "Credit", "Balance"))

    assert not verdict.holds
    assert "not the only candidate" in verdict.reason
    assert "Debit" in verdict.reason


# ------------------------------------------- solving rather than checking


MONEY_COLUMNS = (
    "Gross Amount",
    "Commission",
    "Service Tax (GST)",
    "Amount Credited",
    "Amount Debited",
)


def test_the_equation_is_solved_with_nothing_proposed(settlement: SourceFile) -> None:
    """The case the whole search exists for.

    With no provider there is no suggestion to endorse, and a workbook whose
    credit column is called `Amount Paid In` used to become two questions. The
    equation does not need the suggestion: three known columns and four
    hundred rows leave exactly one way to fill the other two.
    """
    known = {
        field: column
        for field, column in UNFAMILIAR.columns.items()
        if field in ("amount", "fee", "tax")
    }

    answer, verdict = identity.solve(
        settlement, RecordKind.SETTLEMENT_ROWS, known, ("credit", "debit"), MONEY_COLUMNS
    )

    assert answer == {"credit": "Amount Credited", "debit": "Amount Debited"}
    assert verdict.holds
    assert verdict.checked >= identity.MINIMUM_ROWS


def test_fee_and_tax_together_have_no_unique_solution(settlement: SourceFile) -> None:
    """Refusing here is the check working, not failing.

    Both are subtracted, so swapping them satisfies the equation exactly as
    well. Two arrangements survive, the file cannot say which is which, and
    the honest outcome is the question - a GST figure split the wrong way
    between two columns that sum to the same total is invisible downstream.
    """
    known = {
        field: column
        for field, column in UNFAMILIAR.columns.items()
        if field in ("amount", "credit", "debit")
    }

    answer, verdict = identity.solve(
        settlement, RecordKind.SETTLEMENT_ROWS, known, ("fee", "tax"), MONEY_COLUMNS
    )

    assert answer is None
    assert not verdict.holds
    assert "more than one arrangement" in verdict.reason


def test_no_arrangement_at_all_is_not_rounded_up_to_one(settlement: SourceFile) -> None:
    """A search that finds nothing must not return its closest attempt."""
    known = {
        "amount": UNFAMILIAR.columns["fee"],
        "fee": UNFAMILIAR.columns["amount"],
        "tax": UNFAMILIAR.columns["tax"],
    }

    answer, _ = identity.solve(
        settlement, RecordKind.SETTLEMENT_ROWS, known, ("credit", "debit"), MONEY_COLUMNS
    )

    assert answer is None


def test_too_many_unknowns_is_a_search_and_not_a_proof(settlement: SourceFile) -> None:
    """Five unknowns would be asking arithmetic to invent the whole mapping."""
    answer, verdict = identity.solve(
        settlement, RecordKind.SETTLEMENT_ROWS, {}, identity.MONEY_FIELDS, MONEY_COLUMNS
    )

    assert answer is None
    assert "too many" in verdict.reason


def test_only_a_settlement_report_has_an_equation_to_solve(settlement: SourceFile) -> None:
    answer, verdict = identity.solve(settlement, RecordKind.ORDERS, {}, ("credit",), MONEY_COLUMNS)

    assert answer is None
    assert "no arithmetic identity" in verdict.reason


# ------------------------------------------------- naming the deposit column


def test_the_deposit_column_is_named_with_nothing_proposed(icici: SourceFile) -> None:
    column, verdict = identity.only_deposit(
        icici,
        ("S No.", "Withdrawal Amount (INR )", "Deposit Amount (INR )", "Balance (INR )"),
    )

    assert column == "Deposit Amount (INR )"
    assert verdict.holds
    assert "running balance" in verdict.account


# ------------------------------------------------------------ dates in order


def test_the_capture_date_is_the_one_that_never_runs_ahead(settlement: SourceFile) -> None:
    """A gateway cannot settle money it has not taken yet.

    Which makes `created_at` the column that precedes the payout date on every
    row - not the likelier of two guesses, but the only one the file's own
    rows permit.
    """
    column, verdict = identity.earliest_date(
        settlement,
        UNFAMILIAR.columns["settled_at"],
        ("Txn Date & Time", "Payout Date", "Txn Ref No"),
    )

    assert column == "Txn Date & Time"
    assert verdict.holds
    assert "never runs ahead" in verdict.account


def test_two_columns_that_both_precede_settle_nothing(tmp_path: Path) -> None:
    """A capture date and an authorisation date are both always earlier.

    Which of them the merchant means is a fact about their gateway, and
    ordering has nothing to say about it. Naming the first one found would be
    picking, not proving.
    """
    lines = ["Authorised,Captured,Paid Out,Amount"]
    for index in range(40):
        day = 1 + index % 20
        lines.append(f"2026-07-{day:02d},2026-07-{day:02d},2026-07-{day + 2:02d},{100 + index}.00")
    path = tmp_path / "two-earlier.csv"
    path.write_text(chr(10).join(lines), encoding="utf-8")

    column, verdict = identity.earliest_date(
        read(path), "Paid Out", ("Authorised", "Captured", "Paid Out")
    )

    assert column is None
    assert "more than one column always precedes" in verdict.reason
    assert "Authorised" in verdict.reason and "Captured" in verdict.reason


# ---------------------------------------------------- the same IDs elsewhere


def _ids(count: int) -> list[str]:
    return [f"pay_{index:012d}" for index in range(count)]


def _with_columns(path: Path, headers: list[str], columns: list[list[str]]) -> SourceFile:
    lines = [",".join(headers)]
    for row in zip(*columns, strict=True):
        lines.append(",".join(row))
    path.write_text(chr(10).join(lines), encoding="utf-8")
    return read(path)


def test_an_opaque_column_is_named_by_the_file_beside_it(tmp_path: Path) -> None:
    """The check that reads outside the file, and why it has to.

    Nothing about `pay_000000000007` says which field it belongs to. What says
    so is a payments export that names its own column in words the schema
    already knows.
    """
    known = _ids(40)
    source = _with_columns(
        tmp_path / "payouts.csv",
        ["Merchant Ref", "Payout Batch", "Gross"],
        [known, [f"setl_{index // 4:04d}" for index in range(40)], ["100.00"] * 40],
    )

    column, verdict = identity.joined(source, frozenset(known), frozenset())

    assert column == "Merchant Ref"
    assert verdict.holds
    assert "40 of 40 matched" in verdict.account


def test_a_column_already_spoken_for_is_not_taken_twice(tmp_path: Path) -> None:
    """Proving one identifier must not steal the column that proved another."""
    known = _ids(40)
    source = _with_columns(
        tmp_path / "payouts.csv",
        ["Merchant Ref", "Gross"],
        [known, ["100.00"] * 40],
    )

    column, verdict = identity.joined(source, frozenset(known), frozenset({"Merchant Ref"}))

    assert column is None
    assert "no column here holds those identifiers" in verdict.reason


def test_two_columns_holding_the_same_identifiers_settle_nothing(tmp_path: Path) -> None:
    """A settlement report carries the payment id twice, under two names.

    `entity_id` *is* the payment id on payment rows. Where a file's refund
    rows do not dilute it enough to tell the two apart, the honest outcome is
    that neither is claimed.
    """
    known = _ids(40)
    source = _with_columns(
        tmp_path / "payouts.csv",
        ["Txn Ref No", "Merchant Ref", "Gross"],
        [known, known, ["100.00"] * 40],
    )

    column, verdict = identity.joined(source, frozenset(known), frozenset())

    assert column is None
    assert "more than one column holds those identifiers" in verdict.reason


def test_a_handful_of_known_identifiers_proves_nothing(tmp_path: Path) -> None:
    """Overlap with a short list is coincidence, not evidence."""
    known = _ids(40)
    source = _with_columns(
        tmp_path / "payouts.csv", ["Merchant Ref", "Gross"], [known, ["100.00"] * 40]
    )

    column, verdict = identity.joined(source, frozenset(known[:5]), frozenset())

    assert column is None
    assert "known identifiers to compare against" in verdict.reason


def test_a_mostly_matching_column_is_not_mostly_the_field(tmp_path: Path) -> None:
    """The column this has to be told apart from matches about four fifths.

    An `entity_id` column on a settlement report holds the payment id on
    payment rows and a refund or adjustment id on the others. Four fifths is
    not a payment id column, and the threshold sits well above it.
    """
    known = _ids(40)
    mixed = [*known[:30], *[f"rfnd_{index:04d}" for index in range(10)]]
    source = _with_columns(
        tmp_path / "payouts.csv", ["Txn Ref No", "Gross"], [mixed, ["100.00"] * 40]
    )

    column, _ = identity.joined(source, frozenset(known), frozenset())

    assert column is None
