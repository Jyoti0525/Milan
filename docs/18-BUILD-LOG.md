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

---

## Day 3, later — the audit

Prompted by a fair question: the recommendation to cut Splink rested on the
Chaos Engine not producing damaged references, and *a generator not producing
something is not evidence that reality does not contain it*. That principle is
now written at the top of [19-TODO.md](19-TODO.md), because it bounds every
accuracy number in this project and it is easy to forget while looking at a
green test suite.

Auditing days 1-3 against the build order's own definition of done found seven
gaps. Four are fixed below; the rest are in the TODO with priorities.

### 1. Section 194-O had never run

`RateCard.tds_applies` defaults to `False` and no tier turned it on, so **zero
withholding rows had ever been generated** across all four tiers. Everything
downstream had therefore never executed: `_withholding()` in the waterfall, the
statutory-rate check that decides whether a deduction may be *called* TDS, and
the fallback label that exists to stop us attaching a citation to an
unattributed deduction.

It was unit-tested in `test_rates.py` and dead in integration - the state that
looks most like being finished. It is now a `--withholding` flag, and the
oracle test runs across all four tiers with it on. It passed first time, which
is the good outcome and also exactly why nobody noticed: correct dead code
raises no alarms.

```
Settled payments (45) across 3 settlements    Rs 1,72,844.16   45
Platform fee                                    -Rs 3,462.85   45
GST on platform fee @18%                          -Rs 623.30   45
TDS under Section 194-O @1%                     -Rs 1,728.43   45
Rounding drift (per-transaction fee vs batch-level GST) -Rs 0.02
Unexplained                                          Rs 0.00
```

### 2. "UTR corrupted" meant "UTR deleted"

`_narration()` was binary - a perfect reference or none. Real narrations
truncate at a field width, transpose characters when re-keyed, confuse O for 0,
pick up digits from an adjacent column, and get split by a delimiter. All five
are now generated, and none of them survives exact matching:

```
3O9K4443HH6S -> 'NEFT-3O9K4443-RAZORPAY SOFTWARE PVT LTD'
6SIG9HTI1O40 -> 'UTR6SIG9HTI-1O40 RAZORPAY PAYOUT'
1CDXCALQRL72 -> 'IMPS/1CDXCALQRL72340/RAZORPAY/SETTLEMENT'
```

### 3. A generator bug the new defect exposed

Adding damaged references sent the adversarial baseline to **3.4%** - far too
large a fall for a defect affecting 20% of credits, so it was worth not
believing.

The cause was mine, from day 2. `_merge_credits` only considered credits with
`defect is None`, so **merging systematically consumed exactly the credits the
first rung could resolve.** With six merges of up to three members each, it ate
nearly every clean credit; after damaged references shrank that pool further,
it ate all of them. Zero of 35 credits carried an intact reference.

The reference rung's score was therefore measuring that filter's taste rather
than how often a bank keeps a reference. A bank sweeping two transfers together
does not check the reference first, so merging now draws from any real payout.

This one is worth dwelling on. The bug was invisible for two days because it
*lowered* the baseline, and a lower baseline looks like a harder problem, which
is what we wanted to see. **A defect that flatters the story is the one that
survives longest.** The oracle test could not catch it either: the answer key
was entirely self-consistent, and the data was merely unrepresentative.

### 4. Numbers computed and never shown

`rules_share` - the share of exceptions sorted with no model at all, which is
the number behind every claim about where AI is and is not used - was computed
and rendered nowhere. So were `merged_rate`, `unreported_detection_rate` and
`exception_rate`. All now appear in `eval --detail`.

### Corrected numbers

600 orders, seed 42. The adversarial baseline is now 32.1%, not the 46.4%
reported earlier today - that figure was measured before damaged references
existed and before the merge bias was fixed, and it is superseded rather than
merely updated.

| Tier | Reference only | + amount and date | + subset sum | Precision | Refusals | Merged |
|---|---|---|---|---|---|---|
| clean | 100.0% | 100.0% | 100.0% | 100.0% | 0/0 | 0/0 |
| realistic | 77.1% | 94.3% | 100.0% | 100.0% | 1/1 | 2/2 |
| messy | 58.1% | 87.1% | 100.0% | 100.0% | 3/3 | 4/4 |
| adversarial | **32.1%** | 78.6% | 100.0% | 100.0% | 8/8 | 6/6 |

