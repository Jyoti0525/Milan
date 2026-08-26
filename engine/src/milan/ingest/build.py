"""Turning a confirmed mapping into records the engine already knows.

Nothing here decides anything. Every column has been settled by the time this
runs, so this module's whole job is coercion and refusal: read the value under
the mapped column, and if it will not read, drop the row and say which line it
was on.

Dropping is the point. A reconciliation built on rows that were silently
repaired is a reconciliation whose input nobody can check, and the merchant
who wants to know why their total is four rupees light has no way back to the
cell that caused it. So every dropped row carries its file, its line number
and the reason, and the count is printed before the run rather than buried.

Two coercion rules are worth stating because they differ, and the difference
is deliberate:

  - A blank **fee, tax, debit or credit** is zero. A settlement report leaves
    the debit column empty on every payment row, and reading that as missing
    would drop the whole file.
  - A blank **bank credit amount** is not zero, it is a line that is not a
    credit. Reading it as zero would invent a nil payout for every withdrawal
    the merchant made that month.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from milan.domain.enums import EntityType, PaymentMethod
from milan.domain.money import ZERO, Paise
from milan.domain.records import BankCredit, Order, Payment, SettlementRow
from milan.ingest import parsing
from milan.ingest.plan import FileMapping, IngestPlan
from milan.ingest.schema import RecordKind
from milan.recon.inputs import ReconInput


class NotReadyError(RuntimeError):
    """The plan still has open questions or a missing file."""


@dataclass(frozen=True, slots=True)
class Dropped:
    """One row that would not read, and where to find it."""

    file: str
    line: int
    reason: str


@dataclass(frozen=True, slots=True)
class Imported:
    """What came out of a folder, and what did not."""

    data: ReconInput
    dropped: tuple[Dropped, ...]
    withdrawals: int
    """Bank statement lines that were debits rather than credits. Not dropped
    rows - money leaving the account is not an error, it is simply not what a
    settlement reconciliation is about. Counted so the row totals add up."""

    counts: dict[str, int]


class _Row:
    """One source row, read through its file's mapping."""

    def __init__(self, mapping: FileMapping, row: dict[str, str], line: int) -> None:
        self._columns = mapping.columns
        self._patterns = mapping.patterns
        self._row = row
        self.line = line

    def has(self, field: str) -> bool:
        return field in self._columns

    def raw(self, field: str) -> str:
        column = self._columns.get(field)
        return self._row.get(column, "").strip() if column else ""

    def money(self, field: str) -> Paise | None:
        return parsing.parse_money(self.raw(field))

    def money_or_zero(self, field: str) -> Paise:
        value = self.money(field)
        return value if value is not None else ZERO

    def moment(self, field: str) -> datetime | None:
        column = self._columns.get(field)
        if column is None:
            return None
        return parsing.parse_temporal(self._row.get(column, ""), self._patterns.get(field, ""))

    def text(self, field: str) -> str | None:
        value = self.raw(field)
        return value or None

    def flag(self, field: str, default: bool) -> bool:
        value = parsing.parse_bool(self.raw(field))
        return default if value is None else value


def _cursor(mapping: FileMapping) -> list[_Row]:
    """Every row of a file, each carrying the line it was actually read from.

    The line number is tracked through the reader rather than counted here.
    Blank lines inside a statement are skipped on the way in, so a row's
    position in the list stops matching its position in the file the moment
    one appears - and the whole reason to report a line number is that
    somebody is going to open the file and look at it.
    """
    return [
        _Row(mapping, row, line)
        for row, line in zip(mapping.source.rows, mapping.source.line_numbers, strict=True)
    ]


# ---------------------------------------------------------------- the files


def _bank_credits(
    mapping: FileMapping, dropped: list[Dropped], sequence: int
) -> tuple[tuple[BankCredit, ...], int, int]:
    credits: list[BankCredit] = []
    withdrawals = 0

    for cursor in _cursor(mapping):
        line = cursor.line
        amount = cursor.money("amount")

        if amount is None or amount == 0:
            if cursor.has("debit") and cursor.money("debit"):
                withdrawals += 1
            else:
                dropped.append(Dropped(mapping.name, line, "no credit amount on this line"))
            continue
        if amount < 0:
            withdrawals += 1
            continue

        moment = cursor.moment("value_date")
        if moment is None:
            dropped.append(
                Dropped(mapping.name, line, f"unreadable date {cursor.raw('value_date')!r}")
            )
            continue

        sequence += 1
        credits.append(
            BankCredit(
                credit_id=f"bank_{sequence:05d}",
                amount=amount,
                value_date=moment.date(),
                narration=cursor.raw("narration"),
                utr=cursor.text("utr"),
            )
        )
    return tuple(credits), withdrawals, sequence


def _derive_sides(cursor: _Row, kind: EntityType, gross: Paise) -> tuple[Paise, Paise]:
    """Split a single signed amount into a debit and a credit.

    Sign wins where there is one, because a report that bothered to write a
    minus meant it. Where the amount is unsigned the row type decides: a
    payment adds to the payout and everything else takes off it, which is what
    `debit` and `credit` mean in a settlement report.
    """
    if gross < 0:
        return Paise(-gross), ZERO
    if kind is EntityType.PAYMENT:
        return ZERO, gross
    return gross, ZERO


