"""Money that is wrong while everything balances.

Every other module in this engine answers one question: *did the payout
arrive*. This one answers a different question, and it is the reason the
project exists rather than being a matcher.

A domestic consumer card is contracted at 2%. The gateway charges 2.15%. The
settlement row foots. The batch total foots. The bank credit reconciles to the
paisa and the proof closes on zero. **Nothing is unmatched, so nothing looks
wrong** - which is precisely why this class of error survives in real merchant
accounts for years, and why no amount of matching will ever find it.

It is found by reading one row against the contract instead of against another
row. The report declares a domestic consumer card and carries a corporate-rate
fee, so it contradicts itself on a single line, and the contradiction is
arithmetic rather than judgement.

**Precision matters more here than anywhere else in this project.** A false
exception costs somebody five minutes. A false accusation of overcharging
costs them a call with their account manager and some of their credibility,
and it is the fastest way for a tool like this to stop being trusted. So a row
is only ever called a leak when the fee it carries cannot be produced by the
rate its own columns describe.
"""

from __future__ import annotations

from decimal import Decimal

from milan.domain.enums import EntityType
from milan.domain.money import Paise, apply_rate
from milan.domain.rates import RateCard
from milan.domain.records import SettlementRow
from milan.domain.results import Leak


def _rate_of(fee: Paise, gross: Paise) -> Decimal:
    """The rate this fee implies, read back off the row.

    No zero guard. `detect` is the only caller and it has already rejected
    every row with a non-positive amount, so a guard here could not fire -
    and unreachable defensive code is the state that looks most like being
    careful while being untested by construction.
    """
    return Decimal(fee) / Decimal(gross)


def detect(rows: tuple[SettlementRow, ...], rates: RateCard | None = None) -> tuple[Leak, ...]:
    """Every payment row whose fee its own columns cannot account for.

    Only payment rows. A refund carries a flat instant-refund charge rather
    than a rate, so reading a percentage off one and comparing it to a card
    rate would manufacture leaks out of correctly charged refunds.

    The comparison is exact, and it can afford to be. `apply_rate` is the same
    function the fee was computed with, so a correctly charged row reproduces
    to the paisa - there is no rounding slack to allow for, and allowing some
    anyway would hide the smallest leaks, which are the ones most likely to
    survive a human review.
    """
    card = rates if rates is not None else RateCard()
    found: list[Leak] = []

    for row in rows:
        if row.type is not EntityType.PAYMENT or row.amount <= 0:
            continue
        if row.method is None:
            # No method means no contracted rate to compare against, and
            # guessing one would be inventing the contract this check exists
            # to enforce. Silence is the right answer.
            continue

        contracted_rate = card.platform_rate(row.method, row.card_type)
        contracted = apply_rate(row.amount, contracted_rate)
        if row.fee == contracted:
            continue

        # An undercharge is not a leak. It is the gateway's money, the
        # merchant is not out of pocket, and reporting it as a finding in a
        # queue about missing money would be noise at best.
        if row.fee < contracted:
            continue

        found.append(
            Leak(
                payment_id=row.payment_id or row.entity_id,
                settlement_id=row.settlement_id or "",
                gross=row.amount,
                charged_fee=row.fee,
                contracted_fee=contracted,
                charged_rate=_rate_of(row.fee, row.amount),
                contracted_rate=contracted_rate,
                method=row.method.value,
                card_type=row.card_type.value if row.card_type else None,
                card_network=row.card_network,
                card_issuer=row.card_issuer,
                # A payment row always carries a settlement timestamp; the
                # field is optional because refund rows may not, and those
                # never reach here.
                settled_on=row.settled_at.date().isoformat() if row.settled_at else "",
            )
        )

    return tuple(found)