Identical with `--withholding` on, which is the point of the flag: the
reconciliation side is never told whether the merchant is subject to 194-O and
infers the withholding from the rows.

### Where Splink stands now

Better evidenced, and still not decided. Damaged references are generated, they
defeat exact matching completely, and the amount rungs absorb all of them with
no false positives. That is a real measurement rather than an argument from
silence.

What it still does not settle: the amount rungs absorb them *because amounts
are reliable in this generator*. Fuzzy matching would earn its place in the
case where the reference is damaged **and** the amount is ambiguous, and that
combination has not been constructed yet. Until it is, the honest position is
that Splink is unjustified rather than unnecessary.

### Two process notes

**A redirected command hid a failure.** `milan generate --withholding` was run
with `>/dev/null 2>&1` and reported success; typer had never registered the
flag, and a usage error looks exactly like success when the output is thrown
away. There is now a CLI smoke test asserting exit codes, and a persistence
round-trip test - `recon` reconciles what `generate` wrote, and a field lost in
serialisation would have made every downstream number wrong with nothing
failing.

**Dead code removed:** `ExceptionCode.ROUNDING` (never emitted - drift inside
the allowance is a proof line, not an exception), `total_pending()`,
`LedgerDirection`. A code nothing emits reads as a category the system
supports.

---

## Day 3, later still — measuring instead of promising

The pattern behind every gap found so far was pointed out plainly: things kept
being declared done and turning out not to be. A promise to be more careful
does not fix that. The two failure shapes are both mechanical, so the response
was to make them fail a test.

**Implemented but never exercised.** Section 194-O was written, unit-tested and
switched off everywhere.

**Computed but never surfaced.** `rules_share` was calculated on every run and
rendered nowhere.

### Coverage, added first

`pytest-cov` went in before any more code. It immediately found something worse
than either of the above: **`triage.py` at 46%.**

The uncovered lines were `_as_recovery_gap`, `_as_fee_variance` and
`_as_tax_variance` — the three specific-explanation branches of the
deterministic categoriser, which is Tier 1 item 10 and explicitly *not* a
fallback. Its three most valuable branches had never executed once.

Worse, the cause was a regression I introduced on day 2. The cascade veto
withdraws a claim that will not prove, so the pipeline stopped ever seeing an
unprovable match — and every credit that would have been explained as
"short by exactly refund R, which was recovered from batch B" became a generic
UNEXPLAINED. **The veto starved the categoriser, and the match rate went up
while the output quality went down.** That is the second time in three days a
defect survived because it flattered a headline number.

### Three conformance checks

`tests/conformance/` now asserts what no amount of care would reliably catch:

1. **Every exception code is emitted by some tier.** A code nothing emits reads
   as a category the system supports.
2. **Every matching rung produces a match somewhere.**
3. **Every scorecard figure reaches the screen** — read statically out of
   `render.py`, so a metric added and never displayed fails the build.

All four failed on first run: three exception codes unreachable, ten figures
computed and never rendered.

### What it took to make them pass

The ten unrendered figures were a rendering fix. The three unreachable codes
were not — they needed a defect class the generator could not produce.

**Payout variances.** Every existing defect either left the arithmetic intact
or removed a reference. None of them made the money that left disagree with the
report describing it. Three forms, all real: a fee deducted at a rate the
export does not show, GST taken at a non-statutory slab, and a refund whose
cash came out of a different batch than the one it is filed under.

That exposed a gap in the answer key. Such a credit is perfectly
*identifiable* and cannot be *proved*, and `matchable` could not express the
difference. Marking it matchable counted correct behaviour as a false
negative; marking it unmatchable claimed we could not identify a credit whose
reference is sitting right there. So `provable` is now a separate field, and
scoring has three outcomes rather than two:

- **matchable and provable** — match it and prove it. The match rate.
- **matchable, not provable** — name the shortfall. Never claim it.
- **not matchable** — refuse.

