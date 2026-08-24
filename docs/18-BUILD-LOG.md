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
