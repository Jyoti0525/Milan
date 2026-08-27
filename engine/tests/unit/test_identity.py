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