**Two bugs the new defect surfaced.** The fee check was reading the report
against *itself*, so it could not see a bank-versus-report gap at all, and once
rewritten to read the shortfall it was loose enough to answer for tax variances
too — a rate range fits almost any number. Reordering the checks by how
specific they are (a refund matches to the paisa, a GST slab to a published
rate, a fee surcharge merely divides into gross) fixed it. And a credit
carrying both a damaged reference and a variance recorded only the first, which
made the per-defect breakdown quietly wrong about what was costing us.

### Where it stands

600 orders, seed 42. `triage.py` is at 100%, the project at 98%, 203 tests.

| Tier | Reference only | + amount/date | + subset sum | Precision | Refusals | Shortfalls named |
|---|---|---|---|---|---|---|
| clean | 100.0% | 100.0% | 100.0% | 100.0% | 0/0 | 0/0 |
| realistic | 87.9% | 93.9% | 100.0% | 100.0% | 1/1 | 1/3 |
| messy | 53.6% | 85.7% | 100.0% | 100.0% | 3/3 | 3/4 |
| adversarial | 33.3% | 71.4% | 100.0% | 100.0% | 8/8 | 4/6 |

The shortfall column is the honest new one, and it is deliberately not 100%.
The credits we cannot name lost their reference *as well as* being short —
nothing identifies which settlement is missing money, so the only truthful
output is UNEXPLAINED. The breakdown says so by defect rather than leaving a
reader to assume it was a failure.

---

## Days 4-5 — matching core

Three steps, in plan order, each committed before the next started.

### 1. Instant refund fees

The last unmodelled line in the money rules. An ordinary refund costs the
merchant nothing to process; an instant one costs a flat Rs 7.99, Rs 11.99 or
Rs 14.99 by size.

Flat is what makes it worth having. Every other deduction scales with the
transaction, so a few rupees adrift on a large batch reads as rounding. This
one does not scale - it is noise on a big refund and a real percentage on a
small one, which is the shape of charge that gets written off as "some bank
fee". So it gets its own proof line rather than being folded into the platform
fee, which meant batch fee and tax had to start meaning the payment side only.

Two tests failed and both were the tests, not the code: the drift formula was
summing every row's tax when drift is a payment-side concept, and a
damaged-reference filter used exact string equality that had stopped matching
anything once defects became combinable.

### 2. The anchored subset-sum, and a hypothesis that was wrong

Decision 84 said a withdrawn claim should constrain the combination search: a
merged credit carrying member A's reference is a credit whose answer contains
A. Built it, then A/B'd it on identical datasets.

**No difference.** Not on any tier, not on the colliding merchant.

The remaining failure turned out to be a merged credit with *no reference at
all*, so there was nothing to anchor on - the improvement was structurally
inapplicable to the case it was meant to fix. Rather than delete it or claim
it worked, the case where it decides is now constructed directly in a test:
four settlements where A+B and C+D total the same, with A's reference
withdrawn. Without the anchor the rung refuses, correctly. With it, it
resolves. So it works, it is proven, and it is honestly recorded as not yet
changing any tier-level number.

### 3. The similarity rung, which should never have been dropped

Cutting Splink was right about the library. Treating that as licence to skip
Tier 1 item 5 was not, and it was compounded by quietly excluding
`FUZZY_NARRATION` from the conformance check that asserts every rung matches
something - exactly the kind of exclusion that hides missing work.

So the rung got built: `difflib` over a normalised narration, bank words
stripped first because they are long runs of capitals and would otherwise
compete with the reference, and a sliding window so a split reference rejoins.
It runs last, needs a decisive margin rather than merely a best candidate, and
its claim is still subject to the proof veto.

Then the conformance check failed: **it matched nothing.** Every credit
reaching it had already been resolved by arithmetic. Built, wired, and dead.

The fix was to generate the case it exists for rather than excuse it. Twin
credits, identical amount, identical date - so arithmetic has nothing to say
about either - where one narration carries a damaged reference and the other
carries none. That resemblance is then the only evidence in the dataset that
separates them, and a system that can only compare strings for equality has to
refuse the pair.

With that in place, on the same seeds:

