"""What the import refuses to decide, and what it is allowed to decide alone.

One rule is under test throughout: **ambiguity never resolves itself.** A
field two columns could be, or one that only a model's guess supports, either
stops the import or is dropped. It is never quietly assigned - because a wrong
column here does not produce a wrong explanation, it produces a wrong balance,
and a wrong balance looks exactly like a right one.

The model is present in these tests and never trusted. `StaticProvider`
answers the same thing to every question, which is the point: it lets a
proposal be put in front of the verifier without also testing whether a model
happened to be sensible today. What is asserted is the verifier - that a
column whose values contradict the claim is thrown out and recorded, that a
column named for two fields at once is not a mapping, and that a record type
which cannot be filled from a file is not a candidate for it however
confidently anything says otherwise.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from milan.ingest import build
from milan.ingest.plan import ABSENT, DERIVE, Certainty, IngestPlan, QuestionKind
from milan.ingest.propose import coherent
from milan.ingest.resolver import Decisions, Importer, decisions_from
from milan.ingest.schema import RecordKind
from milan.llm.provider import StaticProvider

SETTLEMENT = (
    "entity_id,type,amount,credit,debit,fee,tax,created_at,settlement_id,"
    "settled_at,settlement_utr\n"
    "pay_a1,payment,10000.00,11500.00,0.00,200.00,36.00,2026-07-06 10:00:00,"
    "setl_1,2026-07-08 11:00:00,UTR0000000001\n"
    "pay_a2,payment,2000.00,1764.00,0.00,200.00,36.00,2026-07-06 12:00:00,"
    "setl_1,2026-07-08 11:00:00,UTR0000000001\n"
    "rfnd_a3,refund,500.00,0.00,500.00,0.00,0.00,2026-07-07 09:00:00,"
    "setl_1,2026-07-08 11:00:00,UTR0000000001\n"
)

BANK = (
    "Value Date,Narration,Credit,Ref No\n"
    "08-Jul-2026,NEFT-UTR0000000001-RAZORPAY,12764.00,UTR0000000001\n"
)


def folder(root: Path, **files: str) -> Path:
    for name, text in files.items():
        (root / name.replace("__", ".")).write_text(text, encoding="utf-8")
    return root


class TestAFileWhoseNamesWeKnowNeedsNoModelAndNoQuestions:
    def test_a_normally_named_export_imports_straight_through(self, tmp_path: Path) -> None:
        """The case that has to stay boring. Most exports use names somebody
        has met before, and an import that interrogated the merchant about
        every one of them would be refusing rather than being careful."""
        plan = Importer(None).plan(folder(tmp_path, settlement__csv=SETTLEMENT, bank__csv=BANK))
        assert plan.consulted == "none"
        assert plan.questions == ()
        assert plan.ready
        assert {mapping.kind for mapping in plan.placed} == {
            RecordKind.SETTLEMENT_ROWS,
            RecordKind.BANK_CREDITS,
        }

    def test_every_column_it_settled_says_the_names_settled_it(self, tmp_path: Path) -> None:
        plan = Importer(None).plan(folder(tmp_path, settlement__csv=SETTLEMENT, bank__csv=BANK))
        mapping = plan.of(RecordKind.BANK_CREDITS)
        assert mapping is not None
        settled = [r for r in mapping.resolutions if r.column is not None]
        assert settled
        assert all(r.certainty is Certainty.CONFIRMED for r in settled)
        assert all(r.proposed_by == "" for r in settled)


class TestTwoColumnsForOneFieldIsAQuestionRatherThanAChoice:
    def test_a_statement_with_both_a_transaction_date_and_a_value_date_asks(
        self, tmp_path: Path
    ) -> None:
        """These are genuinely different days on a real statement, and which
        one reconciliation should use is a finance decision, not a parsing
        one."""
        bank = (
            "Txn Date,Value Date,Narration,Credit\n"
            "07-Jul-2026,08-Jul-2026,NEFT-UTR0000000001-RAZORPAY,12764.00\n"
        )
        plan = Importer(None).plan(folder(tmp_path, settlement__csv=SETTLEMENT, bank__csv=bank))
        asked = [q for q in plan.questions if q.subject == "value_date"]
        assert len(asked) == 1
        assert {choice.value for choice in asked[0].choices} >= {"Txn Date", "Value Date"}
        assert not plan.ready

    def test_answering_it_closes_it_and_nothing_else_opens(self, tmp_path: Path) -> None:
        bank = (
            "Txn Date,Value Date,Narration,Credit\n"
            "07-Jul-2026,08-Jul-2026,NEFT-UTR0000000001-RAZORPAY,12764.00\n"
        )
        root = folder(tmp_path, settlement__csv=SETTLEMENT, bank__csv=bank)
        importer = Importer(None)
        importer.plan(root)
        plan = importer.plan(root, {"bank.csv": Decisions(columns={"value_date": "Value Date"})})
        assert plan.questions == ()
        assert plan.ready
        mapping = plan.of(RecordKind.BANK_CREDITS)
        assert mapping is not None
        assert mapping.columns["value_date"] == "Value Date"

    def test_an_optional_field_two_columns_could_be_is_dropped_not_asked_about(
        self, tmp_path: Path
    ) -> None:
        """Losing an optional column costs a stated capability. Guessing at
        one costs a balance. Neither is worth another question."""
        bank = (
            "Value Date,Narration,Credit,Ref No,RRN\n"
            "08-Jul-2026,NEFT-UTR0000000001-RAZORPAY,12764.00,UTR0000000001,UTR0000000001\n"
        )
        plan = Importer(None).plan(folder(tmp_path, settlement__csv=SETTLEMENT, bank__csv=bank))
        mapping = plan.of(RecordKind.BANK_CREDITS)
        assert mapping is not None
        utr = next(r for r in mapping.resolutions if r.target.name == "utr")
        assert utr.certainty is Certainty.ABSENT
        assert plan.questions == ()
        assert any("no utr column" in line for line in plan.limitations())


class TestAModelMayProposeAndTheValuesDecide:
    def test_a_proposal_the_values_contradict_is_thrown_out_and_recorded(
        self, tmp_path: Path
    ) -> None:
        """The whole design in one test. A model naming the narration column
        as the credit amount is not a suggestion to be weighed - the values in
        it are not money, and that is the end of it."""
        bank = (
            "Value Date,Narration,Inflow Value\n08-Jul-2026,NEFT-UTR0000000001-RAZORPAY,12764.00\n"
        )
        answer = json.dumps({"columns": {"amount": "Narration"}})
        plan = Importer(StaticProvider(answer)).plan(
            folder(tmp_path, settlement__csv=SETTLEMENT, bank__csv=bank)
        )
        rejected = [r for r in plan.rejections if r.target == "amount"]
        assert rejected
        assert rejected[0].column == "Narration"
        assert "does not read as money" in rejected[0].reason
        assert rejected[0].proposed_by == "static"
        assert not plan.ready

    def test_a_column_the_file_does_not_have_is_recorded_as_invented(self, tmp_path: Path) -> None:
        answer = json.dumps({"columns": {"amount": "Deposit Amt."}})
        plan = Importer(StaticProvider(answer)).plan(
            folder(
                tmp_path,
                settlement__csv=SETTLEMENT,
                bank__csv="Value Date,Narration,Inflow Value\n"
                "08-Jul-2026,NEFT-UTR0000000001-RAZORPAY,12764.00\n",
            )
        )
        refused = [r for r in plan.rejections if r.file == "bank.csv"]
        assert len(refused) == 1
        assert "no column by that name" in refused[0].reason

    def test_a_proposal_the_values_allow_still_stops_a_required_field(self, tmp_path: Path) -> None:
        """A model being right about the shape is not the same as a person
        agreeing. On a required field the suggestion becomes the question's
        first option, and nothing more."""
        bank = (
            "Value Date,Narration,Inflow Value\n08-Jul-2026,NEFT-UTR0000000001-RAZORPAY,12764.00\n"
        )
        answer = json.dumps({"columns": {"amount": "Inflow Value"}})
        plan = Importer(StaticProvider(answer)).plan(
            folder(tmp_path, settlement__csv=SETTLEMENT, bank__csv=bank)
        )
        asked = [q for q in plan.questions if q.subject == "amount"]
        assert len(asked) == 1
        assert asked[0].choices[0].value == "Inflow Value"
        assert not plan.ready

    def test_one_column_offered_for_two_fields_is_not_a_mapping(self) -> None:
        """A model that answers `igst_rate` for the credit, the debit and the
        tax has not made three mistakes. Keeping any one of the three would be
        picking, which is the thing this package exists not to do."""
        kept, clashes = coherent({"credit": "igst_rate", "debit": "igst_rate", "tax": "fee_amt"})
        assert kept == {"tax": "fee_amt"}
        assert {clash.target for clash in clashes} == {"credit", "debit"}
        assert all("cannot be" in clash.reason for clash in clashes)


class TestARecordTypeAFileCannotSupplyIsNotACandidateForIt:
    def test_a_register_with_no_date_column_is_no_kind_of_record(self, tmp_path: Path) -> None:
        """A GST invoice register has an id, an amount and a reference, which
        satisfies three of the four fields a payments file needs. What it does
        not have is a date, and nothing can invent one - so the answer is
        settled without asking anybody."""
        invoices = (
            "invoice_no,gstin,place_of_supply,taxable_value,igst_rate\n"
            "INV/2026/0001,29AABCU9603R1ZM,Karnataka,1450.00,18\n"
            "INV/2026/0002,29AABCU9603R1ZM,Karnataka,2900.00,18\n"
        )
        answer = json.dumps(
            {
                "columns": {
                    "payment_id": "invoice_no",
                    "order_id": "gstin",
                    "amount": "taxable_value",
                }
            }
        )
        plan = Importer(StaticProvider(answer)).plan(
            folder(
                tmp_path,
                settlement__csv=SETTLEMENT,
                bank__csv=BANK,
                invoices__csv=invoices,
            )
        )
        unplaced = {mapping.name for mapping in plan.unplaced}
        assert unplaced == {"invoices.csv"}
        assert any("reads as temporal" in m.kind_reason for m in plan.unplaced)

    def test_a_file_nobody_could_place_does_not_stop_the_rest_of_the_folder(
        self, tmp_path: Path
    ) -> None:
        """Merchants hand over folders, not curated inputs."""
        plan = Importer(None).plan(
            folder(
                tmp_path,
                settlement__csv=SETTLEMENT,
                bank__csv=BANK,
                notes__csv="invoice_no,gstin\nINV/1,29AABCU9603R1ZM\n",
            )
        )
        assert plan.ready
        assert [m.name for m in plan.unplaced] == ["notes.csv"]


class TestAFolderMissingHalfOfWhatReconciliationNeeds:
    def test_a_settlement_report_with_no_bank_statement_says_so_first(self, tmp_path: Path) -> None:
        """Answering nine column questions and then producing an empty run is
        worse than saying at the top that this is the wrong folder."""
        plan = Importer(None).plan(folder(tmp_path, settlement__csv=SETTLEMENT))
        assert not plan.ready
        assert any("no bank statement" in line for line in plan.blockers())

    def test_a_missing_payments_file_is_a_stated_limitation_not_a_clean_sheet(
        self, tmp_path: Path
    ) -> None:
        plan = Importer(None).plan(folder(tmp_path, settlement__csv=SETTLEMENT, bank__csv=BANK))
        assert plan.ready
        assert any("no payments file" in line for line in plan.limitations())


class TestADateColumnThatCouldBeReadTwoWaysStopsTheImport:
    def test_the_question_shows_what_each_reading_would_make_of_it(self, tmp_path: Path) -> None:
        bank = (
            "Value Date,Narration,Credit\n"
            "06-07-2026,NEFT-UTR0000000001-RAZORPAY,12764.00\n"
            "08-07-2026,NEFT-UTR0000000001-RAZORPAY,1.00\n"
        )
        plan = Importer(None).plan(folder(tmp_path, settlement__csv=SETTLEMENT, bank__csv=bank))
        asked = [q for q in plan.questions if q.kind is QuestionKind.DATE_FORMAT]
        assert len(asked) == 1
        assert asked[0].subject == "value_date.format"
        readings = {choice.label.rsplit(" as ", 1)[1] for choice in asked[0].choices}
        assert "2026-07-06" in readings
        assert "2026-06-07" in readings

    def test_answering_the_format_pins_it(self, tmp_path: Path) -> None:
        bank = (
            "Value Date,Narration,Credit\n"
            "06-07-2026,NEFT-UTR0000000001-RAZORPAY,12764.00\n"
            "08-07-2026,NEFT-UTR0000000001-RAZORPAY,1.00\n"
        )
        root = folder(tmp_path, settlement__csv=SETTLEMENT, bank__csv=bank)
        importer = Importer(None)
        importer.plan(root)
        plan = importer.plan(root, {"bank.csv": Decisions(patterns={"value_date": "%d-%m-%Y"})})
        assert plan.ready
        credits = build.build(plan).data.bank_credits
        assert credits[0].value_date.isoformat() == "2026-07-06"


class TestAnAnswerIsHonouredEvenWhenItIsNotAColumn:
    def test_a_report_with_one_signed_amount_can_be_told_to_derive_the_sides(
        self, tmp_path: Path
    ) -> None:
        """A settlement export that carries a single signed amount instead of
        a debit and a credit column is a shape the engine handles perfectly
        well. Refusing it would be refusing a fact about other people's
        software."""
        settlement = (
            "entity_id,type,amount,fee,tax,created_at,settlement_id,settled_at,settlement_utr\n"
            "pay_a1,payment,11500.00,200.00,36.00,2026-07-06 10:00:00,setl_1,"
            "2026-07-08 11:00:00,UTR0000000001\n"
            "rfnd_a3,refund,500.00,0.00,0.00,2026-07-07 09:00:00,setl_1,"
            "2026-07-08 11:00:00,UTR0000000001\n"
        )
        root = folder(tmp_path, settlement__csv=settlement, bank__csv=BANK)
        importer = Importer(None)
        importer.plan(root)
        plan = importer.plan(
            root,
            {"settlement.csv": Decisions(columns={"credit": DERIVE, "debit": DERIVE})},
        )
        assert plan.ready
        rows = {row.entity_id: row for row in build.build(plan).data.settlement_rows}
        assert rows["pay_a1"].credit and not rows["pay_a1"].debit
        assert rows["rfnd_a3"].debit and not rows["rfnd_a3"].credit

    def test_an_optional_field_can_be_answered_as_simply_absent(self, tmp_path: Path) -> None:
        root = folder(tmp_path, settlement__csv=SETTLEMENT, bank__csv=BANK)
        importer = Importer(None)
        importer.plan(root)
        plan = importer.plan(root, {"bank.csv": Decisions(columns={"utr": ABSENT})})
        mapping = plan.of(RecordKind.BANK_CREDITS)
        assert mapping is not None
        assert "utr" not in mapping.columns
        assert plan.ready

    def test_a_file_the_names_could_not_place_can_be_placed_by_hand(self, tmp_path: Path) -> None:
        """The escape hatch. The merchant knows which file is their settlement
        report, and should be able to say so without renaming anything."""
        odd = (
            "ref,kind,gross,in_amt,out_amt,charge_amt,gst_amt,made_on,batch,paid_on\n"
            "pay_a1,payment,10000.00,11500.00,0.00,200.00,36.00,2026-07-06 10:00:00,"
            "setl_1,2026-07-08 11:00:00\n"
        )
        root = folder(tmp_path, odd__csv=odd, bank__csv=BANK)
        importer = Importer(None)
        assert [m.name for m in importer.plan(root).unplaced] == ["odd.csv"]
        placed = importer.plan(root, {"odd.csv": Decisions(kind=RecordKind.SETTLEMENT_ROWS)})
        mapping = placed.of(RecordKind.SETTLEMENT_ROWS)
        assert mapping is not None
        assert mapping.name == "odd.csv"


class TestTheSecondImportOfAFolderAsksNothing:
    def test_a_saved_mapping_replays_without_a_model_or_a_question(self, tmp_path: Path) -> None:
        """What makes an import reproducible. The judgment happened once and
        was recorded, rather than being repeated and possibly answered
        differently."""
        bank = (
            "Txn Date,Value Date,Narration,Credit\n"
            "07-Jul-2026,08-Jul-2026,NEFT-UTR0000000001-RAZORPAY,12764.00\n"
        )
        root = folder(tmp_path, settlement__csv=SETTLEMENT, bank__csv=bank)
        importer = Importer(None)
        importer.plan(root)
        answered = importer.plan(
            root, {"bank.csv": Decisions(columns={"value_date": "Value Date"})}
        )
        assert answered.ready

        from milan.ingest.plan import to_saved

        replayed = Importer(None).plan(root, decisions_from(to_saved(answered)))
        assert replayed.questions == ()
        assert replayed.ready
        assert _columns(replayed) == _columns(answered)


def _columns(plan: IngestPlan) -> dict[str, dict[str, str]]:
    return {mapping.name: mapping.columns for mapping in plan.placed}


class TestBuildingRefusesAnUnansweredPlan:
    def test_a_plan_with_an_open_question_will_not_produce_records(self, tmp_path: Path) -> None:
        """A partial reconciliation looks exactly like a complete one on
        screen, and the difference is the entire value of the output."""
        plan = Importer(None).plan(folder(tmp_path, settlement__csv=SETTLEMENT))
        with pytest.raises(build.NotReadyError):
            build.build(plan)


class TestOneColumnCannotBeTwoFieldsWhoeverSaysSo:
    """The rule `coherent` enforces on a model, enforced on a person too.

    It was missing here for a while, and the gap was reachable: accept a
    suggestion that puts `paid_in` on the debit, then answer `paid_in` for the
    credit. Both stuck. Every settlement row came out with its debit equal to
    its credit, the reconciliation was nonsense, and nothing on screen said a
    word about it.
    """

    SIGNED = (
        "ref,kind,in_amt,charge_amt,gst_amt,made_on,batch,paid_on,utr_no\n"
        "pay_a1,payment,11500.00,200.00,36.00,2026-07-06 10:00:00,setl_1,"
        "2026-07-08 11:00:00,UTR0000000001\n"
        "rfnd_a3,refund,500.00,0.00,0.00,2026-07-07 09:00:00,setl_1,"
        "2026-07-08 11:00:00,UTR0000000001\n"
    )

    def _placed(self, root: Path) -> tuple[Importer, dict[str, Decisions]]:
        importer = Importer(None)
        importer.plan(root)
        return importer, {"odd.csv": Decisions(kind=RecordKind.SETTLEMENT_ROWS)}

    def test_answering_a_second_field_with_the_same_column_clears_the_first(
        self, tmp_path: Path
    ) -> None:
        root = folder(tmp_path, odd__csv=self.SIGNED, bank__csv=BANK)
        importer, decisions = self._placed(root)

        decisions["odd.csv"] = decisions["odd.csv"].with_answer("debit", "in_amt", is_format=False)
        decisions["odd.csv"] = decisions["odd.csv"].with_answer("credit", "in_amt", is_format=False)

        mapping = importer.plan(root, decisions).of(RecordKind.SETTLEMENT_ROWS)
        assert mapping is not None
        assert mapping.columns.get("credit") == "in_amt"
        assert mapping.columns.get("debit") != "in_amt"

    def test_the_displaced_field_goes_back_to_being_asked(self, tmp_path: Path) -> None:
        """Not silently dropped. The person said that column is the credit;
        what the debit is has become an open question again."""
        root = folder(tmp_path, odd__csv=self.SIGNED, bank__csv=BANK)
        importer, decisions = self._placed(root)

        decisions["odd.csv"] = decisions["odd.csv"].with_answer("debit", "in_amt", is_format=False)
        decisions["odd.csv"] = decisions["odd.csv"].with_answer("credit", "in_amt", is_format=False)

        plan = importer.plan(root, decisions)
        assert any(question.subject == "debit" for question in plan.questions)
        assert not plan.ready

    @pytest.mark.parametrize("sentinel", [ABSENT, DERIVE])
    def test_absent_and_derive_are_not_columns_and_do_not_displace(
        self, tmp_path: Path, sentinel: str
    ) -> None:
        """Two fields can both be derived, and two can both be absent. Neither
        is a claim on a column, so neither can collide with one."""
        root = folder(tmp_path, odd__csv=self.SIGNED, bank__csv=BANK)
        importer, decisions = self._placed(root)

        decisions["odd.csv"] = decisions["odd.csv"].with_answer("debit", sentinel, is_format=False)
        decisions["odd.csv"] = decisions["odd.csv"].with_answer("credit", sentinel, is_format=False)

        mapping = importer.plan(root, decisions).of(RecordKind.SETTLEMENT_ROWS)
        assert mapping is not None
        if sentinel == DERIVE:
            assert set(mapping.derived) == {"credit", "debit"}
        else:
            assert "credit" not in mapping.columns
            assert "debit" not in mapping.columns

    def test_answering_the_same_field_twice_just_replaces_it(self, tmp_path: Path) -> None:
        root = folder(tmp_path, odd__csv=self.SIGNED, bank__csv=BANK)
        importer, decisions = self._placed(root)

        decisions["odd.csv"] = decisions["odd.csv"].with_answer(
            "credit", "charge_amt", is_format=False
        )
        decisions["odd.csv"] = decisions["odd.csv"].with_answer("credit", "in_amt", is_format=False)

        mapping = importer.plan(root, decisions).of(RecordKind.SETTLEMENT_ROWS)
        assert mapping is not None
        assert mapping.columns.get("credit") == "in_amt"


class TestAMerchantCanSayAFileIsNotTheirs:
    """The escape hatch in the other direction.

    Saying what an unrecognised file *is* has existed since the wizard did.
    Saying that a recognised file is **not** what we think has not, and the
    gap has a concrete shape: a purchase ledger four columns wide, which a
    model places as an orders export because a PO number, a value and a
    raised-on date are exactly what an order book needs. Nothing in the file
    rules it out. Only the person who owns it knows.
    """

    def test_ignoring_a_file_unplaces_it(self) -> None:
        decisions = Decisions().ignoring()
        assert decisions.ignored is True
        assert decisions.kind is None

    def test_it_outranks_a_kind_already_chosen(self) -> None:
        """Otherwise the file is placed, ignored, and placed again on the next
        plan, because the column names have not changed."""
        decisions = Decisions().with_kind(RecordKind.ORDERS).ignoring()
        assert decisions.ignored is True
        assert decisions.kind is None

    def test_choosing_a_kind_afterwards_takes_it_back(self) -> None:
        """A person who ignores the wrong file has to be able to undo it."""
        decisions = Decisions().ignoring().with_kind(RecordKind.ORDERS)
        assert decisions.ignored is False
        assert decisions.kind is RecordKind.ORDERS

    def test_column_answers_survive_being_ignored(self) -> None:
        """Ignoring is about the file, not about the work already done on it.
        Somebody who ignores a file and changes their mind should not have to
        answer its columns again."""
        decisions = Decisions().with_answer("amount", "Value", is_format=False).ignoring()
        assert decisions.columns == {"amount": "Value"}