def _settlement_rows(mapping: FileMapping, dropped: list[Dropped]) -> tuple[SettlementRow, ...]:
    rows: list[SettlementRow] = []
    derive = "credit" in mapping.derived or "debit" in mapping.derived

    for cursor in _cursor(mapping):
        line = cursor.line

        entity_id = cursor.text("entity_id")
        if entity_id is None:
            dropped.append(Dropped(mapping.name, line, "no entity id"))
            continue

        kind = parsing.parse_entity_type(cursor.raw("type"))
        if kind is None:
            dropped.append(Dropped(mapping.name, line, f"unrecognised type {cursor.raw('type')!r}"))
            continue

        gross = cursor.money("amount")
        if gross is None:
            dropped.append(
                Dropped(mapping.name, line, f"unreadable amount {cursor.raw('amount')!r}")
            )
            continue

        created = cursor.moment("created_at")
        if created is None:
            dropped.append(
                Dropped(mapping.name, line, f"unreadable date {cursor.raw('created_at')!r}")
            )
            continue

        if derive:
            debit, credit = _derive_sides(cursor, kind, gross)
        else:
            debit, credit = cursor.money_or_zero("debit"), cursor.money_or_zero("credit")

        rows.append(
            SettlementRow(
                entity_id=entity_id,
                type=kind,
                debit=debit,
                credit=credit,
                amount=Paise(abs(gross)),
                currency=cursor.text("currency") or "INR",
                fee=cursor.money_or_zero("fee"),
                tax=cursor.money_or_zero("tax"),
                on_hold=cursor.flag("on_hold", False),
                settled=cursor.flag("settled", True),
                created_at=created,
                settled_at=cursor.moment("settled_at"),
                settlement_id=cursor.text("settlement_id"),
                settlement_utr=cursor.text("settlement_utr"),
                order_id=cursor.text("order_id"),
                order_receipt=cursor.text("order_receipt"),
                payment_id=cursor.text("payment_id"),
                method=parsing.parse_method(cursor.raw("method")),
                card_network=cursor.text("card_network"),
                card_issuer=cursor.text("card_issuer"),
                card_type=parsing.parse_card_type(cursor.raw("card_type")),
                dispute_id=cursor.text("dispute_id"),
            )
        )
    return tuple(rows)


def _payments(mapping: FileMapping, dropped: list[Dropped]) -> tuple[Payment, ...]:
    payments: list[Payment] = []
    for cursor in _cursor(mapping):
        line = cursor.line
        payment_id, order_id = cursor.text("payment_id"), cursor.text("order_id")
        amount, captured = cursor.money("amount"), cursor.moment("captured_at")

        if payment_id is None or order_id is None or amount is None or captured is None:
            dropped.append(Dropped(mapping.name, line, "missing an id, an amount or a date"))
            continue

        payments.append(
            Payment(
                payment_id=payment_id,
                order_id=order_id,
                amount=amount,
                # Falls back to card, which is the T+7-eligible method and so
                # the most forgiving assumption about when money was due. A
                # guess that raises fewer exceptions is the right way round
                # for a guess to be wrong.
                method=parsing.parse_method(cursor.raw("method")) or PaymentMethod.CARD,
                card_type=parsing.parse_card_type(cursor.raw("card_type")),
                card_network=cursor.text("card_network"),
                captured_at=captured,
            )
        )
    return tuple(payments)


def _orders(mapping: FileMapping, dropped: list[Dropped]) -> tuple[Order, ...]:
    orders: list[Order] = []
    for cursor in _cursor(mapping):
        line = cursor.line
        order_id = cursor.text("order_id")
        amount, created = cursor.money("amount"), cursor.moment("created_at")

        if order_id is None or amount is None or created is None:
            dropped.append(Dropped(mapping.name, line, "missing an id, an amount or a date"))
            continue

        orders.append(
            Order(
                order_id=order_id,
                order_receipt=cursor.text("order_receipt") or order_id,
                amount=amount,
                currency=cursor.text("currency") or "INR",
                created_at=created,
            )
        )
    return tuple(orders)


def build(plan: IngestPlan) -> Imported:
    """Read every placed file into the engine's own records.

    Refuses on an unready plan rather than importing what it can. A partial
    reconciliation looks exactly like a complete one on screen, and the
    difference is the entire value of the output.
    """
    blockers = plan.blockers()
    if blockers:
        raise NotReadyError("; ".join(blockers))

    dropped: list[Dropped] = []
    orders: list[Order] = []
    payments: list[Payment] = []
    settlement_rows: list[SettlementRow] = []
    credits: list[BankCredit] = []
    withdrawals = 0
    sequence = 0

    for mapping in plan.all_of(RecordKind.ORDERS):
        orders.extend(_orders(mapping, dropped))
    for mapping in plan.all_of(RecordKind.PAYMENTS):
        payments.extend(_payments(mapping, dropped))
    for mapping in plan.all_of(RecordKind.SETTLEMENT_ROWS):
        settlement_rows.extend(_settlement_rows(mapping, dropped))
    for mapping in plan.all_of(RecordKind.BANK_CREDITS):
        found, skipped, sequence = _bank_credits(mapping, dropped, sequence)
        credits.extend(found)
        withdrawals += skipped

    data = ReconInput(
        orders=tuple(orders),
        payments=tuple(payments),
        settlement_rows=tuple(settlement_rows),
        bank_credits=tuple(credits),
    )
    return Imported(
        data=data,
        dropped=tuple(dropped),
        withdrawals=withdrawals,
        counts={
            "orders": len(orders),
            "payments": len(payments),
            "settlement_rows": len(settlement_rows),
            "bank_credits": len(credits),
        },
    )


def unmapped_card_types(data: ReconInput) -> bool:
    """Whether any settlement row carries a card type.

    Read by the caller to decide whether to warn that fee-rate leaks cannot
    be attributed. A file with no card type column still reconciles; it just
    cannot say a corporate card was billed at the international rate.
    """
    return not any(row.card_type is not None for row in data.settlement_rows)