| Merchant | Tier | + subset sum | + fuzzy | Gain |
|---|---|---|---|---|
| mixed | adversarial | 90.5% | **100.0%** | +9.5 |
| colliding | messy | 83.3% | **94.4%** | +11.1 |
| colliding | adversarial | 72.7% | **90.9%** | +18.2 |

Precision stays at 100% throughout, and a test asserts the rung earns its
place - that removing it costs matches - so it cannot quietly become dead
weight again.

**What this says about the earlier decision.** The measurement that led to
cutting the fuzzy capability was not wrong about the data it had; it was wrong
about what that data covered. The rung was unnecessary *for the defects then
generated*, and the right response to that was to ask which real defect was
missing, not to conclude the technique was unnecessary in general. That is the
same mistake as arguing from the generator's silence, one level up.

### Where it stands

226 tests, 97% coverage, all four tiers reproducible. 600 orders, seed 42:

| Tier | Reference | + amount/date | + subset sum | + fuzzy | Precision | Refusals |
|---|---|---|---|---|---|---|
| clean | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0/0 |
| realistic | 84.4% | 90.6% | 96.9% | 100.0% | 100.0% | 2/2 |
| messy | 53.6% | 78.6% | 92.9% | 100.0% | 100.0% | 5/5 |
| adversarial | 23.8% | 61.9% | 90.5% | 100.0% | 100.0% | 10/10 |

*(The refusal column above is corrected. As first written it said 8/8 on every
row, carried over from an earlier run. Day 6 found it and made it impossible
to happen again - see below.)*

---

## Day 6 — the verification pass, and what it found

Day 6 in the build order is "waterfall solver + eval harness with baselines +
property tests". All three already existed, so the work was to hold each one
against the definition of done rather than to build anything:

> It has a test / it runs from the seeded command / its numbers appear in the
> eval harness output / it works with the LLM turned off.

That is a boring exercise when it passes. It did not pass.

### 1. The drift total, which was the one box still open

Rounding drift is explained inside a proof and never raised as an exception,
which is right - a credit that reconstructs to zero has nothing to raise. But
the merchant-facing figure is the *total*, and no code computed it.

`Proof.drift` now carries the paise a proof closed on the allowance rather
than on the rows, and the scorecard totals it two ways. Gross and net are both
reported, in that order, because drift largely cancels: net alone would read
as "this does not happen" when what it means is "this happens in both
directions".

| Tier | Proofs needing the allowance | Gross | Net |
|---|---|---|---|
| realistic | 14 | Rs 0.19 | -Rs 0.01 |
| messy | 13 | Rs 0.18 | -Rs 0.02 |
| adversarial | 8 | Rs 0.14 | -Rs 0.02 |

The number is small, and it is the honest number. What matters is that it is
now computed rather than assumed to be small.

It is a field on the proof rather than a search for the drift line, because a
total assembled by matching on a label silently becomes zero the day somebody
rewords the label.

### 2. `eval` was scoring whatever happened to be on disk

Found by accident, and the worst thing here.

`milan eval` loads a stored dataset and scores it. It never checked that the
stored dataset was one *this* generator produces. A run generated before the
reference-twin defect was added was still sitting in `data/`, and `eval`
scored it happily: baseline 33.3% against a published 23.8%, eight impossible
credits against ten, and nothing on screen suggesting anything was wrong.

Numbers from a stale dataset are not slightly off. They are about a different
merchant.

`save_dataset` now writes the `GenerationConfig` beside the data, and
`load_dataset` regenerates from it and compares digests before returning.
Twenty milliseconds at six hundred orders. A mismatch, or a missing config, is
`StaleDatasetError` - refused, not warned about, with the exact regenerate
command in the message. The CLI turns it into an exit code rather than a
traceback, and a test asserts that.

The library keeps a `verify=False` escape hatch for inspecting a file. The
command line deliberately does not have one, because a flag that lets you
score stale data is a flag that gets used.

### 3. The README's numbers had already gone stale

Same class of defect, one layer out. The published table's match rates were
current; its refusal column had been carried over from an earlier run and said
8/8 where every tier now says something else. A reader cannot catch that, and
in a project whose entire claim is measurement, a wrong number in the README
is not a documentation problem. It is the claim being wrong.

