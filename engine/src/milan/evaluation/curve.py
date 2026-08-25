"""The same measurements, tier by tier.

Every headline figure this project publishes comes from the adversarial tier.
That is the honest choice for a single number - it is the hardest data the
generator produces - but a single number says nothing about the shape of the
curve, and the shape is what tells a reader whether the system is good or
merely untested.

A curve that is flat at 100% from clean to adversarial invites exactly one
question: is the hard tier actually hard? The answer here is in the
denominators rather than the rates. Clean generates no impossible credits, no
merged payouts and no mispriced rows, so three of these measures have nothing
to score at all; adversarial generates all of them. The rates stay level while
the *work* increases, and the counts beside each rate are what show it.

Nothing new is measured here. This runs the same sweep four times and puts the
results side by side, because a table nobody can produce in one command is a
table that quietly stops matching the code.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from milan.chaos.config import Difficulty
from milan.evaluation.sweep import Spread, Sweep, sweep

TIERS: tuple[Difficulty, ...] = tuple(Difficulty)


class Curve(BaseModel):
    """One sweep per difficulty tier, aligned by measure."""

    model_config = ConfigDict(frozen=True)

    seeds: tuple[int, ...]
    orders: int
    sweeps: tuple[Sweep, ...]

    @property
    def tiers(self) -> tuple[str, ...]:
        return tuple(run.difficulty for run in self.sweeps)

    def measures(self) -> tuple[str, ...]:
        """Every measure name, in the order the sweep reports them.

        Taken from the first sweep rather than from a list written here. A
        measure added to the sweep and not to this file would otherwise be
        silently absent from the published curve, which is the same failure
        as computing a number and never rendering it.
        """
        return tuple(spread.name for spread in self.sweeps[0].spreads)

    def row(self, measure: str) -> tuple[Spread, ...]:
        return tuple(run.named(measure) for run in self.sweeps)


def curve(seeds: tuple[int, ...], orders: int = 600, withholding: bool = False) -> Curve:
    """Score every tier over the same seeds."""
    return Curve(
        seeds=seeds,
        orders=orders,
        sweeps=tuple(sweep(tier, seeds, orders, withholding) for tier in TIERS),
    )
