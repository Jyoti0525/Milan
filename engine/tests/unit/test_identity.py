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

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.dataset import Dataset
from milan.domain.rates import RateCard
from milan.ingest import identity
from milan.ingest.parsing import parse_card_type, parse_entity_type, parse_method
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


# ------------------------------------------------------- a closed vocabulary


def test_a_column_of_card_variants_is_the_card_type(settlement: SourceFile) -> None:
    """Identified by what is written in it, not by its name or its arithmetic.

    `Card Variant` means nothing to an alias list and there is no equation
    over it. What settles it is that every value in it is one of exactly three
    words, and those three words are what a card type is.
    """
    column, verdict = identity.vocabulary(
        settlement, parse_card_type, "a kind of card", frozenset()
    )

    assert column == UNFAMILIAR.columns["card_type"]
    assert verdict.holds
    assert "every value in it is a kind of card" in verdict.account


def test_the_vocabularies_do_not_reach_into_each_other(settlement: SourceFile) -> None:
    """The property that makes this safe rather than merely useful.

    A column of `domestic_consumer` and `international` cannot be a payment
    method, and a column of `upi` and `netbanking` cannot be a card type,
    because the lists share no member. So each check finds its own column and
    only its own, with no ordering between them to get right.
    """
    found = {}
    for reader, named in (
        (parse_entity_type, "a row type"),
        (parse_method, "a way of paying"),
        (parse_card_type, "a kind of card"),
    ):
        column, _ = identity.vocabulary(settlement, reader, named, frozenset())
        found[named] = column

    assert found["a row type"] == UNFAMILIAR.columns["type"]
    assert found["a way of paying"] == UNFAMILIAR.columns["method"]
    assert found["a kind of card"] == UNFAMILIAR.columns["card_type"]
    assert len(set(found.values())) == 3


def test_one_value_outside_the_list_is_enough_to_refuse(tmp_path: Path) -> None:
    """Nearly a vocabulary is a column we have misunderstood.

    Every value, not most. A column of methods with a `chargeback` in it is
    not a method column with a defect - it is something else that happens to
    overlap, and mapping it would carry that misunderstanding into every row.
    """
    lines = ["Instrument,Amount"]
    for index in range(40):
        word = "chargeback" if index == 17 else "upi"
        lines.append(f"{word},{100 + index}.00")
    path = tmp_path / "nearly.csv"
    path.write_text(chr(10).join(lines), encoding="utf-8")

    column, verdict = identity.vocabulary(read(path), parse_method, "a way of paying", frozenset())

    assert column is None
    assert "no column here reads as a way of paying" in verdict.reason


# --------------------------------------------------------- one row, one key


def test_the_row_identifier_is_the_only_column_unique_on_every_row(
    settlement: SourceFile,
) -> None:
    """Found by counting, because reading it says nothing.

    `pay_S3kQ1nZ8vM2xLd` does not announce which field it belongs to. Being
    filled and different on every one of two hundred rows does.
    """
    # The timestamp is unique too and is settled before this runs, which is
    # what leaves exactly one column standing.
    taken = frozenset({UNFAMILIAR.columns["created_at"], UNFAMILIAR.columns["settled_at"]})
    column, verdict = identity.unique_key(settlement, taken)

    assert column == UNFAMILIAR.columns["entity_id"]
    assert verdict.holds
    assert "different on all" in verdict.account


def test_two_unique_columns_settle_nothing(settlement: SourceFile) -> None:
    """With the timestamp still in play there are two answers and no reason.

    This is the ordering the resolver depends on stated as a test: the dates
    are settled first, and if they ever stop being, this refuses rather than
    picking one.
    """
    column, verdict = identity.unique_key(settlement, frozenset())

    assert column is None
    assert "more than one column is unique" in verdict.reason


