"""Folders of files, each one a merchant with a different problem.

Four folders rather than one pile, because "can it read a CSV" is not a
question worth answering and the four below are. Each folder is a claim, and
each claim has an outcome somebody testing can check without reading any code:

  1. **A gateway and a bank whose names we know.** Imports with no model at
     all, and asks one question - which of an HDFC statement's two date
     columns is the value date, a thing no amount of evidence can settle.
  2. **Names nobody has met.** Nothing here is a synonym the schema knows, so
     either a model proposes the mapping or a person answers it. Both paths
     end in the same run, which is the point of having both.
  3. **One Excel workbook.** The format merchants most often actually hold,
     with a cover sheet that is not a table and three sheets that are.
  4. **A folder as it actually arrives.** A statement, a report, an invoice
     register that is none of our business, a refund log kept by hand, a PDF
     that cannot be read, and the lock file Excel leaves behind. The right
     outcome differs for every one of them and not one is an error.
  5. **A real handover.** All of the above at once, plus the thing none of the
     others has: a month that landed in **two bank accounts at two banks**. An
     engine that assumed one file per record kind would reconcile half the
     money perfectly and report nothing wrong. Start here.

All four are built from the same generated month, so they reconcile to the
same answer. A difference between two folders is a difference in the reader.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from milan.chaos.config import Difficulty, GenerationConfig
from milan.chaos.generator import ChaosEngine
from milan.domain.dataset import Dataset
from milan.domain.rates import RateCard
from milan.samples import dialects


@dataclass(frozen=True, slots=True)
class Folder:
    """One sample folder, and what it is for."""

    name: str
    title: str
    expect: str
    """What should happen when this folder is imported, in one sentence.

    Written into the folder's own README so that somebody testing has the
    expected outcome in front of them rather than in a docstring they will
    never open. A sample that does not say what it demonstrates is a sample
    that proves whatever the reader happened to do.
    """

    files: tuple[str, ...]


def month(seed: int = 42, orders: int = 400) -> Dataset:
    """The month every folder is written from.

    The realistic tier rather than the adversarial one. These files exist to
    be handed to somebody who has not seen the system before, and a month
    engineered to be maximally hostile would make the exception list the
    story - when the story here is that a merchant's own files can be read at
    all.
    """
    return ChaosEngine(
        GenerationConfig(
            seed=seed,
            difficulty=Difficulty.REALISTIC,
            order_count=orders,
            span_days=28,
            rates=RateCard(),
        )
    ).generate()


def _readme(root: Path, folder: Folder) -> None:
    lines = [
        f"# {folder.title}",
        "",
        folder.expect,
        "",
        "## What is in here",
        "",
        *(f"- `{name}`" for name in folder.files),
        "",
        "## How to try it",
        "",
        "Open Milan in the browser, press **Import your files**, and drop this",
        "whole folder in. Or from a terminal:",
        "",
        "```",
        f"uv run milan import --from {root.name}",
        "```",
        "",
        "Nothing is reconciled until you approve how the columns were read.",
        "",
    ]
    (root / "README.md").write_text("\n".join(lines), encoding="utf-8")


def clean_folder(data: Dataset, root: Path) -> Folder:
    dialects.razorpay_settlement(data, root / "settlement_report_jul2026.csv")
    dialects.hdfc_statement(data, root / "Acct Statement_XX1234_01082026.csv")
    dialects.capture_log(data, root / "payments_jul2026.csv")
    folder = Folder(
        name=root.name,
        title="A gateway and a bank whose column names we know",
        expect=(
            "Expect **no model consulted, and exactly one question**.\n\n"
            "The column names are ones the schema already has aliases for, so "
            "the values only have to confirm them. Four banner lines above the "
            "statement's header and a closing line under its last row are "
            "walked past rather than read as transactions.\n\n"
            "The one question is real rather than a limitation. An HDFC "
            "statement carries both a `Date` and a `Value Dt` column, and on "
            "the rows where they differ, choosing the wrong one moves a "
            "settlement into the wrong day. Nothing in the values can settle "
            "that, so it is asked."
        ),
        files=(
            "settlement_report_jul2026.csv",
            "Acct Statement_XX1234_01082026.csv",
            "payments_jul2026.csv",
        ),
    )
    _readme(root, folder)
    return folder


def unfamiliar_folder(data: Dataset, root: Path) -> Folder:
    dialects.unfamiliar_settlement(data, root / "MERCHANT_SETTLEMENT_JUL26.csv")
    dialects.icici_statement(data, root / "OpTransactionHistoryUX5.csv")
    folder = Folder(
        name=root.name,
        title="Names nobody has met before",
        expect=(
            "Expect **six questions with no model, and far fewer with one**.\n\n"
            "Nothing in the settlement report is a name the schema knows - "
            "`Txn Ref No`, `Amount Credited`, `Service Tax (GST)` - so either a "
            "model proposes the mapping or you answer it yourself. Either way "
            "the values keep the veto: `Blocked` and `Paid Out` are Y/N flags "
            "sitting next to the money columns, and anything that proposes one "
            "of them for an amount is refused by the values rather than by "
            "somebody noticing three screens later.\n\n"
            "To see the model half, run the engine with a provider:\n\n"
            "```\nuv run milan serve --provider ollama\n```\n\n"
            "The statement also carries two date columns, `Value Date` and "
            "`Transaction Date`, and that question survives a model - because "
            "a model cannot know which day the merchant's bank posted on "
            "either."
        ),
        files=("MERCHANT_SETTLEMENT_JUL26.csv", "OpTransactionHistoryUX5.csv"),
    )
    _readme(root, folder)
    return folder


def workbook_folder(data: Dataset, root: Path) -> Folder:
    dialects.workbook_export(data, root / "Settlement_Jul_2026.xlsx")
    folder = Folder(
        name=root.name,
        title="One Excel workbook, four sheets",
        expect=(
            "Expect **three tables out of one file**. The `Summary` sheet is a "
            "cover page rather than a table and is skipped; `Settlements`, "
            "`Bank Statement` and `Payments` are read, each named after both "
            "the file and the sheet.\n\n"
            "Every amount in here was a floating-point number inside Excel for "
            "the length of the round trip. The totals should still come back "
            "to the paisa."
        ),
        files=("Settlement_Jul_2026.xlsx",),
    )
    _readme(root, folder)
    return folder


def messy_folder(data: Dataset, root: Path) -> Folder:
    dialects.razorpay_settlement(data, root / "settlement_report_jul2026.csv")
    dialects.kotak_statement(data, root / "statement.csv")
    dialects.gst_register(data, root / "GSTR1_July_2026.csv")
    dialects.refunds_note(data, root / "refunds to check.csv")
    dialects.pdf_statement(root / "Statement_Jul2026.pdf")
    dialects.excel_lock_file(root / "~$Settlement_Jul_2026.xlsx")
    folder = Folder(
        name=root.name,
        title="A folder as it actually arrives",
        expect=(
            "Six outcomes, and **none of them is an error**. This is the "
            "folder to try if you only try one:\n\n"
            "- the settlement report is read;\n"
            "- the Kotak statement carries one signed column with a `Cr` marker "
            "instead of separate withdrawal and deposit columns, and is read;\n"
            "- the GST invoice register has an id, an amount and a reference, "
            "so it looks convincingly like a settlement report - and it has no "
            "settlement date, so it is **left alone with the reason printed**;\n"
            "- the hand-kept refund log has an amount and a date, which is "
            "two thirds of what an order book needs. It is **left alone too**: "
            "a file placed on half its names, which then cannot answer "
            "something required, was guessed at rather than placed;\n"
            "- the PDF is **refused with the sentence that gets you unstuck**, "
            "not with 'unsupported format';\n"
            "- the `~$` file is the lock file Excel leaves beside an open "
            "workbook, and you should never hear about it."
        ),
        files=(
            "settlement_report_jul2026.csv",
            "statement.csv",
            "GSTR1_July_2026.csv",
            "refunds to check.csv",
            "Statement_Jul2026.pdf",
            "~$Settlement_Jul_2026.xlsx",
        ),
    )
    _readme(root, folder)
    return folder


def handover_folder(data: Dataset, root: Path) -> Folder:
    """The folder this pack exists to be judged on.

    Everything before it isolates one problem. This one has all of them at
    once, which is the only shape a real handover ever takes: a gateway export
    in a format that is not CSV, with headers in somebody else's vocabulary,
    covering a month that landed in **two different bank accounts** at two
    different banks - plus the two files in every finance folder that are none
    of our business, and the PDF somebody downloaded first.

    The two accounts are the part worth pointing at. An engine that quietly
    assumed one file per record kind would read one statement, reconcile the
    credits in it perfectly, and report a month that balances over half the
    money - with nothing anywhere saying so.
    """
    credits = sorted(data.bank_credits, key=lambda credit: credit.credit_id)
    half = len(credits) // 2

    dialects.gateway_workbook(data, root / "Settlement Report Aug 2026.xlsx")
    dialects.hdfc_statement(data, root / "Acct Statement_XX1234.csv", only=credits[:half])
    dialects.axis_statement(data, root / "axis_918020012345678_aug.csv", only=credits[half:])
    dialects.vendor_ledger(data, root / "purchase orders.csv")
    dialects.gst_register(data, root / "GSTR1_Aug_2026.csv")
    dialects.pdf_statement(root / "August Statement.pdf")

    folder = Folder(
        name=root.name,
        title="A real handover: two banks, one workbook, and three files that are not ours",
        expect=(
            "**Start here if you want to see the whole thing work.**\n\n"
            "The month landed in two current accounts at two banks, so there "
            "are two statements in different formats and the reconciliation is "
            "over both. An engine that assumed one bank file would reconcile "
            "half the money perfectly and report nothing wrong.\n\n"
            "The gateway export is a workbook with two sheets, and its headers "
            "are a payment processor's vocabulary rather than ours - "
            "`Amount Paid In`, `GST On Fee`, `Booked On`. Expect to be asked "
            "about them, and expect the suggestions to be good if the engine "
            "is running with a model:\n\n"
            "```\nuv run milan serve --provider ollama\n```\n\n"
            "`Settlement Ref` and `Payout UTR` are the pair to watch. Both are "
            "opaque identifiers, both plausible for the settlement id, and the "
            "values cannot separate them - so a model proposes and you "
            "confirm, which is this whole design in one column.\n\n"
            "Three files are left alone and **none of that is an error**: the "
            "GST register has no settlement date, the purchase ledger is "
            "somebody's payables, and the PDF is refused with the sentence "
            "that tells you to download the CSV your bank already offers."
        ),
        files=(
            "Settlement Report Aug 2026.xlsx",
            "Acct Statement_XX1234.csv",
            "axis_918020012345678_aug.csv",
            "purchase orders.csv",
            "GSTR1_Aug_2026.csv",
            "August Statement.pdf",
        ),
    )
    _readme(root, folder)
    return folder


BUILDERS = (
    ("1-names-we-know", clean_folder),
    ("2-names-we-do-not", unfamiliar_folder),
    ("3-one-excel-workbook", workbook_folder),
    ("4-a-real-folder", messy_folder),
    ("5-a-real-handover", handover_folder),
)


def write_all(root: Path, *, seed: int = 42, orders: int = 400) -> tuple[Folder, ...]:
    """Build every sample folder under `root`, and return what each one is."""
    data = month(seed=seed, orders=orders)
    built: list[Folder] = []
    for name, builder in BUILDERS:
        folder = root / name
        folder.mkdir(parents=True, exist_ok=True)
        built.append(builder(data, folder))
    _index(root, tuple(built), data)
    return tuple(built)


def _index(root: Path, folders: tuple[Folder, ...], data: Dataset) -> None:
    """A README over the whole pack, saying where the numbers came from.

    The provenance line matters more than it looks. These files are generated
    from a seed, which means they are reproducible and contain nobody's real
    money - and somebody handed a folder of Indian bank statements deserves to
    be told that in the first paragraph rather than to wonder.
    """
    first, last = dialects.statement_date_range(data)
    lines = [
        "# Sample merchant files",
        "",
        "Four folders, each one a different problem. Drop any of them into",
        "Milan's **Import your files** dialog, or point the command line at one.",
        "",
        "None of this is anybody's real money. Every figure is generated from a",
        f"fixed seed (`{data.seed}`), so the same command produces the same files",
        "on any machine, and the month reconciles to a known answer.",
        "",
        f"The month runs {first.isoformat()} to {last.isoformat()}:",
        f"{len(data.orders)} orders, {len(data.payments)} captured payments,",
        f"{len(data.settlement_rows)} settlement rows and",
        f"{len(data.bank_credits)} bank credits.",
        "",
        "| Folder | What it is | What to expect |",
        "| --- | --- | --- |",
    ]
    for folder in folders:
        # The table wants one line per folder, and the expectations are
        # paragraphs. The full version is in each folder's own README.
        summary = folder.expect.split("\n")[0].replace("|", "/")
        lines.append(f"| `{folder.name}` | {folder.title} | {summary} |")
    lines += [
        "",
        "## The files are not written to our schema",
        "",
        "That is deliberate and it is the only reason they are worth having.",
        "Each writer imitates a specific real export - HDFC's `dd/mm/yy`, the",
        "trailing space inside ICICI's `Withdrawal Amount (INR )`, Kotak's `Cr`",
        "suffix, the bracketed negatives an accountant writes refunds in. Test",
        "data invented by the same person who wrote the reader tends to be data",
        "the reader happens to handle.",
        "",
    ]
    (root / "README.md").write_text("\n".join(lines), encoding="utf-8")
