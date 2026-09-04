"""Learning a merchant's own contract from their own rows.

Everything else that needs a rate card is handed one or falls back to the
published pricing. This works it out instead, for the case that has no rate
card to be handed: a merchant who brought three files and nothing else.
"""

from milan.rules.induction import Band, InducedRates, RateFinding, induce_rates

__all__ = ["Band", "InducedRates", "RateFinding", "induce_rates"]
