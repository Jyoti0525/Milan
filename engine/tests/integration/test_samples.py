"""The sample folders, held to what their own READMEs promise.

A sample folder is a claim - "drop this in and exactly one question is asked",
"this file is left alone with the reason printed" - and a claim that nothing
checks is a claim that quietly becomes false. These files are the first thing
somebody new to Milan will point it at, and a README that describes last
month's behaviour is worse than no README, because they will believe it and
conclude the engine is broken.

So every sentence in those READMEs that says what should happen is asserted
here, against the folders the command actually writes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from milan.ingest import build
from milan.ingest.resolver import Importer
from milan.ingest.schema import RecordKind
from milan.samples import write_all
from milan.samples.build import month


@pytest.fixture(scope="module")
def samples(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("samples")
    write_all(root, seed=42, orders=200)
    return root


def plan_for(root: Path, folder: str) -> object:
    return Importer(None).plan(root / folder)


class TestTheFolderWhoseNamesWeKnow:
    """`1-names-we-know`: no model, one question, and the question is real."""

    def test_no_model_is_consulted(self, samples: Path) -> None:
        plan = Importer(None).plan(samples / "1-names-we-know")
        assert plan.consulted == "none"

    def test_all_three_files_are_placed(self, samples: Path) -> None:
        plan = Importer(None).plan(samples / "1-names-we-know")
        assert {mapping.kind for mapping in plan.placed} == {
            RecordKind.SETTLEMENT_ROWS,
            RecordKind.BANK_CREDITS,
            RecordKind.PAYMENTS,
        }

    def test_exactly_one_question_and_it_is_the_date_column(self, samples: Path) -> None:
        """An HDFC statement carries both `Date` and `Value Dt`. On the rows
        where they differ, picking the wrong one moves a settlement into the
        wrong day - and no amount of evidence in the file settles it."""
        plan = Importer(None).plan(samples / "1-names-we-know")
        assert [question.subject for question in plan.questions] == ["value_date"]

    def test_answering_it_produces_a_run(self, samples: Path) -> None:
        from milan.ingest.resolver import Decisions

        root = samples / "1-names-we-know"
        importer = Importer(None)
        question = importer.plan(root).questions[0]
        answered = importer.plan(
            root,
            {question.file: Decisions().with_answer("value_date", "Value Dt", is_format=False)},
        )
        assert answered.ready, answered.blockers()
        assert build.build(answered).data.bank_credits

    def test_the_banner_and_the_closing_line_are_not_transactions(self, samples: Path) -> None:
        """Four lines of account details above the header and
        `*** End of Statement ***` below the last row."""
        plan = Importer(None).plan(samples / "1-names-we-know")
        statement = plan.of(RecordKind.BANK_CREDITS)
        assert statement is not None
        assert len(statement.source.preamble) == 4
        assert len(statement.source.rows) == len(month(seed=42, orders=200).bank_credits)


class TestTheFolderWhoseNamesWeDoNot:
    """`2-names-we-do-not`: nothing matches, so somebody has to say."""

    def test_nothing_is_settled_without_help(self, samples: Path) -> None:
        plan = Importer(None).plan(samples / "2-names-we-do-not")
        assert not plan.ready
        assert plan.questions

    def test_the_statement_two_date_columns_are_both_offered(self, samples: Path) -> None:
        """The ambiguity that survives a model, because a model cannot know
        which day the merchant's bank posted on either."""
        plan = Importer(None).plan(samples / "2-names-we-do-not")
        asked = [q for q in plan.questions if q.subject == "value_date"]
        assert len(asked) == 1
        offered = {choice.value for choice in asked[0].choices}
        assert {"Value Date", "Transaction Date"} <= offered

    def test_answering_every_question_reconciles_the_same_month(self, samples: Path) -> None:
        """The claim that makes this folder worth shipping: an unfamiliar
        dialect answered by hand produces the same run as a familiar one read
        without help."""
        from milan.ingest.resolver import Decisions

        mapping = {
            "MERCHANT_SETTLEMENT_JUL26.csv": {
                "entity_id": "Txn Ref No",
                "type": "Txn Type",
                "amount": "Gross Amount",
                "credit": "Amount Credited",
                "debit": "Amount Debited",
                "fee": "Commission",
                "tax": "Service Tax (GST)",
                "created_at": "Txn Date & Time",
                "settlement_id": "Payout Batch",
                "settled_at": "Payout Date",
                "settlement_utr": "Bank Ref No",
            },
            "OpTransactionHistoryUX5.csv": {
                "amount": "Deposit Amount (INR )",
                "value_date": "Value Date",
                "narration": "Transaction Remarks",
            },
        }
        decisions: dict[str, Decisions] = {}
        for file, columns in mapping.items():
            current = Decisions()
            for field, column in columns.items():
                current = current.with_answer(field, column, is_format=False)
            decisions[file] = current

        plan = Importer(None).plan(samples / "2-names-we-do-not", decisions)
        assert plan.ready, plan.blockers()
        data = month(seed=42, orders=200)
        result = build.build(plan)
        assert result.counts["settlement_rows"] == len(data.settlement_rows)
        assert sum(credit.amount for credit in result.data.bank_credits) == sum(
            credit.amount for credit in data.bank_credits
        )


