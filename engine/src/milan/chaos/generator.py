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

import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from statistics import NormalDist

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
_CARD_ISSUERS = ("HDFC", "ICIC", "SBIN", "UTIB", "KKBK", "IDFB", "YESB")
"""IFSC bank codes, as the issuer column actually reports them."""

_METHOD_WEIGHTS: dict[PaymentMethod, int] = {
    PaymentMethod.UPI: 46,
    PaymentMethod.CARD: 32,
    PaymentMethod.NETBANKING: 12,
    PaymentMethod.WALLET: 6,
    PaymentMethod.EMI: 3,
    PaymentMethod.PAYLATER: 1,
}

_SETTLEMENT_HOUR = time(11, 0)

_LOOKALIKES = {
    "O": "0",
    "0": "O",
    "I": "1",
    "1": "I",
    "S": "5",
    "5": "S",
    "B": "8",
    "8": "B",
    "Z": "2",
    "2": "Z",
}
"""Characters that get confused when a reference is read and re-typed. Not
invented: these are the pairs that collide in most sans-serif faces."""

_VARIANCE_KINDS = ("fee", "tax", "refund")

_UNFAMILIAR_KINDS = ("bank_charge", "fx_markup", "dispute_penalty", "promo_funding")
"""Shortfalls with no rule in `milan.recon.causes` written against them.

Chosen for their arithmetic rather than their story. Each one is a shape no
rule tests for - a constant number of paise, a rate that moves, a recovery
with nothing behind it, a rate over part of a batch - so a rule that names
one of these has matched on a coincidence rather than on evidence.

All four are ordinary things that happen to Indian merchants, which matters:
the test would prove nothing if these were absurd. They are simply four of
the many real mechanisms nobody got round to writing a rule for, standing in
for the ones a merchant will actually bring.
"""

_MERGEABLE_DEFECTS = frozenset({None, "UTR_CORRUPTED", "UTR_DAMAGED"})
"""What a credit may already be carrying and still be merged. Reference
defects, yes - a bank sweeping two transfers together does not care whether
it kept the reference. Orphans and duplicates, no: those are separate cases
and overlapping them would make each one impossible to attribute."""

_MERGE_SPAN_DAYS = 3
"""How far apart two payouts can be and still leave in the same transfer.
Three days covers a weekend. It is deliberately the same number the
matcher searches over: a generator that merged across a wider window than
any honest matcher would consider would be manufacturing failures rather
than difficulty."""


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
    fee: Paise = ZERO
    tax: Paise = ZERO

    @property
    def cash(self) -> Paise:
        """Everything this debit takes out of a payout, charges included."""
        return Paise(self.amount + self.fee + self.tax)


@dataclass(slots=True)
class _Batch:
    """A settlement batch under construction."""

    settle_date: date
    channel: str
    """Which payout run this is. A gateway settles on cut-offs and settles
    international cards separately, so one date carries several batches."""

    settlement_id: str
    utr: str
    payments: list[Payment]
    gross_total: Paise = ZERO
    fee_total: Paise = ZERO
    tax_row_total: Paise = ZERO
    tds_total: Paise = ZERO
    net_total: Paise = ZERO
    debits: list[_Debit] = field(default_factory=list)

    variance: Paise = ZERO
    """Money that left this batch which the report cannot account for.
    Signed: negative means the merchant received less than the rows say."""

    variance_kind: str | None = None


def _combined_defect(reference: str | None, variance: str | None) -> str | None:
    """Both, when both apply.

    A credit can lose its reference *and* be short by an undisclosed fee, and
    those two facts have different fixes. Recording only the first made the
    per-defect breakdown quietly wrong about which one was costing us.
    """
    parts = [part for part in (reference, variance) if part]
    return "+".join(parts) if parts else None


def _reference_defect(corrupted: bool, damaged: bool) -> str | None:
    if corrupted:
        return "UTR_CORRUPTED"
    return "UTR_DAMAGED" if damaged else None


