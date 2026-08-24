# Build Log — what broke, and how we got out

Kept from the first commit, not written at the end. Razorpay's form asks for
this and it cannot be reconstructed afterwards without inventing things.

Newest entries at the bottom of each day.

---

## Day 1 — 25 August 2026

**Goal:** 50 records in, one match, one exception, one honest number out, end
to end, with no LLM anywhere. Achieved.

### What broke

**1. The oracle test failed the first time it ran — and the fault was in the answer key.**

The oracle is a matcher that reads the answers. Handed the right settlement
for every credit, it must score exactly 100%; anything less means the
*generator* is wrong, not the matcher.

It scored 100% on three tiers and failed on ADVERSARIAL. The cause was a real
conceptual error, not a typo: the answer key had one field doing two jobs.

The adversarial tier injects pairs of credits with the same amount, the same
date, and no reference on either — one is the real payout, one is a duplicate
the bank later reverses. The key recorded `matchable=False` for the real one
while still recording the settlement that was genuinely behind it. The oracle
read the settlement and matched it; the scorer read `matchable` and counted
that as a false positive. Both were behaving correctly. The key was
contradicting itself.

**Fix:** the two questions are now two fields with two meanings.

| Field | Question it answers |
|---|---|
| `settlement_id` | What is actually behind this credit — a fact about the world |
| `matchable` | Whether the evidence in the three files can single it out |

Scoring uses `matchable`. The oracle now refuses the same records a perfect
honest system would refuse, because it models the *ceiling of honest
behaviour*, not omniscience. Knowing which of two identical credits is real
is not skill; it is having the answer key.

**Why this one matters:** it is exactly the failure the oracle test exists to
catch. A wrong answer key does not look like a bug. It looks like a slightly
lower match rate, and it would have silently invalidated every accuracy number
in the submission. Cost: about twenty minutes, on day one. Found in week two
it would have invalidated everything measured up to that point.

**2. "Records processed" meant two different things.**

`Dataset.record_count` counted orders, payments, refunds, chargebacks,
settlement rows and bank credits — 324 for a 100-order month. The engine
reported 317, because refunds and chargebacks reach it *as* settlement rows.
The generator was counting the same records twice.

Razorpay's bar is a 50+ record batch, so this is the number the central claim
is measured against and it has to mean one thing. It now counts the three
merchant-side files and nothing else. Both figures agree at 317.

**3. Heredocs could not write the larger source files.**

A shell quoting problem, not an engineering one, but it cost time. Files over
roughly 300 lines went through the editor directly instead.

### What we decided

**`make` is not on the critical path.** Windows has no `make` by default. The
CLI is the real interface (`uv run milan ...`) and the Makefile is a thin
alias layer over it, so the documented `make eval` works where make exists and
nothing breaks where it does not.

**JSON, not Parquet, for now.** The tech stack names DuckDB and Parquet. At
day-1 volumes the columnar format buys nothing and costs two things we need
today: a byte-stable encoding to hash for `milan reproduce`, and a file a
human can open when a number looks wrong. Revisit when a dataset stops fitting
comfortably in memory — not before.

### What the numbers actually say

Full cascade, 600 orders, seed 42, all four tiers:

| Tier | Baseline (reference only) | Full cascade | Precision | Correct refusals |
|---|---|---|---|---|
| clean | 100.0% | 100.0% | 100.0% | 0/0 |
| realistic | 88.2% | 100.0% | 100.0% | 1/1 |
| messy | 81.2% | 100.0% | 100.0% | 3/3 |
| adversarial | 78.6% | 100.0% | 100.0% | 8/8 |

**This is not yet an impressive result, and we should not present it as one.**

100% here says more about the current difficulty of the generated problem than
about the matcher. A 600-order month produces roughly twenty settlement
batches. A batch total is the sum of dozens of arbitrary order values, so on
twenty batches it is effectively unique — which means amount-plus-date
resolves almost everything the reference key missed, and it would do so for
any competent implementation.