class TestTheWorkbookFolder:
    """`3-one-excel-workbook`: one file, four sheets, three tables."""

    def test_the_cover_sheet_is_skipped_and_the_other_three_are_read(self, samples: Path) -> None:
        plan = Importer(None).plan(samples / "3-one-excel-workbook")
        assert {mapping.kind for mapping in plan.placed} == {
            RecordKind.SETTLEMENT_ROWS,
            RecordKind.BANK_CREDITS,
            RecordKind.PAYMENTS,
        }

    def test_not_a_paisa_is_lost_to_excels_floats(self, samples: Path) -> None:
        plan = Importer(None).plan(samples / "3-one-excel-workbook")
        assert plan.ready, plan.blockers()
        result = build.build(plan)
        data = month(seed=42, orders=200)
        assert sum(credit.amount for credit in result.data.bank_credits) == sum(
            credit.amount for credit in data.bank_credits
        )
        assert sum(row.credit for row in result.data.settlement_rows) == sum(
            row.credit for row in data.settlement_rows
        )


class TestTheFolderAsItActuallyArrives:
    """`4-a-real-folder`: six files, six different right answers."""

    def test_it_reconciles(self, samples: Path) -> None:
        plan = Importer(None).plan(samples / "4-a-real-folder")
        assert plan.ready, plan.blockers()
        assert build.build(plan).data.bank_credits

    def test_the_gst_register_is_left_alone_with_a_reason(self, samples: Path) -> None:
        """It has an id, an amount and a reference, which is enough to look
        convincingly like a settlement report. It has no settlement date,
        which is checkable without asking anybody."""
        plan = Importer(None).plan(samples / "4-a-real-folder")
        register = next(m for m in plan.unplaced if m.name.startswith("GSTR1"))
        assert "reads as temporal" in register.kind_reason

    def test_the_hand_kept_refund_log_is_left_alone_too(self, samples: Path) -> None:
        """Two thirds of what an order book needs, and no order id anywhere.
        A file placed on half its names, which then cannot answer something
        required, was guessed at rather than placed."""
        plan = Importer(None).plan(samples / "4-a-real-folder")
        refunds = next(m for m in plan.unplaced if m.name.startswith("refunds"))
        assert "order_id" in refunds.kind_reason
        assert "left alone" in refunds.kind_reason

    def test_neither_left_alone_file_blocks_the_import(self, samples: Path) -> None:
        """The whole point. A folder legitimately contains files that are none
        of our business, and an import that demanded an answer about each of
        them would turn 'we left your other file alone' into an error."""
        plan = Importer(None).plan(samples / "4-a-real-folder")
        assert not [question for question in plan.questions if question.blocking]

    def test_the_pdf_is_refused_with_advice_rather_than_skipped(self, samples: Path) -> None:
        """Silently skipping it is the worst outcome available: the merchant
        dropped a folder containing their statement, the run covers a month
        with no bank side, and nothing says why."""
        plan = Importer(None).plan(samples / "4-a-real-folder")
        pdf = next(item for item in plan.unreadable if item.path.suffix == ".pdf")
        assert "no columns to read" in pdf.reason
        assert "CSV or Excel" in pdf.reason

    def test_the_excel_lock_file_is_never_mentioned(self, samples: Path) -> None:
        """Importing a folder while the merchant still has the statement open
        is not an unusual thing to do."""
        plan = Importer(None).plan(samples / "4-a-real-folder")
        named = {item.path.name for item in plan.unreadable} | {m.name for m in plan.files}
        assert not [name for name in named if name.startswith("~$")]

    def test_the_kotak_single_column_statement_is_read(self, samples: Path) -> None:
        """One signed column with a `Cr` marker instead of separate withdrawal
        and deposit columns."""
        plan = Importer(None).plan(samples / "4-a-real-folder")
        statement = plan.of(RecordKind.BANK_CREDITS)
        assert statement is not None
        assert statement.name == "statement.csv"
        assert len(statement.source.rows) == len(month(seed=42, orders=200).bank_credits)


