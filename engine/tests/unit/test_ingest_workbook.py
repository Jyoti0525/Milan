"""Reading a spreadsheet, and refusing the things that only look like one.

Two claims are worth testing here and they are not the same claim.

The first is that a workbook becomes the same table a CSV would have. That is
mostly about `render`: a date that arrives as a `datetime` has to come out as
something the date-settling step recognises, an order id that Excel stored as
a float has to come out without `.0` on the end, and a rupee amount that has
been through a `SUM` has to come out as the number the merchant sees rather
than the binary double underneath it.

The second is that files which are not workbooks are refused *usefully*. A PDF
bank statement decodes as text perfectly well and would otherwise be imported
as a one-column table called `%PDF-1.7`, which is worse than any error - and
the person holding it is standing in front of a download page that also offers
CSV, so the refusal that names that is the one that costs them thirty seconds
instead of an evening.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from openpyxl import Workbook

from milan.ingest.reading import UnreadableFileError, read, read_all
from milan.ingest.workbook import FormatError, diagnose, render, sheets


def book(path: Path, **pages: list[list[object]]) -> Path:
    """A workbook on disk with one sheet per keyword argument."""
    workbook = Workbook()
    workbook.remove(workbook.active)  # type: ignore[arg-type]
    for title, rows in pages.items():
        sheet = workbook.create_sheet(title=title)
        for row in rows:
            sheet.append(row)
    workbook.save(path)
    return path


class TestACellBecomesTheStringACsvWouldHaveHeld:
    def test_a_date_comes_out_iso(self) -> None:
        """The one source that cannot be ambiguous about day and month, so it
        is written in the form nothing has to ask about."""
        assert render(dt.datetime(2026, 7, 4)) == "2026-07-04"

    def test_a_timestamp_keeps_its_time(self) -> None:
        assert render(dt.datetime(2026, 7, 4, 14, 30, 5)) == "2026-07-04 14:30:05"

    def test_a_whole_float_loses_its_point_zero(self) -> None:
        """Excel holds every number as a float, order ids included. `12345.0`
        is an identifier that matches nothing."""
        assert render(12345.0) == "12345"

    def test_a_typed_amount_survives_exactly(self) -> None:
        assert render(1234.56) == "1234.56"

    def test_a_rate_keeps_its_places(self) -> None:
        """Truncating to two would turn a 2.15% corporate card rate into 2%,
        which is a fee card that disagrees with the contract."""
        assert render(0.0215) == "0.0215"

    def test_excels_arithmetic_is_cut_back_to_the_number_on_screen(self) -> None:
        """A column of amounts that has been through a SUM arrives like this.
        The noise is Excel's, and it stops here rather than travelling into a
        Decimal that is faithfully wrong."""
        assert render(1234.5600000000001) == "1234.56"

    def test_a_boolean_is_not_an_integer(self) -> None:
        """`bool` subclasses `int`, so the obvious ordering renders TRUE as 1
        and the on-hold column stops meaning anything."""
        assert render(True) == "true"
        assert render(False) == "false"

    def test_an_empty_cell_is_an_empty_string(self) -> None:
        assert render(None) == ""


class TestAWorkbookIsEveryTableInIt:
    def test_both_sheets_are_read(self, tmp_path: Path) -> None:
        """The failure this prevents is the quiet one: importing the first
        sheet balances perfectly, over half the month's money."""
        path = book(
            tmp_path / "export.xlsx",
            Settlements=[["utr", "amount"], ["UTR1", 100]],
            Payments=[["payment_id", "amount"], ["pay_1", 100]],
        )
        found = read_all(path)
        assert [source.sheet for source in found] == ["Settlements", "Payments"]

    def test_a_sheet_is_named_by_file_and_sheet(self, tmp_path: Path) -> None:
        """Everything downstream is keyed on `name`. Two sheets answering to
        one key is two halves of a month overwriting each other."""
        path = book(tmp_path / "export.xlsx", Settlements=[["utr", "amount"], ["UTR1", 100]])
        assert read(path).name == "export.xlsx · Settlements"

    def test_a_banner_above_the_header_is_skipped(self, tmp_path: Path) -> None:
        """The same problem as a bank's CSV, in a different container - and
        solved by the same code, which is the reason this reader is fifty
        lines rather than a second one."""
        path = book(
            tmp_path / "stmt.xlsx",
            Sheet1=[
                ["HDFC BANK LTD"],
                ["Account: 50100XXXXXX"],
                [],
                ["Date", "Narration", "Deposit Amt."],
                ["04/07/26", "NEFT-RAZORPAY", 1000],
            ],
        )
        source = read(path)
        assert source.headers == ("Date", "Narration", "Deposit Amt.")
        assert len(source.rows) == 1

    def test_a_cover_sheet_does_not_take_the_file_down(self, tmp_path: Path) -> None:
        """Real exports carry a logo sheet and a notes sheet. Neither is a
        table, and neither should cost the merchant the sheet that is."""
        path = book(
            tmp_path / "export.xlsx",
            Cover=[["Settlement report"], ["Generated 4 July"]],
            Data=[["utr", "amount"], ["UTR1", 100]],
        )
        found = read_all(path)
        assert [source.sheet for source in found] == ["Data"]

    def test_a_workbook_with_no_table_anywhere_is_refused(self, tmp_path: Path) -> None:
        path = book(tmp_path / "empty.xlsx", Cover=[["Settlement report"]])
        with pytest.raises(UnreadableFileError, match="no sheet that looks like a table"):
            read_all(path)

    def test_trailing_blank_columns_are_dropped(self, tmp_path: Path) -> None:
        """A used range is generous on the right after somebody deletes a
        column, and the leftovers arrive as headers called `column_7`."""
        path = book(
            tmp_path / "export.xlsx",
            Data=[["utr", "amount", "", ""], ["UTR1", 100, "", ""]],
        )
        assert read(path).headers == ("utr", "amount")


