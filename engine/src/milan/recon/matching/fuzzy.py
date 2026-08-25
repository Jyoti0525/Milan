"""Rung four: the reference that survived, badly.

A bank narration damages references rather than politely dropping them. It
truncates at a field width, transposes a pair of characters when re-keyed,
confuses O for 0 and I for 1, glues on digits from an adjacent column, or
splits the reference across a delimiter. Exact matching requires string
equality, so every one of those is a total miss - and unlike a deleted
reference, a damaged one still looks like evidence.

This rung measures similarity instead of demanding equality. Three things
keep that from becoming guesswork:

**It runs last.** Every credit reaching here has already failed the join key,
the amount, and the combination search. A fuzzy answer is never preferred
over an arithmetic one; it only ever speaks when nothing else could.

**It needs a clear winner, not a best one.** A ranked list always has a top
entry. What matters is whether the top entry stands apart from the next, so a
match is reported only when the margin is decisive - otherwise the honest
output is that two references are equally plausible, which is a refusal.

**The proof still overrules it.** Like every other rung, its claim is
provisional until the waterfall reconstructs the credit to zero.

Deliberately not Splink. Probabilistic record linkage with EM-estimated match
weights is built for joining datasets across many comparison columns; here
there is one column, a dozen or so candidates inside a date window, and no
training data. `difflib` is in the standard library, is deterministic, and is
the right size of tool for the job.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from milan.domain.enums import MatchStrategy
from milan.domain.records import BankCredit
from milan.recon.batches import GatewayBatch
from milan.recon.matching.base import Attempt, Verdict

SIMILARITY_FLOOR = 0.78
"""Below this, two references are simply different strings.

Set from what damage actually does: a transposition or a single substitution
in a twelve-character reference leaves about 0.83, and a truncation to eight
characters about 0.80. Anything that has to reach further than that is not
recognising a damaged reference, it is finding a coincidence."""

DECISIVE_MARGIN = 0.10
"""How far the best candidate must stand above the second.

Without this the rung would answer every time, because a ranked list always
has a top entry. The margin is what turns "most similar" into "identifiable"."""

_NOISE = re.compile(
    r"\b(?:RAZORPAY|SOFTWARE|SETTLEMENT|PAYOUT|INWARD|NEFT|IMPS|UTR|ACH|PVT|LTD|CR)\b"
)
"""Bank boilerplate, stripped only where it stands as a word of its own.

The word boundaries are not decoration. Without them this pattern removes
`CR` from inside `JMSS5NDW4CR`, which is a perfectly ordinary Razorpay
reference - so the one piece of evidence the rung exists to weigh gets
quietly shortened before it is weighed, and the same happens to any
reference containing ACH, LTD, PVT or UTR. A property test found this by
asking whether a reference is similar to itself; it is not the kind of thing
a hand-written narration would have contained."""


def normalise(narration: str) -> str:
    """Reduce a narration to the characters a reference could be made of.

    Bank words are stripped first. They are long runs of capitals, which is
    exactly what a reference looks like to a similarity measure, and leaving
    them in means competing against "RAZORPAYSOFTWARE" for every comparison.
    """
    return re.sub(r"[^A-Z0-9]", "", _NOISE.sub(" ", narration.upper()))


def _as_reference(reference: str) -> str:
    """The reference reduced the same way the narration is, minus the noise.

    Both sides have to be comparable or the measure is scoring a formatting
    difference. Bank words are deliberately *not* removed here: on this side
    of the comparison they are the thing being looked for, not the wrapping
    around it.
    """
    return re.sub(r"[^A-Z0-9]", "", reference.upper())


def similarity(reference: str, narration: str) -> float:
    """How well a reference matches anywhere inside a narration.

    Compared against every window of the right length rather than against the
    whole string, because the reference is a fragment of the narration and a
    whole-string comparison would be dominated by whatever surrounds it. The
    window is also what lets a split reference match: "DJR/JMSS5NDW4" becomes
    contiguous once the delimiter is stripped.
    """
    text = normalise(narration)
    reference = _as_reference(reference)
    if not text or not reference:
        return 0.0

    width = len(reference)
    matcher = SequenceMatcher(a=reference, autojunk=False)
    best = 0.0
    # Every start position, not just the ones where a full-width window still
    # fits. Banks glue their own label straight onto the number - "UTR" plus a
    # reference that has itself been truncated - and the text is then shorter
    # than the reference it contains. A sweep sized from the reference stops
    # three characters early on exactly that case and misses the alignment
    # that would have matched, which is a defect the messy tier carries and
    # the arithmetic rungs cannot cover for.
    for start in range(len(text)):
        window = text[start : start + width + 3]
        if not window:
            break
        matcher.set_seq2(window)
        best = max(best, matcher.ratio())
    return best


class FuzzyNarrationStrategy:
    """Match a damaged reference against the settlements still unclaimed."""

    name = MatchStrategy.FUZZY_NARRATION

    def __init__(self, floor: float = SIMILARITY_FLOOR, margin: float = DECISIVE_MARGIN) -> None:
        self._floor = floor
        self._margin = margin

    def attempt(
        self,
        credit: BankCredit,
        candidates: tuple[GatewayBatch, ...],
        prior: Attempt | None = None,
    ) -> Attempt:
        del prior
        scored = sorted(
            (
                (similarity(batch.settlement_utr, credit.narration), batch.settlement_id)
                for batch in candidates
                if batch.settlement_utr
            ),
            key=lambda pair: (-pair[0], pair[1]),
        )
        if not scored or scored[0][0] < self._floor:
            return Attempt(
                strategy=self.name,
                verdict=Verdict.NO_CANDIDATE,
                note=(
                    "no settlement reference resembles this narration closely "
                    f"enough ({scored[0][0]:.0%} at best)"
                    if scored
                    else "no unclaimed settlement carries a reference"
                ),
            )

        best, runner_up = scored[0], scored[1] if len(scored) > 1 else (0.0, "")
        if best[0] - runner_up[0] < self._margin:
            return Attempt(
                strategy=self.name,
                verdict=Verdict.AMBIGUOUS,
                candidates=(best[1], runner_up[1]),
                note=(
                    f"two references resemble this narration equally "
                    f"({best[0]:.0%} and {runner_up[0]:.0%}); nothing separates them"
                ),
            )

        return Attempt(
            strategy=self.name,
            verdict=Verdict.MATCHED,
            settlement_ids=(best[1],),
            candidates=(best[1],),
            confidence=self._confidence(best[0]),
            note=f"narration resembles this settlement's reference at {best[0]:.0%}",
        )

    def _confidence(self, score: float) -> float:
        """Capped well below an exact reference match.

        An intact reference is proof of identity. A damaged one is an
        argument about it, and the queue should be able to tell at a glance
        which of the two it is looking at.
        """
        return min(0.70, 0.40 + 0.35 * score)
