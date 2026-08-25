"""Finding money that is wrong while the books balance.

Separate from `recon` on purpose. Reconciliation asks whether a payout
arrived; this asks whether it should have been that size. The two share a
rate card and nothing else, and a leak is found by reading a row against the
contract rather than against another row.
"""
