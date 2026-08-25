"""What the questions would have cost, if anyone had been billed for them.

Nothing in this project has been paid for. The model runs on a laptop GPU and
the hosted adapters point at free tiers, so the actual figure is zero and will
stay zero - which is a fact about the submission and not about the workload.
The useful number is what the same volume would cost at a published rate, and
that is only meaningful if three things travel with it: the rate, where the
rate came from, and when it was read.

A price is somebody else's claim, restated. It goes stale, and a cost figure
with no date on it is a number that was true once.

Token counts are measured, not estimated. `Completion` carries the provider's
own counters, so the volume side of this arithmetic can be checked against a
bill; only the rate side is an assumption.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict

MILLION = Decimal(1_000_000)


class Rate(BaseModel):
    """One provider's published price, with its provenance attached."""

    model_config = ConfigDict(frozen=True)

    label: str
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal

    source: str
    """Where the figure was read. A secondary source is named as one."""

    checked_on: date

    def project(self, prompt_tokens: int, completion_tokens: int) -> Decimal:
        """What this volume would have cost, in USD.

        Rounded to six places rather than to cents. The runs here cost a
        fraction of a cent, and rounding that to `$0.00` would turn a real
        measurement into a rhetorical one.
        """
        cost = (
            Decimal(prompt_tokens) * self.input_usd_per_million
            + Decimal(completion_tokens) * self.output_usd_per_million
        ) / MILLION
        return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


RATES: tuple[Rate, ...] = (
    Rate(
        label="Gemini 2.0 Flash, paid tier",
        input_usd_per_million=Decimal("0.10"),
        output_usd_per_million=Decimal("0.40"),
        source="ai.google.dev/gemini-api/docs/pricing",
        checked_on=date(2026, 8, 26),
    ),
    Rate(
        label="Groq Llama 3.3 70B Versatile, on demand",
        input_usd_per_million=Decimal("0.59"),
        output_usd_per_million=Decimal("0.79"),
        # Not Groq's own pricing page, which did not carry per-model figures
        # when this was read. Named as a secondary source rather than
        # presented as the vendor's word.
        source="cloudzero.com/blog/groq-pricing (secondary)",
        checked_on=date(2026, 8, 26),
    ),
)
"""The rates the projections are quoted at.

Two, not one, because a single price reads as *the* cost of running this with
a model. The spread between them is the point: the same questions, priced by
two vendors, differ by roughly a factor of five and neither is what this
project actually paid.
"""