So the table is no longer typed. `milan eval --markdown` prints it, the README
holds it between generated-block fences, and `tests/integration/
test_published_numbers.py` fails if a fresh run disagrees with what is
published. Two of its cases guard the specific superseded figures, so the old
numbers cannot come back by a copy-paste.

Corrected, and it is the refusal column that was wrong, not the match rates:

| Tier | Reference | + amount/date | + subset sum | + fuzzy | Precision | Refusals |
|---|---|---|---|---|---|---|
| clean | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0/0 |
| realistic | 84.4% | 90.6% | 96.9% | 100.0% | 100.0% | 2/2 |
| messy | 53.6% | 78.6% | 92.9% | 100.0% | 100.0% | 5/5 |
| adversarial | 23.8% | 61.9% | 90.5% | 100.0% | 100.0% | 10/10 |

### 4. Nothing tested the scorer

Every number in the submission comes out of `score()`. The oracle test proves
the matcher is right; nothing proved that the thing *grading* the matcher was
right. A scorer that counted a wrong match as correct would raise every
published figure at once, and every other test in the suite would stay green.

`tests/unit/test_scoring.py` builds reports by hand with the answer known and
asks the scorer what it makes of them. Several cases are the design stance
itself, which until now existed only as prose:

- a forced answer on an impossible credit is a false positive **even when it
  is right**
- a merged credit matched to one of its two settlements is not half a success
- a proof that does not balance is not a claim at all - neither credited nor
  counted against precision
- a guesser and an honest system tie on match rate and separate on precision

Fifteen cases, all green first time. The scorer was correct. It is worth being
plain that this found no bug: the value is that the stance is now enforced
rather than described, and the next person to "improve" the match rate has to
argue with a test.

### 5. The property tests never reached the waterfall

Thirteen invariants existed, covering money arithmetic, batch arithmetic and
reference extraction - every layer *below* the interesting one. Day 6 pairs
the waterfall with property tests for a reason, and the waterfall had none.

Ten new invariants, over `prove`, over the veto, and over the combination
search. Then, because a test that has never failed is a test of unknown
strength, each was checked by mutation:

| Mutation | Caught by |
|---|---|
| allowance one paisa too wide | the veto/proof agreement |
| veto looser than the proof | the veto/proof agreement |
| subset-sum tolerance widened by Rs 50 | nothing, at first |

The third is the useful entry. The combination test built its targets as exact
subset sums, and on an exact target a correct solver and a sloppy one return
the same set - so the invariant held under a mutation that would have let the
rung claim a combination Rs 50 short. Rebuilt to perturb the target off the
combination, it fails on the mutation and passes on the real code. A property
test that cannot fail is a comment.

### 6. Two live defects in the similarity rung, found by asking whether a
reference is similar to itself

The first property to run, `similarity(x, x) == 1.0`, failed immediately on
`2222222222CR`.

The noise-word pattern had no word boundaries, so `CR` was stripped from
anywhere - including from inside a reference. `JMSS5NDW4CR` normalised to
`JMSS5NDW4`, and the same applied to any reference containing ACH, LTD, PVT or
UTR. The rung's only evidence was being quietly shortened before it was
weighed.

Adding boundaries fixed that and broke the messy tier: 100% to 96.4%. The
missed credit's narration was `UTRRKBZWJLK RAZORPAY PAYOUT` - the bank's own
label glued straight onto a reference that had itself been truncated, so the
narration was *shorter* than the reference it contained. The window sweep was
sized from the reference length and stopped three characters before the
alignment that matches.

Both are real bank behaviour and the fix had to cover both: boundaries so a
reference keeps its own characters, and a sweep over every start position so a
glued label is stepped past rather than surgically removed. The docstring
already claimed the function found a reference "anywhere inside a narration";
the sweep was a premature optimisation that made the claim false.

All four tiers back to 100% at 100% precision, and the rung is more robust
than it was before the property test ran. Throughput on the adversarial tier
fell from about 71k to 49k records per second, which is the honest cost and
still far above anything this has to clear.

**The general lesson, again.** Both defects are invisible to example-based
tests, because a person writing a test narration picks a reference that reads
like a reference. Neither would have shown up as a wrong answer either - they
degrade a score, and a degraded score looks like a hard case.

