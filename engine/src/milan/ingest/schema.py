"""What Milan needs from a file, stated once so everything can read it.

This is the target of every mapping: the fields the reconciliation engine
actually consumes, what shape their values have to be, and which names other
people's software tends to give them. It is the same list three different
things read - the profiler, to know what a column has to look like; the
model prompt, to know what it is choosing between; and the question a person
gets asked when neither could decide.

`costs` is the field nobody expects on a schema. A required field missing
stops the import; an optional one missing quietly removes a capability, and
the merchant has a right to be told which. A run that could not look for
unsettled payments because no payments file was supplied should say so, not
report a clean sheet.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RecordKind(StrEnum):
    """The four files a reconciliation needs, whatever they are called."""

    ORDERS = "orders"
    PAYMENTS = "payments"
    SETTLEMENT_ROWS = "settlement_rows"
    BANK_CREDITS = "bank_credits"

    @property
    def describes(self) -> str:
        return _DESCRIPTIONS[self]


_DESCRIPTIONS: dict[RecordKind, str] = {
    RecordKind.ORDERS: "what the merchant sold - one row per order",
    RecordKind.PAYMENTS: "money captured against those orders - one row per payment",
    RecordKind.SETTLEMENT_ROWS: (
        "the payment gateway's settlement or recon report - one row per payment, "
        "refund or adjustment, each carrying the fee and tax taken off it"
    ),
    RecordKind.BANK_CREDITS: (
        "the merchant's bank statement - what actually landed in the account, "
        "with a narration and no idea what a settlement is"
    ),
}


class ValueKind(StrEnum):
    """The shape a column's values must have to be a candidate at all.

    This is the veto. A model may propose any column for any field; if the
    values in it do not parse as this kind, the proposal is rejected before
    anybody sees it as a suggestion.
    """

    MONEY = "money"
    TEMPORAL = "temporal"
    IDENTIFIER = "identifier"
    TEXT = "text"
    BOOLEAN = "boolean"
    ENTITY_TYPE = "entity_type"
    PAYMENT_METHOD = "payment_method"
    CARD_TYPE = "card_type"


@dataclass(frozen=True, slots=True)
class TargetField:
    """One field Milan reads, and everything needed to find it in a stranger's file."""

    name: str
    kind: ValueKind
    required: bool
    describes: str
    aliases: frozenset[str]
    costs: str = ""
    """What the run loses without this. Empty for required fields, which have
    no degraded mode - they stop the import instead."""


def _field(
    name: str,
    kind: ValueKind,
    *,
    required: bool = False,
    describes: str,
    aliases: str,
    costs: str = "",
) -> TargetField:
    """Aliases are written as a space-separated string, because a set literal
    of twelve short strings is unreadable and this list is meant to be edited
    by whoever meets a bank we have not seen."""
    return TargetField(
        name=name,
        kind=kind,
        required=required,
        describes=describes,
        aliases=frozenset(aliases.split()),
        costs=costs,
    )


BANK_CREDIT_FIELDS: tuple[TargetField, ...] = (
    _field(
        "amount",
        ValueKind.MONEY,
        required=True,
        describes="money that came into the account on this line",
        aliases="amount credit credit_amount credit_amt deposit deposit_amt cr "
        "money_in amount_credited inflow receipt",
    ),
    _field(
        "value_date",
        ValueKind.TEMPORAL,
        required=True,
        describes="the day the money was available",
        aliases="value_date date txn_date transaction_date posting_date post_date "
        "value_dt val_date book_date tran_date",
    ),
    _field(
        "narration",
        ValueKind.TEXT,
        required=True,
        describes="the free text the bank wrote against the line",
        aliases="narration description particulars remarks details "
        "transaction_remarks txn_description transaction_description "
        "transaction_details narrative",
    ),
    _field(
        "utr",
        ValueKind.IDENTIFIER,
        describes="the bank reference number, if the statement has its own column for it",
        aliases="utr ref_no reference_no reference_number ref_number utr_no rrn "
        "cheque_ref_no chq_ref_no bank_ref_no reference",
        costs="references will be read out of the narration text instead, "
        "which is what a damaged statement forces anyway",
    ),
    _field(
        "debit",
        ValueKind.MONEY,
        describes="money leaving the account, used only to tell a withdrawal line "
        "from a credit line",
        aliases="debit debit_amount debit_amt withdrawal withdrawal_amt dr "
        "money_out outflow payment",
        costs="lines with no credit amount are dropped on that basis alone",
    ),
)