def test_a_column_with_one_gap_in_it_is_not_a_key(tmp_path: Path) -> None:
    """A primary key is filled on every row. One blank and it is not one."""
    lines = ["Ref,Amount"]
    for index in range(40):
        lines.append(f"{'' if index == 9 else f'id_{index:04d}'},{100 + index}.00")
    path = tmp_path / "gap.csv"
    path.write_text(chr(10).join(lines), encoding="utf-8")

    column, _ = identity.unique_key(read(path), frozenset({"Amount"}))

    assert column is None


# ------------------------------------------------- the reference the bank kept


def test_the_payout_reference_is_the_one_the_bank_quoted(
    settlement: SourceFile, data: Dataset, tmp_path: Path
) -> None:
    """What separates a UTR from the batch id sitting beside it.

    Both are filled on the same rows and both have one value per batch, so
    cardinality cannot tell them apart and neither can their contents. Who
    wrote them can: a batch id is the gateway's own filing reference and
    appears nowhere else, and a UTR comes back in the bank's narration.
    """
    path = tmp_path / "hdfc.csv"
    dialects.hdfc_statement(data, path)
    statement = read(path)
    narration = frozenset(value for value in statement.column("Narration") if value.strip())

    column, verdict = identity.mentioned(settlement, narration, frozenset())

    assert column == UNFAMILIAR.columns["settlement_utr"]
    assert verdict.holds
    assert "the bank quoted it" in verdict.account


def test_the_batch_id_is_never_mistaken_for_the_reference(
    settlement: SourceFile, data: Dataset, tmp_path: Path
) -> None:
    """The column this exists to rule out, checked from the other side."""
    path = tmp_path / "hdfc.csv"
    dialects.hdfc_statement(data, path)
    narration = frozenset(value for value in read(path).column("Narration") if value.strip())

    column, _ = identity.mentioned(settlement, narration, frozenset())

    assert column != UNFAMILIAR.columns["settlement_id"]


def test_no_statement_in_the_folder_means_no_reference_is_claimed(
    settlement: SourceFile,
) -> None:
    """Which is correct, and is why the two questions stand without one."""
    column, verdict = identity.mentioned(settlement, frozenset(), frozenset())

    assert column is None
    assert "narration" in verdict.reason


# ------------------------------------------------ one of these per one of those


def test_the_batch_id_is_what_pairs_with_the_reference(settlement: SourceFile) -> None:
    """Every batch has one reference and every reference belongs to one batch.

    Not merely the same number of distinct values - a date column can manage
    that by coincidence - but the same partition of the rows, which a
    coincidence cannot manage across two hundred of them.
    """
    column, verdict = identity.paired(settlement, UNFAMILIAR.columns["settlement_utr"], frozenset())

    assert column == UNFAMILIAR.columns["settlement_id"]
    assert verdict.holds
    assert "exactly one value per" in verdict.account


def test_two_columns_that_are_both_keys_do_not_pair(settlement: SourceFile) -> None:
    """A correspondence with nothing to correspond is not evidence.

    Written after this test was wrong the other way round. Pairing the row
    identifier against the timestamp *succeeds* on the letter of the rule -
    both are filled and unique on every row, so the map is a bijection - and
    it says only that both are keys, which was already known. Every group
    holds one row and no grouping is preserved.

    So the rule now requires grouping to exist before it can be respected,
    and this is the case that made it necessary rather than an afterthought.
    """
    column, verdict = identity.paired(settlement, UNFAMILIAR.columns["entity_id"], frozenset())

    assert column is None, f"paired the row key with {column!r}"
    assert "one value per" in verdict.reason


def test_a_column_filled_where_the_other_is_blank_does_not_pair(
    settlement: SourceFile,
) -> None:
    """Two facts about a row are not one fact under two names.

    A batch reference is absent exactly when the batch is. The row identifier
    is filled on every row including the unsettled ones, so it cannot be
    what a payout reference is naming.
    """
    column, _ = identity.paired(
        settlement,
        UNFAMILIAR.columns["settlement_utr"],
        frozenset({UNFAMILIAR.columns["settlement_id"]}),
    )

    assert column is None


# ------------------------------------------------------------- the two flags