class TestEveryFolderExplainsItself:
    def test_each_one_ships_a_readme(self, samples: Path) -> None:
        """A sample that does not say what it demonstrates proves whatever the
        reader happened to do."""
        for folder in samples.iterdir():
            if folder.is_dir():
                assert (folder / "README.md").exists(), folder.name
        assert (samples / "README.md").exists()

    def test_the_index_says_the_money_is_generated(self, samples: Path) -> None:
        """Somebody handed a folder of Indian bank statements deserves to be
        told that in the first paragraph rather than to wonder."""
        index = (samples / "README.md").read_text(encoding="utf-8")
        assert "None of this is anybody's real money" in index


class TestARealHandover:
    """`5-a-real-handover`: everything at once, including two bank accounts."""

    ROOT = "5-a-real-handover"
    WB = "Settlement Report Aug 2026.xlsx"

    def answered(self, samples: Path) -> object:
        from milan.ingest.reading import SHEET
        from milan.ingest.resolver import Decisions

        answers = {
            f"{self.WB}{SHEET}Payouts": {
                "credit": "Amount Paid In",
                "debit": "Amount Taken Out",
                "created_at": "Booked On",
            },
            f"{self.WB}{SHEET}Transactions": {
                "payment_id": "Payment Ref",
                "order_id": "Order Ref",
            },
            "Acct Statement_XX1234.csv": {"value_date": "Value Dt"},
        }
        decisions: dict[str, Decisions] = {}
        for file, columns in answers.items():
            current = Decisions()
            for field, column in columns.items():
                current = current.with_answer(field, column, is_format=False)
            decisions[file] = current
        return Importer(None).plan(samples / self.ROOT, decisions)

    def test_both_bank_statements_are_read(self, samples: Path) -> None:
        """Two current accounts at two banks, in two different formats."""
        plan = Importer(None).plan(samples / self.ROOT)
        statements = plan.all_of(RecordKind.BANK_CREDITS)
        assert len(statements) == 2
        assert {mapping.name for mapping in statements} == {
            "Acct Statement_XX1234.csv",
            "axis_918020012345678_aug.csv",
        }

    def test_not_one_credit_is_lost_between_the_two_accounts(self, samples: Path) -> None:
        """The failure this folder exists to catch. An engine that assumed one
        file per record kind reconciles half the money perfectly and reports
        nothing wrong - every downstream check passes over the half it read."""
        plan = self.answered(samples)
        assert plan.ready, plan.blockers()  # type: ignore[attr-defined]
        result = build.build(plan)  # type: ignore[arg-type]
        data = month(seed=42, orders=200)
        assert len(result.data.bank_credits) == len(data.bank_credits)
        assert sum(c.amount for c in result.data.bank_credits) == sum(
            c.amount for c in data.bank_credits
        )

    def test_the_workbooks_two_sheets_are_both_placed(self, samples: Path) -> None:
        plan = Importer(None).plan(samples / self.ROOT)
        placed = {mapping.kind for mapping in plan.placed}
        assert RecordKind.SETTLEMENT_ROWS in placed
        assert RecordKind.PAYMENTS in placed

    def test_the_unfamiliar_headers_are_asked_about_not_guessed(self, samples: Path) -> None:
        """`Amount Paid In` and `Amount Taken Out` are a credit and a debit to
        a person and nothing to an alias list. Getting them the wrong way round
        balances every row to zero and inverts the month."""
        plan = Importer(None).plan(samples / self.ROOT)
        asked = {q.subject for q in plan.questions if q.blocking}
        assert {"credit", "debit"} <= asked

    def test_three_files_are_left_alone_and_none_of_it_is_an_error(self, samples: Path) -> None:
        plan = self.answered(samples)
        unplaced = {mapping.name for mapping in plan.unplaced}  # type: ignore[attr-defined]
        assert "GSTR1_Aug_2026.csv" in unplaced
        assert "purchase orders.csv" in unplaced
        pdf = next(
            item
            for item in plan.unreadable  # type: ignore[attr-defined]
            if item.path.suffix == ".pdf"
        )
        assert "no columns to read" in pdf.reason

    def test_it_reconciles_over_both_accounts(self, samples: Path) -> None:
        from milan.recon.pipeline import ReconciliationPipeline, RunMetadata

        plan = self.answered(samples)
        report = ReconciliationPipeline().run(
            build.build(plan).data,  # type: ignore[arg-type]
            RunMetadata(seed=42, difficulty="realistic"),
        )
        assert report.proofs
        assert all(proof.residual == 0 for proof in report.proofs if proof.balances)