SETTLEMENT_ROW_FIELDS: tuple[TargetField, ...] = (
    _field(
        "entity_id",
        ValueKind.IDENTIFIER,
        required=True,
        describes="the id of the payment, refund or adjustment this row is about",
        aliases="entity_id id record_id entity txn_id transaction_id reference_id",
    ),
    _field(
        "type",
        ValueKind.ENTITY_TYPE,
        required=True,
        describes="payment, refund, adjustment or transfer",
        aliases="type entity_type record_type txn_type transaction_type category",
    ),
    _field(
        "amount",
        ValueKind.MONEY,
        required=True,
        describes="the gross amount of this row before fees",
        aliases="amount gross gross_amount transaction_amount txn_amount value",
    ),
    _field(
        "credit",
        ValueKind.MONEY,
        required=True,
        describes="what this row adds to the payout, zero on a refund or adjustment",
        aliases="credit credit_amount cr amount_credited",
    ),
    _field(
        "debit",
        ValueKind.MONEY,
        required=True,
        describes="what this row takes off the payout, zero on a payment",
        aliases="debit debit_amount dr amount_debited",
    ),
    _field(
        "fee",
        ValueKind.MONEY,
        required=True,
        describes="the gateway's fee on this row, before tax",
        aliases="fee fees commission mdr gateway_fee charge charges processing_fee service_charge",
    ),
    _field(
        "tax",
        ValueKind.MONEY,
        required=True,
        describes="GST charged on the fee",
        aliases="tax gst gst_on_fee gst_amount service_tax tax_amount igst cgst_sgst",
    ),
    _field(
        "created_at",
        ValueKind.TEMPORAL,
        required=True,
        describes="when the payment or refund happened",
        aliases="created_at created created_on txn_date transaction_date date "
        "creation_date created_date",
    ),
    _field(
        "settlement_id",
        ValueKind.IDENTIFIER,
        required=True,
        describes="which payout batch this row was paid out in",
        aliases="settlement_id payout_id batch_id settlement payout batch settlement_ref",
    ),
    _field(
        "settled_at",
        ValueKind.TEMPORAL,
        required=True,
        describes="when the payout batch left the gateway",
        aliases="settled_at settlement_date settled_on settled_date payout_date "
        "credit_date settlement_time",
    ),
    # Required rather than optional, and it was optional first. A batch is
    # rebuilt from the rows that share a settlement id, and a batch with no
    # date is dropped - so a report imported without this column produces
    # zero batches, every bank credit falls through the whole cascade, and the
    # run reports total failure with nothing on screen to say why. There is no
    # degraded mode here to describe in `costs`.
    _field(
        "settlement_utr",
        ValueKind.IDENTIFIER,
        describes="the bank reference the gateway says it paid under - the join "
        "to the bank statement",
        aliases="settlement_utr utr payout_utr bank_ref bank_reference rrn "
        "settlement_reference utr_number",
        costs="the exact-reference rung of the cascade has nothing to match on, "
        "so every credit falls through to amount and date",
    ),
    _field(
        "payment_id",
        ValueKind.IDENTIFIER,
        describes="the payment a refund or adjustment was taken against",
        aliases="payment_id payment parent_payment_id source_payment_id",
        costs="refunds cannot be traced back to the sale they reverse",
    ),
    _field(
        "order_id",
        ValueKind.IDENTIFIER,
        describes="the order behind this row",
        aliases="order_id order sale_id",
    ),
    _field(
        "order_receipt",
        ValueKind.TEXT,
        describes="the merchant's own reference for the order",
        aliases="order_receipt receipt receipt_no invoice_no invoice_number merchant_reference",
    ),
    _field(
        "method",
        ValueKind.PAYMENT_METHOD,
        describes="card, upi, netbanking, wallet, emi or paylater",
        aliases="method payment_method mode payment_mode instrument",
    ),
    _field(
        "card_type",
        ValueKind.CARD_TYPE,
        describes="domestic consumer, domestic corporate or international - "
        "this is what sets the fee rate",
        aliases="card_type card_category card_class",
        costs="fee leaks caused by a card being billed at the wrong rate cannot "
        "be attributed to a card class",
    ),
    _field(
        "card_network",
        ValueKind.TEXT,
        describes="Visa, Mastercard, RuPay and so on",
        aliases="card_network network scheme card_scheme",
    ),
    _field(
        "card_issuer",
        ValueKind.TEXT,
        describes="the issuing bank's code",
        aliases="card_issuer issuer issuing_bank bank issuer_bank",
    ),
    _field(
        "dispute_id",
        ValueKind.IDENTIFIER,
        describes="the chargeback case, on adjustment rows",
        aliases="dispute_id dispute chargeback_id case_id",
    ),
    _field(
        "on_hold",
        ValueKind.BOOLEAN,
        describes="whether the gateway is holding this row back",
        aliases="on_hold hold held is_on_hold",
    ),
    _field(
        "settled",
        ValueKind.BOOLEAN,
        describes="whether this row has been paid out",
        aliases="settled is_settled settlement_status paid_out",
    ),
    _field(
        "currency",
        ValueKind.TEXT,
        describes="the currency code, if the file is not all rupees",
        aliases="currency ccy currency_code",
    ),
)