_ORDER_VALUE = NormalDist(7.3, 1.05)
"""The distribution of ln(order value in rupees).

Median around Rs 1,480, with a long right tail - the shape of a real consumer
basket rather than a uniform draw, which matters because uniform amounts would
make every batch total distinctive and every match easy.
"""


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

        unreported = self._choose_unreported(payments, refunds, adjustments)
        batches, rows, leaks = self._assemble(orders, payments, refunds, adjustments, unreported)
        # Which payouts never arrive is decided before variances are placed.
        # A variance on a settlement nobody ever receives is unobservable: no
        # credit exists to be short, so the defect would be spent producing
        # nothing and the tier would silently inject fewer than it claims.
        missing = self._choose_missing(batches, self._config.defects.missing_credits)
        self._inject_payout_variances(batches, rows, missing)
        # After the familiar ones and only on what they left alone. Off in
        # every tier - reached by setting the knob explicitly, which only the
        # unfamiliar-defect measurement does.
        self._inject_unfamiliar_variances(batches, missing)
        settlements = self._finalise_settlements(batches, rows)
        credits, truths = self._emit_bank_credits(batches, settlements, missing)

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
                missing_settlement_ids=tuple(sorted(missing)),
                unreported_payment_ids=tuple(sorted(unreported)),
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
        """A long-tailed order value: many small baskets, a few large ones.

        Drawn by inverting the CDF over the merchant's price window rather
        than by drawing from the whole lognormal and rejecting what falls
        outside it. Rejection sampling was the obvious way to write this and
        it is unbounded: the cost is one over the acceptance probability, so
        a merchant with a narrow price range pays for it and a merchant with
        a single price never finishes at all. A single-price subscription
        merchant is not a hypothetical - it is the benchmark shape built
        specifically to make batch totals collide, and generating forty of
        its orders took twenty-two seconds and eleven million discarded
        samples.

        The distribution is unchanged in shape. A truncated lognormal is what
        the rejection loop was already producing; this is the same thing
        computed instead of searched for.
        """
        low = float(self._config.min_amount_rupees)
        high = float(self._config.max_amount_rupees)
        floor = _ORDER_VALUE.cdf(math.log(low))
        ceiling = _ORDER_VALUE.cdf(math.log(high))

        if ceiling <= floor:
            # One price, or a window too narrow for the distribution to
            # resolve. Both mean there is nothing to draw.
            rupees = self._config.min_amount_rupees
        else:
            drawn = math.exp(_ORDER_VALUE.inv_cdf(self._rng.uniform(floor, ceiling)))
            rupees = Decimal(str(round(min(max(drawn, low), high), 2)))

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

    def _issuer(self, network: str | None) -> str | None:
        """Only card rails have an issuing bank."""
        if network is None:
            return None
        return self._rng.choice(_CARD_ISSUERS)

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
        unreported: set[str],
    ) -> tuple[list[_Batch], list[SettlementRow], list[LeakTruth]]:
        """Group payments into batches and recover debits from later ones.

        This is where the deduction waterfall is applied per transaction, and
        where a merchant can be charged at a rate they never agreed to.
        """
        receipts = {order.order_id: order.order_receipt for order in orders}
        reported = [p for p in payments if p.payment_id not in unreported]
        grouped = self._group_into_batches(reported)

        batches: list[_Batch] = []
        rows: list[SettlementRow] = []
        leaks: list[LeakTruth] = []

        for settle_date, channel in sorted(grouped):
            batch = _Batch(
                settle_date=settle_date,
                channel=channel,
                settlement_id=self._identifier("setl"),
                utr=self._utr(),
                payments=sorted(
                    grouped[(settle_date, channel)], key=lambda payment: payment.payment_id
                ),
            )
            for payment in batch.payments:
                row, leak = self._settle_payment(batch, payment, receipts)
                rows.append(row)
                if leak is not None:
                    leaks.append(leak)
            batches.append(batch)

        rows.extend(self._route_transfers(batches))

        pending = self._pending_debits(refunds, adjustments)
        rows.extend(self._recover_debits(batches, pending))
        return batches, rows, leaks

    def _route_transfers(self, batches: list[_Batch]) -> list[SettlementRow]:
        """Split part of a payment on to a linked account, Route-style.

        Emitted into the same batch as the payment it comes from, which is
        what makes this different from a refund. A refund lands in whichever
        later batch is large enough to absorb it, so the batch it appears in
        has no other connection to the sale; a Route transfer leaves with the
        money it was taken from, because it is not a reversal of a sale but a
        share of one.

        The row carries the whole cash impact in `debit`, as every debit row
        here does, with the 0.1% commission and its GST broken out into `fee`
        and `tax`. That keeps `credit - debit` the row's true effect on the
        payout while leaving the charge visible as a charge.
        """
        share = self._config.route_probability
        if share <= 0.0:
            # No draw when the merchant has no linked accounts. Consuming
            # from the stream at a setting that means "this product is not in
            # use" would change every dataset this project has published.
            return []

        rates = self._config.rates
        rows: list[SettlementRow] = []
        for batch in batches:
            for payment in batch.payments:
                if self._rng.random() >= share:
                    continue
                transferred = apply_rate(payment.amount, self._config.route_share)
                if transferred <= 0:
                    continue
                fee = rates.route_fee(transferred)
                tax = apply_rate(fee, rates.gst)

                # The batch has this much less to pay out, from the moment the
                # transfer is taken. Emitting the row without this leaves the
                # report and the payout describing two different batches: the
                # rows subtract the transfer and the settlement amount does
                # not, so every affected credit comes up short by exactly the
                # amount routed and no rung can match it. Match rate fell to
                # 4.7% at a 60% Route share, with precision still at 100% -
                # the engine refusing rather than guessing, which is the
                # design working and is also why the bug looked like data.
                batch.net_total = Paise(batch.net_total - (transferred + fee + tax))

                rows.append(
                    SettlementRow(
                        entity_id=self._identifier("trf"),
                        type=EntityType.TRANSFER,
                        debit=Paise(transferred + fee + tax),
                        credit=Paise(0),
                        amount=transferred,
                        fee=fee,
                        tax=tax,
                        settled=True,
                        created_at=payment.captured_at,
                        settled_at=datetime.combine(batch.settle_date, _SETTLEMENT_HOUR),
                        settlement_id=batch.settlement_id,
                        settlement_utr=batch.utr,
                        payment_id=payment.payment_id,
                    )
                )
        return rows

    def _group_into_batches(self, payments: list[Payment]) -> dict[tuple[date, str], list[Payment]]:
        """T+2 working days domestic, T+7 international - and several a day.

        A payout run is a date *and* a cycle. International cards settle on
        their own cycle because they clear on their own timetable, and the
        domestic runs split on capture cut-offs.

        Doing this properly is what stops a batch total from being a unique
        fingerprint. One run a day gives twenty batches a month, each the sum
        of dozens of arbitrary order values, so no two ever collide and
        amount-plus-date is enough on its own. Several runs a day puts
        similar totals on the same date, which is the situation the later
        rungs exist for and which the day-one generator never produced.
        """
        grouped: dict[tuple[date, str], list[Payment]] = defaultdict(list)
        for payment in payments:
            international = payment.card_type is CardType.INTERNATIONAL
            if not international and self._instant_settlement():
                # Same day, and its own channel. Instant payouts do not join
                # a scheduled run - they leave when they are asked for, which
                # is what puts them on a date already carrying batches from
                # captures two working days older.
                grouped[(payment.captured_at.date(), "instant")].append(payment)
                continue
            lag = INTERNATIONAL_SETTLEMENT_DAYS if international else DOMESTIC_SETTLEMENT_DAYS
            settle_date = add_working_days(payment.captured_at.date(), lag)
            channel = "intl" if international else self._cycle(payment)
            grouped[(settle_date, channel)].append(payment)
        return grouped

    def _instant_settlement(self) -> bool:
        """Whether this payout was asked for in minutes rather than T+2.

        Drawn per payment rather than per merchant. A merchant with instant
        settlement enabled does not use it on everything - they use it when
        they need the cash - so a month containing both is the realistic
        shape, and it is also the harder one: a dataset that was entirely
        instant would simply shift every date by two days and change nothing
        about the matching.

        The zero check is not an optimisation. Drawing unconditionally
        consumes a number from the stream for every payment, which shifts
        every later draw and silently changes every dataset this project has
        ever published - at a setting that is supposed to mean "this merchant
        does not use the feature". Caught by the counts moving at
        `instant=0.0`, where by definition nothing should have moved.
        """
        share = self._config.instant_settlement_probability
        return share > 0.0 and self._rng.random() < share

    def _cycle(self, payment: Payment) -> str:
        """Which cut-off this capture fell before."""
        cycles = self._config.settlement_cycles
        index = min(payment.captured_at.hour * cycles // 24, cycles - 1)
        return f"cycle{index + 1}"

    def _choose_unreported(
        self, payments: list[Payment], refunds: list[Refund], adjustments: list[Adjustment]
    ) -> set[str]:
        """Payments the settlement report will never mention.

        Only payments with nothing else attached are eligible. A dropped
        payment that still had its refund sitting in the report would produce
        a debit for money the report never showed arriving, which is a
        different and much stranger defect than the one being modelled here.
        """
        rate = self._config.defects.unreported_payments
        if rate <= 0:
            return set()
        entangled = {refund.payment_id for refund in refunds} | {
            adjustment.payment_id for adjustment in adjustments
        }
        return {
            payment.payment_id
            for payment in payments
            if payment.payment_id not in entangled and self._rng.random() < rate
        }

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
            card_issuer=self._issuer(payment.card_network),
            card_type=payment.card_type,
        )
        return row, leak

    def _pending_debits(self, refunds: list[Refund], adjustments: list[Adjustment]) -> list[_Debit]:
        """Work out when each refund and chargeback becomes recoverable."""
        pending: list[_Debit] = []
        rates = self._config.rates
        for refund in refunds:
            # An instant refund clears the next working day rather than in
            # five to seven, and costs a flat fee to do it. Both halves of
            # that trade have to be modelled or the fee looks arbitrary.
            instant = self._rng.random() < self._config.instant_refund_probability
            lag = (
                1
                if instant
                else self._rng.randint(REFUND_CLEARING_DAYS_MIN, REFUND_CLEARING_DAYS_MAX)
            )
            fee = rates.instant_refund_fee(refund.amount) if instant else ZERO
            pending.append(
                _Debit(
                    entity_id=refund.refund_id,
                    kind=EntityType.REFUND,
                    amount=refund.amount,
                    created_at=refund.created_at,
                    clearing_date=add_working_days(refund.created_at.date(), lag),
                    payment_id=refund.payment_id,
                    fee=fee,
                    tax=apply_rate(fee, rates.gst) if instant else ZERO,
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
                    # The debit column is the whole cash impact, so that
                    # `credit - debit` stays the row's effect on the payout.
                    # The fee and tax columns break out what part of it was a
                    # charge rather than money returned to a customer.
                    debit=debit.cash,
                    credit=Paise(0),
                    amount=debit.amount,
                    fee=debit.fee,
                    tax=debit.tax,
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
            if capacity[batch.settlement_id] >= debit.cash:
                capacity[batch.settlement_id] = Paise(capacity[batch.settlement_id] - debit.cash)
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
            debit_total = Paise(sum(debit.cash for debit in batch.debits))
            batch_tax = self._batch_tax(batch)
            drift = Paise(batch.tax_row_total - batch_tax)
            settlements.append(
                Settlement(
                    settlement_id=batch.settlement_id,
                    settlement_utr=batch.utr,
                    amount=Paise(batch.net_total - debit_total + drift + batch.variance),
                    fee=batch.fee_total,
                    tax=batch_tax,
                    settled_at=datetime.combine(batch.settle_date, _SETTLEMENT_HOUR),
                    entity_ids=tuple(by_settlement[batch.settlement_id]),
                )
            )
        return settlements

    def _inject_payout_variances(
        self, batches: list[_Batch], rows: list[SettlementRow], missing: set[str]
    ) -> None:
        """Make some payouts disagree with the report that describes them.

        Every other defect in this file either leaves the arithmetic intact
        or removes a reference. This one breaks the arithmetic itself, which
        is the situation the deterministic categoriser exists for: the credit
        cannot be proved, so it must not be claimed, and the only useful
        output is an exception that says exactly how much is missing and
        which of the three ordinary causes fits.
        """
        count = self._config.defects.payout_variances
        eligible = [
            b for b in batches if b.payments and b.net_total > 0 and b.settlement_id not in missing
        ]
        if count <= 0 or not eligible:
            return

        chosen = self._rng.sample(eligible, k=min(count, len(eligible)))
        for index, batch in enumerate(chosen):
            # Cycled rather than drawn at random, so a tier that asks for
            # three variances gets one of each kind instead of whichever the
            # seed happened to pick. A defect class that appears only on some
            # seeds is a defect class that is tested only on some runs.
            kind = _VARIANCE_KINDS[index % len(_VARIANCE_KINDS)]
            if kind == "fee":
                batch.variance, batch.variance_kind = self._extra_fee(batch), "FEE"
            elif kind == "tax":
                batch.variance, batch.variance_kind = self._wrong_gst(batch), "TAX"
            else:
                batch.variance, batch.variance_kind = self._foreign_refund(batch, rows), "REFUND"

    def _inject_unfamiliar_variances(self, batches: list[_Batch], missing: set[str]) -> None:
        """Break some payouts in ways nothing was built to recognise.

        Runs after the ordinary variances and only on batches they left
        alone, so a shortfall is never two mechanisms at once - a mixed
        member would make a wrongly-named cause look like a fair call.
        """
        count = self._config.defects.unfamiliar_variances
        eligible = [
            b
            for b in batches
            if b.payments and b.net_total > 0 and b.variance == 0 and b.settlement_id not in missing
        ]
        if count <= 0 or not eligible:
            return

        for index, batch in enumerate(self._rng.sample(eligible, k=min(count, len(eligible)))):
            kind = _UNFAMILIAR_KINDS[index % len(_UNFAMILIAR_KINDS)]
            if kind == "bank_charge":
                batch.variance, batch.variance_kind = self._bank_charge(), "BANK_CHARGE"
            elif kind == "fx_markup":
                batch.variance, batch.variance_kind = self._fx_markup(batch), "FX_MARKUP"
            elif kind == "dispute_penalty":
                batch.variance, batch.variance_kind = self._penalty(), "DISPUTE_PENALTY"
            else:
                batch.variance, batch.variance_kind = self._promo(batch), "PROMO_FUNDING"

    def _bank_charge(self) -> Paise:
        """A flat RTGS charge the receiving bank took out of the transfer.

        Fifteen rupees, the same on a batch of two lakh as on one of twenty
        thousand. Every rate rule in the inducer works in proportions, and a
        constant is the one thing a proportion can never be.
        """
        return Paise(-1500)

    def _fx_markup(self, batch: _Batch) -> Paise:
        """A conversion spread on an international card batch.

        Between 2.8% and 4.2%, drawn per batch, because a spread is a price
        on the day rather than a term in a contract. `_one_undisclosed_rate`
        holds its members to 0.02% of each other, so a rate that wanders like
        this cannot honestly be called one rate - which is the point.
        """
        spread = Decimal(str(round(self._rng.uniform(0.028, 0.042), 5)))
        return Paise(-apply_rate(batch.gross_total, spread))

    def _penalty(self) -> Paise:
        """A chargeback handling penalty recovered out of a later payout.

        Two thousand rupees, flat, per the usual card-network fee. It looks
        exactly like a refund taken from the wrong batch and is not one:
        there is no refund row anywhere in these files to match it against,
        so a rule that named it would be asserting a document that does not
        exist.
        """
        return Paise(-200000)

    def _promo(self, batch: _Batch) -> Paise:
        """A cashback the merchant funded on some of the orders, not all.

        Ten per cent of roughly half the batch. The result is a clean-looking
        proportion of nothing in particular: it is not a rate on the batch,
        and it is not a flat sum either.
        """
        share = batch.payments[: max(1, len(batch.payments) // 2)]
        return Paise(-apply_rate(Paise(sum(p.amount for p in share)), Decimal("0.10")))

    def _extra_fee(self, batch: _Batch) -> Paise:
        """Charged at a higher rate than the report shows, plus GST on it.

        A rate change applied at payout but not reflected in the export. The
        merchant sees a credit short by a few hundred rupees against a report
        that foots perfectly.
        """
        surcharge = apply_rate(batch.gross_total, Decimal("0.0015"))
        return Paise(-(surcharge + apply_rate(surcharge, self._config.rates.gst)))

    def _wrong_gst(self, batch: _Batch) -> Paise:
        """GST deducted at something other than 18% of the fee charged."""
        applied = apply_rate(batch.fee_total, Decimal("0.28"))
        return Paise(-(applied - apply_rate(batch.fee_total, self._config.rates.gst)))

    def _foreign_refund(self, batch: _Batch, rows: list[SettlementRow]) -> Paise:
        """A refund whose cash came out of this batch, filed against another.

        The report shows the refund netted into whichever batch was running
        when it cleared. The money came out of this one. Nothing in the
        report is wrong on its own - the two statements simply describe
        different batches, and the merchant is short by exactly one refund.
        """
        elsewhere = [
            row
            for row in rows
            if row.type is EntityType.REFUND
            and row.settlement_id is not None
            and row.settlement_id != batch.settlement_id
            and row.debit < batch.net_total
        ]
        if not elsewhere:
            return self._extra_fee(batch)
        return Paise(-self._rng.choice(elsewhere).debit)

    def _batch_tax(self, batch: _Batch) -> Paise:
        if not self._config.defects.batch_tax_rounding:
            return batch.tax_row_total
        return apply_rate(batch.fee_total, self._config.rates.gst)

    # --------------------------------------------------------- the bank side

    def _emit_bank_credits(
        self, batches: list[_Batch], settlements: list[Settlement], missing: set[str]
    ) -> tuple[list[BankCredit], list[CreditTruth]]:
        """Turn settlements into what the bank statement actually shows.

        The bank knows an amount, a date and a narration string. Everything
        else - the orders, the fee, the GST - has to be proved from the other
        two files. Three things go wrong here, and all three are real: the
        UTR does not survive the narration, the payout never arrives, and a
        credit arrives that no settlement explains.
        """
        defects = self._config.defects
        by_id = {batch.settlement_id: batch for batch in batches}

        credits: list[BankCredit] = []
        truths: list[CreditTruth] = []

        for settlement in settlements:
            if settlement.settlement_id in missing:
                continue
            batch = by_id[settlement.settlement_id]
            corrupted = self._rng.random() < defects.utr_corrupted
            damaged = not corrupted and self._rng.random() < defects.utr_damaged
            reference = settlement.settlement_utr
            if damaged:
                reference = self._damage_reference(reference)
            credit_id = self._identifier("bank")
            credits.append(
                BankCredit(
                    credit_id=credit_id,
                    amount=settlement.amount,
                    value_date=settlement.settled_at.date(),
                    narration=self._narration(reference, corrupted),
                    # A damaged reference reaches us only as narration text.
                    # The structured column is what a bank fills in when it
                    # kept the reference cleanly; if it had, there would be
                    # nothing to damage.
                    utr=None if (corrupted or damaged) else reference,
                )
            )
            truths.append(
                CreditTruth(
                    credit_id=credit_id,
                    settlement_ids=(settlement.settlement_id,),
                    entity_ids=settlement.entity_ids,
                    gross=batch.gross_total,
                    fee=batch.fee_total,
                    tax=batch.tax_row_total,
                    tds=batch.tds_total,
                    adjustments=Paise(sum(debit.cash for debit in batch.debits)),
                    rounding_drift=Paise(batch.tax_row_total - settlement.tax),
                    matchable=True,
                    provable=batch.variance == 0,
                    defect=_combined_defect(
                        _reference_defect(corrupted, damaged), batch.variance_kind
                    ),
                )
            )

        credits, truths = self._merge_credits(credits, truths, defects.merged_credits)
        credits, truths = self._inject_orphans(credits, truths, defects.orphan_credits)
        credits, truths = self._inject_duplicates(credits, truths, defects.ambiguous_pairs)
        credits, truths = self._inject_reference_duplicates(
            credits, truths, defects.ambiguous_with_reference
        )

        order = {credit.credit_id: index for index, credit in enumerate(credits)}
        credits.sort(key=lambda credit: (credit.value_date, credit.credit_id))
        truths.sort(key=lambda truth: (order[truth.credit_id],))
        return credits, truths

    def _choose_missing(self, batches: list[_Batch], count: int) -> set[str]:
        """Pick payouts that never reach the bank.

        Never the first batch: an opening batch that is simply absent is
        indistinguishable from a dataset that starts a day later, which would
        make the case unanswerable rather than hard.
        """
        eligible = [batch.settlement_id for batch in batches[1:]]
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

    def _merge_credits(
        self, credits: list[BankCredit], truths: list[CreditTruth], count: int
    ) -> tuple[list[BankCredit], list[CreditTruth]]:
        """Collapse two or three payouts into the single line the bank shows.

        This is not the gateway misbehaving. Transfers initiated in the same
        window get swept into one NEFT credit, and the merchant's statement
        then carries an amount that matches no settlement anywhere - because
        it never was one settlement.

        Half of these carry one member's reference, and those are the
        dangerous ones. The join key finds a real settlement, the amount is
        short by the rest of the group, and any system that treats a match as
        settled fact will report a confident wrong answer with a reference
        number attached to it. The other half carry nothing, which is merely
        hard.

        The whole group is still recorded as matchable. A merged credit is
        resolvable from the evidence: the combination that adds up is in the
        report, and finding it is work rather than luck.
        """
        if count <= 0:
            return credits, truths

        by_id = {truth.credit_id: truth for truth in truths}
        # Any real payout can be swept into a transfer. Restricting this to
        # credits whose reference survived would make merging pick off
        # exactly the credits the first rung can resolve, and the reference
        # rung's score would then be measuring this function's taste rather
        # than how often a bank keeps a reference. It did, for two days.
        eligible = sorted(
            (
                credit
                for credit in credits
                if by_id[credit.credit_id].settlement_ids
                and by_id[credit.credit_id].defect in _MERGEABLE_DEFECTS
            ),
            key=lambda credit: (credit.value_date, credit.credit_id),
        )

        consumed: set[str] = set()
        merged: list[tuple[BankCredit, CreditTruth]] = []

        for index, anchor in enumerate(eligible):
            if len(merged) >= count:
                break
            if anchor.credit_id in consumed:
                continue
            partners = [
                candidate
                for candidate in eligible[index + 1 :]
                if candidate.credit_id not in consumed
                and (candidate.value_date - anchor.value_date).days <= _MERGE_SPAN_DAYS
            ]
            size = self._rng.choice((2, 2, 3))
            members = [anchor, *partners[: size - 1]]
            if len(members) < 2:
                continue
            consumed.update(member.credit_id for member in members)
            merged.append(self._one_merged_credit(members, by_id))

        if not merged:
            return credits, truths

        kept = [credit for credit in credits if credit.credit_id not in consumed]
        kept_truths = [by_id[credit.credit_id] for credit in kept]
        return (
            [*kept, *(credit for credit, _ in merged)],
            [*kept_truths, *(truth for _, truth in merged)],
        )

    def _one_merged_credit(
        self, members: list[BankCredit], by_id: dict[str, CreditTruth]
    ) -> tuple[BankCredit, CreditTruth]:
        """Build the single bank line that stands for several payouts."""
        parts = [by_id[member.credit_id] for member in members]
        credit_id = self._identifier("bank")
        reference = next((member.utr for member in members if member.utr), None)
        carries_reference = reference is not None and self._rng.random() < 0.5

        if carries_reference and reference is not None:
            narration = self._narration(reference, corrupted=False)
            utr: str | None = reference
            defect = "MERGED_WITH_REFERENCE"
        else:
            narration = self._narration("", corrupted=True)
            utr = None
            defect = "MERGED_CREDIT"

        credit = BankCredit(
            credit_id=credit_id,
            amount=Paise(sum(member.amount for member in members)),
            value_date=max(member.value_date for member in members),
            narration=narration,
            utr=utr,
        )
        truth = CreditTruth(
            credit_id=credit_id,
            settlement_ids=tuple(sorted(sid for part in parts for sid in part.settlement_ids)),
            entity_ids=tuple(entity for part in parts for entity in part.entity_ids),
            gross=Paise(sum(part.gross for part in parts)),
            fee=Paise(sum(part.fee for part in parts)),
            tax=Paise(sum(part.tax for part in parts)),
            tds=Paise(sum(part.tds for part in parts)),
            adjustments=Paise(sum(part.adjustments for part in parts)),
            rounding_drift=Paise(sum(part.rounding_drift for part in parts)),
            matchable=True,
            provable=all(part.provable for part in parts),
            defect=defect,
        )
        return credit, truth

    def _damage_reference(self, utr: str) -> str:
        """Alter a reference the way a bank statement actually alters one.

        Every kind below is something that happens to a real narration, and
        every one of them defeats string equality completely. That is the
        point: a damaged reference is not weaker evidence than a clean one to
        an exact matcher, it is *no* evidence, and it is indistinguishable
        from a wrong reference without a technique that can measure
        similarity.
        """
        kind = self._rng.choice(("truncate", "transpose", "substitute", "pad", "split"))
        if kind == "truncate":
            # Narration fields have widths, and the reference is at the end.
            return utr[: self._rng.randint(8, len(utr) - 1)]
        if kind == "transpose":
            # Re-keyed by hand somewhere between the two systems.
            index = self._rng.randrange(len(utr) - 1)
            return utr[:index] + utr[index + 1] + utr[index] + utr[index + 2 :]
        if kind == "substitute":
            positions = [i for i, char in enumerate(utr) if char in _LOOKALIKES]
            if not positions:
                # No character in this reference has a look-alike, so
                # substitution would silently return it unchanged and record
                # a defect that was never injected.
                return self._damage_reference(utr[:-1] + "O")
            index = self._rng.choice(positions)
            return utr[:index] + _LOOKALIKES[utr[index]] + utr[index + 1 :]
        if kind == "pad":
            # An adjacent column bleeds into this one.
            digits = "".join(self._rng.choice("0123456789") for _ in range(self._rng.randint(1, 3)))
            return digits + utr if self._rng.random() < 0.5 else utr + digits
        index = self._rng.randrange(3, len(utr) - 2)
        return utr[:index] + self._rng.choice((" ", "/", "-")) + utr[index:]

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
        settled = [
            credit
            for credit in credits
            if by_id[credit.credit_id].settlement_ids and by_id[credit.credit_id].defect is None
        ]
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

    def _inject_reference_duplicates(
        self, credits: list[BankCredit], truths: list[CreditTruth], count: int
    ) -> tuple[list[BankCredit], list[CreditTruth]]:
        """Twins that only a damaged reference can separate.

        The same construction as `_inject_duplicates`, with one difference
        that changes everything: the real credit keeps its reference, mangled
        but present, while the duplicate carries none.

        That makes the pair genuinely resolvable where the plain duplicates
        are not. The amounts are identical and the dates are identical, so
        arithmetic has nothing to say about either credit - but one narration
        still contains something that resembles a settlement's reference, and
        that resemblance is the only evidence in the dataset that tells them
        apart. A system that can only compare strings for equality must
        refuse this pair; one that can measure similarity should get it
        right, and this is where that difference is worth something.
        """
        if count <= 0:
            return credits, truths

        by_id = {truth.credit_id: truth for truth in truths}
        eligible = [
            credit
            for credit in credits
            if credit.utr is not None
            and by_id[credit.credit_id].defect is None
            and by_id[credit.credit_id].provable
        ]
        if not eligible:
            return credits, truths

        chosen = {
            credit.credit_id for credit in self._rng.sample(eligible, k=min(count, len(eligible)))
        }

        rebuilt: list[BankCredit] = []
        for credit in credits:
            if credit.credit_id in chosen:
                assert credit.utr is not None
                damaged = self._damage_reference(credit.utr)
                credit = credit.model_copy(
                    update={"utr": None, "narration": self._narration(damaged, corrupted=False)}
                )
                by_id[credit.credit_id] = by_id[credit.credit_id].model_copy(
                    update={"defect": "AMBIGUOUS_WITH_REFERENCE"}
                )
            rebuilt.append(credit)

        for credit in [c for c in rebuilt if c.credit_id in chosen]:
            twin_id = self._identifier("bank")
            rebuilt.append(
                BankCredit(
                    credit_id=twin_id,
                    amount=credit.amount,
                    value_date=credit.value_date,
                    narration=self._narration("", corrupted=True),
                    utr=None,
                )
            )
            by_id[twin_id] = self._unmatchable(twin_id, "AMBIGUOUS_TWIN")

        return rebuilt, [by_id[credit.credit_id] for credit in rebuilt]

    def _unmatchable(self, credit_id: str, defect: str) -> CreditTruth:
        return CreditTruth(
            credit_id=credit_id,
            settlement_ids=(),
            entity_ids=(),
            gross=Paise(0),
            fee=Paise(0),
            tax=Paise(0),
            tds=Paise(0),
            adjustments=Paise(0),
            rounding_drift=Paise(0),
            matchable=False,
            provable=False,
            defect=defect,
        )