What the run does legitimately establish:

- The pipeline is end to end and every credit is either proved to the paisa or
  raised as an exception. Nothing is silently dropped — that is a test.
- The refusal behaviour works: 8/8 impossible records correctly left alone at
  the adversarial tier, with zero forced answers.
- The baseline column is real and already earning its place — the gap between
  78.6% and 100% is what the second rung is worth.

What it does **not** establish: that the matcher is good. The problem has to
get harder before that number means anything.

### What makes it harder (days 2-3)

The generator needs the cases that make batch totals stop being unique:

1. **Multiple settlements per day** — separate payouts per method or currency,
   which is what the gateway actually does.
2. **N:1 and 1:N** — one bank credit covering several settlements, and one
   settlement split across credits. This is the subset-sum problem that the
   whole matching design exists for, and right now the generator never
   produces it.
3. **Volume** — a quarter, not three weeks, so there are hundreds of batches
   and near-collisions happen by chance rather than by injection.
4. **Orders that never settle** and payments missing from the report entirely.

Until at least (1) and (2) exist, the honest headline is the baseline gap and
the refusal rate, not the match rate.

---

## Days 2-3 — 25 August 2026

**Goal, set by day one:** make the generated problem hard enough that a match
rate means something. Achieved for the baseline. Not achieved for the
headline, and the reason is the most useful thing found so far.

### What was added

| | Why it makes the problem harder |
|---|---|
| **Several settlements a day** | Payout runs happen on cut-offs, and international cards settle on their own cycle. One run a day gave ~20 batches a month, each the sum of dozens of arbitrary order values, so no two ever collided. Now ~39 for the same volume, 2-3 on most days. |
| **Merged bank credits (N:1)** | Banks sweep transfers in the same window into one NEFT line. The credit then matches no settlement at all. Half carry one member's reference, which is worse than carrying none. |
| **Unreported payments** | Captured money the settlement report never mentions. Invisible to every bank-side technique in the system. |

The merged credit that carries one member's reference is the one worth
dwelling on. Rung one recognises the reference and matches a real settlement.
The amount is short by the rest of the group. A system that treats a match as
a settled fact reports a confident wrong answer **with a reference number
attached to it**, and leaves behind a second settlement that looks like an
ordinary missing payout. Two plausible rows, one real error, no flag.

That case is what turned proving from a post-hoc check into part of the
search. The waterfall solver is now handed to the cascade as a verifier: a
rung's claim is provisional until it reconstructs to zero, and a withdrawn
claim sends the credit down to the next rung rather than to the exception
queue. There is a test for exactly this - the same credit, the same
strategies, with and without the veto. Without it the credit resolves to
`setl_a` alone. With it, to the pair.

### What the numbers say now

600 orders, seed 42. One rung added per row, so each row's gain over the one
above it is what that rung is worth.

| Tier | Reference only | + amount and date | + subset sum | Precision | Refusals | Merged |
|---|---|---|---|---|---|---|
| clean | 100.0% | 100.0% | 100.0% | 100.0% | 0/0 | 0/0 |
| realistic | 80.6% | 94.4% | 100.0% | 100.0% | 1/1 | 2/2 |
| messy | 68.8% | 87.5% | 100.0% | 100.0% | 3/3 | 4/4 |
| adversarial | **46.4%** | 78.6% | 100.0% | 100.0% | 8/8 | 6/6 |

The adversarial baseline moved from 78.6% to 46.4%. That is the day's real
result: the gap the cascade has to close has roughly doubled, and all three
rungs now visibly earn their place instead of the second one carrying
everything.

### The uncomfortable part

The full cascade is still at 100%, and pushing on it did not change that.

| Orders | Cycles | Batches | Match | Precision | False + |
|---|---|---|---|---|---|
| 600 | 2 | 39 | 100.0% | 100.0% | 0 |
| 1,500 | 3 | 52 | 100.0% | 100.0% | 0 |
| 3,000 | 4 | 72 | 100.0% | 100.0% | 0 |
| 6,000 | 6 | 100 | 100.0% | 100.0% | 0 |