def test_settled_is_the_flag_that_follows_the_batch_id(settlement: SourceFile) -> None:
    """`Y, N, Y, Y` reads the same whichever field it means.

    Two yes/no columns side by side and nothing in either one to tell them
    apart - so the file is asked instead. A row that settled has a batch
    reference on it and a row that did not has an empty one, and `settled` is
    the flag that agrees with that on every row.
    """
    column, verdict = identity.flag_for(
        settlement, UNFAMILIAR.columns["settlement_id"], frozenset()
    )

    assert column == UNFAMILIAR.columns["settled"]
    assert verdict.holds
    assert "true on exactly the rows" in verdict.account


def test_a_flag_with_one_value_in_it_carries_no_evidence(settlement: SourceFile) -> None:
    """A month in which everything settled cannot identify its own flag.

    `on_hold` is false on every row of an ordinary month, so it agrees with
    nothing and disagrees with nothing. Claiming it here would be claiming a
    column because it failed to object.
    """
    column, _ = identity.flag_for(
        settlement,
        UNFAMILIAR.columns["settlement_id"],
        frozenset({UNFAMILIAR.columns["settled"]}),
    )

    assert column is None


def test_the_last_flag_standing_is_the_one_field_left(settlement: SourceFile) -> None:
    """Two booleans and one field is a question; one and one is an answer."""
    column, verdict = identity.only_flag(settlement, frozenset({UNFAMILIAR.columns["settled"]}))

    assert column == UNFAMILIAR.columns["on_hold"]
    assert "only yes/no column" in verdict.account


def test_two_flags_left_standing_settle_nothing(settlement: SourceFile) -> None:
    column, verdict = identity.only_flag(settlement, frozenset())

    assert column is None
    assert "yes/no columns left are" in verdict.reason


# ------------------------------------ reading the file rather than the top of it


def test_a_flag_is_read_past_the_arithmetic_window(tmp_path: Path, data: Dataset) -> None:
    """The bug this rule exists because of.

    A settlement report is written in date order, so the rows that have not
    settled yet are the last rows in the file. Reading the first four hundred
    of four hundred and nine found a `Paid` column true on every row it looked
    at, concluded it carried no information, and refused - while the seven
    rows that identify it sat just past the window.

    Built to that shape deliberately: the only rows that differ are past
    `SAMPLE`, so a check that samples the head cannot pass this.
    """
    lines = ["Batch,Paid,Amount"]
    total = identity.SAMPLE + 20
    for index in range(total):
        late = index >= identity.SAMPLE + 10
        lines.append(f"{'' if late else f'setl_{index // 8:04d}'},{'N' if late else 'Y'},100.00")
    path = tmp_path / "long.csv"
    path.write_text(chr(10).join(lines), encoding="utf-8")

    column, verdict = identity.flag_for(read(path), "Batch", frozenset({"Amount"}))

    assert column == "Paid", verdict.reason
    assert verdict.checked == total


# ------------------------------------------- the operator, and Section 194-O


@pytest.fixture(scope="module")
def withheld(tmp_path_factory: pytest.TempPathFactory) -> SourceFile:
    """A month belonging to an e-commerce operator, in unfamiliar headers."""
    data = ChaosEngine(
        GenerationConfig(
            seed=42,
            difficulty=Difficulty.REALISTIC,
            order_count=200,
            rates=RateCard(tds_applies=True),
        )
    ).generate()
    path = tmp_path_factory.mktemp("withheld") / "payouts.csv"
    dialects.unfamiliar_settlement(data, path)
    return read(path)


