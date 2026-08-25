"""The published ablation, replayed from the committed cache.

Every other number in this project can be reproduced by anyone with the
repository: the datasets are pure functions of their seeds, so a reader
regenerates them and rescores. The ablation is the one figure that cannot be,
because it depends on a model, a quantisation and a daemon - none of which
live here.

So the answers do. `data/llm-cache` holds what Qwen 2.5 3B actually said,
addressed by the hash of the question, and this replays them with **no model
present at all**. If a single question misses the cache, the stand-in
provider answers nothing and `answered` falls below `asked` - which is the
assertion, and it is what turns "here are our numbers" into "here are our
numbers, and here is the run".

The published figures are asserted exactly. A model swap, a prompt edit or a
change to which shortfalls reach the triage all move them, and any of those
would leave the README describing a run nobody can produce.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from milan.chaos.config import Difficulty
from milan.evaluation.ablate import ablate
from milan.evaluation.ablation import Ablation
from milan.llm.cache import CachedProvider, ResponseCache
from milan.llm.provider import Completion, Request
from milan.llm.registry import default_cache_root

MODEL = "qwen2.5:3b"
SMALLER = "qwen2.5:1.5b"
SEEDS = tuple(range(1, 21))
ORDERS = 600

# What `uv run milan ablate --provider ollama --seeds 20` printed, and what
# the README quotes. Asserted rather than described.
ASKED = 110
AGREEMENT_HITS = 18
REJECTED = 47
INVENTED = 5
PROMPT_TOKENS = 66_146
COMPLETION_TOKENS = 2_453


class Absent:
    """A provider with nothing to say, standing in for a reviewer's machine.

    Named `ollama` and carrying the model, because the cache keys on both. It
    counts its calls so a cache miss is reported as a miss rather than
    quietly answered.
    """

    name = "ollama"

    def __init__(self, model: str = MODEL) -> None:
        self.model = model
        self.calls = 0

    def complete(self, request: Request) -> Completion:
        del request
        self.calls += 1
        return Completion(text="", provider=self.name, model=self.model)


@pytest.fixture(scope="module")
def cache_root() -> Path:
    root = default_cache_root()
    if not root.is_dir():
        pytest.skip(f"no committed cache at {root}")
    return root


@pytest.fixture(scope="module")
def replayed(cache_root: Path) -> tuple[Ablation, Absent]:
    absent = Absent()
    provider = CachedProvider(absent, ResponseCache(cache_root))
    result = ablate(provider, Difficulty.ADVERSARIAL, SEEDS, ORDERS, MODEL)
    return result, absent


class TestTheAblationReplays:
    def test_every_question_is_answered_without_a_model(
        self, replayed: tuple[Ablation, Absent]
    ) -> None:
        """The whole point. A miss here means a reader cannot reproduce the
        published table, and the stand-in provider makes that loud."""
        result, absent = replayed

        assert result.asked == ASKED
        assert result.answered == ASKED
        assert result.replayed == ASKED
        assert absent.calls == 0, (
            f"{absent.calls} questions missed the committed cache. Refresh it with:\n"
            "  uv run milan ablate --provider ollama --seeds 20 --orders 600"
        )

    def test_the_published_figures_are_what_the_cache_produces(
        self, replayed: tuple[Ablation, Absent]
    ) -> None:
        result, _ = replayed

        assert result.agreement_hits == AGREEMENT_HITS
        assert result.rejected == REJECTED
        assert result.invented_ids == INVENTED

    def test_the_contribution_is_zero_over_zero_and_says_so(
        self, replayed: tuple[Ablation, Absent]
    ) -> None:
        """0/0 and 0% are different claims. The rules named every shortfall
        the engine reached, so the model proposed into an empty set - which
        is a measured result, not a failure to contribute."""
        result, _ = replayed

        assert result.open_cases == 0
        assert result.contributions == 0

    def test_the_token_counts_survive_the_cache(self, replayed: tuple[Ablation, Absent]) -> None:
        """The cost figure has to replay too.

        Token counts come from the provider's own counters, so a cache that
        dropped them would leave a replayed run reporting a cost of zero for
        work that was really done - a cheaper claim than the truth, which is
        the direction errors are least likely to be questioned in.
        """
        result, _ = replayed

        assert result.prompt_tokens == PROMPT_TOKENS
        assert result.completion_tokens == COMPLETION_TOKENS


class TestTheSecondModelReplaysToo:
    """The size comparison, and the bug that would have hidden it.

    Until the cache keyed on the model, both of these would have read the
    same entries: a caller never names a model, so `Request.model` was empty
    and the key did not mention one. Two columns of identical figures would
    have looked like a finding about model size rather than a bug in the
    cache.
    """

    def test_the_smaller_model_declined_every_question(self, cache_root: Path) -> None:
        absent = Absent(SMALLER)
        provider = CachedProvider(absent, ResponseCache(cache_root))
        result = ablate(provider, Difficulty.ADVERSARIAL, SEEDS, ORDERS, SMALLER)

        assert absent.calls == 0, f"{absent.calls} questions missed the cache for {SMALLER}"
        assert result.answered == ASKED
        assert result.agreement_hits == 0
        assert result.invented_ids == 0
        assert result.kinds == {"unknown": ASKED}

    def test_the_two_models_did_not_share_answers(self, cache_root: Path) -> None:
        """The assertion that makes the comparison worth publishing."""
        cache = ResponseCache(cache_root)
        larger = ablate(
            CachedProvider(Absent(MODEL), cache), Difficulty.ADVERSARIAL, SEEDS, ORDERS, MODEL
        )
        smaller = ablate(
            CachedProvider(Absent(SMALLER), cache), Difficulty.ADVERSARIAL, SEEDS, ORDERS, SMALLER
        )

        assert larger.kinds != smaller.kinds
