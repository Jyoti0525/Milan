"""The import, scored against files whose answer we know.

This is the only place in the project where accuracy can honestly be
measured, because it is the only corpus with an answer key: the sample files
are generated, so `Amount Paid In` holds the credit as a matter of record
rather than of inference.

Everything here runs with **no provider**. That is deliberate and it is the
same rule every other graded figure in this codebase follows - a number that
moves when a model is swapped is a number about the model, not about the
import. `milan measure --provider ollama` reports the model's contribution on
demand, and it is never asserted in a test, because a test that fails when
Ollama is not running is a test about the machine it ran on.

The assertion that matters is `wrong == 0`. A column settled without a
question and settled incorrectly is the one failure this design exists to
prevent, and unlike everything else it goes on to produce totals that balance
perfectly and are upside down.
"""

from __future__ import annotations

import pytest

from milan.ingest.reading import read_all
from milan.samples import build
from milan.samples.measure import Accuracy, measure, write_corpus
from milan.samples.truth import CORPUS


@pytest.fixture(scope="module")
def scored() -> Accuracy:
    return measure(None)


# ------------------------------------------------------- the answer key itself


def test_every_column_in_the_answer_key_is_a_real_header(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """A truth table that has drifted measures nothing, and says so nowhere.

    The writers in `dialects` are free to be edited; this is what stops such an
    edit from quietly turning the accuracy figure into a comparison against a
    header that no longer exists.
    """
    root = tmp_path_factory.mktemp("corpus")
    written = write_corpus(build.month(seed=42, orders=120), root)

    headers: dict[tuple[str, str], tuple[str, ...]] = {}
    for (writer, sheet), path in written.items():
        for source in read_all(path):
            headers[(writer, source.sheet)] = source.headers
        del sheet

    for truth in CORPUS:
        if not truth.columns:
            continue
        found = headers.get((truth.writer, truth.sheet))
        assert found is not None, f"{truth.writer} wrote no sheet named {truth.sheet!r}"
        for field, column in truth.columns.items():
            assert column in found, (
                f"{truth.writer}{'/' + truth.sheet if truth.sheet else ''}: the answer key says "
                f"{field} is {column!r}, which is not a column in the file"
            )


# ----------------------------------------------------------------- the scores


def test_nothing_is_settled_wrongly(scored: Accuracy) -> None:
    """The figure that is allowed to be zero and nothing else."""
    assert scored.wrong == [], "\n".join(
        f"{outcome.file}: {outcome.field} was settled as {outcome.got!r} "
        f"without asking, and the answer is {outcome.expected!r}"
        for outcome in scored.wrong
    )


def test_every_file_is_placed_as_what_it_is(scored: Accuracy) -> None:
    misplaced = [
        f"{name}: expected {expected}, got {got}"
        for name, expected, got in scored.kinds
        if expected != got
    ]
    assert misplaced == [], "\n".join(misplaced)


def test_the_two_files_that_are_none_of_ours_are_left_alone(scored: Accuracy) -> None:
    """A GST return and a purchase ledger, on names and values alone.

    Both are placed correctly here and only one of them stays that way once a
    model is consulted - the ledger has a date and an amount and reads as an
    orders export to something willing to guess. That is recorded rather than
    hidden: it is the case that makes the model's placement worth checking.
    """
    left = {name for name, expected, _ in scored.kinds if expected is None}
    assert len(left) == 2
    for name, _, got in scored.kinds:
        if name in left:
            assert got is None


def test_the_file_carries_most_of_the_corpus_with_no_model_at_all(scored: Accuracy) -> None:
    """What the import achieves before any model is involved.

    Two sources, and neither is a provider. The header dictionary in
    `schema.py` recognises the names it knows; the checks in `identity.py`
    work out the rest from the merchant's own rows - the settlement equation
    solved for its unknown columns, a deposit column left standing once the
    balance and the row number are eliminated, a capture date that never runs
    ahead of its payout, an opaque reference column whose values are ids the
    file beside it names.

    Not a floor to be defended - a description. If this drops, something that
    used to be derivable stopped being derived.
    """
    settled = len(scored.settled_right)
    assert settled >= 78, f"only {settled} of {len(scored.outcomes)} columns settled with no model"
    assert scored.rate(scored.settled_right, scored.outcomes).endswith(f"of {len(scored.outcomes)}")


def test_what_is_still_asked_is_what_nothing_in_the_file_can_answer(scored: Accuracy) -> None:
    """The list this design is trying to reduce to, rather than to empty.

    One field, and it is genuinely undecidable: `value_date` against a
    transaction date. Two real date columns that disagree with each other,
    where which one a merchant reconciles on is a fact about their bank and
    not about the file in front of us. No amount of reading the file settles
    it, and the only honest thing to do is ask.

    `entity_id` and `settlement_id` were here and are not any more - the row
    key is the only column filled and different on every row, and the batch
    id is whatever pairs one-to-one with the reference the bank quoted back.

    A question appearing here that is not `value_date` means something became
    underivable that used to be derived. A question disappearing from here
    means either a real improvement or a guess dressed as a proof, and
    `test_nothing_is_settled_wrongly` is the one that tells them apart.
    """
    unanswerable = {"value_date"}
    surprising = sorted({outcome.field for outcome in scored.asked} - unanswerable)
    assert surprising == [], f"asked about {', '.join(surprising)}, which the file can answer"


def test_an_identifier_column_is_named_by_the_folder_around_it(scored: Accuracy) -> None:
    """The check that reads outside the file it is deciding about.

    `Merchant Ref` and `Order Ref` on a processor's export are opaque, and
    before this the import concluded the file simply had no payment id - not
    as a question, but silently, with the column sitting there. Every
    downstream check that wanted it went without.
    """
    joined = {
        (outcome.file, outcome.field)
        for outcome in scored.settled_right
        if outcome.field in ("payment_id", "order_id") and not outcome.by_name
    }
    assert len(joined) >= 4, f"only {len(joined)} identifier columns came from another file"


def test_every_question_names_a_column_the_file_actually_has(scored: Accuracy) -> None:
    """A question is only useful if its right answer is among the choices.

    Asking about a field whose true column was never offered turns a
    checkpoint into a dead end, and the person answering has no way to tell
    that is what happened.
    """
    for outcome in scored.asked:
        assert outcome.expected, f"{outcome.file}: asked about {outcome.field} with no answer key"


def test_a_suggestion_shown_to_somebody_is_the_right_one(scored: Accuracy) -> None:
    """With no provider there are no suggestions, and that is the assertion.

    The resolver must not manufacture a lead answer out of its own ranking.
    A bare list of columns says "we do not know"; a highlighted button says
    "we think it is this", and only a proposal earns that.
    """
    assert scored.suggested == []