def test_the_equation_still_solves_when_one_percent_is_withheld(
    withheld: SourceFile,
) -> None:
    """The gap this closed, found by turning the fee stack all the way on.

    A 194-O merchant's payment rows credit `amount - fee - tax` less one
    percent of gross, so the plain identity fails on every one of them - and
    the solver, correctly refusing to conclude from an equation that does not
    hold, went back to asking. Safe, and worse than it needed to be: the
    withheld shape is as fixed and as checkable as the plain one.
    """
    known = {
        field: column
        for field, column in UNFAMILIAR.columns.items()
        if field in ("amount", "fee", "tax")
    }

    answer, verdict = identity.solve(
        withheld, RecordKind.SETTLEMENT_ROWS, known, ("credit", "debit"), MONEY_COLUMNS
    )

    assert answer == {"credit": "Amount Credited", "debit": "Amount Debited"}
    assert verdict.holds
    assert verdict.withheld
    assert "Section 194-O" in verdict.account


def test_the_withholding_is_reported_rather_than_absorbed(withheld: SourceFile) -> None:
    """Which merchant this is, worked out from their own numbers.

    Nobody told the import that this merchant is an e-commerce operator. The
    rows only foot once a statutory one percent comes off each payment, and
    that is a finding worth putting on screen - so the verdict carries it
    instead of quietly picking the shape that fitted.
    """
    verdict = identity.check(withheld, RecordKind.SETTLEMENT_ROWS, dict(UNFAMILIAR.columns))

    assert verdict.holds
    assert verdict.withheld


def test_an_ordinary_month_is_not_reported_as_withheld(settlement: SourceFile) -> None:
    """The plain shape is tried first and wins outright where it holds.

    A merchant selling their own goods has nothing withheld, and reporting
    otherwise would tell them they are an operator with a filing obligation
    they do not have.
    """
    verdict = identity.check(settlement, RecordKind.SETTLEMENT_ROWS, dict(UNFAMILIAR.columns))

    assert verdict.holds
    assert not verdict.withheld
    assert "194-O" not in verdict.account


def test_a_file_that_withholds_on_only_some_rows_is_not_a_withheld_file(
    tmp_path: Path,
) -> None:
    """Two shapes are not twice as many chances to pass.

    Withholding is a fact about the merchant, so it applies to every payment
    row or to none. A file where half the rows foot one way and half the other
    is not an operator's month - it is a mapping we have got wrong, and
    allowing the shapes to be chosen per row would let it through.
    """
    lines = ["Type,Gross,Fee,Tax,In,Out"]
    for index in range(40):
        gross = 100_00 + index * 37
        fee = gross * 2 // 100
        tax = fee * 18 // 100
        net = gross - fee - tax - (gross // 100 if index % 2 else 0)
        lines.append(
            f"payment,{gross / 100:.2f},{fee / 100:.2f},{tax / 100:.2f},{net / 100:.2f},0.00"
        )
    path = tmp_path / "half.csv"
    path.write_text(chr(10).join(lines), encoding="utf-8")

    verdict = identity.check(
        read(path),
        RecordKind.SETTLEMENT_ROWS,
        {"amount": "Gross", "fee": "Fee", "tax": "Tax", "credit": "In", "debit": "Out"},
    )

    assert not verdict.holds
    assert "does not hold" in verdict.reason


def test_a_same_day_payout_does_not_read_as_settling_before_capture(
    tmp_path: Path,
) -> None:
    """Days, not instants - the other thing the full fee stack turned up.

    A settlement date has no time of day in it, so comparing a capture
    timestamp against it reads midnight. A payment captured at half past two
    and settled the same day by instant settlement then looks like a payout
    that happened before the money arrived, and the capture column gets
    disqualified for running ahead of a date it is actually inside.
    """
    lines = ["Captured,Paid Out,Amount"]
    for index in range(40):
        day = 1 + index % 20
        # Every other row settles the same day, at a time of day later than
        # the midnight a bare date parses to.
        paid = day if index % 2 else day + 2
        lines.append(f"2026-07-{day:02d} 14:32:11,2026-07-{paid:02d},{100 + index}.00")
    path = tmp_path / "instant.csv"
    path.write_text(chr(10).join(lines), encoding="utf-8")

    column, verdict = identity.earliest_date(read(path), "Paid Out", ("Captured", "Paid Out"))

    assert column == "Captured", verdict.reason
    assert verdict.holds
