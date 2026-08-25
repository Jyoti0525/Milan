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
| realistic | 84.4% | 90.6% | 96.9% | 100.0% | 100.0% | 1/1 |
| messy | 53.6% | 78.6% | 92.9% | 100.0% | 100.0% | 3/3 |
| adversarial | 23.8% | 61.9% | 90.5% | 100.0% | 100.0% | 8/8 |