class TestAFileThatOnlyLooksLikeATable:
    def test_a_pdf_is_named_as_a_pdf(self, tmp_path: Path) -> None:
        """It decodes as text and would otherwise import as one column called
        `%PDF-1.7`, which balances to nothing and explains nothing."""
        path = tmp_path / "statement.pdf"
        path.write_bytes(b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\n")
        assert "no columns to read" in diagnose(path)

    def test_a_legacy_xls_says_how_to_convert_it(self, tmp_path: Path) -> None:
        path = tmp_path / "statement.xls"
        path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32)
        assert "Save As" in diagnose(path)

    def test_a_bank_html_table_wearing_an_xls_name_is_caught(self, tmp_path: Path) -> None:
        """ICICI's "Excel" download is this, and it is not a rare case - it is
        what that button does."""
        path = tmp_path / "OpTransactionHistory.xls"
        path.write_bytes(b"<html><head></head><body><table><tr><td>Date</td></tr></table>")
        assert "web page saved with a spreadsheet's name" in diagnose(path)

    def test_a_real_csv_is_diagnosed_as_readable(self, tmp_path: Path) -> None:
        path = tmp_path / "settlement.csv"
        path.write_text("utr,amount\nUTR1,100\n", encoding="utf-8")
        assert diagnose(path) == ""

    def test_a_csv_renamed_xlsx_is_told_to_be_renamed_back(self, tmp_path: Path) -> None:
        path = tmp_path / "settlement.xlsx"
        path.write_text("utr,amount\nUTR1,100\n", encoding="utf-8")
        assert "rename it to .csv" in diagnose(path)

    def test_the_refusal_reaches_the_reader(self, tmp_path: Path) -> None:
        """`diagnose` being right is no use if `read_all` still tries."""
        path = tmp_path / "statement.pdf"
        path.write_bytes(b"%PDF-1.7\ntrailer\n")
        with pytest.raises(UnreadableFileError, match="no columns to read"):
            read_all(path)

    def test_a_zip_that_is_not_a_workbook_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "books.xlsx"
        path.write_bytes(b"PK\x03\x04" + b"\x00" * 64)
        with pytest.raises(FormatError):
            sheets(path)


class TestAJsonDumpIsNotATableYet:
    def test_it_is_named_rather_than_failing_at_the_header(self, tmp_path: Path) -> None:
        """A JSON dump reaches the header finder as one very long line and is
        refused there as "no header row found" - true, and it tells nobody
        that what they need is a different export."""
        path = tmp_path / "settlements.json"
        path.write_text('[{"id": "setl_1", "amount": 100}]', encoding="utf-8")
        assert "JSON dump" in diagnose(path)

    def test_an_object_at_the_top_level_counts_too(self, tmp_path: Path) -> None:
        path = tmp_path / "export.json"
        path.write_text('  {"items": []}', encoding="utf-8")
        assert "JSON dump" in diagnose(path)

    def test_a_csv_starting_with_a_brace_is_not_mistaken_for_one(self, tmp_path: Path) -> None:
        """Guarding the guard. A column header can begin with a brace, and a
        statement refused as JSON would be worse than one read as a table."""
        path = tmp_path / "odd.csv"
        path.write_text("date,narration\n2026-07-04,PAID\n", encoding="utf-8")
        assert diagnose(path) == ""
