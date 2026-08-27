"""What each sample file really is, so a proposal can be marked right or wrong.

The samples are generated, which means — uniquely — we know the answer. A
gateway export written by `dialects.gateway_workbook` has `Amount Paid In`
holding the credit because that function put it there, and no amount of
reading the file is needed to establish it.

That is what makes a measurement possible at all. Every accuracy figure in
this project is measured here and nowhere else, because this is the only
corpus with an answer key. A number measured on a merchant's own upload would
be measured against our own guess, which is not a measurement.

Two things this file is deliberately not:

**Not the aliases.** `schema.py` holds the header names the resolver
recognises. If a name appeared in both, a measurement would be scoring the
resolver against a copy of itself. Where a column here is one the schema
already knows by name, the harness reports it as settled by the header and
does not credit a model for it.

**Not asserted by construction.** `test_proposal_accuracy` regenerates the
files and checks that every column named here is a real header in the
generated artefact. A truth table that drifts from the writers would quietly
turn into a measurement of nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from milan.ingest.schema import RecordKind

__all__ = ["CORPUS", "Truth", "for_file"]


@dataclass(frozen=True, slots=True)
class Truth:
    """The answer key for one generated file, or one sheet of one."""

    writer: str
    """The `dialects` function that produces it, for tracing a failure back."""

    kind: RecordKind | None
    """What it is. `None` means it is none of ours and should be left alone."""

    columns: Mapping[str, str] = field(default_factory=dict)
    """Field name to the header that holds it. Only fields the file actually
    has: a statement with no reference column simply omits `utr`, and the
    harness scores a proposal for it as a false positive rather than a miss.
    """

    sheet: str = ""
    """Empty for a flat file; the sheet name inside a workbook otherwise."""

    note: str = ""
    """Why this file is interesting, where it is."""


# --------------------------------------------------------------- settlements

RAZORPAY = Truth(
    writer="razorpay_settlement",
    kind=RecordKind.SETTLEMENT_ROWS,
    columns={
        "entity_id": "entity_id",
        "type": "type",
        "amount": "amount",
        "credit": "credit",
        "debit": "debit",
        "fee": "fee",
        "tax": "tax",
        "created_at": "created_at",
        "settlement_id": "settlement_id",
        "settled_at": "settled_at",
        "settlement_utr": "settlement_utr",
        "payment_id": "payment_id",
        "order_id": "order_id",
        "method": "method",
        "card_type": "card_type",
        "on_hold": "on_hold",
        "settled": "settled",
    },
    note="the gateway's own export, named the way the schema is named",
)

UNFAMILIAR = Truth(
    writer="unfamiliar_settlement",
    kind=RecordKind.SETTLEMENT_ROWS,
    columns={
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
        "payment_id": "Merchant Ref",
        "order_id": "Order Ref",
        "method": "Instrument",
        "card_type": "Card Variant",
        "on_hold": "Blocked",
        "settled": "Paid Out",
    },
    note="a processor's own vocabulary; nothing here is settled by name",
)

WORKBOOK_PAYOUTS = Truth(
    writer="gateway_workbook",
    kind=RecordKind.SETTLEMENT_ROWS,
    sheet="Payouts",
    columns={
        "entity_id": "Record ID",
        "type": "Record Type",
        "amount": "Gross Amount",
        "credit": "Amount Paid In",
        "debit": "Amount Taken Out",
        "fee": "Processing Fee",
        "tax": "GST On Fee",
        "created_at": "Booked On",
        "settlement_id": "Settlement Ref",
        "settled_at": "Settled On",
        "settlement_utr": "Payout UTR",
        "payment_id": "Payment Ref",
        "order_id": "Order Ref",
        "method": "Mode",
        "card_type": "Card Class",
        "on_hold": "Held",
        "settled": "Paid",
    },
    note="`Settlement Ref` against `Payout UTR` - both opaque ids, one bank reference",
)

WORKBOOK_TRANSACTIONS = Truth(
    writer="gateway_workbook",
    kind=RecordKind.PAYMENTS,
    sheet="Transactions",
    columns={
        "payment_id": "Payment Ref",
        "order_id": "Order Ref",
        "amount": "Amount",
        "captured_at": "Captured On",
        "method": "Mode",
        "card_type": "Card Class",
    },
    note="the second sheet of the same workbook, and a different kind of file",
)

# ------------------------------------------------------------------- banks

HDFC = Truth(
    writer="hdfc_statement",
    kind=RecordKind.BANK_CREDITS,
    columns={
        "amount": "Deposit Amt.",
        "value_date": "Value Dt",
        "narration": "Narration",
        "utr": "Chq./Ref.No.",
        "debit": "Withdrawal Amt.",
    },
    note="two date columns, one of which is abbreviated past recognition",
)

ICICI = Truth(
    writer="icici_statement",
    kind=RecordKind.BANK_CREDITS,
    columns={
        "amount": "Deposit Amount (INR )",
        "value_date": "Value Date",
        "narration": "Transaction Remarks",
        "utr": "Cheque Number",
        "debit": "Withdrawal Amount (INR )",
    },
    note="the trailing space inside `(INR )` is the bank's, not a typo",
)

KOTAK = Truth(
    writer="kotak_statement",
    kind=RecordKind.BANK_CREDITS,
    columns={
        "amount": "Amount",
        "value_date": "Transaction Date",
        "narration": "Description",
        "utr": "Reference No",
    },
    note="one signed amount column with a `Cr` suffix, and no separate debit",
)

AXIS = Truth(
    writer="axis_statement",
    kind=RecordKind.BANK_CREDITS,
    columns={
        "amount": "Credit",
        "value_date": "Tran Date",
        "narration": "Particulars",
        "utr": "Chq No",
        "debit": "Debit",
    },
    note="`Credit` and `Debit` named plainly, and a `Balance` beside them",
)

# --------------------------------------------------------- payments, orders

CAPTURES = Truth(
    writer="capture_log",
    kind=RecordKind.PAYMENTS,
    columns={
        "payment_id": "payment_id",
        "order_id": "order_id",
        "amount": "amount",
        "captured_at": "captured_at",
        "method": "method",
        "card_type": "card_type",
    },
    note=(
        "the file has a `currency` column and the payments schema has no such "
        "field, so the answer key does not claim one - scoring a field the "
        "import never looks for would be measuring the schema, not the import"
    ),
)

ORDERS = Truth(
    writer="order_book",
    kind=RecordKind.ORDERS,
    columns={
        "order_id": "order_id",
        "amount": "amount",
        "created_at": "created_at",
        "order_receipt": "receipt",
        "currency": "currency",
    },
)

# ----------------------------------------------------------- none of ours

GST = Truth(
    writer="gst_register",
    kind=None,
    note="a GST return. No date column at all, so nothing can place it",
)

LEDGER = Truth(
    writer="vendor_ledger",
    kind=None,
    note="a purchase ledger. Has a date, so it has to be refused on the values",
)

CORPUS: tuple[Truth, ...] = (
    RAZORPAY,
    UNFAMILIAR,
    WORKBOOK_PAYOUTS,
    WORKBOOK_TRANSACTIONS,
    HDFC,
    ICICI,
    KOTAK,
    AXIS,
    CAPTURES,
    ORDERS,
    GST,
    LEDGER,
)


def for_file(writer: str, sheet: str = "") -> Truth | None:
    """The answer key for one artefact, by the function that wrote it."""
    for truth in CORPUS:
        if truth.writer == writer and truth.sheet == sheet:
            return truth
    return None
