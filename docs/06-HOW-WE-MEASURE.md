# How We Measure

Razorpay's bar: *"Throughput plus measured accuracy plus an honest exception
list. One cherry-picked match proves nothing."*

Everything here exists to answer that bar directly.

## Rule 0 — what "seeded" means, and why every number depends on it

A **seed** is the starting number for the random generator. Fix the seed and the
generator produces the **identical dataset every single time**. Seed 42 today,
seed 42 next month: same 50,000 rows, same defects, same answer key.

### Why this is required, not optional

> Razorpay clones our repo, runs one command, and gets **the exact numbers we
> claimed in the video**.

Without a seed they generate different data, get different numbers, and every
claim we make becomes unverifiable. **A number nobody can reproduce is worthless.**

It also gives us:
- Exact bug reproduction ("it fails on record 4,471" is actionable)
- Fair model comparison (Qwen 3B vs Llama 70B is only valid on identical data)
- A working response cache (same prompts, so re-runs are free)

### The thing people get wrong

> **Seeded does NOT mean easy, fake, or rigged. Seeded means REPEATABLE.**

Difficulty and repeatability are completely independent. Our Adversarial tier
will be brutally hard AND seeded. The seed controls *which* data you get, never
*how hard* it is.

Seeding makes us MORE credible, not less. It is the difference between
"trust our 94%" and "run this command and check our 94% yourself."

Razorpay's brief requires synthetic data. Seeding is synthetic data done
properly instead of sloppily.

## Rule 1 — a number with no baseline means nothing

We never report a bare "94% match rate." We always report a comparison table:

| System | Auto-match rate |
|---|---|
| Naive baseline (exact ID only) | we measure it |
| Rules-only tier | we measure it |
| **Full system** | we measure it |
| Published industry range | **60-70% rules-only / 85-95% rules+AI** |

Those industry figures are real and published. Comparing against them costs us
almost nothing and makes our number mean something. Very few submissions will
do this.

## Rule 2 — precision matters more than match rate

A **wrong silent match** corrupts the books.
A **flagged exception** costs a human five minutes.

So we report both, and we treat precision as the headline:

- **Match rate** — how many did we match?
- **Precision on auto-matched** — of the ones we matched, how many were right?
- **Correct refusal rate** — of the impossible ones, how many did we correctly give up on?
- **False match count** — this should be ZERO, and we say so loudly

## Rule 3 — publish the degradation curve

Four difficulty tiers, four numbers. We show where we break.

| Tier | Match rate | Precision | Exceptions |
|---|---|---|---|
| Clean | | | |
| Realistic | | | |
| Hostile | | | |
| Adversarial | | | |

## Rule 4 — the LLM-off experiment

Run the entire pipeline with the model disabled.

Target claim:
> *"With the LLM off, match rate falls from X% to Y%, and zero incorrect
> matches are introduced."*

This proves the core is sound and the AI is additive, not load-bearing.
It is one experiment and it is rare. Very high value for very low effort.

## Rule 4b — three model configurations, compared

Run triage under three configurations and publish the table:

| Config | Triage accuracy | Parse-fail rate | Cost |
|---|---|---|---|
| Off (deterministic categoriser only) | n/a | n/a | **Rs 0** |
| Ollama Qwen 2.5 3B (local) | measure | measure | **Rs 0** |
| Ollama Qwen 2.5 7B (local) | measure | measure | **Rs 0** |
| Groq Llama 3.3 70B (free tier) | measure | measure | **Rs 0** |
| Gemini 3 Flash (free tier) | measure | measure | **Rs 0** |

Proves the core stands alone, proves a zero-cost deployment path exists, and
proves we measured rather than assumed. See `08-TECH-STACK.md`.

## Rule 5 — cost per 1,000 records (actual AND projected)

Our actual spend is **Rs 0** — everything runs local or on free tiers. A column
of five zeroes proves nothing on its own, so we report two things:

1. **Actual: Rs 0.** Plus wall-clock time and records/second, which are real.
2. **Projected:** what this workload *would* cost per 1,000 records on a paid API,
   computed from measured token counts x published rates.

The projection is the part that shows product thinking: a finance tool costing
more than the clerk it replaces is worthless. And because our architecture only
calls the model on the exception residue, the projected number is small — which
is the point worth making.

## Rule 6 — the honest exception list

Not a count. A categorised, exported list where every single exception has:

- its category (`FEE_DEDUCTION`, `ROUNDING`, `UNEXPLAINED`, etc.)
- why the system could not resolve it
- what a human would need to resolve it

## Rule 6b — a forward schedule is marked against data it could not read

The forward cash position is the only figure in this project about a day that
has not happened, so it gets the strictest version of Rule 0. A schedule is
built from payments captured on or before one chosen day and payouts already
made by it; every settlement row written after that day is withheld, and then
used to mark the schedule.

Reading a future row would be the same failure as scoring a matcher against its
own output. It exists in the file the function is handed, and not reading it is
what makes the number below a measurement rather than a restatement.

Measured over **4 tiers x 6 seeds x 3 vantage days at 600 orders**:

| What is checked | What holds |
| --- | --- |
| Date | Every wrong date belongs to money that never settled at all. On money that arrived, the scheduled day has been the day it arrived. |
| Amount | The error is the fee leak — the overcharge plus the GST on it, to the paisa. Tiers with no rate mismatch have no amount error. |
| Control | A clean tier is exact on both, or the schedule is broken rather than cautious. |

Two guards keep it from passing by having nothing to check: a floor on how many
commitments must reach the measurement at all, and a separate class asserting
the clean tier is perfect. Both fail before any accuracy floor does.

The blind spots are generated rather than described. Instant settlement was
generated at 40% and 80% to cost the schedule its dates and cost it nothing —
an instant payout is already in the bank by the time a schedule is drawn, so
it is omitted rather than mis-dated. Route was generated at 15%, 30% and 60%
and turned out to be modellable after all, because a transfer row carries the
capture timestamp rather than the payout's; it is netted exactly at every
share. Refunds not yet raised are uncosted permanently, and that is recorded
as a limit rather than a task: reaching a decision a customer has not made
would mean predicting.

## Rule 6c — an induced contract must not explain away what it learns from

Learning a rate card from a merchant's rows is circular unless it is measured:
whatever the gateway charged becomes what it was contracted to charge, and the
leak detector goes silent. So `milan.rules` is graded on both halves at once —
does it recover the contract, *and* does the leak check still work against the
card it produces.

Over **4 tiers x 12 seeds at 600 orders**:

| What is checked | What holds |
| --- | --- |
| Contract recovered | 48 / 48 months, exactly — including a negotiated card none of the defaults would produce |
| Leaks still found | 693 / 693 |
| Leaks missed | 0 |
| False accusations | 0 |

The last two decide whether it was safe to build at all. The rule it rests on
is stated rather than assumed: an overcharge is a minority, so the modal rate
over a band is the contract and the rows that disagree are the leak. A band
that splits evenly is refused and both rates are named, because the more
popular of two rates is a guess wearing a majority.

It is wired only into the paths that never had a rate card. Every graded figure
here passes one explicitly, so nothing measured can move because a detector
changed its mind.

## Rule 7 — throughput, measured properly

- Records processed
- Wall-clock time
- Records per second
- A note on complexity: subset-sum is NP-hard, so we state how we bound the
  candidate space (blocking) rather than hand-waving

## The sentence we want to be able to say

> "N records. X% auto-matched at Y% precision. Z exceptions, every one
> categorised. M records were unmatchable by construction — it caught M-k and
> wrongly matched zero. Runs in T seconds at Rs 0 actual cost.
> Here is the full failure list."

**These letters are placeholders, deliberately.** Every one gets filled by
measurement, never by estimate. No number appears in the video or README that
did not come out of the eval harness.

No other submission can say that sentence.

## Tests — because this is a verification tool

Shipping an unverified verification tool would be fatal irony.

Property-based tests (Hypothesis) on financial invariants:

- The waterfall must always balance to zero
- No record may appear in two settlements
- TDS is never applied to the GST component
- Re-running a cycle never double-counts
- Same seed always produces identical output

## Rule 9 — use the industry range to validate our DATA, not just our system

Published figures: rules-only clears 60-70%, rules+AI reaches 85-95% on real
messy data.

We generate our own data, so we could accidentally make it too easy and report a
meaningless 99%. The check:

> **If our "Realistic" tier scores far above the industry range, our data is not
> realistic — the generator is wrong, not the system right.**

This uses the benchmark as an honesty check on ourselves. It is the difference
between measuring and flattering ourselves.

Rough expectations per tier (to be confirmed by measurement, not assumed):

| Tier | Expected match rate |
|---|---|
| Clean | 97-99% |
| Realistic | 88-95% |
| Hostile | 75-88% |
| Adversarial | 60-80% |

**False matches should be ZERO at every tier.** That one is a real target, not an
estimate, because we control the confidence threshold and can set it conservative.

## Rule 10 — the LLM-matcher ablation

Build the thing everyone else is building — a naive LLM matcher — run it on
identical data, and publish the comparison:

| | LLM matcher | Our deterministic core |
|---|---|---|
| Accuracy | measure | measure |
| Speed | measure | measure |
| Cost | measure | Rs 0 |
| **Same answer twice?** | **No** | **Yes** |

The last row is the point. **An LLM matcher run twice on the same data produces
different books.** In financial records that is disqualifying, and it can be
demonstrated live.

This is a *measurement*, which is why it belongs here and not only in the
architecture argument. It converts "we chose not to use AI there" from an
assertion into a result.

**If the ablation shows LLM matching is competitive, we reconsider the
architecture.** The experiment decides, not our priors.

Full context in `17-AI-INVOLVEMENT.md`.

## Rule 8 — state the limits explicitly

The README gets a **"What this cannot do"** section. Honest, specific, unhedged.
For example: single currency only, no multi-entity netting, assumes the order
book is authoritative, no live bank API.

Engineers trust people who state their limits. Almost no submission will have
this section, and it costs nothing to write.
