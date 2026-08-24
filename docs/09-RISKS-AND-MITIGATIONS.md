# Risks and Mitigations

Four named risks. Each has a concrete control, not a hope.

---

## RISK 1 — The Chaos Engine slips (HIGHEST PRIORITY)

**Why it matters:** every number we report and our headline differentiator
(leak detection) both sit on top of the generator. If it is wrong, everything
above it is wrong and we will not know.

### Control 1: The Oracle Test  <- the important one

After generating a dataset, run a **perfect oracle matcher** against it — a
matcher that does nothing but read the answer key.

> **The oracle must score exactly 100.00%. Not 99.9%.**

If the oracle scores anything less, **the generator is broken, not the matcher.**

This completely isolates generator bugs from matching bugs. Without it, a
generator bug looks exactly like a matcher bug and we can burn a day chasing the
wrong thing.

Run the oracle test on every regeneration, in CI.

### Control 2: Invariants on the generator itself

Property tests (Hypothesis) that must hold for EVERY generated batch:

- Gross minus all deductions equals the net credit, to the paise
- Every order appears in exactly one settlement
- No settlement references an order that does not exist
- The answer key is internally consistent
- TDS is never computed on the GST component
- Every injected defect is recorded in the answer key

### Control 3: Each defect type gets its own test

Injecting rounding drift, rate mismatch, double-netting, late refunds and
impossible records are five separate features. Each gets a unit test that
proves the defect was actually injected at the requested rate.

A defect we think we injected but did not = a leak we cannot detect and will
not notice.

### Control 4: Build it first, then FREEZE it

- Build days 2-3, before any matching logic
- **Freeze by day 4**
- After freeze, changing the generator invalidates every measurement taken
  before it

### Control 5: Version the datasets

`data/v1/`, `data/v2/`. Every regeneration bumps the version and records its
seed. Any reported number cites the dataset version it came from.

Prevents the worst failure mode: *"our numbers changed and we do not know why."*

---

## RISK 2 — Splink's learning curve eats two days

### Control: Interface first, naive implementation immediately

Define the interface on day 1:

```python
class FuzzyMatcher(Protocol):
    def score(self, a: Record, b: Record) -> float: ...   # 0.0 - 1.0
```

Ship a **rapidfuzz-based implementation the same day.** It will be worse than
Splink. It will work.

Splink then becomes an **upgrade behind a stable interface**, never a blocker.

### Control: Timebox

4 hours to get Splink working on our data. If it is not working, stop, ship the
rapidfuzz version, and revisit only if Tier 1 is complete.

### Control: Document the decision either way

If we ship rapidfuzz, we say why. "We tried Splink, it cost more than it
returned at our data scale, here is the comparison" is a perfectly good answer —
arguably a better one than using it because it looks impressive.

---

## RISK 3 — Subset-sum is NP-hard and blows up at scale

### The key reframe: this risk cannot hurt correctness

**The honest fallback for an intractable case is an EXCEPTION, not a wrong answer.**

If the search space is too big, we do not attempt it — we flag it. That is a
legitimate, honest outcome that fits our precision-over-recall stance exactly.

So NP-hardness can only cost us **match rate**, never **correctness**. And we
report match rate honestly anyway. The risk is bounded by design.

### Control: Blocking collapses the problem

Candidates are not 50,000 records. They are bounded by:

- Settlement date window (T+2 is known)
- Payment method
- Currency
- Already-settled flag

In practice this reduces candidates from ~50,000 to ~hundreds per settlement.

### Control: Integer arithmetic

Work in **paise as integers**, never floats. Makes DP exact and removes an
entire class of floating-point bugs from money handling.

### Control: Hard cap

If a candidate set exceeds N after blocking, do not attempt the solve. Flag as
`UNEXPLAINED` with the reason recorded. Measure how often this happens and
report it — it is part of the honest exception list.

### Escalation path

If accuracy genuinely demands it, OR-Tools CP-SAT is the right escalation.
Only after Tier 1 is complete.

---

## RISK 4 — The frontend overruns (it always does)

### Control: Build ONE screen

The **exception queue** is the only screen that must exist in React. It carries
the video. Everything else is optional.

### Control: The engine emits static HTML for everything else

Metrics, degradation curve, leak report, run summary — the Python engine writes
a **static HTML report**. No React, no API wiring, no state management.

This is not a compromise. A generated report page is *more* appropriate for an
audit artifact than a live dashboard, and it costs hours instead of days.

### Control: Timebox 1.5 days

If the queue is not done in 1.5 days, ship what exists and move on.

### Control: Design decided upfront

Dense tables, tabular numerals, restrained colour, no gradients. Decided in
`08-TECH-STACK.md` so that zero time is lost to style exploration.

### Control: Do not hand-build a data grid

TanStack Table, defaults where possible. Grid-building is a time sink with no
payoff for us.

---

## The meta-control

Every risk above has the same shape: **make the failure cheap and visible early,
rather than trying to prevent it.**

- Oracle test makes generator bugs visible immediately
- Interface-first makes Splink failure cheap
- Exception fallback makes intractability harmless
- Static HTML makes frontend overrun survivable
