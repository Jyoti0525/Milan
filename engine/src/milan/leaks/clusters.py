"""Turning a list of leaks into a thing somebody can act on.

Thirty-five rows, each a few rupees, is a report nobody reads. It is also
technically complete, which is what makes it a tempting place to stop.

The useful output is the sentence underneath them: *every domestic consumer
card charged at the corporate rate, 35 payments, Rs 136.83*. That is one
finding with one owner and one fix, and it is what a merchant takes to their
account manager. The rows are still there underneath it, because a claim about
money that cannot be drilled into is a claim nobody should act on.

Grouped by what the rows have in common rather than by clustering in any
statistical sense. The mechanism is a rate pair - contracted against charged -
and rows sharing one share a cause by construction. A distance metric over
these fields would find the same groups less legibly and would occasionally
find others that mean nothing, which in a report about money is worse than
useless.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from milan.domain.money import Paise, format_inr
from milan.domain.results import Leak


class LeakCluster(BaseModel):
    """A group of leaks sharing one cause."""

    model_config = ConfigDict(frozen=True)

    contracted_rate: Decimal
    charged_rate: Decimal
    method: str
    card_type: str | None

    payments: int
    overcharge: Paise
    gst: Paise
    gross_affected: Paise

    first_seen: str
    last_seen: str

    networks: tuple[str, ...] = ()
    """Card networks the group spans, most affected first.

    Carried because it is the first question anyone asks about a rate
    mismatch - whether it is one network's pricing or the gateway's
    classification - and because a group confined to a single network is a
    different conversation from one spread across all of them."""

    payment_ids: tuple[str, ...] = ()
    """The rows behind the claim. Truncated for display elsewhere, never
    here: a finding about money has to be checkable against the merchant's
    own export."""

    @property
    def cash_impact(self) -> Paise:
        return Paise(self.overcharge + self.gst)

    @property
    def excess_rate(self) -> Decimal:
        return self.charged_rate - self.contracted_rate


def _quantise(rate: Decimal) -> Decimal:
    """Round a rate read back from a fee to four places.

    A fee is rounded to the paisa before it is recorded, so reading a rate
    back off one gives 0.0214999… rather than 0.0215 and every row lands in a
    group of its own. Four places is finer than any published rate in the
    Indian fee stack and coarse enough to survive that rounding.
    """
    return rate.quantize(Decimal("0.0001"))


def cluster(leaks: tuple[Leak, ...]) -> tuple[LeakCluster, ...]:
    """Group leaks by the rate pair that caused them, worst first."""
    grouped: dict[tuple[Decimal, Decimal, str, str | None], list[Leak]] = defaultdict(list)
    for leak in leaks:
        key = (
            _quantise(leak.contracted_rate),
            _quantise(leak.charged_rate),
            leak.method,
            leak.card_type,
        )
        grouped[key].append(leak)

    clusters = [
        LeakCluster(
            contracted_rate=contracted,
            charged_rate=charged,
            method=method,
            card_type=card_type,
            payments=len(members),
            overcharge=Paise(sum(leak.overcharge for leak in members)),
            gst=Paise(sum(leak.gst_on_overcharge for leak in members)),
            gross_affected=Paise(sum(leak.gross for leak in members)),
            first_seen=min(leak.settled_on for leak in members),
            last_seen=max(leak.settled_on for leak in members),
            networks=tuple(
                name
                for name, _ in Counter(
                    leak.card_network for leak in members if leak.card_network
                ).most_common()
            ),
            payment_ids=tuple(sorted(leak.payment_id for leak in members)),
        )
        for (contracted, charged, method, card_type), members in grouped.items()
    ]

    # By money, not by count. Ten rows costing a rupee each are not the
    # finding; one row costing a thousand is.
    return tuple(sorted(clusters, key=lambda group: (-group.overcharge, group.method)))


class LeakReport(BaseModel):
    """What the leak pass found, whole."""

    model_config = ConfigDict(frozen=True)

    clusters: tuple[LeakCluster, ...] = ()
    rows_examined: int = 0

    @property
    def payments(self) -> int:
        return sum(group.payments for group in self.clusters)

    @property
    def overcharge(self) -> Paise:
        return Paise(sum(group.overcharge for group in self.clusters))

    @property
    def gst(self) -> Paise:
        return Paise(sum(group.gst for group in self.clusters))

    @property
    def cash_impact(self) -> Paise:
        return Paise(self.overcharge + self.gst)

    @property
    def clean(self) -> bool:
        return not self.clusters

    def headline(self) -> str:
        if self.clean:
            return (
                f"Every one of {self.rows_examined:,} payment rows was charged at "
                "its contracted rate."
            )
        return (
            f"{format_inr(self.overcharge)} was overcharged across {self.payments} "
            f"of {self.rows_examined:,} payments, in "
            f"{len(self.clusters)} pattern{'s' if len(self.clusters) > 1 else ''}. "
            f"A further {format_inr(self.gst)} of GST was charged on those fees and "
            "is recoverable as input tax credit."
        )


def summarise(leaks: tuple[Leak, ...], rows_examined: int) -> LeakReport:
    return LeakReport(clusters=cluster(leaks), rows_examined=rows_examined)