Three seeds each. So the question became *why*, and the first two answers
were both wrong.

**Wrong answer one: the pool shrinks.** The story was that rung one consumes
the referenced settlements first, so the weaker rungs face a much smaller
candidate set. Testable, and tested: running the cascade with rung one
removed entirely. Match rate stayed at 100%. The story was wrong.

**Wrong answer two: candidate explanations are far apart.** Measuring the
distance between every pair of candidate explanations gave a closest pair of
₹0.20 at 6,000 orders, against a rounding allowance of ₹1.57 — apparently
overlapping. But that measures the wrong thing. Two candidates being close to
each other only matters if a real credit sits near both, and most of those
440,000 pairs were combinations no credit was ever offered.

**The number that actually governs precision** is, for each real bank credit,
the distance to the nearest *wrong* explanation:

| Orders | Nearest wrong answer (median) | 5th tightest | Allowance |
|---|---|---|---|
| 600 | ₹425.37 | ₹37.08 | ₹0.42 |
| 6,000 | ₹51.73 | ₹1.36 | ₹1.57 |

The median credit sits hundreds of times the allowance away from any
competing answer. **A settlement total is a near-unique fingerprint, and the
fee stack is what makes it one.** Two batches with identical gross still
settle to different nets, because the fee depends on the method and card type
of every row inside them. This was checked directly by replacing the
long-tailed order values with a three-SKU subscription catalogue — every
order ₹499, ₹999 or ₹1,999. Match rate: still 100%.

The tail is tighter than the median, and at 6,000 orders several credits do
sit inside the allowance of a wrong answer. The specific exposure that
creates — rung two claiming a merged credit because some unrelated single
batch happens to fit — was measured across 60 datasets and 360 merged
credits. It occurred **0 times**.

### What this means, and what it changes

The honest conclusion is not that the matcher is good. It is that **this
class of matching problem is largely solved by modelling the fee stack
correctly**, and the remaining risk is not in matching at all.

That contradicts the plan. [07-BUILD-ORDER.md](07-BUILD-ORDER.md) assigns
days 4-5 to "matching core + Splink". Splink is probabilistic record linkage,
and it would be aimed at fuzzy narration matching — a fourth rung, to raise a
number that three deterministic rungs already hold at 100% across every tier,
volume and pricing model tested. Building it would be choosing a technique
because it is impressive rather than because anything needs it.

The risk that is left is the money that is wrong *while everything matches*:

- **Rate leaks.** `LeakTruth` has been recorded at generation time since day
  one and nothing reads it. A batch charged at the corporate rate on consumer
  cards balances perfectly, reconciles perfectly, and is theft.
- **Unreported payments.** Now generated and now detected, but the detection
  rule is young and its recall is bounded by the report horizon.
- **Rounding drift.** Named per credit; not yet totalled across a month,
  which is the number a merchant would actually want.

Proposed: cut Splink, spend days 4-5 on leak detection and property tests
(`tests/property/` is still empty and Hypothesis is already a dependency).
That is a change to the plan, so it is recorded here rather than made
silently.

### Also worth recording

**The 1:N case is deliberately not built.** One settlement paid out as two
bank credits is real - it happens when a merchant's balance goes negative and
the payout splits. It is not here, because it breaks the shape of the answer:
no single credit proves a settlement, so a *group* of credits has to prove a
*group* of settlements, and matching stops being a per-credit question. That
is a partition solver, not a rung. N:1 is both the commoner case and the one
that fits the existing model, so N:1 is what got built. Doing half of 1:N
would have been worse than not doing it.

**Two design decisions came out of the measurement rather than preceding it.**
The subset-sum rung treats a lone batch of the right size as a *competing*
explanation rather than a weaker one, and it declines when its search runs out
of budget rather than reporting its best find. Both exist because a truncated
or contested search has not established uniqueness, and uniqueness is the only
basis on which that rung is entitled to claim anything.
