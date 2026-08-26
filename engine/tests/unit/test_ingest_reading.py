"""Reading files written by software that never heard of us.

Every case here is one a real export actually produces. The banner above the
header is HDFC's. The `Cr` suffix instead of a minus sign is how Indian
statements write direction. The two-digit year, the blank credit column on a
withdrawal line, the duplicate `Amount` header from a spreadsheet paste - none
of these are hypothetical hardening, they are the shapes that arrive.

The date tests are the ones worth reading. `06-07-2026` is two different days
depending on which side of the world wrote it, and the only thing that can
settle it is whether some other value in the same column has a day past the
twelfth. A parser that picks one and moves on is not slightly wrong, it is
silently reporting a different month.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from milan.domain.enums import CardType, EntityType, PaymentMethod
from milan.domain.money import from_rupees
from milan.ingest import parsing
from milan.ingest.profile import profile_column
from milan.ingest.reading import UnreadableFileError, discover, read
from milan.ingest.schema import ValueKind


class TestMoneyIsReadHoweverItWasWritten:
    @pytest.mark.parametrize(
        ("written", "rupees"),
        [
            ("1234.56", "1234.56"),
            ("1,234.56", "1234.56"),
            ("1,23,456.78", "123456.78"),
            ("1,234,567.89", "1234567.89"),
            ("Rs 90,608.47", "90608.47"),
            ("Rs. 90,608.47", "90608.47"),
            ("INR 500.00", "500.00"),
            ("₹ 2,500.50", "2500.50"),
            ("37,419.37 Cr", "37419.37"),
            ("  8,000.00  ", "8000.00"),
            ("42", "42"),
        ],
    )
    def test_the_shapes_a_finance_export_uses(self, written: str, rupees: str) -> None:
        assert parsing.parse_money(written) == from_rupees(rupees)

    @pytest.mark.parametrize(
        ("written", "rupees"),
        [
            ("-1234.56", "-1234.56"),
            ("(1,234.56)", "-1234.56"),
            ("1,234.56 Dr", "-1234.56"),
            ("Rs 1,234.56 Dr", "-1234.56"),
        ],
    )
    def test_every_way_a_statement_writes_money_going_out(self, written: str, rupees: str) -> None:
        assert parsing.parse_money(written) == from_rupees(rupees)

    @pytest.mark.parametrize("written", ["", "   ", "N/A", "-", "pending", "12.34.56", "abc"])
    def test_a_value_that_is_not_money_is_nothing_rather_than_zero(self, written: str) -> None:
        """The distinction the whole bank-statement path rests on.

        A blank credit column on a withdrawal line read as zero would invent a
        nil-rupee payout for every debit the merchant ever made, and each one
        would then be reported as a credit nothing could explain.
        """
        assert parsing.parse_money(written) is None

    def test_reading_money_never_goes_through_a_float(self) -> None:
        """0.1 + 0.2 does not equal 0.3, and a statement has a thousand rows."""
        total = sum(parsing.parse_money(f"{n}.10") or 0 for n in range(1000))
        assert total == sum(from_rupees(f"{n}.10") for n in range(1000))


class TestDatesAreOnlyReadWhenTheColumnSaysHow:
    def test_a_column_with_a_day_past_the_twelfth_settles_its_own_format(self) -> None:
        profile = profile_column("Value Dt", ("06-07-2026", "19-07-2026", "31-07-2026"))
        assert profile.fits(ValueKind.TEMPORAL)
        assert not profile.ambiguous_dates
        assert parsing.parse_temporal("06-07-2026", profile.temporal[0]) == datetime(2026, 7, 6)

    def test_a_column_that_could_be_read_either_way_is_flagged_not_guessed(self) -> None:
        """Every day in this column is under thirteen, so nothing in the file
        can say whether it is day-first or month-first."""
        profile = profile_column("Date", ("06-07-2026", "08-07-2026", "11-07-2026"))
        assert profile.fits(ValueKind.TEMPORAL)
        assert profile.ambiguous_dates
        assert profile.conflict == "06-07-2026"

    def test_two_formats_that_never_disagree_are_not_an_ambiguity(self) -> None:
        """A month name cannot be read the other way round, so there is
        nothing to ask about even though several patterns match."""
        profile = profile_column("Date", ("06-Jul-2026", "08-Jul-2026"))
        assert profile.fits(ValueKind.TEMPORAL)
        assert not profile.ambiguous_dates

    @pytest.mark.parametrize(
        ("written", "pattern", "expected"),
        [
            ("2026-07-06", "%Y-%m-%d", datetime(2026, 7, 6)),
            ("06/07/26", "%d/%m/%y", datetime(2026, 7, 6)),
            ("06-07-2026 14:23:11", "%d-%m-%Y %H:%M:%S", datetime(2026, 7, 6, 14, 23, 11)),
            ("2026-07-06T14:23:11", parsing.ISO, datetime(2026, 7, 6, 14, 23, 11)),
            ("2026-07-06T14:23:11Z", parsing.ISO, datetime(2026, 7, 6, 14, 23, 11)),
        ],
    )
    def test_one_value_under_one_pattern(
        self, written: str, pattern: str, expected: datetime
    ) -> None:
        assert parsing.parse_temporal(written, pattern) == expected

    def test_a_four_digit_year_is_never_read_as_a_two_digit_one(self) -> None:
        assert parsing.parse_temporal("06-07-2026", "%d-%m-%y") is None

    def test_a_column_of_amounts_is_not_a_column_of_dates(self) -> None:
        profile = profile_column("Credit", ("37419.37", "89510.80", "598.67"))
        assert not profile.fits(ValueKind.TEMPORAL)


class TestVocabularyIsMatchedByMeaningNotByOurSpelling:
    @pytest.mark.parametrize(
        ("written", "expected"),
        [
            ("payment", EntityType.PAYMENT),
            ("Sale", EntityType.PAYMENT),
            ("CHARGEBACK", EntityType.ADJUSTMENT),
            ("Route Transfer", EntityType.TRANSFER),
            ("credit note", EntityType.REFUND),
        ],
    )
    def test_entity_types(self, written: str, expected: EntityType) -> None:
        assert parsing.parse_entity_type(written) is expected

    @pytest.mark.parametrize(
        ("written", "expected"),
        [
            ("Credit Card", PaymentMethod.CARD),
            ("net banking", PaymentMethod.NETBANKING),
            ("UPI", PaymentMethod.UPI),
            ("BNPL", PaymentMethod.PAYLATER),
        ],
    )
    def test_payment_methods(self, written: str, expected: PaymentMethod) -> None:
        assert parsing.parse_method(written) is expected

    @pytest.mark.parametrize(
        ("written", "expected"),
        [
            ("Corporate", CardType.DOMESTIC_CORPORATE),
            ("commercial", CardType.DOMESTIC_CORPORATE),
            ("Intl", CardType.INTERNATIONAL),
            ("domestic", CardType.DOMESTIC_CONSUMER),
        ],
    )
    def test_card_types(self, written: str, expected: CardType) -> None:
        assert parsing.parse_card_type(written) is expected

    def test_a_word_we_have_no_name_for_is_refused(self) -> None:
        assert parsing.parse_entity_type("settlement_fee_reversal_v2") is None


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


class TestTheHeaderIsFoundRatherThanAssumed:
    def test_a_bank_banner_above_the_header_is_read_as_a_banner(self, tmp_path: Path) -> None:
        """HDFC's export, and the reason `csv.DictReader` cannot be used here.

        Taking the first line would give one column called `HDFC BANK LIMITED`
        and no rows at all - a failure that produces an empty reconciliation
        rather than an error.
        """
        path = write(
            tmp_path / "OpTxnHistory.csv",
            "HDFC BANK LIMITED\n"
            "Statement of account\n"
            "Account No :50100XXXXXX1234\n"
            "\n"
            "Date,Narration,Deposit Amt.\n"
            "06-07-2026,NEFT INWARD RAZORPAY,37419.37\n"
            "19-07-2026,NEFT INWARD RAZORPAY,89510.80\n",
        )
        source = read(path)
        assert source.headers == ("Date", "Narration", "Deposit Amt.")
        assert len(source.rows) == 2
        assert source.header_line == 5
        assert "HDFC BANK LIMITED" in source.preamble[0]

    def test_a_dropped_row_is_reported_at_the_line_it_is_actually_on(self, tmp_path: Path) -> None:
        """Blank lines inside a statement are skipped on the way in, so the
        line number has to be carried rather than counted afterwards."""
        path = write(
            tmp_path / "gaps.csv",
            "Date,Amount\n06-07-2026,1.00\n\n\n19-07-2026,2.00\n",
        )
        source = read(path)
        assert source.line_numbers == (2, 5)

    @pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
    def test_the_delimiter_is_sniffed(self, tmp_path: Path, delimiter: str) -> None:
        path = write(
            tmp_path / "sep.csv",
            f"Date{delimiter}Narration{delimiter}Credit\n"
            f"06-07-2026{delimiter}NEFT INWARD{delimiter}100.00\n"
            f"19-07-2026{delimiter}NEFT INWARD{delimiter}200.00\n",
        )
        source = read(path)
        assert source.delimiter == delimiter
        assert source.headers == ("Date", "Narration", "Credit")

    def test_an_excel_byte_order_mark_does_not_become_part_of_a_column_name(
        self, tmp_path: Path
    ) -> None:
        """A BOM read as text turns `Date` into `﻿Date`, which no alias
        will ever match - and the failure looks like a missing column."""
        path = tmp_path / "excel.csv"
        path.write_bytes("Date,Credit\n06-07-2026,100.00\n".encode("utf-8-sig"))
        assert read(path).headers == ("Date", "Credit")

    def test_two_columns_with_the_same_name_both_survive(self, tmp_path: Path) -> None:
        """A dict would silently keep one of them, and the other's values
        would vanish from the reconciliation without a word."""
        path = write(tmp_path / "dupes.csv", "Amount,Amount,Date\n1.00,2.00,06-07-2026\n")
        source = read(path)
        assert len(source.headers) == 3
        assert len(set(source.headers)) == 3

    def test_a_trailing_delimiter_does_not_produce_a_nameless_column(self, tmp_path: Path) -> None:
        path = write(tmp_path / "trailing.csv", "Date,Credit,\n06-07-2026,100.00,\n")
        assert all(name.strip() for name in read(path).headers)

    def test_a_file_with_no_table_in_it_is_refused_rather_than_half_read(
        self, tmp_path: Path
    ) -> None:
        path = write(tmp_path / "notes.txt", "Reminder: chase the bank about July.\n")
        with pytest.raises(UnreadableFileError):
            read(path)

    def test_an_empty_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(UnreadableFileError):
            read(write(tmp_path / "empty.csv", "   \n"))

    def test_discovery_does_not_walk_into_subdirectories(self, tmp_path: Path) -> None:
        """A merchant hands over a folder. Walking the tree is how an import
        reads last year's archive alongside this month's statement."""
        write(tmp_path / "statement.csv", "Date,Credit\n06-07-2026,1.00\n")
        (tmp_path / "archive").mkdir()
        write(tmp_path / "archive" / "old.csv", "Date,Credit\n06-07-2025,1.00\n")
        assert [path.name for path in discover(tmp_path)] == ["statement.csv"]


class TestAColumnIsMeasuredNotDescribed:
    def test_an_empty_column_fits_nothing(self) -> None:
        """A bank statement's withdrawal column is blank on a settlement-only
        account. Treating blankness as "could be anything" would let it be
        proposed as the credit amount."""
        profile = profile_column("Withdrawal Amt.", ("", "", ""))
        assert profile.empty
        assert not any(profile.fits(kind) for kind in ValueKind)

    def test_narration_is_text_and_never_an_identifier(self) -> None:
        """The only thing separating a reference column from a narration when
        both are free text: references do not contain spaces."""
        profile = profile_column("Narration", ("NEFT INWARD RAZORPAY SOFTWARE PVT LTD",) * 4)
        assert profile.fits(ValueKind.TEXT)
        assert not profile.fits(ValueKind.IDENTIFIER)

    def test_a_reference_column_is_an_identifier(self) -> None:
        profile = profile_column("Ref No", ("5VBAHQZ7WQ00", "G12FOWP6BIP1", "KZ587WNNJO2H"))
        assert profile.fits(ValueKind.IDENTIFIER)

    def test_a_yes_no_column_is_a_flag_and_not_a_category(self) -> None:
        profile = profile_column("on_hold", ("Y", "N", "N", "Y"))
        assert profile.fits(ValueKind.BOOLEAN)
        assert not profile.fits(ValueKind.MONEY)

    def test_one_unreadable_cell_in_a_thousand_does_not_disqualify_a_column(self) -> None:
        values = tuple(["100.00"] * 99 + ["N/A"])
        assert profile_column("Credit", values).fits(ValueKind.MONEY)

    def test_a_column_that_is_mostly_junk_is_not_money(self) -> None:
        values = tuple(["100.00"] * 4 + ["pending"] * 6)
        assert not profile_column("Credit", values).fits(ValueKind.MONEY)