### Also

- mypy now checks `tests/` as well as `src/`. The tests construct the same
  models the engine does, so an annotation that has drifted from a record's
  real shape is a test asserting something about a type that no longer exists.
  Six errors, all annotation gaps, all fixed. One was real in a small way: a
  verifier written with a parameter named `candidate` did not satisfy the
  `Verifier` protocol, which names it `credit`.

### Where it stands

263 tests, 97% coverage, four tiers reproducible, `milan reproduce` identical
on adversarial. Day 6's three components now each pass all four clauses of the
definition of done, which two of them did not when the day started.

---

## Day 6, later — the generator could hang, and one seed was not a measurement

Both of these were found while trying to answer the Splink question, which
needed the colliding merchant. It would not generate.

### The amount draw was unbounded rejection sampling

`_draw_amount` drew from a lognormal and rejected anything outside the
merchant's price window. On the default window - Rs 199 to Rs 48,000 - almost
everything is accepted and the loop costs one draw. On a narrow window it
costs one over the acceptance probability, and **on a single-price merchant it
costs everything**: forty orders took twenty-two seconds and eleven million
discarded samples. A window the distribution cannot reach would never have
finished at all, with no error, no log line and no progress.

The single-price merchant is not a curiosity. It is the benchmark shape built
on day 3 specifically to make batch totals collide, and it is the only regime
in which the amount rungs genuinely fail - so the config that mattered most
for measuring the matcher was the config the generator could not produce.

Replaced with inverse-CDF sampling over the window: draw uniformly between
`F(low)` and `F(high)` and invert. Same truncated lognormal, computed instead
of searched for. **22.65s to 0.00s.** A degenerate window returns the single
price; a reversed one is now rejected by the config rather than hung on.

The random stream changed, so every seeded figure moved. Match rates and
precision did not (adversarial is identical to the paisa); the realistic and
messy baselines fell, which is the truncation being applied properly rather
than approximated by rejection. The README test caught the change immediately,
which is the second time in one day that test has done its job.

It also exposed a latent test bug of the same shape as an earlier one:
`_row_tax_total` summed every row's tax, including the GST on an instant
refund charge, and compared it against a batch figure that only ever counted
payment rows. It passed for as long as no batch happened to contain an instant
refund. The gap was 216 paise - exactly 18% of the Rs 11.99 slab.

### One seed is not a measurement, for one of the figures

Twenty adversarial seeds, 600 orders each:

| Measure | Pooled | Of | Worst seed | Median | Best seed |
|---|---|---|---|---|---|
| match rate | 100.0% | 389/389 | 100.0% | 100.0% | 100.0% |
| precision | 100.0% | 389/389 | 100.0% | 100.0% | 100.0% |
| refusal rate | 100.0% | 200/200 | 100.0% | 100.0% | 100.0% |
| shortfalls named | **55.0%** | 66/120 | **16.7%** | 50.0% | **83.3%** |
| merged credits resolved | 100.0% | 120/120 | 100.0% | 100.0% | 100.0% |
| missing payouts flagged | 100.0% | 40/40 | 100.0% | 100.0% | 100.0% |
| unsettled payments flagged | 100.0% | 153/153 | 100.0% | 100.0% | 100.0% |

The headline figures are solid and now have real denominators behind them:
**389 credits matched with nothing wrongly claimed, and 200 impossible credits
refused without one forced answer.**

One figure is not solid at all. `shortfalls named` has a denominator of about
six per run and swings from 17% to 83%. The single-seed README had been
showing 5/6 before the sampler change and 3/6 after, and **both were noise**.
The honest number is 55% of 120, and it is the weakest thing this system does.

That is worth stating plainly rather than burying: naming *why* a payout
disagrees with its report - as opposed to detecting that it does - works
slightly more than half the time. Detection is 100%; explanation is 55%. Day 8
and 9 are where that number has to move.

`milan sweep` pools the counts rather than averaging the rates, because a run
with six shortfalls and a run with two should not count equally toward a
percentage. It runs the headline configuration only - the ablation ladder is
the point of a single evaluation and pure cost across twenty seeds - which
brings twenty seeds to 1.4 seconds and lets the README's pooled table be
checked in the ordinary test run.