PAYMENT_FIELDS: tuple[TargetField, ...] = (
    _field(
        "payment_id",
        ValueKind.IDENTIFIER,
        required=True,
        describes="the id of the captured payment",
        aliases="payment_id id payment txn_id transaction_id",
    ),
    _field(
        "order_id",
        ValueKind.IDENTIFIER,
        required=True,
        describes="the order it was captured against",
        aliases="order_id order sale_id",
    ),
    _field(
        "amount",
        ValueKind.MONEY,
        required=True,
        describes="what was captured",
        aliases="amount gross gross_amount transaction_amount value paid",
    ),
    _field(
        "captured_at",
        ValueKind.TEMPORAL,
        required=True,
        describes="when it was captured",
        aliases="captured_at captured captured_on payment_date created_at date "
        "txn_date transaction_date",
    ),
    _field(
        "method",
        ValueKind.PAYMENT_METHOD,
        describes="card, upi, netbanking, wallet, emi or paylater",
        aliases="method payment_method mode payment_mode instrument",
        costs="every payment is read as a card payment, which is the slowest "
        "settlement cycle and so the most forgiving assumption",
    ),
    _field(
        "card_type",
        ValueKind.CARD_TYPE,
        describes="domestic consumer, domestic corporate or international",
        aliases="card_type card_category card_class",
        costs="international payments will be judged against the domestic T+2 "
        "cycle rather than T+7, and may be raised as late when they are not",
    ),
    _field(
        "card_network",
        ValueKind.TEXT,
        describes="Visa, Mastercard, RuPay and so on",
        aliases="card_network network scheme card_scheme",
    ),
)


ORDER_FIELDS: tuple[TargetField, ...] = (
    _field(
        "order_id",
        ValueKind.IDENTIFIER,
        required=True,
        describes="the id of the order",
        aliases="order_id id order sale_id",
    ),
    _field(
        "amount",
        ValueKind.MONEY,
        required=True,
        describes="what the order was for",
        aliases="amount gross gross_amount order_amount value total",
    ),
    _field(
        "created_at",
        ValueKind.TEMPORAL,
        required=True,
        describes="when the order was placed",
        aliases="created_at created created_on order_date date placed_at",
    ),
    _field(
        "order_receipt",
        ValueKind.TEXT,
        describes="the merchant's own reference",
        aliases="order_receipt receipt receipt_no invoice_no invoice_number "
        "merchant_reference reference",
    ),
    _field(
        "currency",
        ValueKind.TEXT,
        describes="the currency code",
        aliases="currency ccy currency_code",
    ),
)


TARGETS: dict[RecordKind, tuple[TargetField, ...]] = {
    RecordKind.ORDERS: ORDER_FIELDS,
    RecordKind.PAYMENTS: PAYMENT_FIELDS,
    RecordKind.SETTLEMENT_ROWS: SETTLEMENT_ROW_FIELDS,
    RecordKind.BANK_CREDITS: BANK_CREDIT_FIELDS,
}


def fields_of(kind: RecordKind) -> tuple[TargetField, ...]:
    return TARGETS[kind]


def field_named(kind: RecordKind, name: str) -> TargetField | None:
    return next((field for field in TARGETS[kind] if field.name == name), None)


def required_of(kind: RecordKind) -> tuple[TargetField, ...]:
    return tuple(field for field in TARGETS[kind] if field.required)
