"""The Chaos Engine.

Generates a merchant's month: orders, the payments against them, the refunds
and chargebacks that follow, the gateway's settlement batches, and the bank
credits that eventually arrive - together with the answer key that says what
was really behind each credit.

Two properties matter more than realism:

1. **It is seeded.** The same seed produces identical output. Seeded is not
   the same as easy: ADVERSARIAL is exactly as reproducible as CLEAN.
2. **The answer key is produced by construction, not by inference.** Truth is
   recorded as each batch is assembled. Nothing here ever runs the matcher to
   decide what the right answer was, which is why the answer key is evidence
   rather than a second opinion.

Randomness comes from one `random.Random` instance and nothing else. No
`uuid4`, no clock reads, no set iteration order - any of those would break
reproducibility in ways that only show up on someone else's machine.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from milan.chaos.config import GenerationConfig
from milan.domain.calendar import (
    DOMESTIC_SETTLEMENT_DAYS,
    INTERNATIONAL_SETTLEMENT_DAYS,
    REFUND_CLEARING_DAYS_MAX,
    REFUND_CLEARING_DAYS_MIN,
    add_working_days,
)
from milan.domain.dataset import Dataset
from milan.domain.enums import CardType, EntityType, PaymentMethod
from milan.domain.money import ZERO, Paise, apply_rate, from_rupees
from milan.domain.rates import compute_deductions
from milan.domain.records import (
    Adjustment,
    BankCredit,
    Order,
    Payment,
    Refund,
    Settlement,
    SettlementRow,
)
from milan.domain.truth import AnswerKey, CreditTruth, LeakTruth

_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
_UTR_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

_CARD_NETWORKS = ("Visa", "MasterCard", "RuPay", "Amex")

_METHOD_WEIGHTS: dict[PaymentMethod, int] = {
    PaymentMethod.UPI: 46,
    PaymentMethod.CARD: 32,
    PaymentMethod.NETBANKING: 12,
    PaymentMethod.WALLET: 6,
    PaymentMethod.EMI: 3,
    PaymentMethod.PAYLATER: 1,
}

_SETTLEMENT_HOUR = time(11, 0)


@dataclass(slots=True)
class _Debit:
    """A refund or chargeback waiting to be recovered from a future batch."""

    entity_id: str
    kind: EntityType
    amount: Paise
    created_at: datetime
    clearing_date: date
    payment_id: str | None
    dispute_id: str | None = None


@dataclass(slots=True)
class _Batch:
    """A settlement batch under construction."""

    settle_date: date
    settlement_id: str
    utr: str
    payments: list[Payment]
    gross_total: Paise = ZERO
    fee_total: Paise = ZERO
    tax_row_total: Paise = ZERO
    tds_total: Paise = ZERO
    net_total: Paise = ZERO
    debits: list[_Debit] = field(default_factory=list)


class ChaosEngine:
    """Produces one reproducible dataset from one config."""

    def __init__(self, config: GenerationConfig) -> None:
        self._config = config
        self._rng = random.Random(config.seed)
        self._issued: set[str] = set()

    # ---------------------------------------------------------------- public

    def generate(self) -> Dataset:
        orders = self._draw_orders()
        payments = self._draw_payments(orders)
        refunds = self._draw_refunds(payments)
        adjustments = self._draw_adjustments(payments)

        batches, rows, leaks = self._assemble(orders, payments, refunds, adjustments)
        settlements = self._finalise_settlements(batches, rows)
        credits, truths, missing = self._emit_bank_credits(batches, settlements)

        return Dataset(
            seed=self._config.seed,
            difficulty=self._config.difficulty.value,
            orders=tuple(orders),
            payments=tuple(payments),
            refunds=tuple(refunds),
            adjustments=tuple(adjustments),
            settlement_rows=tuple(rows),
            settlements=tuple(settlements),
            bank_credits=tuple(credits),
            answer_key=AnswerKey(
                seed=self._config.seed,
                credits=tuple(truths),
                missing_settlement_ids=tuple(missing),
                leaks=tuple(leaks),
            ),
        )

    # ------------------------------------------------------------ primitives

    def _token(self, length: int, alphabet: str = _ID_ALPHABET) -> str:
        while True:
            token = "".join(self._rng.choice(alphabet) for _ in range(length))
            if token not in self._issued:
                self._issued.add(token)
                return token

    def _identifier(self, prefix: str) -> str:
        return f"{prefix}_{self._token(14)}"

    def _utr(self) -> str:
        return self._token(12, _UTR_ALPHABET)

    def _timestamp(self, day: date) -> datetime:
        """A plausible time of day. Shopping skews to the evening."""
        hour = self._rng.choices(
            population=list(range(7, 24)),
            weights=[1, 2, 3, 4, 5, 5, 6, 6, 5, 5, 6, 8, 10, 12, 11, 8, 4],
            k=1,
        )[0]
        return datetime.combine(day, time(hour, self._rng.randrange(60), self._rng.randrange(60)))

    def _draw_amount(self) -> Paise:
        """A long-tailed order value: many small baskets, a few large ones."""
        low = self._config.min_amount_rupees
        high = self._config.max_amount_rupees
        while True:
            rupees = Decimal(str(round(self._rng.lognormvariate(7.3, 1.05), 2)))
            if low <= rupees <= high:
                break
        # Real baskets cluster on round numbers more than a lognormal does.
        if self._rng.random() < 0.35:
            rupees = Decimal(int(rupees))
        return from_rupees(rupees)

    # ----------------------------------------------------------------- steps

    def _draw_orders(self) -> list[Order]:
        start = date.fromisoformat(self._config.start_date)
        orders: list[Order] = []
        for index in range(self._config.order_count):
            day = start + timedelta(days=self._rng.randrange(self._config.span_days))
            orders.append(
                Order(
                    order_id=self._identifier("order"),
                    order_receipt=f"INV-2026-{index + 1:05d}",
                    amount=self._draw_amount(),
                    created_at=self._timestamp(day),
                )
            )
        orders.sort(key=lambda order: (order.created_at, order.order_id))
        return orders

    def _draw_payments(self, orders: list[Order]) -> list[Payment]:
        """Capture most orders. The rest are abandoned carts.

        An unpaid order is not a defect - it is the ordinary case that a
        matcher must not mistake for a missing settlement.
        """
        payments: list[Payment] = []
        for order in orders:
            if self._rng.random() < self._config.unpaid_probability:
                continue
            method = self._rng.choices(
                population=list(_METHOD_WEIGHTS),
                weights=list(_METHOD_WEIGHTS.values()),
                k=1,
            )[0]
            card_type: CardType | None = None
            network: str | None = None
            if method in (PaymentMethod.CARD, PaymentMethod.EMI):
                card_type = self._draw_card_type()
                network = self._rng.choice(_CARD_NETWORKS)
            # Capture normally follows checkout within the hour.
            captured = order.created_at + timedelta(minutes=self._rng.randrange(1, 55))
            payments.append(
                Payment(
                    payment_id=self._identifier("pay"),
                    order_id=order.order_id,
                    amount=order.amount,
                    method=method,
                    card_type=card_type,
                    card_network=network,
                    captured_at=captured,
                )
            )
        return payments

    def _draw_card_type(self) -> CardType:
        roll = self._rng.random()
        international = self._config.international_probability
        corporate = self._config.corporate_card_probability
        if roll < international:
            return CardType.INTERNATIONAL
        if roll < international + corporate:
            return CardType.DOMESTIC_CORPORATE
        return CardType.DOMESTIC_CONSUMER

    def _draw_refunds(self, payments: list[Payment]) -> list[Refund]:
        refunds: list[Refund] = []
        for payment in payments:
            if self._rng.random() >= self._config.refund_probability:
                continue
            raised = payment.captured_at + timedelta(days=self._rng.randrange(1, 9))
            refunds.append(
                Refund(
                    refund_id=self._identifier("rfnd"),
                    payment_id=payment.payment_id,
                    amount=payment.amount,
                    created_at=raised,
                )
            )
        return refunds

    def _draw_adjustments(self, payments: list[Payment]) -> list[Adjustment]:
        adjustments: list[Adjustment] = []
        for payment in payments:
            if self._rng.random() >= self._config.chargeback_probability:
                continue
            raised = payment.captured_at + timedelta(days=self._rng.randrange(6, 25))
            adjustments.append(
                Adjustment(
                    adjustment_id=self._identifier("adj"),
                    payment_id=payment.payment_id,
                    amount=payment.amount,
                    reason="chargeback",
                    created_at=raised,
                )
            )
        return adjustments

    # ------------------------------------------------------------- assembly

    def _assemble(
        self,
        orders: list[Order],
        payments: list[Payment],
        refunds: list[Refund],
        adjustments: list[Adjustment],
    ) -> tuple[list[_Batch], list[SettlementRow], list[LeakTruth]]:
        """Group payments into batches and recover debits from later ones.

        This is where the deduction waterfall is applied per transaction, and
        where a merchant can be charged at a rate they never agreed to.
        """
        receipts = {order.order_id: order.order_receipt for order in orders}
        grouped = self._group_by_settlement_date(payments)

        batches: list[_Batch] = []
        rows: list[SettlementRow] = []
        leaks: list[LeakTruth] = []

        for settle_date in sorted(grouped):
            batch = _Batch(
                settle_date=settle_date,
                settlement_id=self._identifier("setl"),
                utr=self._utr(),
                payments=sorted(grouped[settle_date], key=lambda payment: payment.payment_id),
            )
            for payment in batch.payments:
                row, leak = self._settle_payment(batch, payment, receipts)
                rows.append(row)
                if leak is not None:
                    leaks.append(leak)
            batches.append(batch)

        pending = self._pending_debits(refunds, adjustments)
        rows.extend(self._recover_debits(batches, pending))
        return batches, rows, leaks

    def _group_by_settlement_date(self, payments: list[Payment]) -> dict[date, list[Payment]]:
        """T+2 working days domestic, T+7 international."""
        grouped: dict[date, list[Payment]] = defaultdict(list)
        for payment in payments:
            lag = (
                INTERNATIONAL_SETTLEMENT_DAYS
                if payment.card_type is CardType.INTERNATIONAL
                else DOMESTIC_SETTLEMENT_DAYS
            )
            grouped[add_working_days(payment.captured_at.date(), lag)].append(payment)
        return grouped

    def _settle_payment(
        self, batch: _Batch, payment: Payment, receipts: dict[str, str]
    ) -> tuple[SettlementRow, LeakTruth | None]:
        """Deduct fee, GST and any withholding from one payment.

        When a rate mismatch is injected the batch still balances perfectly.
        That is the entire point: this class of error is invisible to a
        matcher, because there is nothing unmatched to notice.
        """
        rates = self._config.rates
        charged_type = payment.card_type
        overcharged = (
            payment.method is PaymentMethod.CARD
            and charged_type is CardType.DOMESTIC_CONSUMER
            and self._rng.random() < self._config.defects.rate_mismatch
        )
        if overcharged:
            charged_type = CardType.DOMESTIC_CORPORATE

        charged = compute_deductions(payment.amount, payment.method, charged_type, rates)

        leak: LeakTruth | None = None
        if overcharged:
            contracted = compute_deductions(
                payment.amount, payment.method, payment.card_type, rates
            )
            leak = LeakTruth(
                payment_id=payment.payment_id,
                settlement_id=batch.settlement_id,
                contracted_fee=contracted.fee,
                charged_fee=charged.fee,
            )

        batch.gross_total = Paise(batch.gross_total + charged.gross)
        batch.fee_total = Paise(batch.fee_total + charged.fee)
        batch.tax_row_total = Paise(batch.tax_row_total + charged.tax)
        batch.tds_total = Paise(batch.tds_total + charged.tds)
        batch.net_total = Paise(batch.net_total + charged.net)

        row = SettlementRow(
            entity_id=payment.payment_id,
            type=EntityType.PAYMENT,
            debit=Paise(0),
            credit=charged.net,
            amount=payment.amount,
            fee=charged.fee,
            tax=charged.tax,
            created_at=payment.captured_at,
            settled_at=datetime.combine(batch.settle_date, _SETTLEMENT_HOUR),
            settlement_id=batch.settlement_id,
            settlement_utr=batch.utr,
            order_id=payment.order_id,
            order_receipt=receipts.get(payment.order_id),
            payment_id=payment.payment_id,
            method=payment.method,
            card_network=payment.card_network,
            card_type=payment.card_type,
        )
        return row, leak

    def _pending_debits(self, refunds: list[Refund], adjustments: list[Adjustment]) -> list[_Debit]:
        """Work out when each refund and chargeback becomes recoverable."""
        pending: list[_Debit] = []
        for refund in refunds:
            lag = self._rng.randint(REFUND_CLEARING_DAYS_MIN, REFUND_CLEARING_DAYS_MAX)
            pending.append(
                _Debit(
                    entity_id=refund.refund_id,
                    kind=EntityType.REFUND,
                    amount=refund.amount,
                    created_at=refund.created_at,
                    clearing_date=add_working_days(refund.created_at.date(), lag),
                    payment_id=refund.payment_id,
                )
            )
        for adjustment in adjustments:
            pending.append(
                _Debit(
                    entity_id=adjustment.adjustment_id,
                    kind=EntityType.ADJUSTMENT,
                    amount=adjustment.amount,
                    created_at=adjustment.created_at,
                    clearing_date=add_working_days(adjustment.created_at.date(), 3),
                    payment_id=adjustment.payment_id,
                    dispute_id=self._identifier("disp"),
                )
            )
        pending.sort(key=lambda debit: (debit.clearing_date, debit.entity_id))
        return pending

    def _recover_debits(self, batches: list[_Batch], pending: list[_Debit]) -> list[SettlementRow]:
        """Net each debit into the first batch large enough to absorb it.

        A gateway does not send a negative payout, so a debit that would take
        a batch below zero rolls forward. A debit with no batch left to land
        in stays unsettled - a real state, and one a matcher has to tolerate
        rather than treat as a discrepancy.

        The consequence is the lag that makes this problem hard: a refund
        raised against a July sale is recovered from an August batch that has
        no other connection to it.
        """
        rows: list[SettlementRow] = []
        capacity = {batch.settlement_id: batch.net_total for batch in batches}

        for debit in pending:
            landed = self._land_debit(batches, capacity, debit)
            if landed is not None:
                landed.debits.append(debit)
            rows.append(
                SettlementRow(
                    entity_id=debit.entity_id,
                    type=debit.kind,
                    debit=debit.amount,
                    credit=Paise(0),
                    amount=debit.amount,
                    fee=Paise(0),
                    tax=Paise(0),
                    settled=landed is not None,
                    created_at=debit.created_at,
                    settled_at=(
                        datetime.combine(landed.settle_date, _SETTLEMENT_HOUR) if landed else None
                    ),
                    settlement_id=landed.settlement_id if landed else None,
                    settlement_utr=landed.utr if landed else None,
                    payment_id=debit.payment_id,
                    dispute_id=debit.dispute_id,
                )
            )
        return rows

    def _land_debit(
        self, batches: list[_Batch], capacity: dict[str, Paise], debit: _Debit
    ) -> _Batch | None:
        for batch in batches:
            if batch.settle_date < debit.clearing_date:
                continue
            if capacity[batch.settlement_id] >= debit.amount:
                capacity[batch.settlement_id] = Paise(capacity[batch.settlement_id] - debit.amount)
                return batch
        return None

    def _finalise_settlements(
        self, batches: list[_Batch], rows: list[SettlementRow]
    ) -> list[Settlement]:
        """Close each batch and decide what the gateway actually pays.

        Fees are rounded per transaction; GST is charged once on the batch
        total. The two roundings disagree by paise, and that difference is
        carried into the payout rather than quietly discarded - which is why
        a report that foots perfectly can still differ from the bank.
        """
        by_settlement: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            if row.settlement_id is not None:
                by_settlement[row.settlement_id].append(row.entity_id)

        settlements: list[Settlement] = []
        for batch in batches:
            debit_total = Paise(sum(debit.amount for debit in batch.debits))
            batch_tax = self._batch_tax(batch)
            drift = Paise(batch.tax_row_total - batch_tax)
            settlements.append(
                Settlement(
                    settlement_id=batch.settlement_id,
                    settlement_utr=batch.utr,
                    amount=Paise(batch.net_total - debit_total + drift),
                    fee=batch.fee_total,
                    tax=batch_tax,
                    settled_at=datetime.combine(batch.settle_date, _SETTLEMENT_HOUR),
                    entity_ids=tuple(by_settlement[batch.settlement_id]),
                )
            )
        return settlements

    def _batch_tax(self, batch: _Batch) -> Paise:
        if not self._config.defects.batch_tax_rounding:
            return batch.tax_row_total
        return apply_rate(batch.fee_total, self._config.rates.gst)

    # --------------------------------------------------------- the bank side

    def _emit_bank_credits(
        self, batches: list[_Batch], settlements: list[Settlement]
    ) -> tuple[list[BankCredit], list[CreditTruth], list[str]]:
        """Turn settlements into what the bank statement actually shows.

        The bank knows an amount, a date and a narration string. Everything
        else - the orders, the fee, the GST - has to be proved from the other
        two files. Three things go wrong here, and all three are real: the
        UTR does not survive the narration, the payout never arrives, and a
        credit arrives that no settlement explains.
        """
        defects = self._config.defects
        by_id = {batch.settlement_id: batch for batch in batches}
        missing = self._choose_missing(settlements, defects.missing_credits)

        credits: list[BankCredit] = []
        truths: list[CreditTruth] = []

        for settlement in settlements:
            if settlement.settlement_id in missing:
                continue
            batch = by_id[settlement.settlement_id]
            corrupted = self._rng.random() < defects.utr_corrupted
            credit_id = self._identifier("bank")
            credits.append(
                BankCredit(
                    credit_id=credit_id,
                    amount=settlement.amount,
                    value_date=settlement.settled_at.date(),
                    narration=self._narration(settlement.settlement_utr, corrupted),
                    utr=None if corrupted else settlement.settlement_utr,
                )
            )
            truths.append(
                CreditTruth(
                    credit_id=credit_id,
                    settlement_id=settlement.settlement_id,
                    entity_ids=settlement.entity_ids,
                    gross=batch.gross_total,
                    fee=batch.fee_total,
                    tax=batch.tax_row_total,
                    tds=batch.tds_total,
                    adjustments=Paise(sum(debit.amount for debit in batch.debits)),
                    rounding_drift=Paise(batch.tax_row_total - settlement.tax),
                    matchable=True,
                    defect="UTR_CORRUPTED" if corrupted else None,
                )
            )

        credits, truths = self._inject_orphans(credits, truths, defects.orphan_credits)
        credits, truths = self._inject_duplicates(credits, truths, defects.ambiguous_pairs)

        order = {credit.credit_id: index for index, credit in enumerate(credits)}
        credits.sort(key=lambda credit: (credit.value_date, credit.credit_id))
        truths.sort(key=lambda truth: (order[truth.credit_id],))
        return credits, truths, sorted(missing)

    def _choose_missing(self, settlements: list[Settlement], count: int) -> set[str]:
        """Pick payouts that never reach the bank.

        Never the first batch: an opening batch that is simply absent is
        indistinguishable from a dataset that starts a day later, which would
        make the case unanswerable rather than hard.
        """
        eligible = [settlement.settlement_id for settlement in settlements[1:]]
        if not eligible or count <= 0:
            return set()
        return set(self._rng.sample(eligible, k=min(count, len(eligible))))

    def _narration(self, utr: str, corrupted: bool) -> str:
        """Bank narrations are free text, and the UTR does not always survive."""
        if corrupted:
            return self._rng.choice(
                (
                    "NEFT INWARD RAZORPAY SOFTWARE PVT LTD",
                    "IMPS/RZPY/SETTLEMENT",
                    "ACH C- RAZORPAYSOFTWARE",
                    "NEFT CR-RATN0000088-RAZORPAY-SETTLEMENT",
                )
            )
        return self._rng.choice(
            (
                f"NEFT-{utr}-RAZORPAY SOFTWARE PVT LTD",
                f"IMPS/{utr}/RAZORPAY/SETTLEMENT",
                f"UTR{utr} RAZORPAY PAYOUT",
            )
        )

    def _inject_orphans(
        self, credits: list[BankCredit], truths: list[CreditTruth], count: int
    ) -> tuple[list[BankCredit], list[CreditTruth]]:
        """Credits with nothing behind them.

        A direct customer transfer, a supplier refund, a loan disbursal.
        There is no settlement to find, so the only correct answer is to say
        so. These are marked unmatchable, and forcing a match onto one is
        scored as a false positive.
        """
        if count <= 0 or not credits:
            return credits, truths
        for _ in range(count):
            template = self._rng.choice(credits)
            credit_id = self._identifier("bank")
            credits.append(
                BankCredit(
                    credit_id=credit_id,
                    amount=self._draw_amount(),
                    value_date=template.value_date,
                    narration=self._rng.choice(
                        (
                            "NEFT INWARD MR RAJESH KUMAR",
                            "UPI/CR/SUPPLIER REFUND",
                            "NEFT CR-HDFC0000123-VENDOR ADVANCE",
                        )
                    ),
                    utr=None,
                )
            )
            truths.append(self._unmatchable(credit_id, "ORPHAN_CREDIT"))
        return credits, truths

    def _inject_duplicates(
        self, credits: list[BankCredit], truths: list[CreditTruth], count: int
    ) -> tuple[list[BankCredit], list[CreditTruth]]:
        """Two credits, same amount, same day, neither carrying a UTR.

        One is the real payout; the other is a duplicate the bank later
        reverses. With the UTR gone there is nothing left to tell them apart,
        so both are marked unmatchable. A system that confidently picks one is
        not being clever - it is guessing with a merchant's books.
        """
        if count <= 0:
            return credits, truths

        by_id = {truth.credit_id: truth for truth in truths}
        settled = [credit for credit in credits if by_id[credit.credit_id].settlement_id]
        if not settled:
            return credits, truths

        chosen_ids = {
            credit.credit_id for credit in self._rng.sample(settled, k=min(count, len(settled)))
        }

        rebuilt: list[BankCredit] = []
        for credit in credits:
            if credit.credit_id in chosen_ids:
                credit = credit.model_copy(
                    update={"utr": None, "narration": "NEFT INWARD RAZORPAY SOFTWARE PVT LTD"}
                )
                by_id[credit.credit_id] = by_id[credit.credit_id].model_copy(
                    update={"matchable": False, "defect": "AMBIGUOUS_DUPLICATE"}
                )
            rebuilt.append(credit)

        for credit in [c for c in rebuilt if c.credit_id in chosen_ids]:
            twin_id = self._identifier("bank")
            rebuilt.append(
                BankCredit(
                    credit_id=twin_id,
                    amount=credit.amount,
                    value_date=credit.value_date,
                    narration="NEFT INWARD RAZORPAY SOFTWARE PVT LTD",
                    utr=None,
                )
            )
            by_id[twin_id] = self._unmatchable(twin_id, "AMBIGUOUS_DUPLICATE")

        return rebuilt, [by_id[credit.credit_id] for credit in rebuilt]

    def _unmatchable(self, credit_id: str, defect: str) -> CreditTruth:
        return CreditTruth(
            credit_id=credit_id,
            settlement_id=None,
            entity_ids=(),
            gross=Paise(0),
            fee=Paise(0),
            tax=Paise(0),
            tds=Paise(0),
            adjustments=Paise(0),
            rounding_drift=Paise(0),
            matchable=False,
            defect=defect,
        )