---

## The Splink question, settled by measurement

The call was: work out whether we need it, then use it or do not. So it was
measured rather than argued, and the measurement had to survive the rule that
sank the last version of this decision - **"our generator does not produce the
case" is not evidence the case does not exist.**

Two questions, on the standard tiers and on the colliding merchant (single
price, one fee rate, so batch totals genuinely collide and the amount rungs
stop working), eight seeds each.

### Is our own similarity measure what is limiting us?

If a better engine could win, the crude one must be losing. So the floor was
dropped from 0.78 to 0.45 and the decisive margin from 0.10 to 0.00 - which is
"answer with whatever ranks top, always", the most permissive string matcher
there is.

| Tier | Shape | Floor | Margin | Correct | False + |
|---|---|---|---|---|---|
| messy | standard | 0.78 | 0.10 | 211/211 | 0 |
| messy | standard | 0.45 | 0.00 | 211/211 | 0 |
| messy | colliding | 0.78 | 0.10 | 151/157 | 0 |
| messy | colliding | 0.45 | 0.00 | 151/157 | 0 |
| adversarial | standard | 0.78 | 0.10 | 151/151 | 0 |
| adversarial | standard | 0.45 | 0.00 | 151/151 | 0 |
| adversarial | colliding | 0.78 | 0.10 | 95/104 | 0 |
| adversarial | colliding | 0.45 | 0.00 | 95/104 | 0 |

**Removing the threshold entirely gains nothing.** Not one record, on any tier,
in either shape. Whatever is holding those 9 and 6 credits back, it is not the
strictness of the comparison - and a more sophisticated comparison cannot beat
one that has already been allowed to answer unconditionally.

### Is there anything in that column to be sophisticated about?

For every unresolved credit, the best similarity between its narration and its
true settlement's reference:

| Tier | Shape | Unresolved | Carrying narration evidence |
|---|---|---|---|
| messy | standard | 0 | 0 |
| messy | colliding | 6 | 2 |
| adversarial | standard | 0 | 0 |
| adversarial | colliding | 9 | **0** |

The normalised narrations of the adversarial failures are `'RZPY'`, `''`,
`'RZPY'`, `'CRAZORPAYSOFTWARE'`, `''`. The bank sent no reference. There is no
string there to match well or badly, and every one of them is a
`MERGED_CREDIT` - several payouts swept into one transfer with the reference
dropped.

The two exceptions are the interesting ones, and they argue the same way.
Both scored **1.00** - a perfect, undamaged reference - and both are still
unresolved, because they are `MERGED_WITH_REFERENCE`: the reference identifies
one member of the set, and the answer is the whole set. No linkage library
addresses that. It is the anchored subset-sum path from decision 84, and it is
arithmetic, not string comparison.

### The decision

**Splink is not needed, and this is now a measurement rather than a
preference.** The capability it would provide is already present, already
running as rung four, and already unconstrained by its own thresholds. The
records we cannot resolve fail for a reason no string method reaches: either
there is no reference at all, or there is a perfect one that names a member
rather than a set.

Recorded with the boundary of the claim, because that is the honest form:
this says Splink adds nothing **to the defect catalogue we generate**, on both
the standard shape and the hardest shape built specifically to break the
amount rungs. If a defect class turns up where many weak signals across
several columns have to be weighed together - which is the problem Splink is
actually built for - the answer changes, and the first move would be to
generate that defect rather than to reach for the library.

---

## Day 7 — the exception queue

The one the cut rules say is never cut, because it carries the video.

### The API had to exist first

`web/` was empty and had nothing to read from. The architecture doc says
FastAPI is the backend, so that is what got built - thin, because every
decision worth making has already been made in the engine and an API that
starts making its own is a second implementation of the same rules that will
disagree with the first one eventually.

Two things it does that the engine's own output does not:

**It joins exceptions back to their subject.** A `ReconException` names its
subject by id, which is all the pipeline needs and nothing a person can act
on. "bank_x9f2 is short Rs 812" is a spreadsheet row; the same case with the
amount, the date and the bank's verbatim narration beside it is something
somebody can pick up. And the three kinds of subject are genuinely different
people's problems - a credit that arrived unexplained, a payout the gateway
says it sent that never arrived, and a payment the customer made that the
report never mentions - so they are distinguished rather than flattened into
"an id and an amount".

**It computes the running total server-side.** A reader is being invited to
check that the proof lines close, and arithmetic that matters belongs on the
side of the wire that has tests.

Two boundaries are enforced by tests rather than by care:

- **The answer key never leaves the engine.** `milan.recon` may not import
  ground truth; a JSON route serving it to a browser would walk around that
  boundary rather than break it, which is worse, because nothing would fail.
  A test greps the whole payload for `matchable`, `provable`, `answer_key`
  and friends. Scores are still reported - computed inside the evaluation
  package, never exposed record by record.
- **Money crosses as integer paise.** Not a formatted string and above all
  not a float. A test walks the entire response at any depth and fails on a
  float in any field named like money.

### The interface

Next.js 16 as scaffolded (the plan said 15; the current release is 16 and
nothing in the breaking-change list touches this code - no `params`, no
middleware, no `next/image`, no caching APIs).

The design brief in the tech-stack doc is a constraint rather than taste:
**must not look AI-generated.** No gradients, no hero, no forty-pixel cards,
no default shadcn. Finance tools are dense and precise - thirty-pixel rows,
hairline rules, tabular numerals so a column of rupees lines up on the
decimal, colour spent only on state. Somebody reconciling a month is scanning
a few hundred rows for the one that is wrong, and padding is rows they cannot
see.

The screen is a run bar, a list, and a detail pane. Two tabs on the list
because there are two halves to an honest answer: **Queue** is what could not
be resolved, **Proved** is what could, openable line by line down to
`Unexplained 0.00`.

Loading state is derived, not stored. The loaded run is held together with the
key of the run it belongs to, so a slow response for a run you have navigated
away from cannot arrive last and win, and a spinner cannot be left on after a
failure. React 19's lint rule caught the first version of that, correctly.

### Three defects found by running it rather than by testing it

**`/api/runs` returned a 500 because one run on disk was stale.** A dataset
generated before the sampler change was still in `data/`, and the freshness
check raised inside the listing. So the picker could not show the very run the
person needed to be told to regenerate. Listing is metadata; opening is the
thing that has to be trustworthy. Runs are now listed unverified and marked
`stale`, and the check stays where it matters.

**CORS blocked the browser, and the temptation was to widen it.** `next dev`
found port 3000 taken and moved to 3002, which the allowlist deliberately does
not include. The allowlist is narrow because this serves settlement data, and
the version of it that ships with `allow_origins=["*"]` because it was
convenient during a hackathon is the version that stays that way. Added
`MILAN_WEB_ORIGIN` instead: a deliberate, per-machine addition rather than a
permanent hole.

**The queue said `fits 1 settlements equally well`.** The grammar is what made
it visible. The substance is why it mattered: ambiguity has two shapes and
this was reporting the wrong one. A credit that fits several settlements asks
*which payout arrived*; several credits that fit one settlement ask *which of
these bank lines is the payout*. They send whoever picks up the case to
different files, and `_resolve_collisions` was producing the second while the
categoriser described the first.

`Attempt.contested_by` now carries the rival credits, and the queue says:

> Rs 2,06,784.14 on 2026-07-21 and 1 other credit all fit settlement
> setl_xzxbqya4bcfsrh. Only one of them can be it, and nothing in the evidence
> says which.

with the rival's id in the evidence, so both bank lines can be pulled up
together. Nine tests cover the two shapes and assert they never produce the
same sentence.

That defect had been in every run since the collision resolver was written.
Every number was right; the sentence explaining one class of refusal was
wrong, and no test looked at the sentence.

### Where it stands

318 tests, 97% coverage, plus 11 on the browser's money formatter - which
exists because the API refuses to send formatted strings, and which is held to
the same table as `format_inr` so the two implementations of Indian digit
grouping cannot drift apart in the middle of a large number.

Tier 1 is complete. Every item on the list is built, tested, and its numbers
appear in the eval harness output.
